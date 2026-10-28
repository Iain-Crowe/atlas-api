from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class MetricModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


class Pool(MetricModel):
    name: str = Field(max_length=256)
    status: str = Field(max_length=64)
    healthy: bool


class VirtualMachine(MetricModel):
    id: int
    name: str = Field(max_length=256)
    state: str = Field(max_length=64)
    autostart: bool
    memory_mib: int = Field(ge=0)


class TrueNAS(MetricModel):
    hostname: str = Field(max_length=256)
    version: str = Field(max_length=128)
    uptime_seconds: float = Field(ge=0)
    pools: list[Pool] = Field(max_length=32)
    vms: list[VirtualMachine] = Field(max_length=64)


class Host(MetricModel):
    hostname: str = Field(max_length=256)
    uptime_seconds: float = Field(ge=0)
    cpu_percent: float = Field(ge=0, le=100)
    cpu_count: int = Field(ge=1, le=4096)
    memory_total_bytes: int = Field(gt=0)
    memory_used_bytes: int = Field(ge=0)


class Mount(MetricModel):
    state: Literal['mounted', 'unexpected_mount', 'not_mounted', 'unavailable'] = 'unavailable'
    filesystem: str | None = None
    read_only: bool | None = None
    accessibility: Literal['not_probed'] = 'not_probed'


class Jellyfin(MetricModel):
    state: Literal['running', 'exited', 'dead', 'created', 'paused', 'restarting', 'removing', 'unknown']
    health: Literal['healthy', 'unhealthy', 'starting', 'none'] = 'none'
    media: Mount = Field(default_factory=Mount)


class Guest(MetricModel):
    host: Host
    jellyfin: Jellyfin


class NodeState(MetricModel):
    state: Literal['ready', 'stale', 'unavailable']
    sampled_at: float | None = Field(default=None, ge=0)


class TrueNASNode(NodeState):
    data: TrueNAS | None = None


class GuestNode(NodeState):
    data: Guest | None = None


class NodeSnapshot(MetricModel):
    ok: Literal[True]
    truenas: TrueNASNode
    vm: GuestNode
