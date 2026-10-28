"""Read-only maintenance endpoint; no scheduling or control actions."""
from fastapi import APIRouter, Depends, HTTPException, Response

from app.maintenance_models import MaintenanceSnapshot
from app.security import require_role
from app.services.runtime.agent import send_agent_request

router = APIRouter(
    prefix="/maintenance",
    tags=["maintenance"],
    dependencies=[Depends(require_role("viewer"))],
)


@router.get("/status", response_model=MaintenanceSnapshot)
def maintenance_status(response: Response) -> MaintenanceSnapshot:
    response.headers["Cache-Control"] = "no-store"
    try:
        result = send_agent_request("maintenance_status")
    except OSError as exc:
        raise HTTPException(
            status_code=503, detail="Maintenance agent unavailable"
        ) from exc
    if not isinstance(result, MaintenanceSnapshot):
        raise HTTPException(
            status_code=502, detail="Maintenance status unavailable"
        )
    return result
