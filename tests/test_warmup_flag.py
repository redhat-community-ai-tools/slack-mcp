"""Tests for the SLACK_MCP_WARMUP opt-out flag (startup directory warmup)."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import slack_mcp_server as sms


class TestIsWarmupEnabled:
    @pytest.mark.parametrize(
        "value", ["off", "OFF", "Off", "0", "false", "FALSE", "no", "  no  "]
    )
    def test_off_values_disable_warmup(self, monkeypatch, value):
        monkeypatch.setenv(sms.WARMUP_ENV_VAR, value)
        assert sms._is_warmup_enabled() is False

    @pytest.mark.parametrize("value", ["on", "1", "true", "yes", "banana", ""])
    def test_other_values_keep_warmup_enabled(self, monkeypatch, value):
        monkeypatch.setenv(sms.WARMUP_ENV_VAR, value)
        assert sms._is_warmup_enabled() is True

    def test_unset_means_enabled(self, monkeypatch):
        monkeypatch.delenv(sms.WARMUP_ENV_VAR, raising=False)
        assert sms._is_warmup_enabled() is True


class TestLifespanWarmup:
    @pytest.mark.asyncio
    async def test_lifespan_skips_fetch_when_warmup_disabled(self, monkeypatch):
        monkeypatch.setenv(sms.WARMUP_ENV_VAR, "off")
        fetch = AsyncMock(return_value=[])
        with patch.object(sms, "_fetch_all_users", new=fetch):
            async with sms._lifespan(sms.mcp):
                # Give a wrongly-started warmup task every chance to fire.
                await asyncio.sleep(0.1)
        fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_lifespan_runs_fetch_when_warmup_enabled(self, monkeypatch):
        monkeypatch.delenv(sms.WARMUP_ENV_VAR, raising=False)
        started = asyncio.Event()
        calls = []

        async def fake_fetch(**kwargs):
            calls.append(1)
            started.set()
            return []

        with patch.object(sms, "_fetch_all_users", new=fake_fetch):
            async with sms._lifespan(sms.mcp):
                await asyncio.wait_for(started.wait(), timeout=1.0)
        assert calls, "expected _fetch_all_users to run during lifespan warmup"
