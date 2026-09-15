"""Tests for filter_message_fields file-attachment handling."""

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


@pytest.fixture(autouse=True)
def _stub_user_handle():
    with patch.object(sms, "get_user_handle", new_callable=AsyncMock) as mock_handle:
        mock_handle.return_value = "someone"
        yield mock_handle


ONE_FILE = [
    {
        "id": "F0C1SEBRB97",
        "name": "report.pdf",
        "mimetype": "application/pdf",
        "url_private": "https://files.slack.com/files-pri/T1-F1/report.pdf",
        "url_private_download": "https://files.slack.com/files-pri/T1-F1/download/report.pdf",
        "permalink": "https://team.slack.com/files/U1/F1/report.pdf",
        "size": 12345,
    }
]

TWO_FILES = ONE_FILE + [
    {
        "id": "F0C2SEBRB98",
        "name": "screenshot.png",
        "mimetype": "image/png",
        "url_private": "https://files.slack.com/files-pri/T1-F2/screenshot.png",
        "url_private_download": "https://files.slack.com/files-pri/T1-F2/download/screenshot.png",
        "permalink": "https://team.slack.com/files/U1/F2/screenshot.png",
        "size": 6789,
    }
]


class TestFilterMessageFieldsJsonMode:
    @pytest.mark.asyncio
    async def test_message_with_one_file(self):
        with patch.object(sms, "OUTPUT_FORMAT", "json"):
            message = {"text": "here you go", "user": "U1", "ts": "1.1", "files": ONE_FILE}
            result = await sms.filter_message_fields(message)
        assert result["files"] == [
            {
                "id": "F0C1SEBRB97",
                "name": "report.pdf",
                "mimetype": "application/pdf",
                "url_private": "https://files.slack.com/files-pri/T1-F1/report.pdf",
                "url_private_download": "https://files.slack.com/files-pri/T1-F1/download/report.pdf",
                "permalink": "https://team.slack.com/files/U1/F1/report.pdf",
            }
        ]

    @pytest.mark.asyncio
    async def test_message_with_multiple_files(self):
        with patch.object(sms, "OUTPUT_FORMAT", "json"):
            message = {"text": "two things", "user": "U1", "ts": "1.1", "files": TWO_FILES}
            result = await sms.filter_message_fields(message)
        assert len(result["files"]) == 2
        assert [f["name"] for f in result["files"]] == ["report.pdf", "screenshot.png"]

    @pytest.mark.asyncio
    async def test_message_with_no_files_has_no_files_key(self):
        with patch.object(sms, "OUTPUT_FORMAT", "json"):
            message = {"text": "just text", "user": "U1", "ts": "1.1"}
            result = await sms.filter_message_fields(message)
        assert "files" not in result

    @pytest.mark.asyncio
    async def test_message_with_empty_files_list_has_no_files_key(self):
        with patch.object(sms, "OUTPUT_FORMAT", "json"):
            message = {"text": "just text", "user": "U1", "ts": "1.1", "files": []}
            result = await sms.filter_message_fields(message)
        assert "files" not in result


class TestFilterMessageFieldsCompactMode:
    @pytest.mark.asyncio
    async def test_message_with_one_file(self):
        with patch.object(sms, "OUTPUT_FORMAT", "compact"):
            message = {"text": "here you go", "user": "U1", "ts": "1.1", "files": ONE_FILE}
            result = await sms.filter_message_fields(message)
        assert result.endswith("[files: report.pdf]")

    @pytest.mark.asyncio
    async def test_message_with_multiple_files(self):
        with patch.object(sms, "OUTPUT_FORMAT", "compact"):
            message = {"text": "two things", "user": "U1", "ts": "1.1", "files": TWO_FILES}
            result = await sms.filter_message_fields(message)
        assert result.endswith("[files: report.pdf, screenshot.png]")

    @pytest.mark.asyncio
    async def test_message_with_no_files_has_no_files_suffix(self):
        with patch.object(sms, "OUTPUT_FORMAT", "compact"):
            message = {"text": "just text", "user": "U1", "ts": "1.1"}
            result = await sms.filter_message_fields(message)
        assert "files" not in result
        assert result == "[1.1] @someone: just text"

    @pytest.mark.asyncio
    async def test_message_with_empty_files_list_has_no_files_suffix(self):
        with patch.object(sms, "OUTPUT_FORMAT", "compact"):
            message = {"text": "just text", "user": "U1", "ts": "1.1", "files": []}
            result = await sms.filter_message_fields(message)
        assert "files" not in result
