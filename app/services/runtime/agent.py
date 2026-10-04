# app/services/runtime/agent.py

import json
import socket

from typing import cast, Literal

from app.models import (
    AgentResponse,
    RuntimeActionResult,
    RuntimeStatus,
    MinecraftStatusResult,
    SystemTelemetryResult,
)

SOCKET_PATH = "/run/atlas/agent.sock"

type AgentAction = Literal[
    "status", 
    "start", 
    "stop", 
    "restart",
    "minecraft_status",
    "system_status"
]

def send_agent_request(
        action: AgentAction,
        container_name: str | None = None,
) -> AgentResponse:
    request: dict[str,str] = {
        "action": action,
    }

    if container_name is not None:
        request["container"] = container_name

    with socket.socket(
        socket.AF_UNIX, # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType, reportAttributeAccessIssue]
        socket.SOCK_STREAM,
    ) as client:
        client.connect(SOCKET_PATH)
        client.sendall(json.dumps(request).encode("utf-8"))

        raw_response = client.recv(4096)

    response = json.loads(raw_response.decode("utf-8"))

    return cast(AgentResponse, response)

def get_runtime_status(container_name: str) -> RuntimeStatus:
    return cast(
        RuntimeStatus,
        send_agent_request(
            "status",
            container_name
        )
    )

def start_runtime(container_name: str) -> RuntimeActionResult:
    return cast(
        RuntimeActionResult,
        send_agent_request(
            "start",
            container_name
        )
    )

def stop_runtime(container_name: str) -> RuntimeActionResult:
    return cast(
        RuntimeActionResult,
        send_agent_request(
            "stop",
            container_name
        )
    )

def restart_runtime(container_name: str) -> RuntimeActionResult:
    return cast(
        RuntimeActionResult,
        send_agent_request(
            "restart",
            container_name
        )
    )

def get_minecraft_status() -> MinecraftStatusResult:
    return cast(
        MinecraftStatusResult,
        send_agent_request("minecraft_status"),
    )

def get_system_telemetry() -> SystemTelemetryResult:
    return cast(
        SystemTelemetryResult,
        send_agent_request("system_status"),
    )