"""Editor of offers in campaign streams.

Keitaro is the source of truth for active offers and their shares. The
`stream_offer` snapshot adds what Keitaro does not keep: removed offers
(to show them and bring them back) and pinned shares.
"""

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.keitaro.client import KeitaroClient
from app.models import OfferStatus, StreamOffer
from app.schemas import (
    CampaignItem,
    CampaignStreams,
    EditorOffer,
    EditorStream,
    PushRequest,
    ReadonlyStream,
)
from app.services import catalog
from app.services.shares import TOTAL

OFFERS_SCHEMA = "landings"


def load_campaign(
    client: KeitaroClient, db: Session, settings: Settings, campaign_id: int
) -> CampaignStreams:
    """Reads streams from Keitaro and syncs the snapshot ("Fetch streams from KT").

    Offers that disappeared from Keitaro become removed with 0%; shares of the
    rest are left as they are in Keitaro (no rebalancing on fetch).
    """
    campaign = client.get_campaign(campaign_id)
    _check_own(campaign, settings)

    streams, others = [], []
    for stream in sorted(client.get_campaign_streams(campaign_id), key=lambda s: s["position"]):
        if stream.get("schema") == OFFERS_SCHEMA:
            streams.append(_sync_stream(client, db, stream))
        else:
            others.append(_readonly(stream))
    db.commit()
    return CampaignStreams(
        campaign=CampaignItem.model_validate(campaign), streams=streams, other_streams=others
    )


def push_offers(
    client: KeitaroClient, db: Session, settings: Settings, stream_id: int, data: PushRequest
) -> EditorStream:
    """Publishes the draft of a stream to Keitaro ("Push to KT")."""
    stream = client.get_stream(stream_id)
    _check_own(client.get_campaign(stream["campaign_id"]), settings)
    if stream.get("schema") != OFFERS_SCHEMA:
        raise AppError(422, f"Stream {stream_id} has no offers to edit")

    current = {(o["offer_id"], o["share"]) for o in stream["offers"]}
    if current != {(o.offer_id, o.share) for o in data.base}:
        raise AppError(409, "The stream was changed in Keitaro. Fetch streams again.")

    _validate_push(client, stream, data)

    states = {o["offer_id"]: o.get("state", "active") for o in stream["offers"]}
    offers = [
        {"offer_id": o.offer_id, "share": o.share, "state": states.get(o.offer_id, "active")}
        for o in data.offers
        if not o.removed
    ]
    updated = client.update_stream_offers(stream_id, offers)

    # Remember pins and offers removed in this draft before syncing with Keitaro
    rows = _rows_by_offer(db, stream_id)
    for o in data.offers:
        row = rows.get(o.offer_id)
        if row is None:
            if o.removed:
                continue  # added and removed in the same draft: nothing to keep
            row = StreamOffer(stream_id=stream_id, campaign_id=stream["campaign_id"], offer_id=o.offer_id)
            db.add(row)
            rows[o.offer_id] = row
        row.pinned = o.pinned and not o.removed
        row.offer_name = o.name or row.offer_name
    db.flush()

    result = _sync_stream(client, db, {**stream, "offers": updated.get("offers", offers)})
    db.commit()
    return result


def set_pinned(db: Session, stream_id: int, offer_id: int, pinned: bool) -> None:
    row = _rows_by_offer(db, stream_id).get(offer_id)
    if row is None:
        raise AppError(404, f"Offer {offer_id} is not saved in stream {stream_id}")
    row.pinned = pinned
    db.commit()


def _sync_stream(client: KeitaroClient, db: Session, stream: dict) -> EditorStream:
    rows = _rows_by_offer(db, stream["id"])
    names = catalog.offer_names(client)
    in_keitaro = set()

    for position, kt_offer in enumerate(stream["offers"]):
        offer_id = kt_offer["offer_id"]
        in_keitaro.add(offer_id)
        row = rows.get(offer_id)
        if row is None:
            row = StreamOffer(stream_id=stream["id"], campaign_id=stream["campaign_id"], offer_id=offer_id)
            db.add(row)
            rows[offer_id] = row
        row.status = OfferStatus.ACTIVE
        row.share = kt_offer["share"]
        row.kt_position = position
        row.offer_name = names.get(offer_id, row.offer_name)

    for offer_id, row in rows.items():
        if offer_id not in in_keitaro and row.status == OfferStatus.ACTIVE:
            row.status = OfferStatus.REMOVED
            row.share = 0
            row.pinned = False
    db.flush()

    # Active offers in Keitaro order first, then removed ones
    ordered = sorted(
        rows.values(), key=lambda r: (r.status == OfferStatus.REMOVED, r.kt_position, r.id)
    )
    return EditorStream(
        id=stream["id"],
        name=stream["name"],
        position=stream["position"],
        offers=[
            EditorOffer(
                offer_id=r.offer_id,
                name=r.offer_name,
                share=r.share,
                pinned=r.pinned,
                removed=r.status == OfferStatus.REMOVED,
            )
            for r in ordered
        ],
    )


def _validate_push(client: KeitaroClient, stream: dict, data: PushRequest) -> None:
    duplicates = [oid for oid, n in Counter(o.offer_id for o in data.offers).items() if n > 1]
    if duplicates:
        raise AppError(422, f"Duplicate offers: {duplicates}")

    active = [o for o in data.offers if not o.removed]
    total = sum(o.share for o in active)
    if active and total != TOTAL:
        raise AppError(422, f"Shares of active offers sum to {total}%, must be {TOTAL}%")

    # Offers already in the stream may be invisible to the API key (403), so only new ones are checked
    existing = {o["offer_id"] for o in stream["offers"]}
    for o in active:
        if o.offer_id not in existing and not catalog.offer_exists(client, o.offer_id):
            raise AppError(422, f"Offer {o.offer_id} not found or not available")


def _readonly(stream: dict) -> ReadonlyStream:
    payload = stream.get("action_payload")
    return ReadonlyStream(
        id=stream["id"],
        name=stream["name"],
        position=stream["position"],
        schema=stream.get("schema") or "",
        action_type=stream.get("action_type"),
        action_payload=payload if isinstance(payload, str) else None,
        filters=[
            f"{f['name']} {f['mode']} {', '.join(map(str, f.get('payload') or []))}"
            for f in stream.get("filters", [])
        ],
    )


def _rows_by_offer(db: Session, stream_id: int) -> dict[int, StreamOffer]:
    rows = db.scalars(select(StreamOffer).where(StreamOffer.stream_id == stream_id))
    return {r.offer_id: r for r in rows}


def _check_own(campaign: dict, settings: Settings) -> None:
    if not str(campaign.get("name", "")).startswith(settings.campaign_prefix):
        raise AppError(403, f"Only campaigns starting with '{settings.campaign_prefix}' can be edited")
