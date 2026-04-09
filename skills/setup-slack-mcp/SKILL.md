---
name: setup-slack-mcp
description: Guide the user through setting up the redhat-community-ai-tools Slack MCP server for Claude Code. Use when user asks to set up the Slack MCP server, configure Slack for Claude, or connect Claude to Slack.
tools: Bash, Read, Write, Edit
---

# Set Up Slack MCP Server

Guide the user step-by-step through setting up the [redhat-community-ai-tools/slack-mcp](https://github.com/redhat-community-ai-tools/slack-mcp) server for Claude Code.

The server uses browser session tokens (`xoxc`/`xoxd`) extracted from a logged-in Slack session — no Slack admin approval or OAuth app required.

## Step 0: Ensure This Plugin Is Installed

Check if the plugin is already installed:

```bash
cat ~/.claude/plugins/installed_plugins.json 2>/dev/null || echo '{}'
```

If `slack-mcp` does not appear in the output, the plugin needs to be registered as a marketplace source first. Read `~/.claude/settings.json` and add `redhat-community-ai-tools` under `extraKnownMarketplaces` (create the key if it doesn't exist, preserve all existing content):

```json
"extraKnownMarketplaces": {
  "redhat-community-ai-tools": {
    "source": {
      "source": "settings",
      "name": "redhat-community-ai-tools",
      "plugins": [
        {
          "name": "slack-mcp",
          "source": {
            "source": "github",
            "repo": "redhat-community-ai-tools/slack-mcp"
          }
        }
      ]
    }
  }
}
```

Then tell the user:

> I've updated your `~/.claude/settings.json`. Please run these two commands in the Claude Code prompt box, then come back:
>
> 1. `/reload-plugins`
> 2. `/plugin install slack-mcp@redhat-community-ai-tools`
>
> Once installed, tell me and I'll continue the setup.

**Wait for the user to confirm before proceeding.**

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

The extractor opens a real browser window so you can log in to Slack and let it capture your session tokens. You must run this interactively — it cannot run inside Claude Code directly.

Tell the user:

> Open a separate terminal and run:
>
> ```bash
> cd ~/repos/slack-token-extractor
> .venv/bin/python playwright_extract.py
> ```
>
> A Chromium browser window will open. Log in to Slack normally. Once you're logged in, return to the terminal. When the script asks:
>
> ```
> Do you want to save your tokens to '.slack_tokens.env'? [Y/n]
> ```
>
> Enter `Y` to save. The tokens will be written to `.slack_tokens.env` in that directory.
>
> **Optional:** If you have multiple workspaces and want to target a specific one, pass `--workspace https://yourworkspace.slack.com`.
>
> After the first successful run, your browser session is persisted locally, so future token refreshes can use `--headless` without logging in again.

**Wait for the user to confirm the tokens were extracted successfully before proceeding.**

## Step 4: Find Your Logs Channel ID

### Why is this needed?

The MCP server requires a dedicated Slack channel to write internal activity logs — things like errors, connection events, and debug output from the server itself. This keeps operational noise out of your real Slack conversations and gives you a place to look if something isn't working. The channel does not need to be shared with anyone; it just needs to exist and be accessible with your session tokens.

### Choosing a channel

Pick whichever option is most convenient — the channel only receives server logs, not your actual Slack messages:

- **DM with yourself** (easiest) — a self-DM is private, always exists, and requires no setup
- **DM with Slackbot** — similarly private and always available
- **A dedicated private channel** you create for this purpose (e.g., `#claude-mcp-logs`) — useful if you want logs clearly separated and labelled

### How to find the channel ID

Slack channel IDs are not shown in the UI by name — you need to grab them from the browser URL. The desktop app does not work for this; you must use a browser.

1. Open [https://app.slack.com](https://app.slack.com) in your browser and sign in to your workspace
2. Navigate to the channel or DM you want to use:
   - For a **self-DM**: click your own name in the left sidebar
   - For **Slackbot**: click "Slackbot" in the left sidebar
   - For a **channel**: click the channel name in the left sidebar
3. Look at the browser URL bar. It will look like:
   ```
   https://app.slack.com/client/TXXXXXXXX/CXXXXXXXXX
   ```
4. The **last path segment** — the part after the final `/` — is your channel ID. It starts with:
   - `C` for a public or private channel
   - `D` for a direct message
   - `G` for a group DM

Ask the user which option they'd like to use, have them navigate to it in the browser, and record the channel ID from the URL before proceeding.

## Step 5: Create the Wrapper Script

Create a script that sources the tokens from the env file at runtime (so tokens are never stored in the MCP config).

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

**After running this command, tell the user they MUST restart Claude Code before continuing.** Even if `claude mcp get slack` shows "Connected", the tools are not available until the next session. Tell the user:

> The MCP server has been registered. Please fully restart Claude Code now, then come back and we'll verify it's working.

**Wait for the user to confirm they have restarted before proceeding.**

## Step 7: Verify

The `slack` MCP server should now appear in the available tools.

Suggest they test it by asking: *"What channels do I have access to in Slack?"*

## Token Refresh

Tokens expire when the Slack browser session ends (typically weeks to months). When they stop working, re-run the extractor:

```bash
cd ~/repos/slack-token-extractor
.venv/bin/python playwright_extract.py --headless   # if session is still active
# or without --headless to log in again
```

No other changes needed — the wrapper script picks up the new tokens automatically.
