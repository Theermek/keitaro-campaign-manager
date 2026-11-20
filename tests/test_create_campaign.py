import re

import httpx
import pytest

from app.models import OperationLog

VALID = {"name": "test_akella_new", "geo": "au", "offer_id": 3749}


def test_creates_campaign_and_two_flows(client, kt, db):
    r = client.post("/api/campaigns", json=VALID)
    assert r.status_code == 201
    body = r.json()

    (_, _, campaign), (_, _, flow1), (_, _, flow2) = kt.writes
    assert campaign["name"] == "test_akella_new"
    assert re.fullmatch(r"[a-z0-9]{8}", campaign["alias"])
    assert {k: campaign[k] for k in ("type", "domain_id", "group_id", "traffic_source_id")} == {
        "type": "position", "domain_id": 1813, "group_id": 10332, "traffic_source_id": 836,
    }
    assert flow1 == {
        "campaign_id": body["id"], "type": "regular", "name": "Flow 1", "position": 1,
        "schema": "redirect", "action_type": "http", "action_payload": "https://google.com",
        "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}],
    }
    assert flow2 == {
        "campaign_id": body["id"], "type": "regular", "name": "Flow 2", "position": 2,
        "schema": "landings", "action_type": "http",
        "offers": [{"offer_id": 3749, "share": 100, "state": "active"}],
    }
    assert body["url"] == f"https://tracker.example/{campaign['alias']}"
    assert [s["name"] for s in body["streams"]] == ["Flow 1", "Flow 2"]
    assert db.query(OperationLog).count() == 3


@pytest.mark.parametrize(
    ("override", "status"),
    [
        ({"name": "other_campaign"}, 422),
        ({"name": "test_akella_"}, 422),
        ({"geo": "AUS"}, 422),
        ({"geo": "A1"}, 422),
        ({"geo": ""}, 422),
        ({"offer_id": 999}, 422),
        ({"offer_id": 500}, 422),  # deleted offer
    ],
)
def test_validation_sends_nothing(client, kt, override, status):
    r = client.post("/api/campaigns", json={**VALID, **override})
    assert r.status_code == status
    assert kt.writes == []


def test_duplicate_name(client, kt):
    kt.add_campaign("test_akella_new")
    r = client.post("/api/campaigns", json=VALID)
    assert r.status_code == 409
    assert kt.writes == []


def test_offer_added_after_cache_is_found(client, kt):
    client.get("/api/offers")
    kt.offers.append({"id": 777, "name": "Fresh", "state": "active"})
    assert client.post("/api/campaigns", json={**VALID, "offer_id": 777}).status_code == 201


def test_flow_failure_keeps_campaign_and_reports_it(client, kt):
    calls = {"n": 0}
    original = kt._post

    def failing_second_stream(path, request, body):
        if path == "/streams":
            calls["n"] += 1
            if calls["n"] == 2:
                return httpx.Response(422, json={"offers": ["Offer is invalid"]})
        return original(path, request, body)

    kt._post = failing_second_stream
    r = client.post("/api/campaigns", json=VALID)
    assert r.status_code == 502
    body = r.json()
    assert body["campaign_id"] in kt.campaigns
    assert [s["name"] for s in body["created_streams"]] == ["Flow 1"]
    assert "Offer is invalid" in body["error"]
    # Nothing is deleted automatically
    assert all(method == "POST" for method, _, _ in kt.writes)


def test_campaign_creation_error_is_passed_through(client, kt):
    kt.failures[("POST", "/campaigns")] = httpx.Response(422, json={"alias": ["Alias is taken"]})
    r = client.post("/api/campaigns", json=VALID)
    assert r.status_code == 422
    assert r.json()["detail"] == "alias: Alias is taken"
