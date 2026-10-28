"""Bounded SQLite telemetry storage and aggregation, independent of auth data."""
from __future__ import annotations

import math
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Literal

from pydantic import BaseModel

type Kind = Literal['host', 'minecraft']
type HistoryRange = Literal['1h', '6h', '24h', '7d']
type SampleState = Literal['ok', 'partial', 'unavailable', 'stopped', 'unsupported']
DB_PATH = Path(os.environ.get('ATLAS_TELEMETRY_DB', '/data/telemetry.db'))
INTERVAL = int(os.environ.get('ATLAS_SAMPLE_SECONDS', '15'))
RETENTION_DAYS = int(os.environ.get('ATLAS_RETENTION_DAYS', '7'))
if INTERVAL not in {5, 10, 15, 30, 60} or not 1 <= RETENTION_DAYS <= 30:
    raise ValueError('Sample seconds must be 5, 10, 15, 30 or 60; retention days must be 1–30')
RANGES: dict[HistoryRange, tuple[int, int]] = {
    '1h': (3600, 15), '6h': (21600, 60), '24h': (86400, 300), '7d': (604800, 1800),
}
METRICS: dict[Kind, tuple[str, ...]] = {
    'host': ('cpu_percent', 'temperature_c', 'memory_used_mb', 'memory_total_mb',
             'disk_used_gb', 'disk_total_gb', 'load_1m'),
    'minecraft': ('players_online', 'tps', 'mspt', 'loaded_chunks'),
}


class MetricAggregate(BaseModel):
    mean: float | None
    minimum: float | None
    maximum: float | None
    count: int


class HistoryPoint(BaseModel):
    timestamp: int
    samples: int
    expected: int
    successful: int
    metrics: dict[str, MetricAggregate]


class HistoryResponse(BaseModel):
    kind: Kind
    range: HistoryRange
    start: int
    end: int
    bucket_seconds: int
    sample_seconds: int
    retention_days: int
    last_sample_at: int | None
    last_success_at: int | None
    points: list[HistoryPoint]


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def initialize() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connection() as conn:
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version not in {0, 1}:
            raise RuntimeError(f'Unsupported telemetry schema version: {version}')
        conn.execute('PRAGMA journal_mode=WAL')
        with conn:
            for kind, fields in METRICS.items():
                metric_columns = ', '.join(f'{name} REAL' for name in fields)
                conn.execute(f'''CREATE TABLE IF NOT EXISTS {kind}_samples (
                    entity_id INTEGER NOT NULL, sampled_at INTEGER NOT NULL,
                    collected_at INTEGER NOT NULL, state TEXT NOT NULL,
                    {metric_columns}, PRIMARY KEY (entity_id, sampled_at))''')
                conn.execute(f'CREATE INDEX IF NOT EXISTS ix_{kind}_sample_time ON {kind}_samples(sampled_at)')
            conn.execute('PRAGMA user_version=1')


def store_sample(kind: Kind, entity_id: int, sampled_at: int, state: SampleState,
                 values: dict[str, float | None], *, collected_at: int | None = None) -> None:
    fields = METRICS[kind]
    if values.keys() - set(fields):
        raise ValueError('Unknown telemetry metric')
    if state not in {'ok', 'partial', 'unavailable', 'stopped', 'unsupported'}:
        raise ValueError('Unknown telemetry state')
    for value in values.values():
        if value is not None and (isinstance(value, bool) or not math.isfinite(value)):
            raise ValueError('Telemetry values must be finite numbers or null')
    if state not in {'ok', 'partial'} and any(value is not None for value in values.values()):
        raise ValueError('Unavailable samples cannot contain measurements')
    columns = ('entity_id', 'sampled_at', 'collected_at', 'state', *fields)
    params = (entity_id, sampled_at, collected_at if collected_at is not None else int(time.time()),
              state, *(values.get(name) for name in fields))
    with connection() as conn, conn:
        conn.execute(f'INSERT INTO {kind}_samples ({", ".join(columns)}) '
                     f'VALUES ({", ".join("?" for _ in columns)}) '
                     'ON CONFLICT(entity_id, sampled_at) DO NOTHING', params)


def prune(now: int | None = None, batch_size: int = 5000) -> None:
    if not 1 <= batch_size <= 5000:
        raise ValueError('Invalid retention batch size')
    cutoff = (int(time.time()) if now is None else now) - RETENTION_DAYS * 86400
    for kind in METRICS:
        # A bounded transaction per table; no VACUUM in the collector hot path.
        with connection() as conn, conn:
            conn.execute(f'DELETE FROM {kind}_samples WHERE rowid IN '
                         f'(SELECT rowid FROM {kind}_samples WHERE sampled_at < ? '
                         'ORDER BY sampled_at LIMIT ?)', (cutoff, batch_size))


def history(kind: Kind, entity_id: int, requested_range: HistoryRange,
            *, now: int | None = None) -> HistoryResponse:
    end = int(time.time()) if now is None else now
    duration, default_bucket = RANGES[requested_range]
    width = max(default_bucket, INTERVAL)
    start = end - min(duration, RETENTION_DAYS * 86400)
    fields = METRICS[kind]
    expressions = ['(sampled_at / ?) * ? AS bucket', 'COUNT(*) AS samples',
                   "SUM(CASE WHEN state IN ('ok','partial') THEN 1 ELSE 0 END) AS successful"]
    for name in fields:
        expressions.extend(f'{function}({name}) AS {name}_{label}' for function, label in
                           (('AVG', 'mean'), ('MIN', 'minimum'), ('MAX', 'maximum'), ('COUNT', 'count')))
    with connection() as conn:
        if conn.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise sqlite3.DatabaseError("Unsupported telemetry schema")
        rows = conn.execute(f'SELECT {", ".join(expressions)} FROM {kind}_samples '
                            'WHERE entity_id = ? AND sampled_at >= ? AND sampled_at <= ? '
                            'GROUP BY bucket ORDER BY bucket', (width, width, entity_id, start, end)).fetchall()
        latest = conn.execute(f'SELECT MAX(sampled_at), '
                              "MAX(CASE WHEN state IN ('ok','partial') THEN sampled_at ELSE NULL END) "
                              f'FROM {kind}_samples WHERE entity_id = ? AND sampled_at <= ?',
                              (entity_id, end)).fetchone()
    by_time = {row['bucket']: row for row in rows}
    points: list[HistoryPoint] = []
    for timestamp in range(start // width * width, end // width * width + 1, width):
        row = by_time.get(timestamp)
        first_slot = math.ceil(max(timestamp, start) / INTERVAL)
        last_slot = min(timestamp + width - 1, end) // INTERVAL
        expected = max(0, last_slot - first_slot + 1)
        metrics = {name: MetricAggregate(
            mean=row[f'{name}_mean'] if row else None,
            minimum=row[f'{name}_minimum'] if row else None,
            maximum=row[f'{name}_maximum'] if row else None,
            count=row[f'{name}_count'] if row else 0,
        ) for name in fields}
        points.append(HistoryPoint(timestamp=timestamp, samples=row['samples'] if row else 0,
                                   expected=expected, successful=row['successful'] if row else 0,
                                   metrics=metrics))
    return HistoryResponse(kind=kind, range=requested_range, start=start, end=end,
                           bucket_seconds=width, sample_seconds=INTERVAL,
                           retention_days=RETENTION_DAYS, last_sample_at=latest[0],
                           last_success_at=latest[1], points=points)
