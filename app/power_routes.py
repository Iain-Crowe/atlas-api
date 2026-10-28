"""Bounded authenticated power history and CSV, served through the private Agent."""
import csv
import io
import time
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from app.power_models import PowerSnapshot
from app.security import require_role
from app.services.runtime.agent import send_agent_request

router = APIRouter(prefix='/power', tags=['power'], dependencies=[Depends(require_role('viewer'))])

def result(days: int) -> dict[str, object]:
    try:
        value = send_agent_request('power_status')
    except OSError as exc:
        raise HTTPException(503, 'Power history unavailable') from exc
    if not isinstance(value, PowerSnapshot):
        raise HTTPException(503, 'Power history not yet available')
    data = value.model_dump()
    now = time.time()
    fresh = (0 <= now - value.generated_at <= 90 and value.last_success_at is not None
             and 0 <= now - value.last_success_at <= 90)
    data['communication'] = 'current' if fresh and not value.error else 'unavailable'
    data['as_of'] = value.generated_at
    data['days'] = data['days'][-days:]
    # Never imply the last successful wattage is current after failed collection.
    data['current_watts'] = value.latest.watts if fresh and not value.error and value.latest else None
    return data

@router.get('/history')
def history(response: Response, days: int = Query(30, ge=1, le=90)) -> dict[str, object]:
    response.headers['Cache-Control'] = 'no-store'
    return result(days)

@router.get('/export.csv')
def export(days: int = Query(30, ge=1, le=90)) -> Response:
    data = result(days)
    output = io.StringIO(newline='')
    columns = ('day', 'day_seconds', 'elapsed_seconds', 'covered_seconds', 'coverage',
               'kwh', 'utility_kwh', 'battery_kwh', 'unknown_kwh', 'cost', 'average_watts', 'partial', 'revisions')
    writer = csv.writer(output)
    writer.writerow(('source', 'timezone', 'as_of_utc_epoch', *columns))
    for row in data['days']:
        writer.writerow((data['source'], data['timezone'], data['as_of'], *(row[c] for c in columns)))
    return Response(output.getvalue(), media_type='text/csv', headers={
        'Cache-Control': 'no-store', 'Content-Disposition': 'attachment; filename="atlas-power-estimates.csv"'})
