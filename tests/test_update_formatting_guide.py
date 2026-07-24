"""Tests for the update_formatting_guide.py scraper/checker script."""

from unittest.mock import patch

import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from update_formatting_guide import check_markers, EXPECTED_MARKERS, SlackDocsParser


class TestCheckMarkers:
    def test_all_markers_present(self):
        text = " ".join(EXPECTED_MARKERS) + " extra content"
        missing = check_markers(text)
        assert missing == []

    def test_some_markers_missing(self):
        text = "*bold* _italic_ ``` &amp;"
        missing = check_markers(text)
        assert len(missing) > 0
        assert all(m not in text for m in missing)

    def test_empty_text_all_missing(self):
        missing = check_markers("")
        assert len(missing) == len(EXPECTED_MARKERS)

    def test_returns_specific_missing_markers(self):
        text = "*bold* _italic_ ~strike~ <@ <# <!here> @channel ``` &amp; &lt; &gt;"
        missing = check_markers(text)
        assert "<!date^" in missing
        assert "*bold*" not in missing


class TestSlackDocsParser:
    def test_extracts_text(self):
        parser = SlackDocsParser()
        parser.feed("<html><body><p>Hello world</p></body></html>")
        assert "Hello world" in parser.text_parts

    def test_skips_script_tags(self):
        parser = SlackDocsParser()
        parser.feed("<html><script>var x = 1;</script><p>Visible</p></html>")
        assert "Visible" in parser.text_parts
        assert "var x = 1;" not in parser.text_parts

    def test_skips_style_tags(self):
        parser = SlackDocsParser()
        parser.feed("<html><style>.foo{color:red}</style><p>Content</p></html>")
        assert "Content" in parser.text_parts
        assert ".foo" not in parser.text_parts

    def test_skips_nav_and_footer(self):
        parser = SlackDocsParser()
        parser.feed("<nav>Navigation</nav><main>Main content</main><footer>Footer</footer>")
        assert "Main content" in parser.text_parts
        assert "Navigation" not in parser.text_parts
        assert "Footer" not in parser.text_parts

    def test_skips_empty_text(self):
        parser = SlackDocsParser()
        parser.feed("<p>   </p><p>Real content</p>")
        assert "Real content" in parser.text_parts
        assert len(parser.text_parts) == 1


class TestExpectedMarkers:
    def test_markers_list_not_empty(self):
        assert len(EXPECTED_MARKERS) >= 10

    def test_markers_cover_key_formatting(self):
        markers_str = " ".join(EXPECTED_MARKERS)
        assert "*bold*" in markers_str
        assert "_italic_" in markers_str
        assert "```" in markers_str
        assert "<@" in markers_str
        assert "<#" in markers_str
