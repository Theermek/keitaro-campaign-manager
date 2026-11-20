"""Read-only data from Keitaro: reference objects, offers, own campaigns."""

from app.cache import TTLValue
from app.config import Settings
from app.keitaro.client import KeitaroClient
from app.schemas import CampaignItem, OfferItem, Reference, RefItem

OFFERS_TTL = 300
REFERENCE_TTL = 600
OFFER_SEARCH_LIMIT = 20

_offers: TTLValue[list[OfferItem]] = TTLValue(OFFERS_TTL)
_reference: TTLValue[Reference] = TTLValue(REFERENCE_TTL)


class ReferenceNotFoundError(Exception):
    """A domain, group or source from the config does not exist in Keitaro."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def get_reference(client: KeitaroClient, settings: Settings) -> Reference:
    return _reference.get(lambda: _load_reference(client, settings))


def _load_reference(client: KeitaroClient, settings: Settings) -> Reference:
    return Reference(
        domain=_find("Domain", settings.keitaro_domain, client.list_domains()),
        group=_find("Campaign group", settings.keitaro_group, client.list_campaign_groups()),
        source=_find("Traffic source", settings.keitaro_source, client.list_traffic_sources()),
    )


def _find(kind: str, name: str, items: list[dict]) -> RefItem:
    matches = [i for i in items if i.get("name") == name and i.get("state", "active") == "active"]
    if not matches:
        raise ReferenceNotFoundError(f"{kind} '{name}' not found in Keitaro")
    if len(matches) > 1:
        raise ReferenceNotFoundError(f"{kind} '{name}' is ambiguous in Keitaro")
    return RefItem(id=matches[0]["id"], name=name)


def search_offers(client: KeitaroClient, query: str) -> list[OfferItem]:
    """Matches by offer id prefix or by name substring, case-insensitive.

    Keitaro has no offer search, so the full list is cached and filtered here.
    """
    offers = _offers.get(lambda: _load_offers(client))
    q = query.strip().lower()
    if not q:
        return offers[:OFFER_SEARCH_LIMIT]
    found = [o for o in offers if str(o.id).startswith(q) or q in o.name.lower()]
    return found[:OFFER_SEARCH_LIMIT]


def offer_names(client: KeitaroClient) -> dict[int, str]:
    return {o.id: o.name for o in _offers.get(lambda: _load_offers(client))}


def offer_exists(client: KeitaroClient, offer_id: int) -> bool:
    if any(o.id == offer_id for o in _offers.get(lambda: _load_offers(client))):
        return True
    # The offer may have been added after the cache was filled
    _offers.clear()
    return any(o.id == offer_id for o in _offers.get(lambda: _load_offers(client)))


def _load_offers(client: KeitaroClient) -> list[OfferItem]:
    return [
        OfferItem(id=o["id"], name=o["name"])
        for o in client.list_offers()
        if o.get("state") == "active"
    ]


def list_own_campaigns(client: KeitaroClient, settings: Settings) -> list[CampaignItem]:
    campaigns = [
        CampaignItem.model_validate(c)
        for c in client.list_campaigns()
        if c.get("name", "").startswith(settings.campaign_prefix)
    ]
    return sorted(campaigns, key=lambda c: c.id, reverse=True)
