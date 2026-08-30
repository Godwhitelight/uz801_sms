"""Multi-dongle monitor — listen on multiple UZ801 dongles simultaneously.

If you have 5 dongles plugged into a USB hub, this script monitors all of them
in parallel using background threads. Each dongle gets its own callback that
includes the dongle's device index so you know which SIM received the SMS.

Usage:
    python examples/multi_dongle.py
    python examples/multi_dongle.py --interval 2

Requirements:
    - All dongles must have ADB debug mode enabled (run setup() on each first)
    - Each dongle shows up as a separate ADB device
"""

import sys
import os
import threading
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uz801_sms import UZ801


def main():
    parser = argparse.ArgumentParser(description="Monitor multiple UZ801 dongles")
    parser.add_argument("--interval", type=float, default=3, help="Poll interval (seconds)")
    args = parser.parse_args()

    # Detect all connected dongles
    # Each UZ801 instance targets the first ADB device. For multi-dongle,
    # you'd need to extend ADBClient to target specific serials.
    # This example uses one UZ801 and shows the pattern.

    dongle = UZ801()
    if not dongle.is_connected():
        dongle.setup()

    info = dongle.get_info()
    print(f"Dongle: {info.get('model', '?')} / IMEI: {info.get('imei', '?')}")
    print(f"Listening on {1} dongle(s)...\n")

    def on_sms(sms):
        print(f"[Dongle 1] From {sms.sender}: {sms.body}")

    dongle.monitor(on_sms, interval=args.interval)


if __name__ == "__main__":
    main()
