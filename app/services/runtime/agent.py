"""Validated, deadline-bounded requests to the host Atlas Agent."""

from __future__ import annotations

import json
import logging
import math
import socket
import time
from typing import Literal, NoReturn, cast

from pydantic import TypeAdapter

from app.node_models import NodeSnapshot
from app.power_models import PowerSnapshot
from app.maintenance_models import MaintenanceSnapshot
from app.resource_models import ResourceSnapshot
from app.network_models import NetworkSnapshot
from app.jellyfin_models import JellyfinSnapshot
from app.pihole_models import PiHoleSnapshot
from app.media_models import MediaSnapshot

from app.models import (
    AgentError,
    AgentResponse,
    MinecraftStatusResult,
    MinecraftStatusSuccess,
    RuntimeActionResult,
    RuntimeActionSuccess,
    RuntimeStatus,
    RuntimeStatusSuccess,
    SystemTelemetryResult,
    SystemTelemetrySuccess,
)

SOCKET_PATH = "/run/atlas/agent.sock"
MAX_REQUEST_BYTES = 4096
MAX_RESPONSE_BYTES = 256 * 1024
CONNECT_TIMEOUT_SECONDS = 2.0

type AgentAction = Literal["power_status", "node_status", "maintenance_status", "resource_status", "status", "start", "stop", "restart", "minecraft_status", "system_status", "network_status", "jellyfin_status", "pihole_status", "media_status"]

# Longer than the corresponding Agent subprocess budgets (150 / 5 / 3x3 s).
REQUEST_TIMEOUT_SECONDS: dict[AgentAction, float] = {
    "power_status": 5.0,
    "node_status": 5.0,
    "maintenance_status": 5.0,
    "resource_status": 5.0,
    "status": 10.0,
    "start": 165.0,
    "stop": 165.0,
    "restart": 165.0,
    "minecraft_status": 15.0,
    "system_status": 10.0,
    "network_status": 10.0,
    "jellyfin_status": 10.0,
    "pihole_status": 10.0,
    "media_status": 10.0,
}

logger = logging.getLogger("atlas-api.agent")
_error_adapter = TypeAdapter(AgentError)
_status_adapter = TypeAdapter(RuntimeStatusSuccess)
_action_adapter = TypeAdapter(RuntimeActionSuccess)
_minecraft_adapter = TypeAdapter(MinecraftStatusSuccess)
_system_adapter = TypeAdapter(SystemTelemetrySuccess)


class AgentProtocolError(ValueError):
    """An Agent response is malformed or does not match its request."""


def _set_remaining_timeout(client: socket.socket, deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Atlas Agent request deadline exceeded")
    client.settimeout(remaining)


def _reject_constant(value: str) -> NoReturn:
    raise AgentProtocolError("Non-finite JSON numbers are not permitted")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise AgentProtocolError("Non-finite JSON numbers are not permitted")
    return number


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AgentProtocolError("Duplicate JSON keys are not permitted")
        result[key] = value
    return result


def _read_response(client: socket.socket, deadline: float) -> object:
    data = bytearray()
    while True:
        _set_remaining_timeout(client, deadline)
        chunk = client.recv(min(8192, MAX_RESPONSE_BYTES + 1 - len(data)))
        if not chunk:
            raise AgentProtocolError("Response ended before its newline delimiter")
        data.extend(chunk)
        newline = data.find(b"\n")
        if newline >= 0:
            if newline > MAX_RESPONSE_BYTES:
                raise AgentProtocolError("Response is too large")
            if data[newline + 1:].strip():
                raise AgentProtocolError("Unexpected data after the Agent response")
            payload = bytes(data[:newline])
            break
        if len(data) > MAX_RESPONSE_BYTES:
            raise AgentProtocolError("Response is too large")
    try:
        return json.loads(
            payload.decode("utf-8"),
            parse_constant=_reject_constant,
            parse_float=_finite_float,
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise AgentProtocolError("Invalid UTF-8 JSON response") from exc


def _validate_response(action: AgentAction, container_name: str | None, response: object) -> AgentResponse | NetworkSnapshot | JellyfinSnapshot | PiHoleSnapshot | MediaSnapshot | ResourceSnapshot | MaintenanceSnapshot | NodeSnapshot | PowerSnapshot:
    if not isinstance(response, dict) or type(response.get("ok")) is not bool:
        raise AgentProtocolError("Response must contain a boolean ok field")
    if response["ok"] is False:
        return _error_adapter.validate_python(response, strict=True)
    match action:
        case "power_status":
            return PowerSnapshot.model_validate(response)
        case "node_status":
            return NodeSnapshot.model_validate(response)
        case "maintenance_status":
            return MaintenanceSnapshot.model_validate(response)
        case "media_status":
            return MediaSnapshot.model_validate(response)
        case "pihole_status":
            return PiHoleSnapshot.model_validate(response)
        case "jellyfin_status":
            return JellyfinSnapshot.model_validate(response)
        case "network_status":
            return NetworkSnapshot.model_validate(response)
        case "status":
            status = _status_adapter.validate_python(response, strict=True)
            if status["name"] != container_name:
                raise AgentProtocolError("Container does not match request")
            return status
        case "start" | "stop" | "restart":
            result = _action_adapter.validate_python(response, strict=True)
            if result["name"] != container_name or result["action"] != action:
                raise AgentProtocolError("Action response does not match request")
            return result
        case "resource_status":
            return ResourceSnapshot.model_validate(response, strict=True)
        case "minecraft_status":
            return _minecraft_adapter.validate_python(response, strict=True)
        case "system_status":
            telemetry = _system_adapter.validate_python(response, strict=True)
            if len(telemetry["load_average"]) != 3:
                raise AgentProtocolError("Expected three load averages")
            return telemetry
    raise AgentProtocolError("Unsupported Agent action")


def send_agent_request(action: AgentAction, container_name: str | None = None) -> AgentResponse | NetworkSnapshot | JellyfinSnapshot | PiHoleSnapshot | MediaSnapshot | ResourceSnapshot | MaintenanceSnapshot | NodeSnapshot | PowerSnapshot:
    request: dict[str, str] = {"action": action}
    if container_name is not None:
        request["container"] = container_name
    payload = json.dumps(request, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_REQUEST_BYTES:
        return {"ok": False, "error": "Agent request is too large"}
    deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS[action]

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(min(CONNECT_TIMEOUT_SECONDS, REQUEST_TIMEOUT_SECONDS[action]))
            client.connect(SOCKET_PATH)
            _set_remaining_timeout(client, deadline)
            client.sendall(payload + b"\n")
            response = _read_response(client, deadline)
        return _validate_response(action, container_name, response)
    except TimeoutError:
        logger.warning("Agent request timed out: action=%s", action)
        message = "Atlas Agent request timed out"
        if action in {"start", "stop", "restart"}:
            message += "; the operation may still complete. Check its status before retrying."
        return {"ok": False, "error": message}
    except (ValueError, RecursionError):
        # Pydantic ValidationError is a ValueError too.
        logger.warning("Invalid Agent response: action=%s", action)
        return {"ok": False, "error": "Atlas Agent returned an invalid response"}
    # Connection failures remain OSError: existing API routes map them to 503.
    # Protocol/timeout failures become AgentError: existing routes map to 502.
    # Never retry a control action automatically.


def get_runtime_status(container_name: str) -> RuntimeStatus:
    return cast(RuntimeStatus, send_agent_request("status", container_name))


def start_runtime(container_name: str) -> RuntimeActionResult:
    return cast(RuntimeActionResult, send_agent_request("start", container_name))


def stop_runtime(container_name: str) -> RuntimeActionResult:
    return cast(RuntimeActionResult, send_agent_request("stop", container_name))


def restart_runtime(container_name: str) -> RuntimeActionResult:
    return cast(RuntimeActionResult, send_agent_request("restart", container_name))


def get_minecraft_status(container_name: str = "minecraft") -> MinecraftStatusResult:
    if container_name not in {"minecraft", "minecraft-craftbox"}:
        raise ValueError("Unsupported Minecraft container")
    return cast(MinecraftStatusResult, send_agent_request("minecraft_status", container_name))


def get_system_telemetry() -> SystemTelemetryResult:
    return cast(SystemTelemetryResult, send_agent_request("system_status"))


def get_network_telemetry() -> NetworkSnapshot:
    result = send_agent_request("network_status")
    if not isinstance(result, NetworkSnapshot):
        raise RuntimeError("Network telemetry is unavailable")
    return result


def get_jellyfin_status() -> JellyfinSnapshot:
    result = send_agent_request("jellyfin_status")
    if not isinstance(result, JellyfinSnapshot):
        raise RuntimeError("Jellyfin telemetry is unavailable")
    return result


def get_pihole_status() -> PiHoleSnapshot:
    result = send_agent_request("pihole_status")
    if not isinstance(result, PiHoleSnapshot):
        raise RuntimeError("Pi-hole telemetry is unavailable")
    return result


def get_media_status() -> MediaSnapshot:
    result = send_agent_request("media_status")
    if not isinstance(result, MediaSnapshot):
        raise RuntimeError("Media telemetry is unavailable")
    return result


def get_service_resources() -> ResourceSnapshot:
    result = send_agent_request("resource_status")
    if not isinstance(result, ResourceSnapshot):
        raise RuntimeError("Service telemetry unavailable")
    return result
