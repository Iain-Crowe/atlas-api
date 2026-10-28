from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.db_models import ManagedService, User
from app.security import require_role
from app.jellyfin_models import JellyfinSnapshot
from app.services.runtime.agent import get_jellyfin_status

router = APIRouter()


@router.get('/services/{service_id}/jellyfin/status', response_model=JellyfinSnapshot)
def jellyfin_status(service_id: int, user: User = Depends(require_role('viewer')),
                    db: Session = Depends(get_db)) -> JellyfinSnapshot:
    service = db.get(ManagedService, service_id)
    if service is None:
        raise HTTPException(404, 'Service not found')
    if (service.name != 'jellyfin' or service.runtime_type != 'docker'
            or service.runtime_name != 'jellyfin'):
        raise HTTPException(400, 'Service is not the configured Jellyfin service')
    try:
        return get_jellyfin_status()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(503, 'Jellyfin telemetry is temporarily unavailable') from exc
