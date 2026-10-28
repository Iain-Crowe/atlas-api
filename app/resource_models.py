from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class ResourceReading(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    state: Literal['running','exited','dead','created','paused','restarting','removing','unavailable']
    health: Literal['none','starting','healthy','unhealthy']
    observed_at: float | None = Field(default=None, ge=0)
    sampled_at: float | None = Field(default=None, ge=0)
    started_at: float | None = Field(default=None, ge=0)
    uptime_seconds: float | None = Field(default=None, ge=0)
    cpu_percent: float | None = Field(default=None, ge=0, le=1_000_000)
    memory_used_bytes: int | None = Field(default=None, ge=0)
    memory_limit_bytes: int | None = Field(default=None, gt=0)
    limit_configured: bool = False
    telemetry: Literal['ready','stopped','unavailable']
    generation: str | None = Field(default=None, max_length=256)

class ResourceSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ok: Literal[True]
    readings: dict[str, ResourceReading] = Field(max_length=64)
