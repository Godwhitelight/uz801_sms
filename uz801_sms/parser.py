"""Parse ``content query`` output into structured data."""

from __future__ import annotations

import re
from typing import Any

from uz801_sms.constants import (
    FIELD_ID, FIELD_ADDRESS, FIELD_BODY, FIELD_DATE,
    FIELD_READ, FIELD_TYPE, FIELD_SERVICE_CENTER, FIELD_THREAD_ID,
)
from uz801_sms.models import SMS, SMSStatus, ReadState


def parse_content_query(output: str) -> list[dict[str, Any]]:
    """Parse ``content query`` output into a list of row dicts.

    Each line looks like::

        Row: 0 _id=3, address=+972501234567, body=Hello, type=1, read=0

    Multi-line bodies are handled by joining subsequent non-Row lines
    to the ``body`` field of the current row.
    """
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] = {}

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("Row:"):
            # Save previous row
            if current:
                rows.append(current)
            current = {}

            # Parse "Row: N key1=val1, key2=val2, ..."
            # Remove the "Row: N" prefix
            match = re.match(r"Row:\s*\d+\s*(.*)", line)
            if match:
                rest = match.group(1)
                _parse_kv_pairs(rest, current)
        elif line and "=" in line and not line.startswith("Result:"):
            # Continuation of previous row data (key=value pairs)
            _parse_kv_pairs(line, current)
        elif current and FIELD_BODY in current:
            # Multi-line body content (no = sign, append to body)
            current[FIELD_BODY] += "\n" + line

    if current:
        rows.append(current)

    return rows


def _parse_kv_pairs(text: str, target: dict[str, Any]) -> None:
    """Parse ``key1=val1, key2=val2, ...`` into ``target`` dict."""
    # Split on ", " but be careful with commas inside values
    # Android content query uses ", " as separator
    parts = _smart_split(text, ", ")
    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()
            v = v.strip()
            # Type-convert known integer fields
            if k in (FIELD_ID, FIELD_TYPE, FIELD_READ, FIELD_THREAD_ID):
                try:
                    target[k] = int(v) if v != "NULL" else None
                except ValueError:
                    target[k] = v
            elif k == FIELD_DATE:
                try:
                    target[k] = int(v)
                except ValueError:
                    target[k] = v
            else:
                target[k] = v


def _smart_split(text: str, sep: str) -> list[str]:
    """Split on ``sep`` but don't split inside quoted strings."""
    result = []
    current = []
    in_quotes = False
    quote_char = None
    i = 0
    sep_len = len(sep)

    while i < len(text):
        char = text[i]
        if char in ('"', "'"):
            if not in_quotes:
                in_quotes = True
                quote_char = char
            elif char == quote_char:
                in_quotes = False
                quote_char = None
            current.append(char)
        elif not in_quotes and text[i:i + sep_len] == sep:
            result.append("".join(current))
            current = []
            i += sep_len
            continue
        else:
            current.append(char)
        i += 1

    if current:
        result.append("".join(current))

    return result


def rows_to_sms(rows: list[dict[str, Any]]) -> list[SMS]:
    """Convert raw content-provider rows into ``SMS`` objects."""
    messages = []
    for row in rows:
        try:
            status = SMSStatus(row.get(FIELD_TYPE, 1))
        except ValueError:
            status = SMSStatus.INBOX

        try:
            read = ReadState(row.get(FIELD_READ, 0))
        except ValueError:
            read = ReadState.UNREAD

        address = str(row.get(FIELD_ADDRESS, ""))
        is_incoming = status == SMSStatus.INBOX

        sms = SMS(
            id=row.get(FIELD_ID, 0) or 0,
            sender=address if is_incoming else "",
            recipient=address if not is_incoming else "",
            body=str(row.get(FIELD_BODY, "")),
            timestamp=row.get(FIELD_DATE, 0) or 0,
            status=status,
            read=read,
            service_center=str(row.get(FIELD_SERVICE_CENTER, "")),
            thread_id=row.get(FIELD_THREAD_ID),
            raw=row,
        )
        messages.append(sms)

    return messages
