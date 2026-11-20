"""In-memory Keitaro Admin API with the behaviour observed on the real one."""

import json
import re
from dataclasses import dataclass, field
from itertools import count

import httpx

API_PREFIX = "/admin_api/v1"


@dataclass
class FakeKeitaro:
    campaigns: dict[int, dict] = field(default_factory=dict)
    streams: dict[int, dict] = field(default_factory=dict)
    offers: list[dict] = field(
        default_factory=lambda: [
            {"id": 3749, "name": "Miaflow 0009", "state": "active"},
            {"id": 3717, "name": "Miaflow 0008", "state": "active"},
            {"id": 11111, "name": "FitoMishki", "state": "active"},
            {"id": 11112, "name": "Oxys", "state": "active"},
            {"id": 500, "name": "Archived offer", "state": "deleted"},
        ]
    )
    domains: list[dict] = field(
        default_factory=lambda: [{"id": 1813, "name": "tracker.example", "state": "active"}]
    )
    groups: list[dict] = field(default_factory=lambda: [{"id": 10332, "name": "FORTESTS"}])
    sources: list[dict] = field(
        default_factory=lambda: [{"id": 836, "name": "FORTESTS", "state": "active"}]
    )
    # Every non-GET request: (method, path, body)
    writes: list[tuple[str, str, dict]] = field(default_factory=list)
    # path -> httpx.Response or exception, to simulate failures
    failures: dict[tuple[str, str], object] = field(default_factory=dict)
    api_keys: list[str] = field(default_factory=list)
    _ids: count = field(default_factory=lambda: count(1000))

    # --- seeding helpers ---

    def add_campaign(self, name: str, **extra) -> dict:
        cid = next(self._ids)
        campaign = {
            "id": cid,
            "name": name,
            "alias": f"alias{cid}",
            "state": "active",
            "token": "secret-click-token",
            "domain": "https://tracker.example/",
            "updated_at": "2026-11-20 10:00:00",
            **extra,
        }
        self.campaigns[cid] = campaign
        return campaign

    def add_stream(self, campaign_id: int, name: str, position: int, **extra) -> dict:
        sid = next(self._ids)
        stream = {
            "id": sid,
            "campaign_id": campaign_id,
            "name": name,
            "position": position,
            "type": "regular",
            "schema": "landings",
            "action_type": "http",
            "action_payload": None,
            "filters": [],
            "offers": [],
            **extra,
        }
        self.streams[sid] = stream
        return stream

    def set_offers(self, stream_id: int, *pairs: tuple[int, int]) -> None:
        self.streams[stream_id]["offers"] = [
            {"offer_id": oid, "share": share, "state": "active"} for oid, share in pairs
        ]

    def offer_shares(self, stream_id: int) -> list[tuple[int, int]]:
        return [(o["offer_id"], o["share"]) for o in self.streams[stream_id]["offers"]]

    # --- request handling ---

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.api_keys.append(request.headers.get("Api-Key", ""))
        path = request.url.path.removeprefix(API_PREFIX)
        failure = self.failures.get((request.method, path))
        if isinstance(failure, Exception):
            raise failure
        if failure is not None:
            return failure

        body = json.loads(request.content) if request.content else {}
        if request.method != "GET":
            self.writes.append((request.method, path, body))

        route = getattr(self, f"_{request.method.lower()}", None)
        return route(path, request, body) if route else _not_found()

    def _get(self, path: str, request: httpx.Request, _: dict) -> httpx.Response:
        if path == "/campaigns":
            return _ok(list(self.campaigns.values()))
        if m := re.fullmatch(r"/campaigns/(\d+)", path):
            return _ok_or_404(self.campaigns.get(int(m[1])))
        if m := re.fullmatch(r"/campaigns/(\d+)/streams", path):
            cid = int(m[1])
            if cid not in self.campaigns:
                return _not_found()
            return _ok([s for s in self.streams.values() if s["campaign_id"] == cid])
        if m := re.fullmatch(r"/streams/(\d+)", path):
            return _ok_or_404(self.streams.get(int(m[1])))
        if path == "/offers":
            return _ok(self.offers)
        if path == "/domains":
            return _ok(self.domains)
        if path == "/groups":
            return _ok(self.groups if request.url.params.get("type") == "campaigns" else [])
        if path == "/traffic_sources":
            return _ok(self.sources)
        return _not_found()

    def _post(self, path: str, _: httpx.Request, body: dict) -> httpx.Response:
        if path == "/campaigns":
            if not body.get("alias"):
                return httpx.Response(422, json={"alias": ["Alias is required"]})
            campaign = self.add_campaign(body["name"])
            campaign.update(body)
            return _ok(campaign)
        if path == "/streams":
            stream = self.add_stream(
                body["campaign_id"], body["name"], body.get("position", 1),
                **{k: v for k, v in body.items() if k not in ("campaign_id", "name", "position")},
            )
            return _ok(stream)
        return _not_found()

    def _put(self, path: str, _: httpx.Request, body: dict) -> httpx.Response:
        if m := re.fullmatch(r"/streams/(\d+)", path):
            stream = self.streams.get(int(m[1]))
            if stream is None:
                return _not_found()
            # Verified: the offers array is replaced as a whole
            if "offers" in body:
                stream["offers"] = body["offers"]
            return _ok(stream)
        return _not_found()


def _ok(data) -> httpx.Response:
    return httpx.Response(200, json=data)


def _ok_or_404(data) -> httpx.Response:
    return _ok(data) if data is not None else _not_found()


def _not_found() -> httpx.Response:
    # Real Keitaro answers unknown paths with an nginx HTML page
    return httpx.Response(404, text="<html><body>404 Not Found</body></html>")
