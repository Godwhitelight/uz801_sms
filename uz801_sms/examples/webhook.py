"""Webhook Listener — forward incoming SMS to an HTTP endpoint.

Each new SMS is POSTed as JSON to your webhook URL. This lets you
integrate the UZ801 into any backend (Node.js, Go, Flask, etc.)

Usage:
    python examples/webhook.py http://localhost:8080/sms
    python examples/webhook.py https://api.myapp.com/sms-received --interval 2
    python examples/webhook.py http://localhost:8080/sms --delete

POST body format:
    {
        "id": 5,
        "sender": "+972501234567",
        "body": "Your OTP is 123456",
        "timestamp": 1395041066,
        "datetime": "2014-03-17 09:24:26",
        "service_center": "+972500200011"
    }

Example receiver (Flask):
    from flask import Flask, request
    app = Flask(__name__)

    @app.route('/sms', methods=['POST'])
    def receive_sms():
        data = request.json
        print(f"SMS from {data['sender']}: {data['body']}")
        return '', 200

    app.run(port=8080)
"""

import sys
import os
import json
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uz801_sms import UZ801


def post_webhook(url, sms):
    """POST SMS to webhook URL using curl (no external deps)."""
    payload = json.dumps({
        "id": sms.id,
        "sender": sms.sender,
        "body": sms.body,
        "timestamp": sms.timestamp,
        "datetime": sms.datetime,
        "service_center": sms.service_center,
    })

    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST",
             "-H", "Content-Type: application/json",
             "-d", payload, url,
             "--max-time", "10"],
            capture_output=True, text=True, timeout=15
        )
        print(f"  -> forwarded to {url} ({result.returncode})")
    except FileNotFoundError:
        # curl not available — try Python urllib
        import urllib.request
        req = urllib.request.Request(
            url, data=payload.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            print(f"  -> forwarded to {url}")
        except Exception as e:
            print(f"  -> webhook error: {e}")
    except Exception as e:
        print(f"  -> webhook error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Forward UZ801 SMS to a webhook")
    parser.add_argument("url", help="Webhook URL to POST new SMS to")
    parser.add_argument("--interval", type=float, default=3, help="Poll interval (seconds)")
    parser.add_argument("--delete", action="store_true", help="Delete SMS after forwarding")
    args = parser.parse_args()

    dongle = UZ801()
    if not dongle.is_connected():
        dongle.setup()

    print(f"Listening for SMS -> forwarding to {args.url}")
    print(f"Polling every {args.interval}s. Press Ctrl+C to stop.\n")

    def on_sms(sms):
        print(f"[{sms.datetime}] From {sms.sender}: {sms.body[:60]}")
        post_webhook(args.url, sms)

    dongle.monitor(on_sms, interval=args.interval, auto_delete=args.delete)


if __name__ == "__main__":
    main()
