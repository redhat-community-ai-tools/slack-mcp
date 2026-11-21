"""users.list page pacing and atomic cache-file writes (#83)."""

import asyncio
import json
from types import SimpleNamespace

import pytest

import slack_mcp_server as sms


@pytest.fixture(autouse=True)
def isolated_caches(monkeypatch, tmp_path):
    monkeypatch.setattr(sms, "_reverse_user_memory_cache", [])
    monkeypatch.setattr(sms, "_reverse_user_memory_cache_time", None)
    monkeypatch.setattr(sms, "_user_cache", {})
    monkeypatch.setattr(sms, "_foreground_waiting", asyncio.Event())
    monkeypatch.setattr(sms, "USER_CACHE_FILE", tmp_path / "u.json")
    monkeypatch.setattr(sms, "REVERSE_USER_CACHE_FILE", tmp_path / "r.json")


def _fake_pages(n, calls, on_request=None):
    """users.list stand-in returning n one-user pages; records each call."""
    async def fake_request(url, method="POST", payload=None):
        i = len(calls)
        calls.append(i)
        if on_request:
            await on_request(i)
        return {"ok": True, "members": [{"id": f"U{i}"}],
                "response_metadata": {"next_cursor": "c" if i < n - 1 else ""}}
    return fake_request


async def _walk(monkeypatch, response_time, paced):
    """Run a 3-page users.list walk on a fake clock; return the pacing waits."""
    clock, waits, calls = [100.0], [], []

    async def advance(_):
        clock[0] += response_time

    async def fake_wait_for(aw, timeout):
        aw.close()
        waits.append(timeout)
        clock[0] += timeout
        raise asyncio.TimeoutError

    monkeypatch.setattr(sms, "make_request", _fake_pages(3, calls, advance))
    monkeypatch.setattr(sms, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(sms.asyncio, "wait_for", fake_wait_for)
    users = await sms._fetch_all_users(paced=paced)
    assert [u["id"] for u in users] == ["U0", "U1", "U2"]
    return waits


@pytest.mark.asyncio
async def test_paced_walk_spaces_fast_pages_by_min_interval(monkeypatch):
    sleeps = await _walk(monkeypatch, response_time=0, paced=True)
    assert sleeps == [pytest.approx(sms.USERS_LIST_MIN_INTERVAL_S)] * 2


@pytest.mark.asyncio
async def test_paced_walk_adds_no_delay_to_slow_pages(monkeypatch):
    sleeps = await _walk(monkeypatch, response_time=sms.USERS_LIST_MIN_INTERVAL_S + 1, paced=True)
    assert sleeps == []


@pytest.mark.asyncio
async def test_on_demand_walk_is_not_paced(monkeypatch):
    sleeps = await _walk(monkeypatch, response_time=0, paced=False)
    assert sleeps == []


@pytest.mark.asyncio
async def test_on_demand_call_promotes_in_progress_paced_walk(monkeypatch):
    monkeypatch.setattr(sms, "USERS_LIST_MIN_INTERVAL_S", 60.0)
    calls, first_page = [], asyncio.Event()

    async def on_request(i):
        first_page.set()

    monkeypatch.setattr(sms, "make_request", _fake_pages(3, calls, on_request))
    warmup = asyncio.create_task(sms._fetch_all_users(paced=True))
    await first_page.wait()  # warmup now holds the lock, pacing a 60s wait

    users = await asyncio.wait_for(sms._fetch_all_users(paced=False), timeout=2.0)

    assert [u["id"] for u in users] == ["U0", "U1", "U2"]
    assert len(calls) == 3  # served by the promoted walk, not a second walk
    assert (await warmup) == users
    assert not sms._foreground_waiting.is_set()  # next warmup starts paced again


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
