"""Local router and wireless history; no extrapolated probes or throughput claims."""
from __future__ import annotations
import math
import time
from app.network_models import LinkQuality
from app.network_history import NetworkHistory, NetworkPoint
from app.telemetry import INTERVAL, RETENTION_DAYS, RANGES, HistoryRange, HistoryPoint, MetricAggregate, connection

METRICS = ('latency_ms', 'loss_percent', 'signal_dbm', 'rx_link_mbps', 'tx_link_mbps', 'link_speed_mbps')


def initialize() -> None:
    with connection() as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        existed = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='link_samples_v2'").fetchone()
        conn.execute('''CREATE TABLE IF NOT EXISTS link_samples_v2 (
            sampled_at INTEGER PRIMARY KEY, observed_at REAL UNIQUE,
            packets_sent INTEGER, packets_received INTEGER,
            latency_ms REAL, loss_percent REAL, signal_dbm REAL,
            rx_link_mbps REAL, tx_link_mbps REAL, link_speed_mbps REAL,
            interface TEXT NOT NULL DEFAULT '', link_type TEXT NOT NULL DEFAULT 'unknown')''')
        if not existed and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='link_samples'").fetchone():
            conn.execute("INSERT INTO link_samples_v2 SELECT *, NULL, '', 'unknown' FROM link_samples")


def store(reading: LinkQuality | None, slot: int) -> None:
    fresh = reading is not None and 0 <= time.time()-reading.observed_at <= 35
    values: dict[str, float | None] = dict.fromkeys(METRICS)
    sent = received = None
    if fresh and reading is not None:
        if reading.ping_state in {'ok', 'no_reply'}:
            sent, received = reading.packets_sent, reading.packets_received
            values.update(latency_ms=reading.latency_ms, loss_percent=reading.loss_percent)
        if reading.link_type == 'ethernet' and reading.link_state == 'up':
            values['link_speed_mbps'] = reading.link_speed_mbps
        if reading.wifi_state == 'connected':
            values.update(signal_dbm=reading.signal_dbm, rx_link_mbps=reading.rx_link_mbps,
                          tx_link_mbps=reading.tx_link_mbps)
    with connection() as conn, conn:
        conn.execute('INSERT INTO link_samples_v2 VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',
                     (slot, reading.observed_at if fresh and reading is not None else None,
                      sent, received, *(values[name] for name in METRICS),
                      reading.interface if fresh and reading else '', reading.link_type if fresh and reading else 'unknown'))


def prune() -> None:
    with connection() as conn, conn:
        conn.execute('DELETE FROM link_samples_v2 WHERE sampled_at IN '
                     '(SELECT sampled_at FROM link_samples_v2 WHERE sampled_at<? ORDER BY sampled_at LIMIT 5000)',
                     (int(time.time())-RETENTION_DAYS*86400,))


def history(period: HistoryRange, *, now: int | None = None) -> NetworkHistory:
    end = int(time.time()) if now is None else now
    duration, width = RANGES[period]
    width = max(width, INTERVAL, 15)
    cadence = max(INTERVAL, 15)
    start = end-min(duration, RETENTION_DAYS*86400)
    expressions = ['(sampled_at / ?) * ? AS bucket', 'COUNT(*) AS samples', 'COUNT(DISTINCT interface) AS interface_count', 'MIN(interface) AS interface',
                   'COUNT(CASE WHEN loss_percent IS NOT NULL OR signal_dbm IS NOT NULL OR link_speed_mbps IS NOT NULL THEN 1 END) AS successful']
    for metric in METRICS:
        if metric == 'loss_percent':
            expressions.append('100.0*SUM(packets_sent-packets_received)/NULLIF(SUM(packets_sent),0) AS loss_percent_mean')
        else:
            expressions.append(f'AVG({metric}) AS {metric}_mean')
        expressions.extend(f'{fn}({metric}) AS {metric}_{suffix}' for fn,suffix in
                           (('MIN','minimum'),('MAX','maximum'),('COUNT','count')))
    with connection() as conn:
        rows = conn.execute(f'SELECT {", ".join(expressions)} FROM link_samples_v2 '
                            'WHERE sampled_at>=? AND sampled_at<=? GROUP BY bucket ORDER BY bucket',
                            (width,width,start,end)).fetchall()
        latest = conn.execute('SELECT MAX(sampled_at), MAX(CASE WHEN loss_percent IS NOT NULL OR '
                              'signal_dbm IS NOT NULL OR link_speed_mbps IS NOT NULL THEN sampled_at END) FROM link_samples_v2 WHERE sampled_at<=?', (end,)).fetchone()
    indexed = {r['bucket']:r for r in rows}
    points: list[NetworkPoint] = []
    for timestamp in range(start//width*width,end//width*width+1,width):
        row = indexed.get(timestamp)
        expected = max(0,min(timestamp+width-1,end)//cadence-math.ceil(max(timestamp,start)/cadence)+1)
        mixed = bool(row and row['interface_count'] > 1)
        interfaces = [row['interface']] if row and row['interface'] and not mixed else []
        metrics = {name:MetricAggregate(mean=row[f'{name}_mean'] if row and not mixed else None,
                                        minimum=row[f'{name}_minimum'] if row and not mixed else None,
                                        maximum=row[f'{name}_maximum'] if row and not mixed else None,
                                        count=row[f'{name}_count'] if row and not mixed else 0) for name in METRICS}
        points.append(NetworkPoint(timestamp=timestamp, interfaces=interfaces, mixed_interfaces=mixed,samples=row['samples'] if row else 0,
                                   successful=row['successful'] if row else 0,expected=expected,metrics=metrics))
    return NetworkHistory(source='link',range=period,start=start,end=end,bucket_seconds=width,
                          sample_seconds=cadence,last_sample_at=latest[0],last_success_at=latest[1],
                          received_bytes=0,sent_bytes=0,covered_seconds=0,points=points)
