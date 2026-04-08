---
name: setup-slack-mcp
description: Guide the user through setting up the redhat-community-ai-tools Slack MCP server for Claude Code. Use when user asks to set up the Slack MCP server, configure Slack for Claude, or connect Claude to Slack.
tools: Bash, Read, Write, Edit
---

# Set Up Slack MCP Server

Guide the user step-by-step through setting up the [redhat-community-ai-tools/slack-mcp](https://github.com/redhat-community-ai-tools/slack-mcp) server for Claude Code.

The server uses browser session tokens (`xoxc`/`xoxd`) extracted from a logged-in Slack session — no Slack admin approval or OAuth app required.

## Step 1: Check Prerequisites

```bash
python3 --version   # needs 3.8+
podman --version    # or: docker --version
```

If podman/docker is missing, tell the user to install it and stop here.

## Step 2: Set Up the Token Extractor

Clone [maorfr/slack-token-extractor](https://github.com/maorfr/slack-token-extractor) and install Playwright:

```bash
gh repo clone maorfr/slack-token-extractor ~/repos/slack-token-extractor
python3 -m venv ~/repos/slack-token-extractor/.venv
~/repos/slack-token-extractor/.venv/bin/pip install playwright
~/repos/slack-token-extractor/.venv/bin/playwright install chromium
```

## Step 3: Extract Slack Tokens

Run the extractor — it opens a browser window:

```bash
cd ~/repos/slack-token-extractor
.venv/bin/python playwright_extract.py
```

Log in to Slack when the browser opens, then follow the terminal prompts. Tokens are saved to `.slack_tokens.env`.

**Optional:** pass `--workspace https://yourworkspace.slack.com` to target a specific workspace.

After the first login the session is persisted, so future runs can use `--headless`.

## Step 4: Find Your Logs Channel ID

The MCP server requires a `LOGS_CHANNEL_ID` — a Slack channel where it will log activity.

To find a channel's ID: open Slack in a browser, navigate to the channel, and copy the ID from the URL:
`https://app.slack.com/client/TXXXXXXXX/`**`CXXXXXXXXX`** ← this is the channel ID

Ask the user which channel they want to use, then record the ID.

## Step 5: Create the Wrapper Script

Create a script that sources the tokens from the env file at runtime (so tokens are never stored in the MCP config):

Write the following to `~/repos/slack-token-extractor/run-slack-mcp.sh`, substituting the user's actual channel ID for `CXXXXXXXXX`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="$(dirname "$0")/.slack_tokens.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: $ENV_FILE not found. Run playwright_extract.py to generate it." >&2
  exit 1
fi

# Source the env file - it uses SLACK_MCP_* names, remap to what the server expects
source "$ENV_FILE"

exec podman run -i --rm \
  -e SLACK_XOXC_TOKEN="${SLACK_MCP_XOXC_TOKEN}" \
  -e SLACK_XOXD_TOKEN="${SLACK_MCP_XOXD_TOKEN}" \
  -e MCP_TRANSPORT=stdio \
  -e LOGS_CHANNEL_ID=CXXXXXXXXX \
  quay.io/redhat-ai-tools/slack-mcp
```

Then make it executable:

```bash
chmod +x ~/repos/slack-token-extractor/run-slack-mcp.sh
```

## Step 6: Register the MCP Server

```bash
claude mcp add -s user slack ~/repos/slack-token-extractor/run-slack-mcp.sh
```

## Step 7: Verify

Restart Claude Code. The `slack` MCP server should now appear in the available tools.

To test it, ask Claude: *"What channels do I have access to in Slack?"*

## Token Refresh

Tokens expire when the Slack browser session ends (typically weeks to months). When they stop working, re-run the extractor:

```bash
cd ~/repos/slack-token-extractor
.venv/bin/python playwright_extract.py --headless   # if session is still active
# or without --headless to log in again
```

No other changes needed — the wrapper script picks up the new tokens automatically.
