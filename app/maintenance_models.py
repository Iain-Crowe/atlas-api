"""Validated maintenance status exposed by the host agent."""
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class MaintenanceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    node: Literal["atlas"]
    enabled: bool
    simulation: bool
    phase: Literal["idle", "scheduled", "running", "complete", "failed", "skipped"]
    updated_at: AwareDatetime
    scheduled_for: AwareDatetime | None
    message: str = Field(min_length=1, max_length=1000)
    pending_updates: int | None = Field(default=None, ge=0)
    reboot_required: bool | None = None


class MaintenanceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: Literal[True]
    configured: bool
    status: MaintenanceStatus | None

    @model_validator(mode="after")
    def consistent_status(self) -> "MaintenanceSnapshot":
        if self.configured != (self.status is not None):
            raise ValueError("Configured flag does not match maintenance status")
        return self
