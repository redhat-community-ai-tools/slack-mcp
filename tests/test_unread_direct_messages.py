"""Unread DM results use read markers without changing Slack read state."""

from unittest.mock import AsyncMock, patch

import pytest

import slack_mcp_server as sms


@pytest.mark.asyncio
async def test_unread_dms_fetch_only_messages_after_read_marker(monkeypatch):
    monkeypatch.setattr(sms, "SLACK_BOT_TOKEN", "")
    calls = []

    async def request(url, method="POST", payload=None):
        calls.append((url.rsplit("/", 1)[-1], method, payload))
        if url.endswith("/auth.test"):
            return {"ok": True, "team_id": "T123", "user_id": "UME"}
        if url.endswith("/client.counts"):
            return {"ok": True, "ims": [
                {"id": "D123", "has_unreads": True, "last_read": "1.0"},
                {"id": "D456", "has_unreads": False},
            ]}
        if url.endswith("/conversations.info"):
            return {"ok": True, "channel": {
                "user": "UOTHER", "unread_count": 2, "last_read": "1.0"
            }}
        if url.endswith("/conversations.history"):
            return {"ok": True, "messages": [
                {"ts": "2.0", "text": "First", "user": "UOTHER"},
                {"ts": "3.0", "text": "Mine", "user": "UME"},
                {"ts": "4.0", "text": "Second", "user": "UOTHER"},
            ]}
        raise AssertionError(f"Unexpected Slack request: {url}")

    with patch.object(sms, "make_request", side_effect=request):
        with patch.object(sms, "get_user_handle", new_callable=AsyncMock, return_value="alice"):
            result = await sms.get_unread_direct_messages()

    assert result["unread_conversations"] == 1
    assert result["truncated"] is False
    dm = result["direct_messages"][0]
    assert dm["user"] == "alice"
    assert dm["url"] == "https://app.slack.com/client/T123/D123"
    assert [msg["text"] for msg in dm["messages"]] == ["First", "Second"]
    assert [method for _, method, _ in calls] == ["POST", "POST", "GET", "GET"]
    assert calls[-1][2]["oldest"] == "1.0"


@pytest.mark.asyncio
async def test_unread_dms_report_unavailable_counts(monkeypatch):
    monkeypatch.setattr(sms, "SLACK_BOT_TOKEN", "")
    with patch.object(sms, "make_request", new_callable=AsyncMock) as request:
        request.side_effect = [
            {"ok": True, "team_id": "T123"},
            {"ok": False, "error": "enterprise_is_restricted"},
        ]
        result = await sms.get_unread_direct_messages()

    assert "error" in result
    assert request.await_count == 2


@pytest.mark.asyncio
async def test_unread_dms_stop_on_stalled_pagination(monkeypatch):
    monkeypatch.setattr(sms, "SLACK_BOT_TOKEN", "")

    async def request(url, method="POST", payload=None):
        if url.endswith("/auth.test"):
            return {"ok": True, "team_id": "T123", "user_id": "UME"}
        if url.endswith("/client.counts"):
            return {"ok": True, "ims": [{"id": "D123", "has_unreads": True}]}
        if url.endswith("/conversations.info"):
            return {"ok": True, "channel": {"last_read": "1.0", "unread_count": 5}}
        return {"ok": True, "messages": [], "response_metadata": {"next_cursor": "stalled"}}

    with patch.object(sms, "make_request", side_effect=request) as mock_request:
        result = await sms.get_unread_direct_messages()

    assert mock_request.await_count == 4
    assert result["direct_messages"][0]["note"] == "DM history pagination stopped early."


@pytest.mark.asyncio
async def test_unread_dms_note_when_count_includes_missing_thread_replies(monkeypatch):
    monkeypatch.setattr(sms, "SLACK_BOT_TOKEN", "")

    async def request(url, method="POST", payload=None):
        if url.endswith("/auth.test"):
            return {"ok": True, "team_id": "T123", "user_id": "UME"}
        if url.endswith("/client.counts"):
            return {"ok": True, "ims": [{"id": "D123", "has_unreads": True}]}
        if url.endswith("/conversations.info"):
            return {"ok": True, "channel": {"last_read": "1.0", "unread_count": 4}}
        return {"ok": True, "messages": [{"ts": "2.0", "user": "UOTHER", "text": "Hello"}]}

    with patch.object(sms, "make_request", side_effect=request):
        with patch.object(sms, "get_user_handle", new_callable=AsyncMock, return_value="alice"):
            result = await sms.get_unread_direct_messages()

    assert result["direct_messages"][0]["unread_count"] == 4
    assert len(result["direct_messages"][0]["messages"]) == 1
    assert "thread replies" in result["direct_messages"][0]["note"]


@pytest.mark.asyncio
async def test_unread_dms_reject_missing_count_list(monkeypatch):
    monkeypatch.setattr(sms, "SLACK_BOT_TOKEN", "")
    with patch.object(sms, "make_request", new_callable=AsyncMock) as request:
        request.side_effect = [{"ok": True, "team_id": "T123"}, {"ok": True}]
        result = await sms.get_unread_direct_messages()

    assert result == {"error": "Slack did not return a DM count list."}


@pytest.mark.asyncio
async def test_bot_token_does_not_claim_user_unread_state(monkeypatch):
    monkeypatch.setattr(sms, "SLACK_BOT_TOKEN", "xoxb-test")
    with patch.object(sms, "make_request", new_callable=AsyncMock) as request:
        result = await sms.get_unread_direct_messages()

    assert "error" in result
    request.assert_not_awaited()
