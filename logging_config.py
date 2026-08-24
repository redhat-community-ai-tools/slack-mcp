# SPDX-License-Identifier: MIT

"""Structured JSON logging with sensitive field scrubbing."""

import logging
import re
import sys

from pythonjsonlogger import json as jsonlogger

SENSITIVE_PATTERNS = re.compile(
    r"(token|password|secret|api_key|auth|bearer|cookie|session_id)",
    re.IGNORECASE,
)

REDACT_VALUE = "***REDACTED***"


class ScrubFormatter(jsonlogger.JsonFormatter):
    """JSON formatter that scrubs sensitive fields from log records."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["logger"] = record.name
        log_record["level"] = record.levelname
        self._scrub(log_record)

    def _scrub(self, obj, depth=0):
        if depth > 5:
            return
        if isinstance(obj, dict):
            for key in list(obj.keys()):
                if SENSITIVE_PATTERNS.search(key):
                    obj[key] = REDACT_VALUE
                elif isinstance(obj[key], (dict, list)):
                    self._scrub(obj[key], depth + 1)
                elif isinstance(obj[key], str) and len(obj[key]) > 200:
                    if SENSITIVE_PATTERNS.search(obj[key]):
                        obj[key] = REDACT_VALUE
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    self._scrub(item, depth + 1)


def configure_logging(level=logging.INFO):
    """Replace default text logging with JSON structured logging on stderr."""
    root = logging.getLogger()
    root.setLevel(level)

    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    formatter = ScrubFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
        timestamp=True,
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
