"""Strict, finite validation at the existing Agent boundary."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class PowerModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class PowerSettings(PowerModel):
    rate: float = Field(ge=0, le=10)
    rated_watts: float = Field(ge=1, le=100000)
    note: str = Field(max_length=240)
    equipment: str = Field(max_length=240)

class Provenance(PowerSettings):
    id: int
    effective_at: float
    source: Literal['nut-load-estimate-v1']

class PowerReading(PowerModel):
    status: str = Field(max_length=120)
    supply: Literal['utility', 'battery', 'unknown']
    load: float = Field(ge=0, le=100)
    watts: float = Field(ge=0, le=100000)
    nominal_watts: float | None = Field(ge=1, le=100000)
    charge: float | None = Field(ge=0, le=100)
    runtime: float | None = Field(ge=0, le=604800)
    voltage: float | None = Field(ge=0, le=500)
    driver_state: str | None

class PowerDay(PowerModel):
    day: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    day_seconds: float = Field(ge=82800, le=90000)
    elapsed_seconds: float = Field(ge=0, le=90000)
    covered_seconds: float = Field(ge=0, le=90000)
    coverage: float = Field(ge=0, le=1)
    kwh: float | None = Field(ge=0)
    utility_kwh: float | None = Field(ge=0)
    battery_kwh: float | None = Field(ge=0)
    unknown_kwh: float | None = Field(ge=0)
    cost: float | None = Field(ge=0)
    average_watts: float | None = Field(ge=0)
    partial: bool
    revisions: list[int]

class PowerAverage(PowerModel):
    included_days: int = Field(ge=0, le=30)
    window_days: Literal[7,30]
    coverage: float = Field(ge=0, le=1)
    kwh: float | None = Field(ge=0)
    cost: float | None = Field(ge=0)

class PowerSnapshot(PowerModel):
    ok: Literal[True]
    schema_version: Literal[1]
    source: Literal['nut-load-estimate-v1']
    timezone: Literal['America/New_York']
    generated_at: float
    last_attempt_at: float | None
    last_success_at: float | None
    error: str | None
    latest: PowerReading | None
    settings: PowerSettings | None
    settings_effective_at: float | None
    settings_id: int | None
    days: list[PowerDay] = Field(max_length=90)
    averages: dict[Literal['7','30'], PowerAverage]
    provenance: list[Provenance]
