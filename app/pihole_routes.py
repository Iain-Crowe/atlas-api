from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.db_models import ManagedService, User
from app.security import require_role
from app.pihole_models import PiHoleSnapshot
from app.services.runtime.agent import get_pihole_status

router = APIRouter()

@router.get('/services/{service_id}/pihole/status', response_model=PiHoleSnapshot)
def pihole_status(service_id: int, user: User = Depends(require_role('viewer')),
                  db: Session = Depends(get_db)) -> PiHoleSnapshot:
    service = db.get(ManagedService, service_id)
    if service is None:
        raise HTTPException(404, 'Service not found')
    if service.name != 'pihole' or service.runtime_type != 'docker' or service.runtime_name != 'pihole':
        raise HTTPException(400, 'Service is not the configured Pi-hole service')
    try:
        return get_pihole_status()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(503, 'Pi-hole telemetry is temporarily unavailable') from exc
