"""users.list page pacing and atomic cache-file writes (#83)."""

import asyncio
import json
from types import SimpleNamespace

import pytest

import slack_mcp_server as sms


async def _walk(monkeypatch, tmp_path, response_time, paced):
    """Run a 3-page users.list walk on a fake clock; return the sleeps taken."""
    monkeypatch.setattr(sms, "_reverse_user_memory_cache", [])
    monkeypatch.setattr(sms, "_reverse_user_memory_cache_time", None)
    monkeypatch.setattr(sms, "_user_cache", {})
    monkeypatch.setattr(sms, "USER_CACHE_FILE", tmp_path / "u.json")
    monkeypatch.setattr(sms, "REVERSE_USER_CACHE_FILE", tmp_path / "r.json")
    clock, sleeps, pages = [100.0], [], iter(range(3))

    async def fake_request(url, method="POST", payload=None):
        clock[0] += response_time
        i = next(pages)
        return {"ok": True, "members": [{"id": f"U{i}"}],
                "response_metadata": {"next_cursor": "c" if i < 2 else ""}}

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(sms, "make_request", fake_request)
    monkeypatch.setattr(sms, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(sms.asyncio, "sleep", fake_sleep)
    users = await sms._fetch_all_users(paced=paced)
    assert [u["id"] for u in users] == ["U0", "U1", "U2"]
    return sleeps


@pytest.mark.asyncio
async def test_paced_walk_spaces_fast_pages_by_min_interval(monkeypatch, tmp_path):
    sleeps = await _walk(monkeypatch, tmp_path, response_time=0, paced=True)
    assert sleeps == [pytest.approx(sms.USERS_LIST_MIN_INTERVAL_S)] * 2


@pytest.mark.asyncio
async def test_paced_walk_adds_no_delay_to_slow_pages(monkeypatch, tmp_path):
    sleeps = await _walk(monkeypatch, tmp_path, response_time=sms.USERS_LIST_MIN_INTERVAL_S + 1, paced=True)
    assert sleeps == []


@pytest.mark.asyncio
async def test_on_demand_walk_is_not_paced(monkeypatch, tmp_path):
    sleeps = await _walk(monkeypatch, tmp_path, response_time=0, paced=False)
    assert sleeps == []


@pytest.mark.asyncio
async def test_warmup_uses_paced_walk(monkeypatch):
    monkeypatch.delenv(sms.WARMUP_ENV_VAR, raising=False)
    called = asyncio.Event()
    kwargs_seen = {}

    async def fake_fetch(**kwargs):
        kwargs_seen.update(kwargs)
        called.set()
        return []

    monkeypatch.setattr(sms, "_fetch_all_users", fake_fetch)
    async with sms._lifespan(sms.mcp):
        await asyncio.wait_for(called.wait(), timeout=1.0)
    assert kwargs_seen == {"paced": True}


def test_failed_atomic_write_keeps_previous_file(tmp_path):
    target = tmp_path / "cache.json"
    target.write_text('{"old": true}')
    with pytest.raises(TypeError):
        sms._atomic_write_json(target, {"bad": object()})  # not JSON-serializable
    assert json.loads(target.read_text()) == {"old": True}
    assert [p.name for p in tmp_path.iterdir()] == ["cache.json"]
