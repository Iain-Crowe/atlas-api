"""Run once per host: python -m app.collector. No browser or JWT is required."""
from __future__ import annotations

import fcntl
import logging
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import FrameType

from sqlalchemy import select

from app import network_history, link_history
from app.network_models import NetworkSnapshot
from app.services.runtime.agent import get_network_telemetry
from app.database import SessionLocal
from app.db_models import ManagedService
from app.services.runtime.agent import get_minecraft_status, get_runtime_status, get_system_telemetry
from app.telemetry import DB_PATH, INTERVAL, initialize, prune, store_sample

logger = logging.getLogger('atlas-collector')


def collect_host(sampled_at: int) -> None:
    try:
        result = get_system_telemetry()
    except OSError:
        result = {'ok': False, 'error': 'Agent unavailable'}
    if not result['ok']:
        store_sample('host', 0, sampled_at, 'unavailable', {})
        return
    values = {
        'cpu_percent': result['cpu_usage_percent'], 'temperature_c': result['cpu_temperature_c'],
        'memory_used_mb': result['memory_total_mb'] - result['memory_available_mb'],
        'memory_total_mb': result['memory_total_mb'], 'disk_used_gb': result['disk_used_gb'],
        'disk_total_gb': result['disk_total_gb'], 'load_1m': result['load_average'][0],
    }
    store_sample('host', 0, sampled_at, 'partial' if any(v is None for v in values.values()) else 'ok', values)


def collect_minecraft(sampled_at: int) -> None:
    # End the inventory DB transaction before any socket calls.
    with SessionLocal() as db:
        services = list(db.execute(select(ManagedService.id, ManagedService.runtime_type,
                                          ManagedService.runtime_name).where(ManagedService.runtime_name.in_(('minecraft', 'minecraft-craftbox')))))
    for service_id, runtime_type, runtime_name in services:
        if runtime_type != 'docker' or runtime_name not in {'minecraft', 'minecraft-craftbox'}:
            store_sample('minecraft', service_id, sampled_at, 'unsupported', {})
            continue
        try:
            status = get_runtime_status(runtime_name)
            if not status['ok']:
                store_sample('minecraft', service_id, sampled_at, 'unavailable', {})
                continue
            if status['state'] != 'running':
                store_sample('minecraft', service_id, sampled_at, 'stopped', {})
                continue
            result = get_minecraft_status(runtime_name)
            if not result['ok']:
                store_sample('minecraft', service_id, sampled_at, 'unavailable', {})
                continue
            values = {'players_online': float(result['online']), 'tps': result['tps'],
                      'mspt': result['mspt'], 'loaded_chunks': result['loaded_chunks']}
            store_sample('minecraft', service_id, sampled_at,
                         'partial' if any(v is None for v in values.values()) else 'ok', values)
        except OSError:
            store_sample('minecraft', service_id, sampled_at, 'unavailable', {})


def collect_network(sampled_at: int) -> None:
    try:
        snapshot = get_network_telemetry()
    except (OSError, RuntimeError):
        logger.warning('Network measurements unavailable')
        snapshot = NetworkSnapshot(ok=True, sample_seconds=5.0, readings=[])
    network_history.store(snapshot, sampled_at)
    link_history.store(snapshot.quality, sampled_at)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(DB_PATH) + '.collector.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('A telemetry collector already owns this database') from exc
        initialize()
        network_history.initialize()
        link_history.initialize()
        stop = threading.Event()
        def shutdown(signum: int, frame: FrameType | None) -> None:
            stop.set()
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        last_prune = 0.0
        last_slot: int | None = None
        logger.info('Collecting every %s seconds into %s', INTERVAL, DB_PATH)
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix='telemetry') as pool:
            while not stop.is_set():
                slot = int(time.time()) // INTERVAL * INTERVAL
                if slot != last_slot:
                    futures = [pool.submit(collect_host, slot), pool.submit(collect_minecraft, slot), pool.submit(collect_network, slot)]
                    for name, future in zip(('host', 'minecraft', 'network'), futures):
                        try:
                            future.result()
                        except Exception:
                            # One source/storage failure must not terminate the other stream.
                            logger.exception('%s collection failed', name)
                    last_slot = slot
                if time.monotonic() - last_prune >= 60:
                    try:
                        prune()
                        network_history.prune()
                        link_history.prune()
                    except Exception:
                        logger.exception('Retention cleanup failed')
                    last_prune = time.monotonic()
                # Skip missed slots; do not manufacture historical measurements.
                delay = INTERVAL - (time.time() % INTERVAL)
                stop.wait(max(0.1, delay))
        logger.info('Collector stopped')


if __name__ == '__main__':
    main()
