"""Read SMS — read all, unread, or by type.

Usage:
    python examples/read_sms.py                 # All messages
    python examples/read_sms.py --unread         # Unread only
    python examples/read_sms.py --inbox          # Inbox only
    python examples/read_sms.py --sent           # Sent only
    python examples/read_sms.py --delete         # Delete after reading
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uz801_sms import UZ801


def main():
    parser = argparse.ArgumentParser(description="Read SMS from UZ801 dongle")
    parser.add_argument("--unread", action="store_true", help="Only unread messages")
    parser.add_argument("--inbox", action="store_true", help="Only inbox messages")
    parser.add_argument("--sent", action="store_true", help="Only sent messages")
    parser.add_argument("--delete", action="store_true", help="Delete messages after reading")
    args = parser.parse_args()

    dongle = UZ801()
    if not dongle.is_connected():
        dongle.setup()

    if args.unread:
        messages = dongle.read_sms("unread")
    elif args.inbox:
        messages = dongle.read_sms("inbox")
    elif args.sent:
        messages = dongle.read_sms("sent")
    else:
        messages = dongle.read_sms("all")

    if not messages:
        print("No messages found.")
        return

    print(f"Found {len(messages)} message(s):\n")

    for sms in messages:
        status = "UNREAD" if sms.is_unread else "read"
        direction = "From" if sms.is_incoming else "To"
        party = sms.sender if sms.is_incoming else sms.recipient
        print(f"[{sms.id}] {status} {direction} {party}")
        print(f"  {sms.datetime}")
        print(f"  {sms.body}")
        print("-" * 60)

        if args.delete:
            if dongle.delete_sms(sms.id):
                print(f"  (deleted)")


if __name__ == "__main__":
    main()
