"""Slack Lists tools: record flattening, archive/restore and deletion."""

from unittest.mock import AsyncMock, patch

import pytest

import slack_mcp_server as sms

LIST_URL = "https://app.slack.com/client/E030G10V24F/unified-files/list/F0CD4B5NFSQ"

LIST_FILE = {
    "id": "F0CD4B5NFSQ",
    "title": "to-do",
    "filetype": "list",
    "permalink": "https://example.slack.com/lists/T1/F0CD4B5NFSQ",
    "list_limits": {"row_count": 1, "archived_row_count": 0},
    "list_metadata": {
        "schema": [
            {"id": "ColName", "key": "name", "name": "Name", "type": "text", "is_primary_column": True},
            {"id": "ColMessage", "key": "message", "name": "Message", "type": "message"},
            {"id": "ColReporter", "key": "reporter", "name": "Reporter", "type": "user"},
        ]
    },
}

RECORD = {
    "id": "Rec123",
    "date_created": 1700000000,
    "updated_timestamp": "1700000001",
    "created_by": "UOWNER",
    "fields": [
        {
            "key": "name",
            "column_id": "ColName",
            "text": "Review the PR",
            "value": '[{"type":"rich_text","elements":[{"type":"text","text":"Review the PR"}]}]',
        },
        {
            "key": "message",
            "column_id": "ColMessage",
            "value": "https://example.slack.com/archives/D123/p1700000000000000",
            "message": [
                {
                    "value": "https://example.slack.com/archives/D123/p1700000000000000",
                    "channel_id": "D123",
                    "ts": "1700000000.000100",
                    "thread_ts": "0000000000.000000",
                }
            ],
        },
        {"key": "reporter", "column_id": "ColReporter", "user": ["UREPORTER"]},
    ],
}


@pytest.mark.asyncio
async def test_get_slack_list_accepts_url_and_flattens_records(monkeypatch):
    monkeypatch.setattr(sms, "SLACK_BOT_TOKEN", "")
    monkeypatch.setattr(sms, "_slack_host", "https://example.slack.com")
    calls = []

    async def request(url, method="POST", payload=None):
        calls.append((url, payload))
        if url.endswith("/files.info"):
            return {"ok": True, "file": LIST_FILE}
        if url.endswith("/lists.records.list"):
            return {"ok": True, "records": [RECORD], "response_metadata": {"next_cursor": ""}}
        if url.endswith("/users.info"):
            return {"ok": True, "user": {"name": payload["user"].lower(), "profile": {}}}
        raise AssertionError(f"Unexpected Slack request: {url}")

    with patch.object(sms, "make_request", side_effect=request):
        result = await sms.get_slack_list(LIST_URL)

    assert result["ok"] is True
    assert result["id"] == "F0CD4B5NFSQ"
    assert [column["key"] for column in result["columns"]] == ["name", "message", "reporter"]
    item = result["items"][0]
    assert item["id"] == "Rec123"
    assert item["values"]["name"] == "Review the PR"
    assert item["values"]["reporter"] == "ureporter"
    assert item["messages"][0]["channel_id"] == "D123"
    assert item["messages"][0]["ts"] == "1700000000.000100"
    assert any(url.endswith("/lists.records.list") for url, _ in calls)


@pytest.mark.asyncio
async def test_get_slack_list_item_hydrates_message_and_thread(monkeypatch):
    monkeypatch.setattr(sms, "SLACK_BOT_TOKEN", "")
    monkeypatch.setattr(sms, "_slack_host", "https://example.slack.com")
    fetched = {}

    async def request(url, method="POST", payload=None):
        if url.endswith("/lists.records.info"):
            return {"ok": True, "list": LIST_FILE, "record": RECORD, "subtasks": []}
        if url.endswith("/users.info"):
            return {"ok": True, "user": {"name": payload["user"].lower(), "profile": {}}}
        if url.endswith("/conversations.history"):
            fetched["history"] = payload
            return {"ok": True, "messages": [{"ts": "1700000000.000100", "text": "Original", "user": "UREPORTER", "thread_ts": "1700000000.000100", "reply_count": 1}]}
        if url.endswith("/conversations.replies"):
            fetched["replies"] = payload
            return {"ok": True, "messages": [{"ts": "1700000000.000100"}, {"ts": "1700000002.000000", "text": "Reply", "user": "UOWNER"}]}
        raise AssertionError(f"Unexpected Slack request: {url}")

    with patch.object(sms, "make_request", side_effect=request):
        with patch.object(sms, "filter_message_fields", new_callable=AsyncMock) as fmt:
            fmt.side_effect = lambda message: message.get("text", "")
            result = await sms.get_slack_list_item("F0CD4B5NFSQ", "Rec123")

    assert result["ok"] is True
    ref = result["item"]["messages"][0]
    assert ref["message"] == "Original"
    assert ref["thread"] == ["Reply"]
    assert fetched["history"]["channel"] == "D123"
    assert fetched["replies"]["ts"] == "1700000000.000100"


@pytest.mark.asyncio
async def test_archive_slack_list_items_sends_ids_and_restore(monkeypatch):
    monkeypatch.setattr(sms, "SLACK_BOT_TOKEN", "")
    monkeypatch.setattr(sms, "_slack_host", "https://example.slack.com")
    payloads = {}

    async def request(url, method="POST", payload=None):
        payloads[url] = payload
        return {"ok": True}

    with patch.object(sms, "make_request", side_effect=request):
        archived = await sms.archive_slack_list_items("F0CD4B5NFSQ", ["Rec1", "Rec2"])
        restored = await sms.archive_slack_list_items(
            "F0CD4B5NFSQ", ["Rec1"], restore=True
        )

    archive_url = "https://example.slack.com/api/lists.records.archive"
    assert payloads[archive_url]["ids"] == ["Rec1"]
    assert payloads[archive_url]["restore"] is True
    assert archived == {
        "ok": True,
        "action": "archived",
        "list_id": "F0CD4B5NFSQ",
        "item_ids": ["Rec1", "Rec2"],
    }
    assert restored["action"] == "restored"


@pytest.mark.asyncio
async def test_delete_slack_list_items_uses_delete_multiple(monkeypatch):
    monkeypatch.setattr(sms, "SLACK_BOT_TOKEN", "")
    monkeypatch.setattr(sms, "_slack_host", "https://example.slack.com")
    payloads = {}

    async def request(url, method="POST", payload=None):
        payloads[url] = payload
        return {"ok": True}

    with patch.object(sms, "make_request", side_effect=request):
        result = await sms.delete_slack_list_items("F0CD4B5NFSQ", ["Rec1"])

    assert result["ok"] is True
    assert result["action"] == "deleted"
    payload = payloads["https://example.slack.com/api/lists.records.deleteMultiple"]
    assert payload["list_id"] == "F0CD4B5NFSQ"
    assert payload["ids"] == ["Rec1"]


@pytest.mark.asyncio
async def test_list_tools_reject_bot_token(monkeypatch):
    monkeypatch.setattr(sms, "SLACK_BOT_TOKEN", "xoxb-test")
    result = await sms.get_slack_list("F0CD4B5NFSQ")
    assert result["ok"] is False
    assert "browser-session" in result["error"]
