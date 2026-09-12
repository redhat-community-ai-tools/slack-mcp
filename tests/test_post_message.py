"""Tests for post_message returning {"ok", "ts"}."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import slack_mcp_server as sms


@pytest.fixture(autouse=True)
def _suppress_side_effects():
    with patch.object(sms, "log_to_slack", new_callable=AsyncMock), patch.object(
        sms, "join_channel", new_callable=AsyncMock
    ):
        yield


class TestPostMessage:
    @pytest.mark.asyncio
    async def test_returns_ts_on_success(self):
        with patch.object(sms, "make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True, "ts": "1728000000.123456"}
            result = await sms.post_message("C123", "hello")
            assert result == {"ok": True, "ts": "1728000000.123456"}

    @pytest.mark.asyncio
    async def test_returns_empty_ts_on_api_error(self):
        with patch.object(sms, "make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": False, "error": "channel_not_found"}
            result = await sms.post_message("C123", "hello")
            assert result == {"ok": False, "ts": ""}

    @pytest.mark.asyncio
    async def test_returns_empty_ts_on_no_response(self):
        with patch.object(sms, "make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = None
            result = await sms.post_message("C123", "hello")
            assert result == {"ok": False, "ts": ""}

    @pytest.mark.asyncio
    async def test_thread_ts_is_forwarded_in_payload(self):
        with patch.object(sms, "make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True, "ts": "1728000000.222222"}
            await sms.post_message("C123", "reply", thread_ts="1728000000.111111")
            payload = mock_req.call_args.kwargs.get("payload") or mock_req.call_args[0][1]
            assert payload["thread_ts"] == sms.convert_thread_ts("1728000000.111111")

    @pytest.mark.asyncio
    async def test_invalid_blocks_json_returns_not_ok(self):
        with patch.object(sms, "make_request", new_callable=AsyncMock) as mock_req:
            result = await sms.post_message("C123", "hello", blocks="{not valid json")
            assert result == {"ok": False, "ts": ""}
            mock_req.assert_not_called()
