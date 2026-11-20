import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.learning import label_export
from app.learning.label_export import validate_labels
from app.web import api
from app.web.api import build_app, is_authorized

TOKEN = "test-token-not-real"


def test_auth_header():
    assert is_authorized(f"Bearer {TOKEN}", TOKEN)
    assert not is_authorized(f"Bearer wrong", TOKEN)
    assert not is_authorized(TOKEN, TOKEN)            # thiếu "Bearer "
    assert not is_authorized(f"Bearer {TOKEN}", None)  # chưa cấu hình token → luôn từ chối


def test_validate_labels_skips_bad_items():
    ok, errors = validate_labels([
        {"id": 1, "label": "pos", "reason": "x"},
        {"id": "2", "label": "NEG"},
        {"id": 3, "label": "GOOD"},
        {"label": "NEU"},
    ])
    assert ok == {1: "POS", 2: "NEG"}
    assert len(errors) == 2


@pytest.fixture
def fake_db(monkeypatch):
    saved = {}

    async def fake_pending(days, limit, **_kw):
        return [{"id": 7, "ticker": "SBT", "title": "t"}][:limit]

    async def fake_import(labels, labeler):
        saved.update(labels=labels, labeler=labeler)
        return {"saved": len(labels), "unknown_ids": [], "by_label": {}}

    monkeypatch.setattr(api, "fetch_pending", fake_pending)
    monkeypatch.setattr(api, "import_labels", fake_import)
    return saved


async def _client(token):
    client = TestClient(TestServer(build_app(token)))
    await client.start_server()
    return client


def test_api_requires_token(fake_db):
    asyncio.run(_requires_token(fake_db))


async def _requires_token(fake_db):
    client = await _client(TOKEN)
    try:
        assert (await client.get("/healthz")).status == 200
        assert (await client.get("/api/labeling/pending")).status == 401
        r = await client.get("/api/labeling/pending?days=3", headers={"Authorization": f"Bearer {TOKEN}"})
        body = await r.json()
        assert r.status == 200 and body["count"] == 1 and "POS" in body["instructions"]

        r = await client.post("/api/labeling/labels", headers={"Authorization": f"Bearer {TOKEN}"},
                              json={"labeler": "claude-haiku", "labels": [{"id": 7, "label": "POS"}, {"id": 8, "label": "??"}]})
        body = await r.json()
        assert body["saved"] == 1 and len(body["errors"]) == 1
        assert fake_db == {"labels": {7: "POS"}, "labeler": "claude-haiku"}
    finally:
        await client.close()


def test_api_disabled_without_token(fake_db):
    asyncio.run(_disabled(fake_db))


async def _disabled(fake_db):
    client = await _client(None)
    try:
        assert (await client.get("/api/labeling/pending")).status == 404
    finally:
        await client.close()
