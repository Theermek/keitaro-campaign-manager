import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.parametrize(
    ("keitaro_response", "status", "error"),
    [
        (httpx.Response(401, json={"error": "Unauthorized"}), 502, "Keitaro rejected the API key"),
        (httpx.Response(402, json={"error": "License"}), 502, "Keitaro license problem"),
        (httpx.Response(403, json={"error": "No permission"}), 502, "The API key has no access to this object in Keitaro"),
        (httpx.Response(500, text="oops"), 502, "Keitaro API error"),
        (httpx.Response(503, text="maintenance"), 502, "Keitaro API error"),
    ],
)
def test_keitaro_errors_are_mapped(client, kt, keitaro_response, status, error):
    kt.failures[("GET", "/campaigns")] = keitaro_response
    r = client.get("/api/campaigns")
    assert r.status_code == status
    assert r.json()["error"] == error
    assert r.json()["keitaro_status"] == keitaro_response.status_code


def test_not_found(client):
    r = client.get("/api/campaigns/424242/streams")
    assert r.status_code == 404
    assert r.json()["error"] == "Not found in Keitaro"


def test_timeout(client, kt):
    kt.failures[("GET", "/campaigns")] = httpx.ReadTimeout("slow")
    r = client.get("/api/campaigns")
    assert r.status_code == 504
    assert r.json()["keitaro_status"] is None


def test_network_error(client, kt):
    kt.failures[("GET", "/campaigns")] = httpx.ConnectError("refused")
    r = client.get("/api/campaigns")
    assert r.status_code == 502
    assert r.json()["error"] == "Keitaro is unavailable"


def test_unexpected_response_shape_is_json_500(kt):
    kt.failures[("GET", "/campaigns")] = httpx.Response(200, json=[{"id": 1, "name": "test_akella_x"}])
    r = TestClient(app, raise_server_exceptions=False).get("/api/campaigns")
    assert r.status_code == 500
    assert r.json() == {"error": "Internal error"}


def test_errors_do_not_leak_secrets(client, kt):
    kt.failures[("GET", "/campaigns")] = httpx.ConnectError("https://kt.test/admin_api/v1 test-key")
    text = client.get("/api/campaigns").text
    assert "kt.test" not in text
    assert "test-key" not in text


def test_pages_render(client):
    assert client.get("/").status_code == 200
    assert "test_akella_" in client.get("/").text
    assert client.get("/editor").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}
