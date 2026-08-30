"""Data models for UZ801 SMS."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class SMSStatus(IntEnum):
    """SMS message type/status as stored in Android's content provider."""

    INBOX = 1      # Received message
    SENT = 2       # Successfully sent
    DRAFT = 3      # Saved as draft (not sent)
    OUTBOX = 4     # Queued for sending
    FAILED = 5     # Send failed
    QUEUED = 6     # Queued by system


class ReadState(IntEnum):
    """Whether a message has been read."""

    UNREAD = 0
    READ = 1


@dataclass
class SMS:
    """A single SMS message.

    Attributes:
        id:           Database row ID (from Android content provider).
        sender:       Sender phone number or name (for received messages).
        recipient:    Recipient phone number (for sent messages).
        body:         Message text content.
        timestamp:    Unix epoch timestamp (seconds).
        status:       Message type (INBOX, SENT, DRAFT, etc.).
        read:         Whether the message has been read.
        service_center: The SMSC that delivered the message.
        thread_id:    Android conversation thread ID.
        raw:          Raw dict from the content provider (all fields).
    """

    id: int
    sender: str = ""
    recipient: str = ""
    body: str = ""
    timestamp: int = 0
    status: SMSStatus = SMSStatus.INBOX
    read: ReadState = ReadState.UNREAD
    service_center: str = ""
    thread_id: Optional[int] = None
    raw: dict = field(default_factory=dict)

    @property
    def is_incoming(self) -> bool:
        """True if this is a received message (INBOX)."""
        return self.status == SMSStatus.INBOX

    @property
    def is_unread(self) -> bool:
        """True if the message hasn't been read yet."""
        return self.read == ReadState.UNREAD

    @property
    def datetime(self) -> str:
        """Human-readable datetime string (local time)."""
        if self.timestamp:
            try:
                return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp))
            except (ValueError, OSError):
                return str(self.timestamp)
        return "unknown"

    def __str__(self) -> str:
        direction = "From" if self.is_incoming else "To"
        party = self.sender if self.is_incoming else self.recipient
        return f"[{self.id}] {self.datetime} {direction} {party}: {self.body[:60]}"
