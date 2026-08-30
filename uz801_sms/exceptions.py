"""Custom exceptions for UZ801 SMS."""

from __future__ import annotations


class UZ801Error(Exception):
    """Base exception for all UZ801-related errors."""


class DongleNotFoundError(UZ801Error):
    """The UZ801 dongle is not connected or not detected via ADB."""


class ADBNotFoundError(UZ801Error):
    """ADB (Android Debug Bridge) is not installed or not on PATH.

    Call ``UZ801.setup()`` to auto-download ADB, or install the
    Android platform-tools manually.
    """


class DebugModeError(UZ801Error):
    """Could not enable ADB debug mode on the dongle.

    This usually means the dongle's web UI is not reachable or
    the firmware version uses a different backdoor URL.
    """


class SMSError(UZ801Error):
    """An error occurred while sending, reading, or deleting SMS."""
