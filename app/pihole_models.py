"""Aggregate Pi-hole telemetry; no queried domains or client addresses."""
from __future__ import annotations
from typing import Generic, Literal, TypeVar
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)

class PiHoleSummary(StrictModel):
    queries: int = Field(ge=0, le=2**53-1)
    blocked: int = Field(ge=0, le=2**53-1)
    percent_blocked: float = Field(ge=0, le=100)
    active_clients: int = Field(ge=0, le=2**53-1)
    blocklist_domains: int = Field(ge=0, le=2**53-1)
    cached: int = Field(ge=0, le=2**53-1)
    forwarded: int = Field(ge=0, le=2**53-1)

    @model_validator(mode='after')
    def consistent(self) -> PiHoleSummary:
        if self.blocked > self.queries:
            raise ValueError('Blocked count exceeds total')
        return self

class PiHoleBlocking(StrictModel):
    status: Literal['enabled', 'disabled', 'unknown', 'failed']
    timer_seconds: float | None = Field(ge=0, le=2**53-1)

T = TypeVar('T')
class Reading(StrictModel, Generic[T]):
    state: Literal['warming_up', 'ready', 'unavailable']
    updated_at: float | None = Field(ge=0)
    values: T | None

    @model_validator(mode='after')
    def consistent(self) -> Reading[T]:
        if self.state == 'ready':
            if self.values is None or self.updated_at is None:
                raise ValueError('Ready reading is incomplete')
        elif self.values is not None or self.updated_at is not None:
            raise ValueError('Unavailable reading contains data')
        return self

class PiHoleSnapshot(StrictModel):
    ok: Literal[True]
    summary: Reading[PiHoleSummary]
    blocking: Reading[PiHoleBlocking]
    refresh_seconds: Literal[30]
