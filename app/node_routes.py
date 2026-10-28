from fastapi import APIRouter, Depends, HTTPException, Response
from app.node_models import NodeSnapshot
from app.security import require_role
from app.services.runtime.agent import send_agent_request

router = APIRouter(prefix='/nodes', dependencies=[Depends(require_role('viewer'))])


@router.get('/status', response_model=NodeSnapshot)
def node_status(response: Response) -> NodeSnapshot:
    response.headers['Cache-Control'] = 'no-store'
    try:
        result = send_agent_request('node_status')
    except OSError as exc:
        raise HTTPException(503, 'Node telemetry unavailable') from exc
    if not isinstance(result, NodeSnapshot):
        raise HTTPException(502, 'Invalid node telemetry')
    return result
