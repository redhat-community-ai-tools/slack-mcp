"""
Metrics for the MCP server.

This module provides metrics for the MCP server.
"""

from typing import Callable, Any
from functools import wraps

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.responses import PlainTextResponse


# Define counter for request count
REQUEST_COUNT = Counter(
    "slack_mcp_tool_request_count",
    "Request count",
    ["tool"],
)

# Define histogram for request latency
REQUEST_LATENCY = Histogram(
    "slack_mcp_tool_request_duration",
    "Request latency",
    ["tool"],
    buckets=(0.1, 1.0, 10.0, 30.0, float("inf")),
)


def track_tool_usage() -> Callable:
    """Decorator to track tool usage metrics"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            tool_name = func.__name__
            REQUEST_COUNT.labels(tool=tool_name).inc()
            with REQUEST_LATENCY.labels(tool=tool_name).time():
                response = await func(*args, **kwargs)
            return response

        return wrapper

    return decorator


# Metrics route
async def metrics(request):
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
