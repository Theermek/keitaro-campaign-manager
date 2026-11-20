from fastapi import APIRouter, Depends, Query

from app.config import Settings, get_settings
from app.deps import get_keitaro
from app.keitaro.client import KeitaroClient
from app.schemas import CampaignItem, OfferItem, Reference
from app.services import catalog

router = APIRouter(prefix="/api")


@router.get("/reference")
def reference(
    client: KeitaroClient = Depends(get_keitaro),
    settings: Settings = Depends(get_settings),
) -> Reference:
    return catalog.get_reference(client, settings)


@router.get("/offers")
def offers(
    q: str = Query("", max_length=100),
    client: KeitaroClient = Depends(get_keitaro),
) -> list[OfferItem]:
    return catalog.search_offers(client, q)


@router.get("/campaigns")
def campaigns(
    client: KeitaroClient = Depends(get_keitaro),
    settings: Settings = Depends(get_settings),
) -> list[CampaignItem]:
    return catalog.list_own_campaigns(client, settings)
