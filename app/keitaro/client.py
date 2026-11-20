import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings
from app.keitaro.errors import ForbiddenCampaignError, KeitaroError


@dataclass
class WriteRecord:
    method: str
    path: str
    campaign_id: int | None
    body: dict[str, Any]
    status_code: int | None
    error: str | None


AuditHook = Callable[[WriteRecord], None]

CONNECT_RETRIES = 2


class KeitaroClient:
    """Keitaro Admin API client.

    Reads anything; writes only campaigns with the configured prefix and their
    streams. There are deliberately no methods that change offers, domains,
    groups or traffic sources.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        audit: AuditHook | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self._prefix = settings.campaign_prefix
        self._audit = audit
        self._http = httpx.Client(
            base_url=settings.keitaro_api_url.rstrip("/"),
            headers={"Api-Key": settings.keitaro_api_key.get_secret_value()},
            timeout=settings.keitaro_timeout,
            # Retries only failed connections: the request was not sent, so writes are safe too
            transport=transport or httpx.HTTPTransport(retries=CONNECT_RETRIES),
        )

    def close(self) -> None:
        self._http.close()

    # --- reads ---

    def list_campaigns(self) -> list[dict]:
        return self._get("/campaigns")

    def get_campaign(self, campaign_id: int) -> dict:
        return self._get(f"/campaigns/{campaign_id}")

    def get_campaign_streams(self, campaign_id: int) -> list[dict]:
        return self._get(f"/campaigns/{campaign_id}/streams")

    def get_stream(self, stream_id: int) -> dict:
        return self._get(f"/streams/{stream_id}")

    def list_offers(self) -> list[dict]:
        return self._get("/offers")

    def get_offer(self, offer_id: int) -> dict:
        return self._get(f"/offers/{offer_id}")

    def list_domains(self) -> list[dict]:
        return self._get("/domains")

    def list_campaign_groups(self) -> list[dict]:
        return self._get("/groups", params={"type": "campaigns"})

    def list_traffic_sources(self) -> list[dict]:
        return self._get("/traffic_sources")

    # --- writes (prefix-guarded) ---

    def create_campaign(self, payload: dict[str, Any]) -> dict:
        self._check_name(payload.get("name"))
        return self._write("POST", "/campaigns", payload, campaign_id=None)

    def create_stream(self, payload: dict[str, Any]) -> dict:
        campaign_id = payload.get("campaign_id")
        if not isinstance(campaign_id, int):
            raise ForbiddenCampaignError("Stream payload has no campaign_id")
        self._check_campaign(campaign_id)
        return self._write("POST", "/streams", payload, campaign_id=campaign_id)

    def update_stream_offers(self, stream_id: int, offers: list[dict[str, Any]]) -> dict:
        """Replaces the whole offers array of the stream (verified behaviour)."""
        campaign_id = self.get_stream(stream_id)["campaign_id"]
        self._check_campaign(campaign_id)
        return self._write(
            "PUT", f"/streams/{stream_id}", {"offers": offers}, campaign_id=campaign_id
        )

    # --- guard ---

    def _check_name(self, name: Any) -> None:
        if not isinstance(name, str) or not name.startswith(self._prefix):
            raise ForbiddenCampaignError(
                f"Campaign name must start with '{self._prefix}'"
            )

    def _check_campaign(self, campaign_id: int) -> None:
        # Always re-read the campaign: the name in Keitaro is the source of truth
        name = self.get_campaign(campaign_id).get("name")
        if not isinstance(name, str) or not name.startswith(self._prefix):
            raise ForbiddenCampaignError(
                f"Campaign {campaign_id} does not start with '{self._prefix}'"
            )

    # --- transport ---

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def _write(
        self, method: str, path: str, body: dict[str, Any], *, campaign_id: int | None
    ) -> Any:
        status_code: int | None = None
        error: str | None = None
        try:
            response = self._send(method, path, json=body)
            status_code = response.status_code
            result = _parse(response, path)
            if campaign_id is None and isinstance(result, dict):
                campaign_id = result.get("id")
            return result
        except KeitaroError as exc:
            status_code, error = exc.status_code, exc.message
            raise
        finally:
            if self._audit:
                self._audit(WriteRecord(method, path, campaign_id, body, status_code, error))

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        return _parse(self._send(method, path, **kwargs), path)

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise KeitaroError("Keitaro did not respond in time", path=path, timed_out=True) from None
        except httpx.HTTPError as exc:
            # str(exc) may contain the full URL, so only the exception type is exposed
            raise KeitaroError(
                f"Cannot reach Keitaro ({type(exc).__name__})", path=path
            ) from None


def _parse(response: httpx.Response, path: str) -> Any:
    if response.is_error:
        raise KeitaroError(
            _error_message(response),
            status_code=response.status_code,
            path=path,
        )
    try:
        return response.json()
    except json.JSONDecodeError:
        raise KeitaroError(
            "Keitaro returned a non-JSON response",
            status_code=response.status_code,
            path=path,
        ) from None


def _error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except json.JSONDecodeError:
        return f"Keitaro error {response.status_code}"
    if isinstance(data, dict) and data.get("error"):
        return str(data["error"])
    # Validation errors come as {"field": ["message", ...]}
    if isinstance(data, dict) and data:
        parts = []
        for field, messages in data.items():
            if isinstance(messages, list):
                messages = "; ".join(map(str, messages))
            parts.append(f"{field}: {messages}")
        return ", ".join(parts)
    return f"Keitaro error {response.status_code}"
