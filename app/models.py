from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict

# === System Status Models ===
class CPUStatus(BaseModel):
    usage_percent: float
    temperature_c: float | None

class MemoryStatus(BaseModel):
    total_mb: float
    available_mb: float

class DiskStatus(BaseModel):
    total_gb: float
    used_gb: float
    free_gb: float

class SystemStatus(BaseModel):
    hostname: str
    uptime_seconds: float
    load_average: list[float]
    cpu: CPUStatus
    memory: MemoryStatus
    disk: DiskStatus

# === User Auth Models ===
class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str

class TokenPayload(BaseModel):
    sub: str
    role: str
    exp: int

    model_config = ConfigDict(strict=True)

class CurrentUserResponse(BaseModel):
    username: str
    role: str
    active: bool

    model_config = ConfigDict(from_attributes=True)

# === Service/Runtime Models ===
class ManagedServiceCreate(BaseModel):
    name: str
    display_name: str
    runtime_type: str = "docker"
    runtime_name: str | None = None

class RuntimeInfo(BaseModel):
    state: str

class ManagedServiceResponse(BaseModel):
    id: int
    name: str
    display_name: str
    runtime_type: str
    runtime_name: str | None
    runtime: RuntimeInfo | None = None

    model_config = ConfigDict(from_attributes=True)

class RuntimeStatusSuccess(TypedDict):
    ok: Literal[True]
    name: str
    state: str

class AgentError(TypedDict):
    ok: Literal[False]
    error: str

class RuntimeActionSuccess(TypedDict):
    ok: Literal[True]
    name: str
    action: Literal["start", "stop", "restart"]
    output: str

class RuntimeActionResponse(BaseModel):
    name: str
    action: Literal["start", "stop", "restart"]
    output: str

class MinecraftStatusSuccess(TypedDict):
    ok: Literal[True]
    online: int
    max: int
    players: list[str]
    tps: float | None
    mspt: float | None
    loaded_chunks: int | None

class MinecraftStatusResponse(BaseModel):
    online: int
    max: int
    players: list[str]
    tps: float | None
    mspt: float | None
    loaded_chunks: int | None

class SystemTelemetrySuccess(TypedDict):
    ok: Literal[True]
    hostname: str
    uptime_seconds: float
    load_average: list[float]
    cpu_usage_percent: float
    cpu_temperature_c: float | None
    memory_total_mb: float
    memory_available_mb: float
    disk_total_gb: float
    disk_used_gb: float
    disk_free_gb: float

type RuntimeStatus = RuntimeStatusSuccess | AgentError
type RuntimeActionResult = RuntimeActionSuccess | AgentError
type MinecraftStatusResult = MinecraftStatusSuccess | AgentError
type SystemTelemetryResult = SystemTelemetrySuccess | AgentError
type AgentResponse = (
    RuntimeStatus 
    | RuntimeActionResult
    | MinecraftStatusResult
    | SystemTelemetryResult
)