def test_reference_resolves_ids(client):
    r = client.get("/api/reference")
    assert r.status_code == 200
    assert r.json() == {
        "domain": {"id": 1813, "name": "tracker.example"},
        "group": {"id": 10332, "name": "FORTESTS"},
        "source": {"id": 836, "name": "FORTESTS"},
    }


def test_reference_unknown_name(client, kt):
    kt.domains = [{"id": 1, "name": "other.com", "state": "active"}]
    r = client.get("/api/reference")
    assert r.status_code == 500
    assert r.json() == {"error": "Domain 'tracker.example' not found in Keitaro"}


def test_reference_ignores_deleted_and_ambiguous(client, kt):
    kt.sources = [
        {"id": 1, "name": "FORTESTS", "state": "deleted"},
        {"id": 2, "name": "FORTESTS", "state": "active"},
        {"id": 3, "name": "FORTESTS", "state": "active"},
    ]
    r = client.get("/api/reference")
    assert r.status_code == 500
    assert "ambiguous" in r.json()["error"]


def test_offers_all_active(client):
    r = client.get("/api/offers")
    assert [o["id"] for o in r.json()] == [3749, 3717, 11111, 11112]


def test_offers_search_by_id_prefix_and_name(client):
    assert [o["id"] for o in client.get("/api/offers?q=1111").json()] == [11111, 11112]
    assert [o["id"] for o in client.get("/api/offers?q=MIAFLOW").json()] == [3749, 3717]
    assert client.get("/api/offers?q=nothing").json() == []


def test_offers_are_cached(client, kt):
    client.get("/api/offers")
    client.get("/api/offers?q=oxy")
    assert len(kt.api_keys) == 1


def test_offers_query_length_limit(client):
    assert client.get("/api/offers?q=" + "x" * 101).status_code == 422


def test_campaigns_only_own_and_without_token(client, kt):
    kt.add_campaign("someone_else")
    first = kt.add_campaign("test_akella_one")
    second = kt.add_campaign("test_akella_two")
    body = client.get("/api/campaigns").json()
    assert [c["id"] for c in body] == [second["id"], first["id"]]
    assert all("token" not in c for c in body)
