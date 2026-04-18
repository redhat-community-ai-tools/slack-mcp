# slack-mcp

A Model Context Protocol (MCP) server that enables AI assistants to interact with Slack workspaces. This server provides a bridge between AI tools and Slack, allowing you to read messages, post content, and manage Slack channels programmatically through MCP-compatible clients.

## What is this and why should I use it?

This MCP server transforms your Slack workspace into an AI-accessible environment. Instead of manually switching between your AI assistant and Slack, you can now:

- **Read channel messages** - Get real-time updates and conversation history
- **Post messages and commands** - Send text, files, or execute Slack commands
- **Manage reactions** - Add emoji reactions to messages
- **Join channels** - Automatically join new channels as needed
- **Thread conversations** - Maintain context in threaded discussions

### Key Benefits

- **Seamless Integration**: Connect your AI assistant directly to Slack without manual copy-pasting
- **Automated Workflows**: Build AI-powered Slack bots that can read, analyze, and respond to messages
- **Enhanced Productivity**: Let AI help manage notifications, summarize conversations, or automate routine Slack tasks
- **Real-time Collaboration**: Enable AI assistants to participate in team discussions and provide instant insights

### Use Cases

- **Team Assistant**: Have an AI that can read team updates and provide summaries
- **Notification Manager**: Automatically categorize and respond to incoming messages
- **Knowledge Base**: AI that can search through channel history and provide context
- **Meeting Scheduler**: AI that can read meeting requests and help coordinate schedules

## Setting Up with Claude Code

This repo ships as a Claude Code plugin with a guided setup skill. Claude will walk you through the entire process — no manual config editing required.

Run the setup script. It handles everything — venv, Playwright, token extraction, wrapper script, and Claude Code registration. The only interaction required is logging in to Slack when the browser opens, and entering a channel ID for server logs.

```bash
python3 <(curl -fsSL https://raw.githubusercontent.com/redhat-community-ai-tools/slack-mcp/main/scripts/setup-slack-mcp.py)
```

Or clone the repo first and run it locally:

```bash
git clone https://github.com/redhat-community-ai-tools/slack-mcp
python3 slack-mcp/scripts/setup-slack-mcp.py
```

**Options:**

| Flag | Description |
|------|-------------|
| `--logs-channel DXXXXXXXXX` | Slack channel ID for server logs (prompted if omitted) |
| `--workspace https://myco.slack.com` | Specific Slack workspace to open |
| `--refresh-tokens` | Re-extract tokens when they expire (skips all other steps) |
| `--skip-verify` | Skip the post-setup smoke test |

When tokens expire, just run:
```bash
python3 slack-mcp/scripts/setup-slack-mcp.py --refresh-tokens
```

---

## Read-only mode

For agents or automation that should **browse and search** Slack without posting, reacting, running commands, or joining channels, enable read-only mode.

- **Environment variable:** set `SLACK_MCP_READ_ONLY` to a truthy value (`1`, `true`, `yes`, or `on`, case-insensitive).
- **CLI:** pass `--read-only` when starting `slack_mcp_server.py` (equivalent to setting the variable).

In read-only mode, tools that mutate Slack state (`post_message`, `send_dm`, `post_command`, `add_reaction`, `join_channel`) raise a clear error. Read tools (history, search, threads, `whoami`, channel listing, cache refresh helpers, and so on) behave as usual. Tool activity that would normally be mirrored to `LOGS_CHANNEL_ID` is written to **stderr** instead so the logs channel is not written to.

On startup, the server logs a line to stderr when read-only mode is active.

For Podman or Docker, add `-e SLACK_MCP_READ_ONLY=true` (and the matching key in `env`) when you want the container to run read-only.

## Running with Podman or Docker

You can run the slack-mcp server in a container using Podman or Docker:

Example configuration for running with Podman:

```json
{
  "mcpServers": {
    "slack": {
      "command": "podman",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e", "SLACK_XOXC_TOKEN",
        "-e", "SLACK_XOXD_TOKEN",
        "-e", "MCP_TRANSPORT",
        "-e", "LOGS_CHANNEL_ID",
        "quay.io/redhat-ai-tools/slack-mcp"
      ],
      "env": {
        "SLACK_XOXC_TOKEN": "xoxc-...",
        "SLACK_XOXD_TOKEN": "xoxd-...",
        "MCP_TRANSPORT": "stdio",
        "LOGS_CHANNEL_ID": "C7000000"
      }
    }
  }
}
```

## Running with non-stdio transport

To run the server with a non-stdio transport (such as SSE), set the `MCP_TRANSPORT` environment variable to a value other than `stdio` (e.g., `sse`).

Example configuration to connect to a non-stdio MCP server:

```json
{
  "mcpServers": {
    "slack": {
      "url": "https://slack-mcp.example.com/sse",
      "headers": {
        "X-Slack-Web-Token": "xoxc-...",
        "X-Slack-Cookie-Token": "xoxd-..."
      }
    }
  }
}
```

Extract your Slack XOXC and XOXD tokens easily using browser extensions or Selenium automation: https://github.com/maorfr/slack-token-extractor.
