"""Internal constants for the UZ801."""

from __future__ import annotations

import os

# --- USB identifiers ---
USB_VENDOR_ID = "05c6"
USB_PRODUCT_ID = "90b6"
USB_ID = f"{USB_VENDOR_ID}:{USB_PRODUCT_ID}"

# --- Network ---
DONGLE_IP = "192.168.100.1"
ALT_DONGLE_IP = "192.168.43.1"
WEB_UI_TIMEOUT = 5  # seconds

# --- ADB ---
# ADB is bundled with this library. If it's missing, we download it.
ADB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "platform-tools")
ADB_PATH = os.path.join(ADB_DIR, "adb.exe")
ADB_DOWNLOAD_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
ADB_TIMEOUT = 15  # seconds for shell commands

# --- Debug backdoor URLs (firmware-version dependent) ---
DEBUG_URLS = [
    "/usbdebug.html",
    "/usb_debug.html",
]

# --- AJAX endpoints ---
AJAX_URL = "/ajax"

# --- Android content provider URIs ---
URI_SMS_ALL = "content://sms"
URI_SMS_INBOX = "content://sms/inbox"
URI_SMS_SENT = "content://sms/sent"
URI_SMS_OUTBOX = "content://sms/outbox"

# --- SMS field names in content provider ---
FIELD_ID = "_id"
FIELD_ADDRESS = "address"
FIELD_BODY = "body"
FIELD_DATE = "date"
FIELD_READ = "read"
FIELD_TYPE = "type"
FIELD_SERVICE_CENTER = "service_center"
FIELD_THREAD_ID = "thread_id"

# --- Default credentials ---
WEB_ADMIN_PASSWORD = "admin"
