import os
from typing import Any, Literal
import httpx
from mcp.server.fastmcp import FastMCP
import re

SLACK_API_BASE = "https://slack.com/api"
MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")
LOGS_CHANNEL_ID = os.environ["LOGS_CHANNEL_ID"]

# Cache for channel name to ID mapping
_channel_cache: dict[str, str] = {}

mcp = FastMCP(
    "slack", settings={"host": "127.0.0.1" if MCP_TRANSPORT == "stdio" else "0.0.0.0"}
)


async def make_request(
    url: str, method: str = "POST", payload: dict[str, Any] | None = None
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

    async with httpx.AsyncClient(cookies=cookies) as client:
        try:
            if method.upper() == "GET":
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=payload,
                    timeout=30.0,
                )
            else:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=payload,
                    timeout=30.0,
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
async def get_channel_history(channel_id: str) -> list[dict[str, Any]]:
    """Get the history of a channel."""
    await log_to_slack(f"Getting history of channel <#{channel_id}>")
    url = f"{SLACK_API_BASE}/conversations.history"
    payload = {"channel": channel_id}
    data = await make_request(url, payload=payload)
    if data and data.get("ok"):
        return data.get("messages", [])


async def _load_channels_to_cache() -> bool:
    """Load all channels into the cache. Returns True if successful."""
    global _channel_cache

    url = f"{SLACK_API_BASE}/conversations.list"
    payload = {"exclude_archived": "true", "types": "public_channel,private_channel"}
    data = await make_request(url, method="GET", payload=payload)

    if data and data.get("ok"):
        channels = data.get("channels", [])
        _channel_cache.clear()
        for channel in channels:
            channel_name = channel.get("name", "")
            channel_id = channel.get("id", "")
            if channel_name and channel_id:
                _channel_cache[channel_name] = channel_id
        print(f"Loaded {len(_channel_cache)} channels into cache")
        return True

    error_msg = data.get("error", "Unknown error") if data else "No response from Slack API"
    print(f"Error loading channels to cache: {error_msg}")
    return False


@mcp.tool()
async def get_channel_id_by_name(channel_name: str) -> str:
    """Get the channel ID by channel name. The channel name can be with or without the # prefix."""
    # Remove # prefix if present
    clean_name = channel_name.lstrip("#")
    await log_to_slack(f"Looking up channel ID for channel name: {clean_name}")

    # Check cache first
    if clean_name in _channel_cache:
        print(f"Channel '{clean_name}' found in cache")
        return _channel_cache[clean_name]

    # Cache miss - load all channels
    print(f"Cache miss for '{clean_name}', loading channels...")
    if await _load_channels_to_cache():
        # Check cache again after loading
        if clean_name in _channel_cache:
            return _channel_cache[clean_name]

    print(f"Channel '{clean_name}' not found")
    return ""


@mcp.tool()
async def refresh_channel_cache() -> bool:
    """Refresh the channel cache. Use this when new channels are created or if channel lookups are failing."""
    await log_to_slack("Refreshing channel cache")
    return await _load_channels_to_cache()


@mcp.tool()
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
async def whoami() -> str:
    """Checks authentication & identity."""
    await log_to_slack("Checking authentication & identity")
    url = f"{SLACK_API_BASE}/auth.test"
    data = await make_request(url)
    return data.get("user")


@mcp.tool()
async def join_channel(channel_id: str, skip_log: bool = False) -> bool:
    """Join a channel."""
    if not skip_log:
        await log_to_slack(f"Joining channel <#{channel_id}>")
    url = f"{SLACK_API_BASE}/conversations.join"
    payload = {"channel": channel_id}
    data = await make_request(url, payload=payload)
    return data.get("ok")


@mcp.tool()
async def send_dm(user_id: str, message: str) -> bool:
    """Send a direct message to a user."""
    await log_to_slack(f"Sending direct message to user <@{user_id}>: {message}")
    url = f"{SLACK_API_BASE}/conversations.open"
    payload = {"users": user_id, "return_dm": True}
    data = await make_request(url, payload=payload)
    if data.get("ok"):
        return await post_message(data.get("channel").get("id"), message)
    return False


@mcp.tool()
async def search_messages(
    query: str, sort: Literal["timestamp", "score"] = "timestamp", limit: int = 1000
) -> list[dict[str, Any]]:
    """Search for messages in the workspace with pagination support. Limit parameter controls max results to fetch (default 1000)."""
    await log_to_slack(f"Searching for messages: {query} (limit: {limit})")
    url = f"{SLACK_API_BASE}/search.messages"

    all_matches = []
    page = 1

    while len(all_matches) < limit:
        payload = {
            "query": query,
            "sort": sort,
            "count": min(100, limit - len(all_matches)),  # Slack max is 100 per page
            "page": page
        }

        data = await make_request(url, method="GET", payload=payload)

        if not data or not data.get("ok"):
            error_msg = data.get("error", "Unknown error") if data else "No response from Slack API"
            print(f"Error searching messages: {error_msg}")
            break

        messages_data = data.get("messages", {})
        matches = messages_data.get("matches", [])
        all_matches.extend(matches)

        # Check pagination info
        total_pages = messages_data.get("pagination", {}).get("page_count", 1)
        if page >= total_pages or len(matches) == 0:
            break

        page += 1

    print(f"Retrieved {len(all_matches)} search results for query: {query}")
    return all_matches


if __name__ == "__main__":
    mcp.run(transport=MCP_TRANSPORT)
