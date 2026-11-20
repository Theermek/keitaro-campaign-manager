from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_keitaro
from app.errors import AppError
from app.keitaro.client import KeitaroClient
from app.schemas import (
    CampaignStreams,
    EditorStream,
    PinRequest,
    PushRequest,
    RebalanceRequest,
    ShareRowIn,
)
from app.services import editor
from app.services.shares import ShareError, ShareRow, rebalance

router = APIRouter(prefix="/api")


@router.get("/campaigns/{campaign_id}/streams")
def campaign_streams(
    campaign_id: int,
    client: KeitaroClient = Depends(get_keitaro),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CampaignStreams:
    return editor.load_campaign(client, db, settings, campaign_id)


@router.post("/shares/rebalance")
def rebalance_shares(data: RebalanceRequest) -> list[ShareRowIn]:
    try:
        rows = rebalance([ShareRow(**o.model_dump()) for o in data.offers])
    except ShareError as exc:
        raise AppError(422, str(exc)) from None
    return [ShareRowIn(**vars(r)) for r in rows]


@router.patch("/streams/{stream_id}/offers/{offer_id}", status_code=204)
def pin_offer(
    stream_id: int, offer_id: int, data: PinRequest, db: Session = Depends(get_db)
) -> Response:
    editor.set_pinned(db, stream_id, offer_id, data.pinned)
    return Response(status_code=204)


@router.put("/streams/{stream_id}/offers")
def push_offers(
    stream_id: int,
    data: PushRequest,
    client: KeitaroClient = Depends(get_keitaro),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EditorStream:
    return editor.push_offers(client, db, settings, stream_id, data)
