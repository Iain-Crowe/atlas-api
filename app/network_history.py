"""Network history uses additive tables, preserving existing telemetry history."""
from __future__ import annotations

import math
import json
import time
from typing import Literal
from pydantic import BaseModel, Field

from app.network_models import NetworkSnapshot, SOURCES
from app.telemetry import (INTERVAL, RETENTION_DAYS, RANGES, HistoryRange,
                           HistoryPoint, MetricAggregate, connection)


class NetworkPoint(HistoryPoint):
    interfaces: list[str] = Field(default_factory=list)
    mixed_interfaces: bool = False


class NetworkHistory(BaseModel):
    kind: Literal['network'] = 'network'
    source: str
    range: HistoryRange
    start: int
    end: int
    bucket_seconds: int
    sample_seconds: int = INTERVAL
    retention_days: int = RETENTION_DAYS
    last_sample_at: int | None
    last_success_at: int | None
    received_bytes: int
    sent_bytes: int
    covered_seconds: float
    points: list[NetworkPoint]


def initialize() -> None:
    with connection() as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        existed = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='network_samples_v2'").fetchone()
        conn.execute('''CREATE TABLE IF NOT EXISTS network_samples_v2 (
            source TEXT NOT NULL, sampled_at INTEGER NOT NULL, observed_at REAL NOT NULL, monotonic_at REAL,
            generation TEXT, rx_bytes INTEGER, tx_bytes INTEGER,
            interval_start REAL, elapsed REAL, rx_delta INTEGER, tx_delta INTEGER,
            rx_mbps REAL, tx_mbps REAL, interfaces TEXT NOT NULL DEFAULT '[]', PRIMARY KEY(source, sampled_at))''')
        conn.execute('CREATE INDEX IF NOT EXISTS ix_network_v2_time ON network_samples_v2(sampled_at)')
        if not existed and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='network_samples'").fetchone():
            conn.execute("INSERT INTO network_samples_v2 SELECT *, '[]' FROM network_samples")


def store(snapshot: NetworkSnapshot, slot: int) -> None:
    now = time.time()
    with connection() as conn, conn:
        # Persist a gap for sources missing from the snapshot, including a
        # container that joined a shared namespace after being measured alone.
        readings = {r.source: r for r in snapshot.readings}
        for source in SOURCES:
            r = readings.get(source)
            observed = r.observed_at if r else now
            valid = (r is not None and r.state in {'ok', 'warming_up'}
                     and 0 <= now-observed <= 20 and r.generation is not None
                     and r.rx_bytes is not None and r.tx_bytes is not None)
            old = conn.execute('SELECT * FROM network_samples_v2 WHERE source=? AND sampled_at<? '
                               'ORDER BY sampled_at DESC LIMIT 1', (source, slot)).fetchone()
            elapsed = rx_delta = tx_delta = start = rx_rate = tx_rate = None
            if valid and old and old['generation'] == r.generation and old['rx_bytes'] is not None:
                duration = r.monotonic_at-old['monotonic_at']
                drx, dtx = r.rx_bytes-old['rx_bytes'], r.tx_bytes-old['tx_bytes']
                if 0 < duration <= INTERVAL*3 and drx >= 0 and dtx >= 0:
                    elapsed, rx_delta, tx_delta, start = duration, drx, dtx, old['observed_at']
                    rx_rate, tx_rate = drx*8/duration/1e6, dtx*8/duration/1e6
            conn.execute('INSERT INTO network_samples_v2 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) '
                         'ON CONFLICT(source,sampled_at) DO NOTHING',
                         (source, slot, observed, r.monotonic_at if valid else None, r.generation if valid else None,
                          r.rx_bytes if valid else None, r.tx_bytes if valid else None,
                          start, elapsed, rx_delta, tx_delta, rx_rate, tx_rate, json.dumps(r.interfaces if r else [])))


def prune() -> None:
    with connection() as conn, conn:
        conn.execute('DELETE FROM network_samples_v2 WHERE rowid IN '
                     '(SELECT rowid FROM network_samples_v2 WHERE sampled_at<? ORDER BY sampled_at LIMIT 5000)',
                     (int(time.time())-RETENTION_DAYS*86400,))


def history(source: str, period: HistoryRange, *, now: int | None = None) -> NetworkHistory:
    if source not in SOURCES:
        raise ValueError('Unknown network source')
    end = int(time.time()) if now is None else now
    duration, width = RANGES[period]
    width = max(width, INTERVAL)
    start = end-min(duration, RETENTION_DAYS*86400)
    expressions = ['(sampled_at / ?) * ? AS bucket', 'COUNT(*) AS samples', 'GROUP_CONCAT(DISTINCT interfaces) AS interface_sets',
                   'COUNT(DISTINCT interfaces) AS interface_count', 'MIN(interfaces) AS single_interfaces']
    for metric in ('rx_mbps', 'tx_mbps'):
        expressions.extend(f'{fn}({metric}) AS {metric}_{suffix}' for fn, suffix in
                           (('AVG', 'mean'), ('MIN', 'minimum'), ('MAX', 'maximum'), ('COUNT', 'count')))
    with connection() as conn:
        rows = conn.execute(f'SELECT {", ".join(expressions)} FROM network_samples_v2 '
                            'WHERE source=? AND sampled_at>=? AND sampled_at<=? GROUP BY bucket ORDER BY bucket',
                            (width, width, source, start, end)).fetchall()
        latest = conn.execute('SELECT MAX(sampled_at), MAX(CASE WHEN rx_mbps IS NOT NULL THEN sampled_at END) '
                              'FROM network_samples_v2 WHERE source=? AND sampled_at<=?', (source, end)).fetchone()
        # Only fully observed intervals inside the requested window are summed.
        # Missing time and boundary-crossing intervals are never extrapolated.
        totals = conn.execute('SELECT COALESCE(SUM(rx_delta),0), COALESCE(SUM(tx_delta),0), '
                              'COALESCE(SUM(elapsed),0) FROM network_samples_v2 '
                              'WHERE source=? AND interval_start>=? AND observed_at<=? AND sampled_at<=?',
                              (source, start, end, end)).fetchone()
    indexed = {row['bucket']: row for row in rows}
    points: list[NetworkPoint] = []
    for timestamp in range(start//width*width, end//width*width+1, width):
        row = indexed.get(timestamp)
        expected = max(0, min(timestamp+width-1, end)//INTERVAL-math.ceil(max(timestamp,start)/INTERVAL)+1)
        mixed = bool(row and row['interface_count'] > 1)
        interfaces = json.loads(row['single_interfaces']) if row and not mixed else []
        metrics = {name: MetricAggregate(mean=row[f'{name}_mean'] if row and not mixed else None,
                                         minimum=row[f'{name}_minimum'] if row and not mixed else None,
                                         maximum=row[f'{name}_maximum'] if row and not mixed else None,
                                         count=row[f'{name}_count'] if row and not mixed else 0)
                   for name in ('rx_mbps', 'tx_mbps')}
        points.append(NetworkPoint(timestamp=timestamp, interfaces=interfaces, mixed_interfaces=mixed, samples=row['samples'] if row else 0,
                                   expected=expected, successful=metrics['rx_mbps'].count, metrics=metrics))
    return NetworkHistory(source=source, range=period, start=start, end=end, bucket_seconds=width,
                          last_sample_at=latest[0], last_success_at=latest[1],
                          received_bytes=totals[0], sent_bytes=totals[1], covered_seconds=totals[2], points=points)
