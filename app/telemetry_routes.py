from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.db_models import ManagedService, User
from app.security import require_role
from app.telemetry import HistoryRange, HistoryResponse, history

router = APIRouter()
logger = logging.getLogger('atlas-api.telemetry')


@router.get('/system/history', response_model=HistoryResponse)
def system_history(
    range: HistoryRange = Query(default='1h'),
    user: User = Depends(require_role('viewer')),
) -> HistoryResponse:
    try:
        return history('host', 0, range)
    except sqlite3.Error as exc:
        logger.exception('Host history database unavailable')
        raise HTTPException(503, 'Telemetry history is temporarily unavailable') from exc


@router.get('/services/{service_id}/minecraft/history', response_model=HistoryResponse)
def minecraft_history(
    service_id: int,
    range: HistoryRange = Query(default='1h'),
    user: User = Depends(require_role('viewer')),
    db: Session = Depends(get_db),
) -> HistoryResponse:
    service = db.get(ManagedService, service_id)
    if service is None:
        raise HTTPException(404, 'Service not found')
    if service.runtime_type != 'docker' or service.runtime_name not in {'minecraft', 'minecraft-craftbox'}:
        raise HTTPException(400, 'Service is not a Minecraft service')
    try:
        return history('minecraft', service_id, range)
    except sqlite3.Error as exc:
        logger.exception('Minecraft history database unavailable')
        raise HTTPException(503, 'Telemetry history is temporarily unavailable') from exc


# Network monitoring is read-only and does not register container controls.
from app.network_models import NetworkSnapshot, SOURCES
from app.services.runtime.agent import get_network_telemetry
from app import network_history, link_history


@router.get('/network/status', response_model=NetworkSnapshot)
def network_status(user: User = Depends(require_role('viewer'))) -> NetworkSnapshot:
    try:
        return get_network_telemetry()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(503, 'Network telemetry is temporarily unavailable') from exc


@router.get('/network/{source}/history', response_model=network_history.NetworkHistory)
def get_network_history(source: str, range: HistoryRange = Query(default='1h'),
                        user: User = Depends(require_role('viewer'))) -> network_history.NetworkHistory:
    if source not in (*SOURCES, 'link'):
        raise HTTPException(404, 'Network source not found')
    try:
        return link_history.history(range) if source == 'link' else network_history.history(source, range)
    except sqlite3.Error as exc:
        logger.exception('Network history database unavailable')
        raise HTTPException(503, 'Network history is temporarily unavailable') from exc
