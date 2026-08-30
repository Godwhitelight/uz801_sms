"""Allow `python -m uz801_sms` as a quick CLI.

Usage:
    python -m uz801_sms read                 # Read all SMS
    python -m uz801_sms read --unread        # Read unread only
    python -m uz801_sms send +972501234567 "Hello"
    python -m uz801_sms monitor              # Live monitor
    python -m uz801_sms info                 # Device info
    python -m uz801_sms delete 3             # Delete by ID
    python -m uz801_sms delete --all         # Delete all
    python -m uz801_sms setup               # One-time ADB setup
"""

import sys
import argparse


def main():
    parser = argparse.ArgumentParser(
        prog="uz801_sms",
        description="Send, receive, and monitor SMS on the UZ801 4G LTE USB dongle.",
    )
    sub = parser.add_subparsers(dest="command")

    # setup
    sub.add_parser("setup", help="One-time: enable ADB debug mode on the dongle")

    # info
    sub.add_parser("info", help="Show device info (IMEI, firmware, network, signal)")

    # read
    read_p = sub.add_parser("read", help="Read SMS messages")
    read_p.add_argument("--unread", action="store_true", help="Only unread messages")
    read_p.add_argument("--inbox", action="store_true", help="Only inbox messages")
    read_p.add_argument("--sent", action="store_true", help="Only sent messages")

    # send
    send_p = sub.add_parser("send", help="Send an SMS")
    send_p.add_argument("phone", help="Phone number with country code (e.g. +972501234567)")
    send_p.add_argument("message", help="SMS message text")

    # monitor
    mon_p = sub.add_parser("monitor", help="Monitor for new incoming SMS")
    mon_p.add_argument("--interval", type=float, default=3, help="Poll interval (seconds)")
    mon_p.add_argument("--delete", action="store_true", help="Delete SMS after reading")

    # delete
    del_p = sub.add_parser("delete", help="Delete SMS")
    del_p.add_argument("id", nargs="?", type=int, help="SMS ID to delete")
    del_p.add_argument("--all", action="store_true", help="Delete all SMS")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Import here so `--help` is instant
    from uz801_sms.manager import UZ801
    from uz801_sms.exceptions import UZ801Error

    dongle = UZ801()

    try:
        if args.command == "setup":
            print("Setting up UZ801 (enabling ADB debug mode)...")
            dongle.setup()
            print("Done! Dongle is ready.")

        elif args.command == "info":
            if not dongle.is_connected():
                print("Dongle not connected. Run: python -m uz801_sms setup")
                sys.exit(1)
            info = dongle.get_info()
            for k, v in info.items():
                print(f"  {k}: {v}")

        elif args.command == "read":
            if not dongle.is_connected():
                print("Dongle not connected. Run: python -m uz801_sms setup")
                sys.exit(1)
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
            for sms in messages:
                print(sms)

        elif args.command == "send":
            if not dongle.is_connected():
                print("Dongle not connected. Run: python -m uz801_sms setup")
                sys.exit(1)
            print(f"Sending to {args.phone}...")
            if dongle.send_sms(args.phone, args.message):
                print("SMS queued for sending.")
            else:
                print("SMS may not have been sent (check signal/SIM balance).")

        elif args.command == "monitor":
            if not dongle.is_connected():
                print("Dongle not connected. Run: python -m uz801_sms setup")
                sys.exit(1)
            print("Monitoring for new SMS... (Ctrl+C to stop)\n")

            def on_sms(sms):
                status = "UNREAD" if sms.is_unread else "READ"
                print(f"[{sms.id}] {status} from {sms.sender}")
                print(f"  {sms.datetime}")
                print(f"  {sms.body}")
                print("-" * 50)

            dongle.monitor(on_sms, interval=args.interval, auto_delete=args.delete)

        elif args.command == "delete":
            if not dongle.is_connected():
                print("Dongle not connected. Run: python -m uz801_sms setup")
                sys.exit(1)
            if args.all:
                count = dongle.delete_all_sms()
                print(f"Deleted {count} message(s).")
            elif args.id:
                if dongle.delete_sms(args.id):
                    print(f"Deleted message {args.id}.")
                else:
                    print(f"Failed to delete message {args.id}.")
            else:
                print("Specify an ID or use --all.")

    except UZ801Error as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
