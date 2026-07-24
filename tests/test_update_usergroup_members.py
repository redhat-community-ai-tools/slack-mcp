"""Tests for update_usergroup_members."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import slack_mcp_server as sms


@pytest.fixture(autouse=True)
def _suppress_logging():
    with patch.object(sms, "log_to_slack", new_callable=AsyncMock):
        yield


class TestUpdateUsergroupMembers:
    @pytest.mark.asyncio
    async def test_updates_single_member(self):
        with patch.object(sms, "make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True}
            result = await sms.update_usergroup_members("S123", ["U001"])
            assert result is True
            call_payload = mock_req.call_args[1].get("payload") or mock_req.call_args[0][1] if len(mock_req.call_args[0]) > 1 else None
            if call_payload is None:
                call_payload = mock_req.call_args.kwargs.get("payload", mock_req.call_args[0][1] if len(mock_req.call_args[0]) > 1 else {})
            assert mock_req.called

    @pytest.mark.asyncio
    async def test_updates_multiple_members(self):
        with patch.object(sms, "make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True}
            result = await sms.update_usergroup_members("S123", ["U001", "U002", "U003"])
            assert result is True
            call_args = mock_req.call_args
            payload = call_args.kwargs.get("payload") or call_args[0][1]
            assert "U001,U002,U003" == payload["users"]

    @pytest.mark.asyncio
    async def test_rejects_empty_user_list(self):
        with patch.object(sms, "make_request", new_callable=AsyncMock) as mock_req:
            result = await sms.update_usergroup_members("S123", [])
            assert result is False
            mock_req.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_false_on_api_error(self):
        with patch.object(sms, "make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": False, "error": "invalid_auth"}
            result = await sms.update_usergroup_members("S123", ["U001"])
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_no_response(self):
        with patch.object(sms, "make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = None
            result = await sms.update_usergroup_members("S123", ["U001"])
            assert result is False

    @pytest.mark.asyncio
    async def test_calls_correct_api_endpoint(self):
        with patch.object(sms, "make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True}
            await sms.update_usergroup_members("S456", ["U789"])
            url = mock_req.call_args[0][0]
            assert url.endswith("/usergroups.users.update")

    @pytest.mark.asyncio
    async def test_sends_usergroup_id_in_payload(self):
        with patch.object(sms, "make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True}
            await sms.update_usergroup_members("SABC", ["U001"])
            payload = mock_req.call_args.kwargs.get("payload") or mock_req.call_args[0][1]
            assert payload["usergroup"] == "SABC"
