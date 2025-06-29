import os
from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP
import asyncio
from starlette.responses import PlainTextResponse

SLACK_API_BASE = "https://slack.com/api"
MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")
LOGS_CHANNEL_ID = os.environ["LOGS_CHANNEL_ID"]

mcp = FastMCP(
    "slack", settings={"host": "127.0.0.1" if MCP_TRANSPORT == "stdio" else "0.0.0.0"}
)

# Global metrics store
metrics = {
    'get_channel_history_total': 0,
    'post_message_total': 0,
    'post_command_total': 0,
    'add_reaction_total': 0,
    'whoami_total': 0,
    'join_channel_total': 0,
}
metrics_lock = asyncio.Lock()

async def make_request(
    url: str, payload: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    if MCP_TRANSPORT == "stdio":
        xoxc_token = os.environ["SLACK_XOXC_TOKEN"]
        xoxd_token = os.environ["SLACK_XOXD_TOKEN"]
    else:
        request_headers = mcp.get_context().request_context.request.headers
        xoxc_token = request_headers["X-Slack-Web-Token"]
        xoxd_token = request_headers["X-Slack-Cookie-Token"]

    headers = {
        "Authorization": f"Bearer {xoxc_token}",
        "Content-Type": "application/json",
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


@mcp.tool()
async def get_channel_history(channel_id: str) -> str:
    """Get the history of a channel."""
    async with metrics_lock:
        metrics['get_channel_history_total'] += 1
    await log_to_slack(f"Getting history of channel <#{channel_id}>")
    url = f"{SLACK_API_BASE}/conversations.history"
    payload = {"channel": channel_id}
    data = await make_request(url, payload=payload)
    if data and data.get("ok"):
        return data.get("messages", [])


@mcp.tool()
async def post_message(
    channel_id: str, message: str, thread_ts: str = "", skip_log: bool = False
) -> str:
    """Post a message to a channel."""
    async with metrics_lock:
        metrics['post_message_total'] += 1
    if not skip_log:
        await log_to_slack(f"Posting message to channel <#{channel_id}>: {message}")
    await join_channel(channel_id, skip_log=skip_log)
    url = f"{SLACK_API_BASE}/chat.postMessage"
    payload = {"channel": channel_id, "text": message}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    data = await make_request(url, payload=payload)
    return data.get("ok")


@mcp.tool()
async def post_command(
    channel_id: str, command: str, text: str, skip_log: bool = False
) -> str:
    """Post a command to a channel."""
    async with metrics_lock:
        metrics['post_command_total'] += 1
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
async def add_reaction(channel_id: str, message_ts: str, reaction: str) -> str:
    """Add a reaction to a message."""
    async with metrics_lock:
        metrics['add_reaction_total'] += 1
    await log_to_slack(
        f"Adding reaction to message {message_ts} in channel <#{channel_id}>: :{reaction}:"
    )
    url = f"{SLACK_API_BASE}/reactions.add"
    payload = {"channel": channel_id, "name": reaction, "timestamp": message_ts}
    data = await make_request(url, payload=payload)
    return data.get("ok")


@mcp.tool()
async def whoami() -> str:
    """Checks authentication & identity."""
    async with metrics_lock:
        metrics['whoami_total'] += 1
    await log_to_slack("Checking authentication & identity")
    url = f"{SLACK_API_BASE}/auth.test"
    data = await make_request(url)
    return data.get("user")


@mcp.tool()
async def join_channel(channel_id: str, skip_log: bool = False) -> str:
    """Join a channel."""
    async with metrics_lock:
        metrics['join_channel_total'] += 1
    if not skip_log:
        await log_to_slack(f"Joining channel <#{channel_id}>")
    url = f"{SLACK_API_BASE}/conversations.join"
    payload = {"channel": channel_id}
    data = await make_request(url, payload=payload)
    return data.get("ok")


@mcp.custom_route("/metrics", methods=["GET"])
async def metrics_endpoint(request):
    async with metrics_lock:
        lines = [f"{k} {v}" for k, v in metrics.items()]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain")


if __name__ == "__main__":
    mcp.run(transport=MCP_TRANSPORT)
