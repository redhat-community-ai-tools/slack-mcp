import os
from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP
import re
import uvicorn
from metrics import metrics, track_tool_usage

SLACK_API_BASE = "https://slack.com/api"
MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")
LOGS_CHANNEL_ID = os.environ["LOGS_CHANNEL_ID"]

mcp = FastMCP(
    "slack", settings={"host": "127.0.0.1" if MCP_TRANSPORT == "stdio" else "0.0.0.0"}
)


async def make_request(
    url: str, payload: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    if MCP_TRANSPORT == "stdio":
        xoxc_token = os.environ["SLACK_XOXC_TOKEN"]
        xoxd_token = os.environ["SLACK_XOXD_TOKEN"]
        user_agent = "MCP-Server/1.0"
    else:
        request_headers = mcp.get_context().request_context.request.headers
        xoxc_token = request_headers["X-Slack-Web-Token"]
        xoxd_token = request_headers["X-Slack-Cookie-Token"]
        user_agent = request_headers.get("User-Agent", "MCP-Server/1.0")

    headers = {
        "Authorization": f"Bearer {xoxc_token}",
        "Content-Type": "application/json",
        "User-Agent": user_agent,
    }

    cookies = {"d": xoxd_token}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                url, headers=headers, cookies=cookies, json=payload, timeout=30.0
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(e)
            return None


async def log_to_slack(message: str):
    await post_message(LOGS_CHANNEL_ID, message, skip_log=True)


# Validate and convert thread_ts if needed
def convert_thread_ts(ts: str) -> str:
    # If ts is already in the correct format, return as is
    if re.match(r"^\d+\.\d+$", ts):
        return ts
    # If ts is a long integer string (from Slack URL), convert it
    if re.match(r"^\d{16}$", ts):
        return f"{ts[:10]}.{ts[10:]}"
    return ""


@mcp.tool()
@track_tool_usage()
async def get_channel_history(channel_id: str) -> list[dict[str, Any]]:
    """Get the history of a channel."""
    await log_to_slack(f"Getting history of channel <#{channel_id}>")
    url = f"{SLACK_API_BASE}/conversations.history"
    payload = {"channel": channel_id}
    data = await make_request(url, payload=payload)
    if data and data.get("ok"):
        return data.get("messages", [])


@mcp.tool()
@track_tool_usage()
async def post_message(
    channel_id: str, message: str, thread_ts: str = "", skip_log: bool = False
) -> bool:
    """Post a message to a channel."""
    if not skip_log:
        await log_to_slack(f"Posting message to channel <#{channel_id}>: {message}")
    await join_channel(channel_id, skip_log=skip_log)
    url = f"{SLACK_API_BASE}/chat.postMessage"
    payload = {"channel": channel_id, "text": message}
    if thread_ts:
        payload["thread_ts"] = convert_thread_ts(thread_ts)
    data = await make_request(url, payload=payload)
    return data.get("ok")


@mcp.tool()
@track_tool_usage()
async def post_command(
    channel_id: str, command: str, text: str, skip_log: bool = False
) -> bool:
    """Post a command to a channel."""
    if not skip_log:
        await log_to_slack(
            f"Posting command to channel <#{channel_id}>: {command} {text}"
        )
    await join_channel(channel_id, skip_log=skip_log)
    url = f"{SLACK_API_BASE}/chat.command"
    payload = {"channel": channel_id, "command": command, "text": text}
    data = await make_request(url, payload=payload)
    return data.get("ok")


@mcp.tool()
@track_tool_usage("add_reaction")
async def add_reaction(channel_id: str, message_ts: str, reaction: str) -> bool:
    """Add a reaction to a message."""
    await log_to_slack(
        f"Adding reaction to message {message_ts} in channel <#{channel_id}>: :{reaction}:"
    )
    url = f"{SLACK_API_BASE}/reactions.add"
    payload = {
        "channel": channel_id,
        "name": reaction,
        "timestamp": convert_thread_ts(message_ts),
    }
    data = await make_request(url, payload=payload)
    return data.get("ok")


@mcp.tool()
@track_tool_usage()
async def whoami() -> str:
    """Checks authentication & identity."""
    await log_to_slack("Checking authentication & identity")
    url = f"{SLACK_API_BASE}/auth.test"
    data = await make_request(url)
    return data.get("user")


@mcp.tool()
@track_tool_usage()
async def join_channel(channel_id: str, skip_log: bool = False) -> bool:
    """Join a channel."""
    if not skip_log:
        await log_to_slack(f"Joining channel <#{channel_id}>")
    url = f"{SLACK_API_BASE}/conversations.join"
    payload = {"channel": channel_id}
    data = await make_request(url, payload=payload)
    return data.get("ok")


if __name__ == "__main__":
    if MCP_TRANSPORT == "stdio":
        mcp.run_stdio_async()
    elif MCP_TRANSPORT == "sse":
        app = mcp.sse_app()
        app.add_route("/metrics", metrics)
        uvicorn.run(app, host="0.0.0.0")
    elif MCP_TRANSPORT == "streamable-http":
        app = mcp.streamable_http_app()
        app.add_route("/metrics", metrics)
        uvicorn.run(app, host="0.0.0.0")
    else:
        raise ValueError(f"Invalid transport: {MCP_TRANSPORT}")
