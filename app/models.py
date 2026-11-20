from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OfferStatus(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"


class StreamOffer(Base):
    """Snapshot of an offer in a Keitaro stream.

    Keitaro forgets removed offers and has no notion of pinned shares,
    so both are kept here.
    """

    __tablename__ = "stream_offer"
    __table_args__ = (UniqueConstraint("stream_id", "offer_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(Integer, index=True)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    offer_id: Mapped[int] = mapped_column(Integer)
    # Cached: the API key may get 403 on some offers
    offer_name: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[OfferStatus] = mapped_column(String(16), default=OfferStatus.ACTIVE)
    pinned: Mapped[bool] = mapped_column(default=False)
    share: Mapped[int] = mapped_column(Integer, default=0)
    # Order of the offer inside the stream as returned by Keitaro
    kt_position: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class OperationLog(Base):
    """Audit of every mutating request sent to Keitaro."""

    __tablename__ = "operation_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(255))
    campaign_id: Mapped[int | None] = mapped_column(Integer, index=True)
    status_code: Mapped[int | None] = mapped_column(Integer)
    request_body: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
