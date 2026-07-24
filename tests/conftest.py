import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Add repo root to path so we can import slack_mcp_server
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _isolate_caches(monkeypatch, tmp_path):
    """Redirect cache files to a temp directory and reset in-memory caches."""
    import slack_mcp_server as sms

    monkeypatch.setattr(sms, "USER_CACHE_FILE", tmp_path / ".user_cache.json")
    monkeypatch.setattr(sms, "REVERSE_USER_CACHE_FILE", tmp_path / ".reverse_user_cache.json")
    monkeypatch.setattr(sms, "FORMATTING_GUIDE_FILE", tmp_path / "formatting_guide.json")

    sms._user_cache.clear()
    sms._channel_cache.clear()
    sms._formatting_guide = None


@pytest.fixture
def mock_make_request():
    """Patch make_request to avoid real Slack API calls."""
    with patch("slack_mcp_server.make_request", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def mock_log_to_slack():
    """Patch log_to_slack to suppress logging side effects."""
    with patch("slack_mcp_server.log_to_slack", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def sample_formatting_guide(tmp_path):
    """Write a minimal formatting_guide.json and point the module at it."""
    import json
    import slack_mcp_server as sms

    guide = {
        "source": "https://docs.slack.dev/messaging/formatting-message-text",
        "description": "Test guide",
        "rules": [
            {
                "name": "bold",
                "syntax": "*text*",
                "description": "Bold text",
                "example": "*important*",
            }
        ],
        "mentions": [
            {
                "name": "user-mention",
                "syntax": "<@USER_ID>",
                "description": "Mention a user by ID",
                "example": "<@U012AB3CD>",
            }
        ],
        "escaping": [
            {
                "character": "&",
                "escape_as": "&amp;",
                "description": "Ampersand",
            }
        ],
        "unsupported": [
            {
                "feature": "markdown-bold",
                "markdown_syntax": "**text**",
                "note": "Use *text* instead",
            }
        ],
    }

    guide_path = tmp_path / "formatting_guide.json"
    guide_path.write_text(json.dumps(guide))
    sms.FORMATTING_GUIDE_FILE = guide_path
    sms._formatting_guide = None
    return guide
