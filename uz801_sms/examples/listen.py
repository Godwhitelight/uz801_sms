"""SMS Listener — continuously monitor for incoming SMS.

This is the main use case: run this script and it blocks forever,
printing each new SMS as it arrives. Perfect for OTP receiving,
notification systems, or feeding SMS into another application.

Usage:
    python examples/listen.py                        # Default: poll every 3s
    python examples/listen.py --interval 1            # Poll every 1s (faster)
    python examples/listen.py --delete                # Delete after reading
    python examples/listen.py --quiet                 # Only print new SMS (no status)

You can also pipe the output to a file:
    python examples/listen.py > sms_log.txt 2>&1 &
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uz801_sms import UZ801


def main():
    parser = argparse.ArgumentParser(description="Listen for incoming SMS on UZ801")
    parser.add_argument("--interval", type=float, default=3,
                        help="Poll interval in seconds (default: 3)")
    parser.add_argument("--delete", action="store_true",
                        help="Delete SMS after reading (keeps SIM clean)")
    parser.add_argument("--quiet", action="store_true",
                        help="Only print new SMS, no status messages")
    args = parser.parse_args()

    dongle = UZ801()
    if not dongle.is_connected():
        dongle.setup()

    if not args.quiet:
        # Show existing messages first
        existing = dongle.read_sms("inbox")
        print(f"{len(existing)} existing message(s) in inbox.")
        print(f"Listening for new SMS (polling every {args.interval}s)...")
        print("Press Ctrl+C to stop.\n")

    def on_sms(sms):
        print(f"[{sms.datetime}] From {sms.sender}:")
        print(f"  {sms.body}")
        print()

    dongle.monitor(
        on_sms,
        interval=args.interval,
        auto_delete=args.delete,
        auto_mark_read=True,
    )


if __name__ == "__main__":
    main()
