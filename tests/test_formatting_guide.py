"""Tests for get_formatting_guide and _load_formatting_guide."""

import json

import pytest

import slack_mcp_server as sms


class TestLoadFormattingGuide:
    def test_loads_from_file(self, sample_formatting_guide):
        guide = sms._load_formatting_guide()
        assert guide["rules"][0]["name"] == "bold"
        assert len(guide["unsupported"]) == 1

    def test_caches_after_first_load(self, sample_formatting_guide):
        first = sms._load_formatting_guide()
        second = sms._load_formatting_guide()
        assert first is second

    def test_returns_empty_when_file_missing(self, tmp_path):
        sms.FORMATTING_GUIDE_FILE = tmp_path / "nonexistent.json"
        guide = sms._load_formatting_guide()
        assert guide == {"rules": [], "unsupported": []}

    def test_returns_empty_on_invalid_json(self, tmp_path):
        bad_file = tmp_path / "formatting_guide.json"
        bad_file.write_text("not json{{{")
        sms.FORMATTING_GUIDE_FILE = bad_file
        guide = sms._load_formatting_guide()
        assert guide == {"rules": [], "unsupported": []}


class TestGetFormattingGuide:
    @pytest.mark.asyncio
    async def test_returns_guide(self, sample_formatting_guide):
        guide = await sms.get_formatting_guide()
        assert "rules" in guide
        assert "mentions" in guide
        assert "escaping" in guide
        assert "unsupported" in guide

    @pytest.mark.asyncio
    async def test_guide_has_required_sections(self, sample_formatting_guide):
        guide = await sms.get_formatting_guide()
        assert isinstance(guide["rules"], list)
        assert len(guide["rules"]) > 0
        rule = guide["rules"][0]
        assert "name" in rule
        assert "syntax" in rule
        assert "description" in rule

    @pytest.mark.asyncio
    async def test_guide_source_url(self, sample_formatting_guide):
        guide = await sms.get_formatting_guide()
        assert guide["source"].startswith("https://")


class TestShippedFormattingGuide:
    """Validate the actual formatting_guide.json shipped with the repo."""

    @pytest.fixture(autouse=True)
    def _use_real_guide(self):
        from pathlib import Path

        real_guide = Path(__file__).resolve().parent.parent / "formatting_guide.json"
        sms.FORMATTING_GUIDE_FILE = real_guide
        sms._formatting_guide = None

    def test_shipped_guide_loads(self):
        guide = sms._load_formatting_guide()
        assert len(guide["rules"]) >= 10
        assert len(guide["mentions"]) >= 4
        assert len(guide["escaping"]) >= 3
        assert len(guide["unsupported"]) >= 5

    def test_shipped_guide_has_critical_rules(self):
        guide = sms._load_formatting_guide()
        rule_names = {r["name"] for r in guide["rules"]}
        assert "bold" in rule_names
        assert "italic" in rule_names
        assert "code-block" in rule_names
        assert "link" in rule_names

    def test_shipped_guide_warns_about_markdown_bold(self):
        guide = sms._load_formatting_guide()
        unsupported_features = {u["feature"] for u in guide["unsupported"]}
        assert "markdown-bold" in unsupported_features
        assert "markdown-links" in unsupported_features
        assert "code-block-language" in unsupported_features
