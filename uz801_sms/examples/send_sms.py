"""Send an SMS.

Usage:
    python examples/send_sms.py +972501234567 "Hello World"
    python examples/send_sms.py +972501234567 "Hello" --no-wait

Note: The SIM must have credit/balance to send. Prepaid SIMs with zero
balance will silently fail (the message is accepted by Android but
rejected by the carrier network).
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uz801_sms import UZ801


def main():
    parser = argparse.ArgumentParser(description="Send an SMS via UZ801 dongle")
    parser.add_argument("phone", help="Phone number with country code (e.g. +972501234567)")
    parser.add_argument("message", help="SMS message text")
    parser.add_argument("--no-wait", action="store_true", help="Don't wait for send confirmation")
    args = parser.parse_args()

    dongle = UZ801()
    if not dongle.is_connected():
        dongle.setup()

    print(f"Sending to {args.phone}...")
    print(f"Message: {args.message}")

    try:
        if dongle.send_sms(args.phone, args.message, wait=not args.no_wait):
            print("SMS queued/sent successfully.")
        else:
            print("SMS may not have been sent (check signal, SIM balance, carrier).")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
