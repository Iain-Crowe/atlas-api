from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Depends

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import logging
import sqlite3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

logger = logging.getLogger("atlas-api")

from app.telemetry import initialize as initialize_telemetry
from app.telemetry_routes import router as telemetry_router
from app.jellyfin_routes import router as jellyfin_router
from app.pihole_routes import router as pihole_router
from app.media_routes import router as media_router
from app.node_routes import router as node_router
from app.maintenance_routes import router as maintenance_router
from app.power_routes import router as power_router
from app.database import Base, engine, get_db
from app.resource_models import ResourceSnapshot
from app.services.runtime.agent import get_service_resources
from app.db_models import User, ManagedService
from app.models import (
    RuntimeInfo,
    SystemStatus, 
    CPUStatus,
    MemoryStatus, 
    DiskStatus, 
    ManagedServiceCreate, 
    ManagedServiceResponse,
    LoginRequest,
    TokenResponse, 
    CurrentUserResponse,
    RuntimeActionResponse,
    MinecraftStatusResponse,
)
from app.security import (
    verify_password, 
    create_access_token, 
    get_current_user,
    require_role
)
from app.services.database import (
    create_managed_service, 
    get_managed_services,
    get_user_by_username,
)
from app.services.runtime.agent import (
    get_runtime_status,
    restart_runtime,
    start_runtime,
    stop_runtime,
    get_minecraft_status,
    get_system_telemetry,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    try:
        initialize_telemetry()
    except (sqlite3.Error, OSError, RuntimeError):
        logger.exception("History storage initialization failed; live API remains available")
    yield

app = FastAPI(lifespan=lifespan)
app.include_router(telemetry_router)
app.include_router(jellyfin_router)
app.include_router(pihole_router)
app.include_router(media_router)
app.include_router(maintenance_router)
app.include_router(power_router)
app.include_router(node_router)

# === Health Endpoint ===
@app.get("/health")
async def health_check():
    logger.info("Health check requested")
    return {"status": "healthy"}

# === System Endpoints ===
@app.get("/system/status")
def system_status(
    current_user: User = Depends(require_role("viewer"))
):
    try:
        logger.info("System status requested")
        result = get_system_telemetry()

    except OSError as exc:
        logger.error("System status failed: %s", exc)
        raise HTTPException(
            status_code=503, 
            detail="Atlas Agent is unavailable"
        ) from exc

    if result["ok"] is False:
        logger.error(
            "System status failed: %s",
            result["error"]
        )

        raise HTTPException(
            status_code=502,
            detail=result["error"]
        )

    return SystemStatus(
        hostname=result["hostname"],
        uptime_seconds=result["uptime_seconds"],
        load_average=result["load_average"],
        cpu=CPUStatus(
            usage_percent=result["cpu_usage_percent"],
            temperature_c=result["cpu_temperature_c"]
        ),
        memory=MemoryStatus(
            total_mb=result["memory_total_mb"],
            available_mb=result["memory_available_mb"]
        ),
        disk=DiskStatus(
            total_gb=result["disk_total_gb"],
            used_gb=result["disk_used_gb"],
            free_gb=result["disk_free_gb"]
        )
    )

    # try:
    #     logger.info("System status requested")

    #     hostname = get_hostname()
    #     uptime_seconds = get_uptime()
    #     load_average = get_load_average()
    #     total_mb, available_mb = get_memory_info()
    #     total_gb, used_gb, free_gb = get_disk_usage("/srv/data")
        
    #     return SystemStatus(
    #         hostname=hostname,
    #         uptime_seconds=uptime_seconds,
    #         load_average=load_average,
    #         memory=MemoryStatus(
    #             total_mb=total_mb, 
    #             available_mb=available_mb
    #         ),
    #         disk=DiskStatus(
    #             total_gb=total_gb, 
    #             used_gb=used_gb, 
    #             free_gb=free_gb
    #         )
    #     )
    # except FileNotFoundError as exc:
    #     logger.error("System status failed: %s", exc)
    #     raise HTTPException(status_code=500, detail="System storage path unavailable")

# === Services Endpoints ===
type ServiceAction = Literal["start", "stop", "restart"]

def perform_service_action(
        service_id: int,
        action: ServiceAction,
        db: Session
) -> RuntimeActionResponse:
    service = db.get(ManagedService, service_id)

    if service is None:
        raise HTTPException(
            status_code=404,
            detail="Service not found",
        )

    if service.name == "jellyfin" or service.runtime_name == "jellyfin":
        raise HTTPException(409, "Jellyfin runs on the Cronus VM; remote controls are not enabled")

    if service.runtime_type != "docker":
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported runtime type: {service.runtime_type}",
        )

    if not service.runtime_name:
        raise HTTPException(
            status_code=409,
            detail="Service has no runtime name",
        )

    try:
        match action:
            case "start":
                result = start_runtime(service.runtime_name)
            case "stop":
                result = stop_runtime(service.runtime_name)
            case "restart":
                result = restart_runtime(service.runtime_name)
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail="Atlas Agent is unavailable"
        ) from exc

    if result["ok"] is False:
        logger.error(
            "Service action failed: id=%s action=%s error=%s",
            service_id,
            action,
            result["error"]
        )

        raise HTTPException(
            status_code=502,
            detail=result["error"]
        )

    return RuntimeActionResponse(
        name=result["name"],
        action=result["action"],
        output=result["output"]
    )

@app.post("/services/{service_id}/start", response_model=RuntimeActionResponse)
def start_service(
    service_id: int,
    current_user: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
):
    return perform_service_action(
        service_id=service_id,
        action="start",
        db=db,
    )

@app.post("/services/{service_id}/stop", response_model=RuntimeActionResponse)
def stop_service(
    service_id: int,
    current_user: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
):
    return perform_service_action(
        service_id=service_id,
        action="stop",
        db=db,
    )

@app.post("/services/{service_id}/restart", response_model=RuntimeActionResponse)
def restart_service(
    service_id: int,
    current_user: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
):
    return perform_service_action(
        service_id=service_id,
        action="restart",
        db=db,
    )

@app.get("/services", response_model=list[ManagedServiceResponse])
def list_services(
    current_user: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db)
):
    services = get_managed_services(db)

    response: list[ManagedServiceResponse] = []
    try:
        remote = get_service_resources().readings.get("cronus-jellyfin/jellyfin")
    except (OSError, RuntimeError, ValueError):
        remote = None

    for service in services:
        runtime: RuntimeInfo | None = None

        is_remote = service.name == "jellyfin"
        if is_remote:
            runtime = RuntimeInfo(state=remote.state) if remote else None
        elif service.runtime_type == "docker" and service.runtime_name:
            try:    
                result = get_runtime_status(service.runtime_name)

            
                if result["ok"] is True:
                    runtime = RuntimeInfo(state=result["state"])
            except (OSError, RuntimeError):
                runtime = None

        response.append(
            ManagedServiceResponse(
                id=service.id,
                name=service.name,
                display_name=service.display_name,
                node_id="cronus-jellyfin" if is_remote else "atlas",
                node_label="Cronus VM" if is_remote else "Atlas",
                controls_available=not is_remote,
                resource_key="cronus-jellyfin/jellyfin" if is_remote else service.runtime_name,
                runtime_type="remote_docker" if is_remote else service.runtime_type,
                runtime_name=service.runtime_name,
                runtime=runtime
            )
        )

    return response
  
@app.get("/services/resources", response_model=ResourceSnapshot)
def service_resources(
    current_user: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> ResourceSnapshot:
    names = {"cronus-jellyfin/jellyfin" if s.name == "jellyfin" else s.runtime_name
             for s in get_managed_services(db) if s.runtime_type == "docker"}
    try:
        snapshot = get_service_resources()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(503, "Service telemetry is temporarily unavailable") from exc
    return ResourceSnapshot(ok=True, readings={name:row for name,row in snapshot.readings.items() if name in names})


@app.post("/services", response_model=ManagedServiceResponse)
async def add_service(
    service: ManagedServiceCreate,
    current_user: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
):
    try:
        return create_managed_service(
            session=db, 
            name=service.name, 
            display_name=service.display_name,
            runtime_type=service.runtime_type,
            runtime_name=service.runtime_name
        )
    except IntegrityError:
        logger.error("Service creation failed: %s", service.name)
        raise HTTPException(
            status_code=409, 
            detail="Service already exists"
        )

@app.get(
    "/services/{service_id}/minecraft/status",
    response_model=MinecraftStatusResponse,
)
def minecraft_status(
    service_id: int,
    current_user: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> MinecraftStatusResponse:
    service = db.get(ManagedService, service_id)

    if service is None:
        raise HTTPException(
            status_code=404,
            detail="Service not found",
        )

    if service.runtime_type != "docker" or service.runtime_name not in {"minecraft", "minecraft-craftbox"}:
        raise HTTPException(
            status_code=400,
            detail="Service is not a Minecraft service",
        )

    try:
        result = get_minecraft_status(service.runtime_name)
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail="Atlas Agent is unavailable",
        ) from exc

    if result["ok"] is False:
        raise HTTPException(
            status_code=502,
            detail=result["error"],
        )

    return MinecraftStatusResponse(
        online=result["online"],
        max=result["max"],
        players=result["players"],
        tps=result["tps"],
        mspt=result["mspt"],
        loaded_chunks=result["loaded_chunks"]
    )

# === Auth Endpoints
@app.get("/auth/me", response_model=CurrentUserResponse)
async def get_me(
    current_user: User = Depends(get_current_user)
):
    return current_user

@app.post("/auth/login", response_model=TokenResponse)
async def login(
    login_request: LoginRequest,
    db: Session = Depends(get_db)
):
    user = get_user_by_username(db, login_request.username)
    
    if not user or not verify_password(login_request.password, user.password_hash):
        logger.warning("Login failed for user: %s", login_request.username)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not user.active:
            logger.warning("Login attempt for inactive user: %s", login_request.username)
            raise HTTPException(status_code=401, detail="Invalid username or password")
    
    access_token = create_access_token(
        username=user.username, 
        role=user.role
    )
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer"
)

@app.post("/auth/refresh", response_model=TokenResponse)
async def refresh_session(current_user: User = Depends(get_current_user)) -> TokenResponse:
    """Renew a still-valid session using the active user's current database role."""
    return TokenResponse(
        access_token=create_access_token(username=current_user.username, role=current_user.role),
        token_type="bearer",
    )
