import pytest

from app.models import OfferStatus, StreamOffer


@pytest.fixture
def setup(kt):
    """The campaign from the video: Flow 1 geo redirect, Flow 2 with two offers 50/50."""
    campaign = kt.add_campaign("test_akella_video")
    geo = kt.add_stream(
        campaign["id"], "Flow 1", 1, schema="redirect", action_payload="https://google.com",
        filters=[{"name": "country", "mode": "accept", "payload": ["AU"]}],
    )
    offers = kt.add_stream(campaign["id"], "Flow 2", 2)
    kt.set_offers(offers["id"], (3749, 50), (3717, 50))
    return campaign["id"], geo["id"], offers["id"]


def load(client, campaign_id):
    r = client.get(f"/api/campaigns/{campaign_id}/streams")
    assert r.status_code == 200, r.text
    return r.json()


def rows(stream):
    return [
        {k: o[k] for k in ("offer_id", "share", "pinned", "removed")} | {"name": o["name"]}
        for o in stream["offers"]
    ]


def rebalance(client, draft):
    r = client.post(
        "/api/shares/rebalance",
        json={"offers": [{k: o[k] for k in ("offer_id", "share", "pinned", "removed")} for o in draft]},
    )
    assert r.status_code == 200, r.text
    for o, new in zip(draft, r.json()):
        o["share"] = new["share"]
    return draft


def push(client, stream, draft):
    base = [{"offer_id": o["offer_id"], "share": o["share"]} for o in stream["offers"] if not o["removed"]]
    return client.put(f"/api/streams/{stream['id']}/offers", json={"base": base, "offers": draft})


def view(stream):
    return [(o["offer_id"], o["share"], o["pinned"], o["removed"]) for o in stream["offers"]]


def new_offer(offer_id, name="New"):
    return {"offer_id": offer_id, "share": 0, "pinned": False, "removed": False, "name": name}


def test_load_splits_streams(client, setup):
    campaign_id, geo_id, offers_id = setup
    data = load(client, campaign_id)
    assert data["campaign"]["name"] == "test_akella_video"
    assert [s["id"] for s in data["streams"]] == [offers_id]
    assert view(data["streams"][0]) == [(3749, 50, False, False), (3717, 50, False, False)]
    assert data["streams"][0]["offers"][0]["name"] == "Miaflow 0009"
    assert data["other_streams"] == [{
        "id": geo_id, "name": "Flow 1", "position": 1, "schema": "redirect",
        "action_type": "http", "action_payload": "https://google.com",
        "filters": ["country accept AU"],
    }]


def test_video_scenario(client, kt, setup):
    campaign_id, _, offers_id = setup
    stream = load(client, campaign_id)["streams"][0]

    # Add a third offer: 33/33/34, the new one gets the remainder
    draft = rebalance(client, rows(stream) + [new_offer(11111, "FitoMishki")])
    r = push(client, stream, draft)
    assert r.status_code == 200, r.text
    assert kt.offer_shares(offers_id) == [(3749, 33), (3717, 33), (11111, 34)]
    stream = r.json()

    # Fourth offer: 25 x 4
    stream = push(client, stream, rebalance(client, rows(stream) + [new_offer(11112)])).json()
    assert kt.offer_shares(offers_id) == [(3749, 25), (3717, 25), (11111, 25), (11112, 25)]

    # Remove one: it stays in the table as removed with 0%
    draft = rows(stream)
    draft[1]["removed"] = True
    stream = push(client, stream, rebalance(client, draft)).json()
    assert kt.offer_shares(offers_id) == [(3749, 33), (11111, 33), (11112, 34)]
    assert view(stream)[-1] == (3717, 0, False, True)
    assert view(load(client, campaign_id)["streams"][0])[-1] == (3717, 0, False, True)

    # Bring it back
    draft = rows(stream)
    draft[-1]["removed"] = False
    push(client, stream, rebalance(client, draft))
    assert kt.offer_shares(offers_id) == [(3749, 25), (11111, 25), (11112, 25), (3717, 25)]


def test_deleted_in_keitaro_becomes_removed_without_rebalance(client, kt, setup):
    campaign_id, _, offers_id = setup
    kt.set_offers(offers_id, (3749, 25), (3717, 25), (11111, 25), (11112, 25))
    load(client, campaign_id)

    kt.set_offers(offers_id, (3717, 25), (11112, 25))  # two deleted in the Keitaro admin
    stream = load(client, campaign_id)["streams"][0]
    assert view(stream) == [
        (3717, 25, False, False), (11112, 25, False, False),
        (3749, 0, False, True), (11111, 0, False, True),
    ]
    assert kt.writes == []

    # Any action rebalances: here bring one back -> three active offers
    draft = rows(stream)
    draft[2]["removed"] = False
    r = push(client, stream, rebalance(client, draft))
    assert r.status_code == 200
    assert kt.offer_shares(offers_id) == [(3717, 33), (11112, 33), (3749, 34)]


def test_pin_is_kept_on_rebalance(client, kt, setup, db):
    campaign_id, _, offers_id = setup
    assert client.patch(f"/api/streams/{offers_id}/offers/3749", json={"pinned": True}).status_code == 404

    stream = load(client, campaign_id)["streams"][0]
    assert client.patch(f"/api/streams/{offers_id}/offers/3749", json={"pinned": True}).status_code == 204
    assert kt.writes == []
    stream = load(client, campaign_id)["streams"][0]
    assert view(stream)[0] == (3749, 50, True, False)

    stream = push(client, stream, rebalance(client, rows(stream) + [new_offer(11111), new_offer(11112)])).json()
    assert kt.offer_shares(offers_id) == [(3749, 50), (3717, 16), (11111, 17), (11112, 17)]
    assert db.get(StreamOffer, _row_id(db, offers_id, 3749)).pinned


def test_pin_of_new_offer_is_saved_on_push(client, setup, db):
    campaign_id, _, offers_id = setup
    stream = load(client, campaign_id)["streams"][0]
    draft = rows(stream) + [new_offer(11111) | {"pinned": True, "share": 20}]
    push(client, stream, rebalance(client, draft))
    assert db.get(StreamOffer, _row_id(db, offers_id, 11111)).pinned


def test_removing_pinned_offer_unpins_it(client, setup, db):
    campaign_id, _, offers_id = setup
    load(client, campaign_id)
    client.patch(f"/api/streams/{offers_id}/offers/3749", json={"pinned": True})
    stream = load(client, campaign_id)["streams"][0]
    draft = rows(stream)
    draft[0].update(removed=True, pinned=False)
    stream = push(client, stream, rebalance(client, draft)).json()
    assert view(stream)[-1] == (3749, 0, False, True)
    row = db.get(StreamOffer, _row_id(db, offers_id, 3749))
    assert (row.status, row.pinned) == (OfferStatus.REMOVED, False)


def test_stale_push_is_rejected(client, kt, setup):
    campaign_id, _, offers_id = setup
    stream = load(client, campaign_id)["streams"][0]
    kt.set_offers(offers_id, (3749, 70), (3717, 30))  # changed in the admin meanwhile
    r = push(client, stream, rebalance(client, rows(stream) + [new_offer(11111)]))
    assert r.status_code == 409
    assert kt.writes == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d[0].update(share=60), "sum to 110%"),
        (lambda d: d.append(new_offer(3749)), "Duplicate"),
        (lambda d: (d[0].update(share=50), d[1].update(share=0), d.append(new_offer(999) | {"share": 50})), "Offer 999"),
    ],
)
def test_invalid_push(client, kt, setup, change, message):
    campaign_id, _, _ = setup
    stream = load(client, campaign_id)["streams"][0]
    draft = rows(stream)
    change(draft)
    r = push(client, stream, draft)
    assert r.status_code == 422
    assert message in r.json()["error"]
    assert kt.writes == []


def test_all_offers_removed_is_allowed(client, kt, setup):
    campaign_id, _, offers_id = setup
    stream = load(client, campaign_id)["streams"][0]
    draft = [o | {"removed": True, "share": 0} for o in rows(stream)]
    assert push(client, stream, draft).status_code == 200
    assert kt.offer_shares(offers_id) == []


def test_offer_hidden_from_api_key_keeps_working(client, kt, setup):
    # Offers in a stream may be invisible to the key (403 on /offers/{id})
    campaign_id, _, offers_id = setup
    kt.set_offers(offers_id, (3749, 50), (424242, 50))
    stream = load(client, campaign_id)["streams"][0]
    assert stream["offers"][1]["name"] is None
    draft = rows(stream)
    draft[0]["removed"] = True
    assert push(client, stream, rebalance(client, draft)).status_code == 200
    assert kt.offer_shares(offers_id) == [(424242, 100)]


def test_offer_state_from_keitaro_is_kept(client, kt, setup):
    campaign_id, _, offers_id = setup
    kt.streams[offers_id]["offers"][1]["state"] = "disabled"
    stream = load(client, campaign_id)["streams"][0]
    push(client, stream, rebalance(client, rows(stream) + [new_offer(11111)]))
    assert [o["state"] for o in kt.streams[offers_id]["offers"]] == ["active", "disabled", "active"]


def test_foreign_campaign_is_rejected(client, kt):
    foreign = kt.add_campaign("someone_else")
    stream = kt.add_stream(foreign["id"], "Flow 2", 2)
    kt.set_offers(stream["id"], (3749, 100))

    assert client.get(f"/api/campaigns/{foreign['id']}/streams").status_code == 403
    r = client.put(
        f"/api/streams/{stream['id']}/offers",
        json={"base": [{"offer_id": 3749, "share": 100}], "offers": [new_offer(3717) | {"share": 100}]},
    )
    assert r.status_code == 403
    assert kt.writes == []


def test_push_to_redirect_stream_is_rejected(client, kt, setup):
    _, geo_id, _ = setup
    r = client.put(f"/api/streams/{geo_id}/offers", json={"base": [], "offers": []})
    assert r.status_code == 422
    assert kt.writes == []


def test_rebalance_rejects_pins_over_100(client):
    r = client.post("/api/shares/rebalance", json={"offers": [
        {"offer_id": 1, "share": 70, "pinned": True}, {"offer_id": 2, "share": 40, "pinned": True},
    ]})
    assert r.status_code == 422


def _row_id(db, stream_id, offer_id):
    db.expire_all()
    return db.query(StreamOffer.id).filter_by(stream_id=stream_id, offer_id=offer_id).scalar()
