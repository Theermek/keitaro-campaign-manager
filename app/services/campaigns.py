"""Campaign creation: campaign + Flow 1 (geo -> google.com) + Flow 2 (offer)."""

import secrets
import string

from app.config import Settings
from app.errors import AppError
from app.keitaro.client import KeitaroClient
from app.keitaro.errors import KeitaroError
from app.schemas import CampaignCreate, CampaignCreated, StreamRef
from app.services import catalog

GEO_REDIRECT_URL = "https://google.com"
ALIAS_ALPHABET = string.ascii_lowercase + string.digits
ALIAS_LENGTH = 8


def create_campaign(
    client: KeitaroClient, settings: Settings, data: CampaignCreate
) -> CampaignCreated:
    _validate(client, settings, data)
    ref = catalog.get_reference(client, settings)

    campaign = client.create_campaign(
        {
            "name": data.name,
            # Keitaro requires an alias despite the docs saying it is generated
            "alias": _random_alias(),
            "type": "position",
            "domain_id": ref.domain.id,
            "group_id": ref.group.id,
            "traffic_source_id": ref.source.id,
        }
    )
    campaign_id = campaign["id"]

    streams: list[StreamRef] = []
    try:
        for payload in (_geo_flow(campaign_id, data.geo), _offer_flow(campaign_id, data.offer_id)):
            stream = client.create_stream(payload)
            streams.append(StreamRef(id=stream["id"], name=stream["name"]))
    except KeitaroError as exc:
        # The campaign stays in Keitaro (agreed): report what exists so it can be fixed by hand
        raise AppError(
            502,
            f"Campaign {campaign_id} was created, but a flow failed: {exc.message}",
            campaign_id=campaign_id,
            created_streams=[s.model_dump() for s in streams],
        ) from None

    return CampaignCreated(
        id=campaign_id,
        name=campaign["name"],
        alias=campaign["alias"],
        url=_campaign_url(campaign),
        streams=streams,
    )


def _validate(client: KeitaroClient, settings: Settings, data: CampaignCreate) -> None:
    prefix = settings.campaign_prefix
    if not data.name.startswith(prefix) or data.name == prefix:
        raise AppError(422, f"Name must start with '{prefix}' and have a suffix")
    if any(c.name == data.name for c in catalog.list_own_campaigns(client, settings)):
        raise AppError(409, f"Campaign '{data.name}' already exists")
    if not catalog.offer_exists(client, data.offer_id):
        raise AppError(422, f"Offer {data.offer_id} not found or not available")


def _geo_flow(campaign_id: int, geo: str) -> dict:
    return {
        "campaign_id": campaign_id,
        "type": "regular",
        "name": "Flow 1",
        "position": 1,
        "schema": "redirect",
        "action_type": "http",
        "action_payload": GEO_REDIRECT_URL,
        "filters": [{"name": "country", "mode": "accept", "payload": [geo]}],
    }


def _offer_flow(campaign_id: int, offer_id: int) -> dict:
    return {
        "campaign_id": campaign_id,
        "type": "regular",
        "name": "Flow 2",
        "position": 2,
        "schema": "landings",
        "action_type": "http",
        "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
    }


def _random_alias() -> str:
    return "".join(secrets.choice(ALIAS_ALPHABET) for _ in range(ALIAS_LENGTH))


def _campaign_url(campaign: dict) -> str | None:
    # Keitaro returns the domain as "https://example.com/"
    domain = campaign.get("domain")
    if not domain or not campaign.get("alias"):
        return None
    return f"{domain.rstrip('/')}/{campaign['alias']}"
