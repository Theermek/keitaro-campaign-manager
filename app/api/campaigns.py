from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.deps import get_keitaro
from app.keitaro.client import KeitaroClient
from app.schemas import CampaignCreate, CampaignCreated
from app.services import campaigns

router = APIRouter(prefix="/api")


@router.post("/campaigns", status_code=201)
def create_campaign(
    data: CampaignCreate,
    client: KeitaroClient = Depends(get_keitaro),
    settings: Settings = Depends(get_settings),
) -> CampaignCreated:
    return campaigns.create_campaign(client, settings, data)
