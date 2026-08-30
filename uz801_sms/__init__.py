"""UZ801 SMS Manager — send, receive, and monitor SMS on UZ801 LTE dongles.

A pure-Python library that talks to the UZ801 4G LTE USB dongle (Qualcomm MSM8916)
via ADB and Android's content provider system. No AT commands, no serial drivers,
no firmware hacking — just plug in the dongle and use Python.

Quick Start:
    from uz801_sms import UZ801

    dongle = UZ801()          # auto-detects and connects
    dongle.setup()            # one-time: enable ADB debug mode

    # Read all SMS
    for sms in dongle.read_sms():
        print(f"[{sms.sender}] {sms.body}")

    # Send an SMS
    dongle.send_sms("+972501234567", "Hello from UZ801!")

    # Monitor for new SMS (blocking)
    def on_sms(sms):
        print(f"New SMS from {sms.sender}: {sms.body}")

    dongle.monitor(on_sms)
"""

from uz801_sms.manager import UZ801
from uz801_sms.models import SMS, SMSStatus
from uz801_sms.exceptions import (
    UZ801Error,
    DongleNotFoundError,
    ADBNotFoundError,
    DebugModeError,
    SMSError,
)

__version__ = "1.0.0"
__author__ = "Godwhitelight"
__license__ = "MIT"

__all__ = [
    "UZ801",
    "SMS",
    "SMSStatus",
    "UZ801Error",
    "DongleNotFoundError",
    "ADBNotFoundError",
    "DebugModeError",
    "SMSError",
]
