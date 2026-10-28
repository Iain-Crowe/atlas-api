from __future__ import annotations
from typing import Generic, Literal, TypeVar
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)

class Health(StrictModel):
    warnings: int = Field(ge=0, le=2**53-1)
    errors: int = Field(ge=0, le=2**53-1)

class Pipeline(Health):
    queue_items: int = Field(ge=0, le=2000)
    awaiting_import: int = Field(ge=0, le=2000)
    queue_warnings: int = Field(ge=0, le=2000)
    queue_errors: int = Field(ge=0, le=2000)
    missing: int = Field(ge=0, le=2**53-1)

class Requests(StrictModel):
    pending: int = Field(ge=0, le=2**53-1)

class Downloads(StrictModel):
    downloading: int = Field(ge=0, le=2000)
    seeding: int = Field(ge=0, le=2000)
    queued: int = Field(ge=0, le=2000)
    stalled: int = Field(ge=0, le=2000)
    errors: int = Field(ge=0, le=2000)
    stopped: int = Field(ge=0, le=2000)
    other: int = Field(ge=0, le=2000)
    download_bps: int = Field(ge=0, le=2**53-1)
    upload_bps: int = Field(ge=0, le=2**53-1)

class Container(StrictModel):
    state: Literal['running', 'exited', 'created', 'paused', 'restarting', 'removing', 'dead', 'missing']
    health: Literal['none', 'starting', 'healthy', 'unhealthy']

class Containers(StrictModel):
    sonarr: Container
    radarr: Container
    prowlarr: Container
    seerr: Container
    qbittorrent: Container
    gluetun: Container
    flaresolverr: Container

T = TypeVar('T')
class Reading(StrictModel, Generic[T]):
    state: Literal['warming_up', 'ready', 'unavailable', 'not_configured', 'unauthorized', 'timeout', 'limit', 'invalid_response', 'changing', 'stopped']
    updated_at: float | None = Field(ge=0)
    values: T | None

    @model_validator(mode='after')
    def consistent(self) -> Reading[T]:
        if self.state == 'ready':
            if self.values is None or self.updated_at is None: raise ValueError('Missing reading')
        elif self.values is not None or self.updated_at is not None:
            raise ValueError('Unavailable reading contains data')
        return self

class MediaSnapshot(StrictModel):
    ok: Literal[True]
    containers: Reading[Containers]
    sonarr: Reading[Pipeline]
    radarr: Reading[Pipeline]
    prowlarr: Reading[Health]
    seerr: Reading[Requests]
    downloads: Reading[Downloads]
    refresh_seconds: Literal[30]
