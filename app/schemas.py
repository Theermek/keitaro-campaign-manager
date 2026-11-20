from pydantic import BaseModel, Field, field_validator


class RefItem(BaseModel):
    id: int
    name: str


class Reference(BaseModel):
    domain: RefItem
    group: RefItem
    source: RefItem


class OfferItem(BaseModel):
    id: int
    name: str


class CampaignItem(BaseModel):
    id: int
    name: str
    alias: str
    state: str
    updated_at: str | None = None


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    geo: str
    offer_id: int

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip()

    @field_validator("geo")
    @classmethod
    def check_geo(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 2 or not v.isascii() or not v.isalpha():
            raise ValueError("geo must be a two-letter country code, e.g. AU")
        return v


class StreamRef(BaseModel):
    id: int
    name: str


class CampaignCreated(BaseModel):
    id: int
    name: str
    alias: str
    url: str | None
    streams: list[StreamRef]


class EditorOffer(BaseModel):
    offer_id: int
    name: str | None
    share: int
    pinned: bool
    removed: bool


class EditorStream(BaseModel):
    id: int
    name: str
    position: int
    offers: list[EditorOffer]


class ReadonlyStream(BaseModel):
    """A stream without offers (e.g. geo redirect), shown as is."""

    id: int
    name: str
    position: int
    schema_: str = Field(alias="schema", serialization_alias="schema")
    action_type: str | None
    action_payload: str | None
    filters: list[str]


class CampaignStreams(BaseModel):
    campaign: CampaignItem
    streams: list[EditorStream]
    other_streams: list[ReadonlyStream]


class ShareRowIn(BaseModel):
    offer_id: int
    share: int = Field(ge=0, le=100)
    pinned: bool = False
    removed: bool = False


class RebalanceRequest(BaseModel):
    offers: list[ShareRowIn]


class OfferShare(BaseModel):
    offer_id: int
    share: int


class PushOffer(ShareRowIn):
    name: str | None = None


class PushRequest(BaseModel):
    # What the user saw when the stream was loaded, to detect concurrent changes
    base: list[OfferShare]
    # Keitaro order; removed offers included to keep them in the snapshot
    offers: list[PushOffer]


class PinRequest(BaseModel):
    pinned: bool
