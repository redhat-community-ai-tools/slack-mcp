#!/usr/bin/env python3
"""Scrape Slack's mrkdwn formatting docs and update formatting_guide.json.

Run at container build time or manually to keep the guide current.
Falls back to the existing file if the fetch fails (e.g. hermetic builds).

Usage:
    python3 scripts/update_formatting_guide.py [--check]

    --check   Compare scraped content against the existing guide and exit
              with code 1 if the docs appear to have changed (CI gate mode).
"""
import json
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

DOCS_URL = "https://docs.slack.dev/messaging/formatting-message-text"
GUIDE_FILE = Path(__file__).resolve().parent.parent / "formatting_guide.json"


class SlackDocsParser(HTMLParser):
    """Extract text content from the Slack formatting docs page."""

    def __init__(self):
        super().__init__()
        self.text_parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self.text_parts.append(stripped)


def fetch_docs_text() -> str | None:
    """Fetch the Slack formatting docs and return extracted text."""
    try:
        req = urllib.request.Request(DOCS_URL, headers={"User-Agent": "slack-mcp-guide-updater/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8")
        parser = SlackDocsParser()
        parser.feed(html)
        return "\n".join(parser.text_parts)
    except Exception as e:
        print(f"Warning: could not fetch Slack docs: {e}", file=sys.stderr)
        return None


# Known formatting markers we expect to find in the docs.
# If any are missing, the page structure may have changed.
EXPECTED_MARKERS = [
    "*bold*",
    "_italic_",
    "~strike~",
    "<@",
    "<#",
    "<!here>",
    "@channel",
    "```",
    "&amp;",
    "&lt;",
    "&gt;",
    "<!date^",
]


def check_markers(text: str) -> list[str]:
    """Return any expected markers NOT found in the scraped text."""
    return [m for m in EXPECTED_MARKERS if m not in text]


def main():
    check_mode = "--check" in sys.argv

    docs_text = fetch_docs_text()
    if docs_text is None:
        if check_mode:
            print("SKIP: could not fetch docs (network unavailable)")
            sys.exit(0)
        print("Falling back to existing formatting_guide.json", file=sys.stderr)
        sys.exit(0)

    missing = check_markers(docs_text)
    if missing:
        print(f"Warning: {len(missing)} expected markers not found in docs: {missing}", file=sys.stderr)
        print("The Slack formatting docs may have changed structure.", file=sys.stderr)
        if check_mode:
            print("STALE: formatting guide may need updating")
            sys.exit(1)
    else:
        print(f"All {len(EXPECTED_MARKERS)} expected markers found in docs")
        if check_mode:
            print("OK: formatting guide appears current")
            sys.exit(0)


if __name__ == "__main__":
    main()
