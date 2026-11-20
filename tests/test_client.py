import httpx
import pytest

from app.config import get_settings
from app.keitaro.client import KeitaroClient
from app.keitaro.errors import ForbiddenCampaignError, KeitaroError


@pytest.fixture
def records():
    return []


@pytest.fixture
def kc(kt, records):
    client = KeitaroClient(get_settings(), audit=records.append)
    yield client
    client.close()


def test_sends_api_key_and_uses_base_path(kt, kc):
    kt.add_campaign("test_akella_a")
    assert len(kc.list_campaigns()) == 1
    assert kt.api_keys == ["test-key"]


def test_create_campaign_rejects_foreign_name(kt, kc):
    with pytest.raises(ForbiddenCampaignError):
        kc.create_campaign({"name": "other_campaign", "alias": "x"})
    assert kt.writes == []


def test_create_stream_rejects_foreign_campaign(kt, kc):
    foreign = kt.add_campaign("someone_else")
    with pytest.raises(ForbiddenCampaignError):
        kc.create_stream({"campaign_id": foreign["id"], "name": "Flow"})
    assert kt.writes == []


def test_create_stream_requires_campaign_id(kt, kc):
    with pytest.raises(ForbiddenCampaignError):
        kc.create_stream({"name": "Flow"})
    assert kt.writes == []


def test_update_offers_rejects_foreign_stream(kt, kc):
    foreign = kt.add_campaign("someone_else")
    stream = kt.add_stream(foreign["id"], "Flow 2", 2)
    with pytest.raises(ForbiddenCampaignError):
        kc.update_stream_offers(stream["id"], [])
    assert kt.writes == []


def test_guard_rereads_campaign_name(kt, kc):
    # A campaign renamed in Keitaro loses write access
    own = kt.add_campaign("test_akella_a")
    stream = kt.add_stream(own["id"], "Flow 2", 2)
    own["name"] = "renamed"
    with pytest.raises(ForbiddenCampaignError):
        kc.update_stream_offers(stream["id"], [])


def test_update_offers_on_own_stream(kt, kc, records):
    own = kt.add_campaign("test_akella_a")
    stream = kt.add_stream(own["id"], "Flow 2", 2)
    kc.update_stream_offers(stream["id"], [{"offer_id": 3749, "share": 100, "state": "active"}])
    assert kt.offer_shares(stream["id"]) == [(3749, 100)]
    assert [(r.method, r.path, r.campaign_id, r.status_code, r.error) for r in records] == [
        ("PUT", f"/streams/{stream['id']}", own["id"], 200, None)
    ]


def test_failed_write_is_audited(kt, kc, records):
    with pytest.raises(KeitaroError) as exc:
        kc.create_campaign({"name": "test_akella_a"})  # no alias
    assert exc.value.status_code == 422
    assert exc.value.message == "alias: Alias is required"
    assert records[0].status_code == 422
    assert records[0].error == "alias: Alias is required"


def test_error_message_from_error_field(kt, kc):
    kt.failures[("GET", "/offers/1")] = httpx.Response(403, json={"error": "No permission"})
    with pytest.raises(KeitaroError) as exc:
        kc.get_offer(1)
    assert (exc.value.status_code, exc.value.message, exc.value.path) == (403, "No permission", "/offers/1")


def test_non_json_error(kt, kc):
    with pytest.raises(KeitaroError) as exc:
        kc.get_campaign(424242)
    assert (exc.value.status_code, exc.value.message) == (404, "Keitaro error 404")


def test_non_json_success_body(kt, kc):
    kt.failures[("GET", "/offers")] = httpx.Response(200, text="<html>")
    with pytest.raises(KeitaroError, match="non-JSON"):
        kc.list_offers()


def test_timeout_message_has_no_url(kt, kc):
    kt.failures[("GET", "/offers")] = httpx.ReadTimeout("timed out https://kt.test/admin_api/v1/offers")
    with pytest.raises(KeitaroError) as exc:
        kc.list_offers()
    assert exc.value.timed_out
    assert "kt.test" not in str(exc.value)


def test_network_error_message_has_no_url(kt, kc):
    kt.failures[("GET", "/offers")] = httpx.ConnectError("cannot connect to https://kt.test")
    with pytest.raises(KeitaroError) as exc:
        kc.list_offers()
    assert exc.value.status_code is None
    assert "kt.test" not in exc.value.message
