import os
import sys
from typing import Any, Literal
import httpx
from mcp.server.fastmcp import FastMCP
import re
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path


def log(msg: str) -> None:
    """Write diagnostic output to stderr (stdout is reserved for JSON-RPC in stdio mode)."""
    print(msg, file=sys.stderr, flush=True)


READ_ONLY_ENV_VAR = "SLACK_MCP_READ_ONLY"


def _is_read_only() -> bool:
    """True when operators want browse/search only — no Slack state changes."""
    v = os.environ.get(READ_ONLY_ENV_VAR, "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _deny_if_read_only() -> None:
    if _is_read_only():
        raise RuntimeError(
            f"This server is running in read-only mode ({READ_ONLY_ENV_VAR}). "
            "Mutating Slack operations (post message, DM, reactions, commands, join channel) are disabled."
        )


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

mcp = FastMCP("slack")


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
            log(str(e))
            return None


async def log_to_slack(message: str):
    if _is_read_only():
        log(f"[read-only] {message}")
        return
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
        log(f"Error parsing date '{date_str}': {e}")
        return ""


def _load_user_cache() -> None:
    """Load user cache from disk."""
    global _user_cache

    try:
        if USER_CACHE_FILE.exists():
            with open(USER_CACHE_FILE, 'r') as f:
                _user_cache = json.load(f)
            log(f"Loaded {len(_user_cache)} user handles from cache")
    except Exception as e:
        log(f"Error loading user cache: {e}")
        _user_cache = {}


def _save_user_cache() -> None:
    """Save user cache to disk."""
    try:
        with open(USER_CACHE_FILE, 'w') as f:
            json.dump(_user_cache, f, indent=2)
    except Exception as e:
        log(f"Error saving user cache: {e}")


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

    # Extract channel info (present in search results)
    channel = message.get("channel", {})
    channel_id = channel.get("id", "") if isinstance(channel, dict) else ""
    channel_name = channel.get("name", "") if isinstance(channel, dict) else ""

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
        if channel_id:
            filtered["channel_id"] = channel_id
        if channel_name:
            filtered["channel_name"] = channel_name
        return filtered
    else:
        # Return compact text format (default)
        result = f"[{ts}] @{user_handle}: {text}"
        if channel_id:
            result += f" [channel:{channel_id}|{channel_name}]"
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


async def get_thread_replies(channel_id: str, thread_ts: str) -> list[dict[str, Any]]:
    """Get all replies in a thread."""
    url = f"{SLACK_API_BASE}/conversations.replies"
    payload = {"channel": channel_id, "ts": thread_ts}

    data = await make_request(url, method="GET", payload=payload)

    if not data or not data.get("ok"):
        error_msg = data.get("error", "Unknown error") if data else "No response from Slack API"
        log(f"Error getting thread replies: {error_msg}")
        return []

    # Returns all messages including the parent, so we skip the first one
    messages = data.get("messages", [])
    return messages[1:] if len(messages) > 1 else []


@mcp.tool()
async def get_thread(
    channel_id: str,
    thread_ts: str,
    limit: int = 100
) -> list[dict[str, Any] | str]:
    """Get all messages in a thread given a channel ID and the parent message timestamp.

    Use this to read a full conversation thread before replying to it.
    The thread_ts is the timestamp of the parent message that started the thread.
    """
    await log_to_slack(f"Getting thread {thread_ts} in channel <#{channel_id}> (limit: {limit})")
    url = f"{SLACK_API_BASE}/conversations.replies"
    payload = {
        "channel": channel_id,
        "ts": convert_thread_ts(thread_ts),
        "limit": limit,
    }

    data = await make_request(url, method="GET", payload=payload)

    if not data or not data.get("ok"):
        error_msg = data.get("error", "Unknown error") if data else "No response from Slack API"
        log(f"Error getting thread: {error_msg}")
        return []

    messages = data.get("messages", [])
    log(f"Retrieved {len(messages)} messages from thread {thread_ts}")

    # Pre-fetch all unique user handles
    unique_users = {msg.get("user") for msg in messages if msg.get("user")}
    mention_pattern = r'<@([A-Z0-9]+)>'
    for msg in messages:
        text = msg.get("text", "")
        if text:
            unique_users.update(re.findall(mention_pattern, text))
    for user_id in unique_users:
        await get_user_handle(user_id)

    return await asyncio.gather(*[filter_message_fields(msg) for msg in messages])


@mcp.tool()
async def get_channel_history(
    channel_id: str,
    limit: int = 1000,
    oldest: str = "",
    latest: str = "",
    include_threads: bool = False
) -> list[dict[str, Any] | str]:
    """Get the history of a channel with pagination support. Limit parameter controls max messages to fetch (default 1000).

    Optional date filtering (accepts ISO 8601 dates or Unix timestamps):
    - oldest: Only messages after this date (e.g., "2024-01-15" or "2024-01-15T10:30:00")
    - latest: Only messages before this date (e.g., "2024-01-20" or "2024-01-20T18:00:00")
    - include_threads: If True, also fetch all replies in threads (default False)

    Note: For date-only formats, 'oldest' defaults to start of day (00:00:00) and 'latest' to end of day (23:59:59).
    """
    await log_to_slack(f"Getting history of channel <#{channel_id}> (limit: {limit}, include_threads: {include_threads})")
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
            log(f"Error getting channel history: {error_msg}")
            break

        messages = data.get("messages", [])
        all_messages.extend(messages)

        # Check if there are more messages
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    log(f"Retrieved {len(all_messages)} messages from channel {channel_id}")

    # Fetch thread replies if requested
    if include_threads:
        thread_messages = []
        for msg in all_messages:
            # Check if message has replies (is a parent message)
            reply_count = msg.get("reply_count", 0)
            if reply_count > 0:
                thread_ts = msg.get("ts")
                if thread_ts:
                    replies = await get_thread_replies(channel_id, thread_ts)
                    thread_messages.extend(replies)

        all_messages.extend(thread_messages)
        log(f"Retrieved {len(thread_messages)} additional messages from threads")

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
    """Load all channels into the cache with pagination. Returns True if successful."""
    global _channel_cache

    url = f"{SLACK_API_BASE}/conversations.list"
    _channel_cache.clear()
    cursor = None

    while True:
        payload = {
            "exclude_archived": "true",
            "types": "public_channel,private_channel",
            "limit": 200,
        }
        if cursor:
            payload["cursor"] = cursor

        data = await make_request(url, method="GET", payload=payload)

        if not data or not data.get("ok"):
            error_msg = data.get("error", "Unknown error") if data else "No response from Slack API"
            log(f"Error loading channels to cache: {error_msg}")
            return bool(_channel_cache)

        for channel in data.get("channels", []):
            channel_name = channel.get("name", "")
            channel_id = channel.get("id", "")
            if channel_name and channel_id:
                _channel_cache[channel_name] = channel_id

        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    log(f"Loaded {len(_channel_cache)} channels into cache")
    return True


@mcp.tool()
async def get_channel_id_by_name(channel_name: str) -> str:
    """Get the channel ID by channel name. The channel name can be with or without the # prefix."""
    # Remove # prefix if present
    clean_name = channel_name.lstrip("#")
    await log_to_slack(f"Looking up channel ID for channel name: {clean_name}")

    # Check cache first
    if clean_name in _channel_cache:
        log(f"Channel '{clean_name}' found in cache")
        return _channel_cache[clean_name]

    # Cache miss - load all channels
    log(f"Cache miss for '{clean_name}', loading channels...")
    if await _load_channels_to_cache():
        # Check cache again after loading
        if clean_name in _channel_cache:
            return _channel_cache[clean_name]

    log(f"Channel '{clean_name}' not found")
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
            log(f"Cleared {count} user cache entries and deleted cache file")
    except Exception as e:
        log(f"Cleared {count} user cache entries but failed to delete cache file: {e}")

    return count


@mcp.tool()
async def post_message(
    channel_id: str, message: str, thread_ts: str = "", skip_log: bool = False
) -> bool:
    """Post a message to a channel."""
    _deny_if_read_only()
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
    _deny_if_read_only()
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
    _deny_if_read_only()
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
    _deny_if_read_only()
    if not skip_log:
        await log_to_slack(f"Joining channel <#{channel_id}>")
    url = f"{SLACK_API_BASE}/conversations.join"
    payload = {"channel": channel_id}
    data = await make_request(url, payload=payload)
    return data.get("ok")


@mcp.tool()
async def list_joined_channels(
    exclude_archived: bool = True,
    limit: int = 1000,
    types: str = "public_channel,private_channel",
) -> list[dict[str, Any]]:
    """List channels the authenticated user is a member of.

    Uses Slack's users.conversations API. By default returns public and private
    channels only. To include DMs and group DMs, set types to e.g.
    \"public_channel,private_channel,im,mpim\".
    """
    await log_to_slack(
        f"Listing joined channels (limit: {limit}, types: {types}, exclude_archived: {exclude_archived})"
    )
    url = f"{SLACK_API_BASE}/users.conversations"
    all_channels: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(all_channels) < limit:
        payload: dict[str, Any] = {
            "types": types,
            "limit": min(200, limit - len(all_channels)),
            "exclude_archived": "true" if exclude_archived else "false",
        }
        if cursor:
            payload["cursor"] = cursor

        data = await make_request(url, method="GET", payload=payload)

        if not data or not data.get("ok"):
            error_msg = data.get("error", "Unknown error") if data else "No response from Slack API"
            print(f"Error listing joined channels: {error_msg}")
            break

        for ch in data.get("channels", []):
            entry: dict[str, Any] = {
                "id": ch.get("id", ""),
                "name": ch.get("name", ""),
                "is_private": ch.get("is_private", False),
                "is_archived": ch.get("is_archived", False),
            }
            if ch.get("is_im"):
                entry["is_im"] = True
            if ch.get("is_mpim"):
                entry["is_mpim"] = True
            all_channels.append(entry)

        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    print(f"Listed {len(all_channels)} joined channels")
    return all_channels


@mcp.tool()
async def send_dm(user_id: str, message: str) -> bool:
    """Send a direct message to a user."""
    _deny_if_read_only()
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
            log(f"Error searching messages: {error_msg}")
            break

        messages_data = data.get("messages", {})
        matches = messages_data.get("matches", [])
        all_matches.extend(matches)

        # Check pagination info
        total_pages = messages_data.get("pagination", {}).get("page_count", 1)
        if page >= total_pages or len(matches) == 0:
            break

        page += 1

    log(f"Retrieved {len(all_matches)} search results for query: {query}")

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


@mcp.tool()
async def search_channel_messages(
    channel_id: str,
    query: str,
    sort: Literal["timestamp", "score"] = "timestamp",
    limit: int = 100,
) -> list[dict[str, Any] | str]:
    """Search for messages within a specific channel.

    Uses Slack's search API with an 'in:<channel>' filter.

    Args:
        channel_id: The channel ID to search within.
        query: The search query text.
        sort: Sort results by "timestamp" (newest first) or "score" (relevance).
        limit: Max number of results to return (default 100).
    """
    await log_to_slack(f"Searching in channel <#{channel_id}> for: {query} (limit: {limit})")
    url = f"{SLACK_API_BASE}/search.messages"

    all_matches = []
    page = 1
    scoped_query = f"in:<#{channel_id}> {query}"

    while len(all_matches) < limit:
        payload = {
            "query": scoped_query,
            "sort": sort,
            "count": min(100, limit - len(all_matches)),
            "page": page,
        }

        data = await make_request(url, method="GET", payload=payload)

        if not data or not data.get("ok"):
            error_msg = data.get("error", "Unknown error") if data else "No response from Slack API"
            print(f"Error searching channel messages: {error_msg}")
            break

        messages_data = data.get("messages", {})
        matches = messages_data.get("matches", [])
        all_matches.extend(matches)

        total_pages = messages_data.get("pagination", {}).get("page_count", 1)
        if page >= total_pages or len(matches) == 0:
            break

        page += 1

    print(f"Retrieved {len(all_matches)} search results for query in channel {channel_id}")

    unique_users = {msg.get("user") for msg in all_matches if msg.get("user")}
    mention_pattern = r'<@([A-Z0-9]+)>'
    for msg in all_matches:
        text = msg.get("text", "")
        if text:
            unique_users.update(re.findall(mention_pattern, text))
    for user_id in unique_users:
        await get_user_handle(user_id)

    return await asyncio.gather(*[filter_message_fields(msg) for msg in all_matches])


if __name__ == "__main__":
    if "--read-only" in sys.argv:
        os.environ[READ_ONLY_ENV_VAR] = "true"
        sys.argv = [a for a in sys.argv if a != "--read-only"]
    # Load user cache from disk on startup
    _load_user_cache()
    if _is_read_only():
        log(
            f"slack-mcp: read-only mode is active ({READ_ONLY_ENV_VAR}); "
            "mutating Slack tools will raise errors; audit lines go to stderr only."
        )
    mcp.run(transport=MCP_TRANSPORT)
