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

## Steps 2–6: Run the Setup Script

The setup script handles everything from here: venv creation, Playwright install, token extraction, wrapper script generation, and Claude Code registration.

Download and run it in a **separate terminal** (it cannot run inside Claude Code because it opens a browser window):

```bash
python3 <(curl -fsSL https://raw.githubusercontent.com/redhat-community-ai-tools/slack-mcp/main/scripts/setup-slack-mcp.py)
```

Or if the user has already cloned this repo:

```bash
python3 /path/to/slack-mcp/scripts/setup-slack-mcp.py
```

Tell the user:

> Run the script in a separate terminal. It will:
>
> 1. Install Playwright and Chromium (one-time, ~2 min)
> 2. Pull the `quay.io/redhat-ai-tools/slack-mcp` container image
> 3. Open a Chromium browser — **log in to Slack**, then press Enter in the terminal
> 4. Prompt you for a Slack channel ID to receive server logs (a self-DM or DM with Slackbot works well — navigate there in https://app.slack.com and copy the last segment of the URL)
> 5. Write the wrapper script and update `~/.claude/settings.json` automatically
>
> Come back here when the script prints "Setup complete!"

**Wait for the user to confirm the script finished before proceeding.**

## Step 7: Restart and Verify

Tell the user:

> Please fully restart Claude Code now. The `slack` MCP tools will not be available until the next session.

**Wait for the user to confirm they have restarted.**

The `slack` MCP server should now appear in the available tools. Suggest they test it by asking: *"What channels do I have access to in Slack?"*

## Token Refresh

Tokens expire when the Slack browser session ends (typically weeks to months). When they stop working, run:

```bash
python3 /path/to/slack-mcp/scripts/setup-slack-mcp.py --refresh-tokens
```

No other changes needed — the wrapper script picks up the new tokens automatically.
