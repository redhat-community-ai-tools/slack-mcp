import os
from typing import Any, Literal
import httpx
from mcp.server.fastmcp import FastMCP
import re
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

SLACK_API_BASE = "https://slack.com/api"
MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")
LOGS_CHANNEL_ID = os.environ["LOGS_CHANNEL_ID"]
OUTPUT_FORMAT = os.environ.get("OUTPUT_FORMAT", "compact").lower()

# Cache file path (in same directory as script)
SCRIPT_DIR = Path(__file__).parent
USER_CACHE_FILE = SCRIPT_DIR / ".user_cache.json"

# Cache for channel name to ID mapping
_channel_cache: dict[str, str] = {}

# Cache for user ID to handle mapping
_user_cache: dict[str, str] = {}

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


def parse_timestamp(date_str: str, is_end_of_range: bool = False) -> str:
    """Convert various date formats to Slack Unix timestamp.

    Args:
        date_str: Unix timestamp or ISO 8601 date string
        is_end_of_range: If True and date has no time, use end of day (23:59:59.999999)
                        If False and date has no time, use start of day (00:00:00)

    Returns:
        Unix timestamp as string with microsecond precision
    """
    if not date_str:
        return ""

    # Already a Unix timestamp (with or without microseconds)
    if re.match(r"^\d+(\.\d+)?$", date_str):
        return date_str

    # Parse ISO 8601 date
    try:
        # Check if it's a date-only format (no time component)
        is_date_only = re.match(r"^\d{4}-\d{2}-\d{2}$", date_str)

        if is_date_only:
            # Parse date and set time based on whether it's start or end of range
            dt = datetime.fromisoformat(date_str)
            if is_end_of_range:
                # End of day: 23:59:59.999999
                dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)
            else:
                # Start of day: 00:00:00
                dt = dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
        else:
            # Has time component, parse as-is
            # Handle both with and without timezone
            if 'Z' in date_str:
                date_str = date_str.replace('Z', '+00:00')
            dt = datetime.fromisoformat(date_str)
            # If no timezone info, assume UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

        # Convert to Unix timestamp with microsecond precision
        return f"{dt.timestamp():.6f}"
    except ValueError as e:
        print(f"Error parsing date '{date_str}': {e}")
        return ""


def _load_user_cache() -> None:
    """Load user cache from disk."""
    global _user_cache

    try:
        if USER_CACHE_FILE.exists():
            with open(USER_CACHE_FILE, 'r') as f:
                _user_cache = json.load(f)
            print(f"Loaded {len(_user_cache)} user handles from cache")
    except Exception as e:
        print(f"Error loading user cache: {e}")
        _user_cache = {}


def _save_user_cache() -> None:
    """Save user cache to disk."""
    try:
        with open(USER_CACHE_FILE, 'w') as f:
            json.dump(_user_cache, f, indent=2)
    except Exception as e:
        print(f"Error saving user cache: {e}")


async def get_user_handle(user_id: str) -> str:
    """Get user handle by ID with caching. Returns user_id if lookup fails."""
    global _user_cache

    if not user_id:
        return ""

    # Check cache first
    if user_id in _user_cache:
        return _user_cache[user_id]

    # Cache miss - fetch user info
    url = f"{SLACK_API_BASE}/users.info"
    payload = {"user": user_id}
    data = await make_request(url, method="GET", payload=payload)

    if data and data.get("ok"):
        user = data.get("user", {})
        profile = user.get("profile", {})
        # Prefer display_name, fall back to real_name, then name
        handle = (
            profile.get("display_name")
            or user.get("real_name")
            or user.get("name")
            or user_id
        )
        _user_cache[user_id] = handle
        _save_user_cache()  # Persist to disk
        return handle

    # If lookup fails, cache the user_id itself to avoid repeated failed lookups
    _user_cache[user_id] = user_id
    _save_user_cache()  # Persist to disk
    return user_id


async def replace_user_mentions(text: str) -> str:
    """Replace user ID mentions (<@USERID>) with handles (@handle)."""
    if not text:
        return text

    # Find all user mentions in the format <@USERID>
    mention_pattern = r'<@([A-Z0-9]+)>'
    matches = re.finditer(mention_pattern, text)

    # Process each mention
    replacements = {}
    for match in matches:
        user_id = match.group(1)
        if user_id not in replacements:
            handle = await get_user_handle(user_id)
            replacements[user_id] = handle

    # Replace all mentions with handles
    for user_id, handle in replacements.items():
        text = text.replace(f'<@{user_id}>', f'@{handle}')

    return text


async def filter_message_fields(message: dict[str, Any]) -> dict[str, Any] | str:
    """Filter message to only essential fields to reduce token usage."""
    # Extract essential fields
    text = message.get("text", "")
    user_id = message.get("user", "")
    ts = message.get("ts", "")
    thread_ts = message.get("thread_ts", "")

    # Get user handle instead of ID
    user_handle = await get_user_handle(user_id) if user_id else ""

    # Replace user mentions in text with handles
    text = await replace_user_mentions(text)

    if OUTPUT_FORMAT == "json":
        # Return structured JSON format with handle instead of ID
        filtered = {
            "text": text,
            "user": user_handle,
            "ts": ts,
        }
        if thread_ts:
            filtered["thread_ts"] = thread_ts
        return filtered
    else:
        # Return compact text format (default)
        result = f"[{ts}] @{user_handle}: {text}"
        if thread_ts and thread_ts != ts:
            result += f" [thread:{thread_ts}]"
        return result


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
async def get_channel_history(
    channel_id: str,
    limit: int = 1000,
    oldest: str = "",
    latest: str = ""
) -> list[dict[str, Any] | str]:
    """Get the history of a channel with pagination support. Limit parameter controls max messages to fetch (default 1000).

    Optional date filtering (accepts ISO 8601 dates or Unix timestamps):
    - oldest: Only messages after this date (e.g., "2024-01-15" or "2024-01-15T10:30:00")
    - latest: Only messages before this date (e.g., "2024-01-20" or "2024-01-20T18:00:00")

    Note: For date-only formats, 'oldest' defaults to start of day (00:00:00) and 'latest' to end of day (23:59:59).
    """
    await log_to_slack(f"Getting history of channel <#{channel_id}> (limit: {limit})")
    url = f"{SLACK_API_BASE}/conversations.history"

    # Parse timestamp parameters
    oldest_ts = parse_timestamp(oldest, is_end_of_range=False)
    latest_ts = parse_timestamp(latest, is_end_of_range=True)

    all_messages = []
    cursor = None

    while len(all_messages) < limit:
        payload = {"channel": channel_id, "limit": min(200, limit - len(all_messages))}
        if oldest_ts:
            payload["oldest"] = oldest_ts
        if latest_ts:
            payload["latest"] = latest_ts
        if cursor:
            payload["cursor"] = cursor

        data = await make_request(url, method="GET", payload=payload)

        if not data or not data.get("ok"):
            error_msg = data.get("error", "Unknown error") if data else "No response from Slack API"
            print(f"Error getting channel history: {error_msg}")
            break

        messages = data.get("messages", [])
        all_messages.extend(messages)

        # Check if there are more messages
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    print(f"Retrieved {len(all_messages)} messages from channel {channel_id}")

    # Pre-fetch all unique user handles to avoid duplicate API calls
    # Include both message authors and users mentioned in text
    unique_users = {msg.get("user") for msg in all_messages if msg.get("user")}

    # Extract user IDs from mentions in message text
    mention_pattern = r'<@([A-Z0-9]+)>'
    for msg in all_messages:
        text = msg.get("text", "")
        if text:
            mentioned_users = re.findall(mention_pattern, text)
            unique_users.update(mentioned_users)

    # Fetch all unique users
    for user_id in unique_users:
        await get_user_handle(user_id)

    # Filter messages to reduce token usage (now all users are cached)
    return await asyncio.gather(*[filter_message_fields(msg) for msg in all_messages])


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
async def refresh_user_cache() -> int:
    """Clear the user cache. Use this when user handles are outdated or if user lookups are failing. Returns the number of cached entries cleared."""
    global _user_cache
    await log_to_slack("Clearing user cache")
    count = len(_user_cache)
    _user_cache.clear()

    # Also remove the cache file
    try:
        if USER_CACHE_FILE.exists():
            USER_CACHE_FILE.unlink()
            print(f"Cleared {count} user cache entries and deleted cache file")
    except Exception as e:
        print(f"Cleared {count} user cache entries but failed to delete cache file: {e}")

    return count


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
) -> list[dict[str, Any] | str]:
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

    # Pre-fetch all unique user handles to avoid duplicate API calls
    # Include both message authors and users mentioned in text
    unique_users = {msg.get("user") for msg in all_matches if msg.get("user")}

    # Extract user IDs from mentions in message text
    mention_pattern = r'<@([A-Z0-9]+)>'
    for msg in all_matches:
        text = msg.get("text", "")
        if text:
            mentioned_users = re.findall(mention_pattern, text)
            unique_users.update(mentioned_users)

    # Fetch all unique users
    for user_id in unique_users:
        await get_user_handle(user_id)

    # Filter messages to reduce token usage (now all users are cached)
    return await asyncio.gather(*[filter_message_fields(msg) for msg in all_matches])


if __name__ == "__main__":
    # Load user cache from disk on startup
    _load_user_cache()
    mcp.run(transport=MCP_TRANSPORT)
