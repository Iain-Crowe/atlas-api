from fastapi import APIRouter, Depends, HTTPException
from app.db_models import User
from app.security import require_role
from app.media_models import MediaSnapshot
from app.services.runtime.agent import get_media_status

router = APIRouter()

@router.get('/media/status', response_model=MediaSnapshot)
def media_status(user: User = Depends(require_role('viewer'))) -> MediaSnapshot:
    try:
        return get_media_status()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(503, 'Media telemetry is temporarily unavailable') from exc
