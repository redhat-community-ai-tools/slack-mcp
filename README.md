# slack-mcp

MCP server for Slack

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
