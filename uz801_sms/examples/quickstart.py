"""Quick Start — read existing SMS and monitor for new ones in 30 seconds.

Requirements:
    - UZ801 dongle plugged into USB with a SIM card
    - Python 3.10+

Usage:
    python examples/quickstart.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uz801_sms import UZ801


def main():
    # 1. Connect
    dongle = UZ801()
    print(f"Connected: {dongle.is_connected()}")

    # 2. One-time setup (enables ADB debug mode — no-op if already done)
    if not dongle.is_connected():
        print("Running setup (enabling ADB debug mode)...")
        dongle.setup()

    # 3. Device info
    info = dongle.get_info()
    print(f"\nDevice:   {info.get('model', '?')}")
    print(f"Firmware: {info.get('firmware', '?')}")
    print(f"Android:  {info.get('android_version', '?')}")

    # 4. Read existing SMS
    print("\n--- Existing SMS ---")
    for sms in dongle.read_sms():
        print(sms)

    # 5. Monitor for new SMS (blocks until Ctrl+C)
    print("\n--- Monitoring for new SMS (Ctrl+C to stop) ---")

    def on_sms(sms):
        print(f"\n  NEW SMS from {sms.sender}")
        print(f"  {sms.body}")
        print(f"  ({sms.datetime})")

    dongle.monitor(on_sms, interval=3)


if __name__ == "__main__":
    main()
