"""UZ801 — high-level SMS manager for the UZ801 LTE dongle.

This is the main entry point. See ``__init__.py`` for the quick-start guide.
"""

from __future__ import annotations

import time
import re
import threading
from typing import Optional, Callable, Literal

from uz801_sms import constants
from uz801_sms.adb_client import ADBClient
from uz801_sms.models import SMS, SMSStatus, ReadState
from uz801_sms.parser import parse_content_query, rows_to_sms
from uz801_sms.exceptions import (
    DongleNotFoundError,
    DebugModeError,
    SMSError,
    ADBNotFoundError,
)

# Type alias for the monitor callback
OnSMSCallback = Callable[[SMS], None]


def _parse_parcel_string(raw: str) -> str:
    """Extract the string value from an Android ``service call`` Parcel response.

    The Parcel format shows hex and ASCII side by side. The ASCII column
    (between single quotes) contains the string characters with dots for
    null bytes. We strip the dots to get the actual value.
    """
    import re as _re
    ascii_parts = _re.findall(r"'([^']*)'", raw)
    if not ascii_parts:
        return ""
    full = "".join(ascii_parts)
    return full.replace(".", "").strip()


class UZ801:
    """High-level interface to a UZ801 LTE dongle.

    Example::

        from uz801_sms import UZ801

        dongle = UZ801()
        dongle.setup()               # one-time: enable ADB debug mode

        for sms in dongle.read_sms():
            print(sms)

        dongle.send_sms("+972501234567", "Hello!")

    Args:
        adb_path: Path to ``adb.exe``. If ``None``, uses the bundled copy
                  (auto-downloaded by :meth:`setup`).
    """

    def __init__(self, adb_path: Optional[str] = None):
        self._adb = ADBClient(adb_path=adb_path)
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None

    # ================================================================
    #  SETUP / DETECTION
    # ================================================================

    def setup(self) -> None:
        """One-time setup: download ADB, enable debug mode, connect.

        Steps:
            1. Download ADB if not already present.
            2. Try to reach the dongle's web UI over USB (RNDIS).
            3. Enable the ADB debug backdoor.
            4. Wait for the device to reboot and appear in ADB.

        If the device is already in ADB mode, this is a no-op.

        Raises:
            ADBNotFoundError: Could not download ADB.
            DongleNotFoundError: Dongle not detected.
            DebugModeError: Could not enable debug mode.
        """
        # 1. Ensure ADB is available
        self._adb.ensure_installed()
        self._adb.start_server()

        # 2. Check if device is already connected
        if self._adb.get_device_serial():
            return  # already set up

        # 3. Try to enable debug mode via web UI
        self._enable_debug_mode()

        # 4. Wait for device to appear
        print("[uz801_sms] Waiting for dongle to reboot into ADB mode...")
        self._adb.wait_for_device(timeout=60)
        print("[uz801_sms] Dongle connected via ADB!")

    def is_connected(self) -> bool:
        """Return True if the dongle is reachable via ADB."""
        return self._adb.get_device_serial() is not None

    def _enable_debug_mode(self) -> None:
        """Trigger the hidden ADB debug backdoor on the dongle's web UI."""
        import urllib.request
        import urllib.error

        for ip in (constants.DONGLE_IP, constants.ALT_DONGLE_IP):
            for path in constants.DEBUG_URLS:
                url = f"http://{ip}{path}"
                try:
                    req = urllib.request.Request(url, method="GET")
                    urllib.request.urlopen(req, timeout=constants.WEB_UI_TIMEOUT)
                    print(f"[uz801_sms] Debug backdoor triggered: {url}")
                    print("[uz801_sms] Dongle will reboot now. Wait ~20 seconds.")
                    return
                except (urllib.error.URLError, urllib.error.HTTPError, OSError):
                    continue

        # Last resort: try AJAX
        for ip in (constants.DONGLE_IP, constants.ALT_DONGLE_IP):
            url = f"http://{ip}{constants.AJAX_URL}"
            try:
                import json as _json
                data = _json.dumps({"funcNo": "2001"}).encode()
                req = urllib.request.Request(url, data=data, method="POST")
                req.add_header("Content-Type", "application/json")
                urllib.request.urlopen(req, timeout=constants.WEB_UI_TIMEOUT)
                print(f"[uz801_sms] Debug backdoor triggered via AJAX: {url}")
                return
            except Exception:
                continue

        raise DebugModeError(
            "Could not enable ADB debug mode.\n"
            f"Manually visit http://{constants.DONGLE_IP}/usbdebug.html "
            "in your browser while the dongle is plugged in, then call setup() again."
        )

    # ================================================================
    #  INFO
    # ================================================================

    def get_info(self) -> dict[str, str]:
        """Return device info (IMEI, firmware, model, network, etc.).

        Returns a dict with keys like ``model``, ``firmware``,
        ``android_version``, ``imei``, ``network``, ``signal``.
        All values are strings (may be empty if unavailable).
        """
        info = {}
        info["model"] = self._adb.shell("getprop ro.product.model")
        info["firmware"] = self._adb.shell("getprop ro.build.display.id")
        info["android_version"] = self._adb.shell("getprop ro.build.version.release")
        info["imei"] = self._get_imei()
        info["network"] = self._clean_at("AT+COPS?")
        info["signal"] = self._clean_at("AT+CSQ")
        return {k: v for k, v in info.items() if v}

    def get_sim_info(self) -> dict[str, str]:
        """Return SIM card info.

        Retrieves as many identifiers as possible from the SIM and modem:

        - ``imsi``: International Mobile Subscriber Identity (always available)
        - ``imei``: International Mobile Equipment Identity
        - ``iccid``: Integrated Circuit Card ID (SIM serial number)
        - ``msisdn``: Phone number (often empty on prepaid SIMs)
        - ``carrier``: Network operator name
        - ``mcc``: Mobile Country Code (e.g. ``425`` = Israel)
        - ``mnc``: Mobile Network Code (e.g. ``030`` = Pelephone)
        - ``signal``: Signal quality (0-31, higher is better)

        Note:
            Many prepaid SIMs do not have the MSISDN (phone number)
            field programmed. In that case ``msisdn`` will be empty.
            You can often find the number in the carrier's welcome SMS
            (check ``dongle.read_sms()``).
        """
        info: dict[str, str] = {}

        # IMSI — always available
        imsi_raw = self._at_command("AT+CIMI")
        imsi = re.sub(r"[^0-9]", "", imsi_raw)
        if len(imsi) >= 10:
            info["imsi"] = imsi
            info["mcc"] = imsi[:3]
            info["mnc"] = imsi[3:6]

        # IMEI
        info["imei"] = self._get_imei()

        # ICCID (SIM serial number)
        iccid_raw = self._at_command("AT+QCCID")
        if "ERROR" not in iccid_raw and "+QCCID" not in iccid_raw:
            iccid = re.sub(r"[^0-9]", "", iccid_raw)
            if len(iccid) >= 18:
                info["iccid"] = iccid
        # Fallback: try AT+ICCID
        if "iccid" not in info:
            iccid_raw2 = self._at_command("AT+ICCID")
            iccid2 = re.sub(r"[^0-9]", "", iccid_raw2)
            if len(iccid2) >= 18:
                info["iccid"] = iccid2

        # MSISDN (phone number) — often empty on prepaid SIMs
        cnum_raw = self._at_command("AT+CNUM")
        # Response: +CNUM: "Name","+972501234567",129
        msisdn_match = re.search(r'\+CNUM:\s*"[^"]*","([^"]+)"', cnum_raw)
        if msisdn_match:
            info["msisdn"] = msisdn_match.group(1)
        else:
            info["msisdn"] = ""  # SIM doesn't have it programmed

        # Carrier name
        cops_raw = self._at_command("AT+COPS?")
        carrier_match = re.search(r'\+COPS:\s*[^,]*,[^,]*,"([^"]+)"', cops_raw)
        if carrier_match:
            info["carrier"] = carrier_match.group(1)
        else:
            # Fallback: from Android properties
            info["carrier"] = self._adb.shell("getprop gsm.operator.alpha")

        # Signal
        csq_raw = self._at_command("AT+CSQ")
        csq_match = re.search(r"\+CSQ:\s*(\d+)", csq_raw)
        if csq_match:
            info["signal"] = csq_match.group(1)

        return {k: v for k, v in info.items() if v}

    def get_phone_number(self) -> str:
        """Return the phone number (MSISDN) of the SIM, or empty string.

        Tries three methods in order and returns the first success:

            1. ``AT+CNUM`` — read MSISDN directly from the SIM's EF_MSISDN
               file via AT command. Rarely works on the UZ801 because the
               modem firmware has a broken SIM file-access layer.
            2. Android ``service call iphonesubinfo`` — scans transaction
               codes 1-20 for a phone-number-like value. On the UZ801 this
               typically returns a **factory default** number (e.g.
               ``+972505000151``) that is NOT the actual assigned number.
               Used as a fallback only.
            3. **Welcome SMS extraction** — searches the SMS inbox for a
               carrier activation/welcome message containing a phone number
               (e.g. Pelephone's "Congratulations. You can now use your
               Pelephone number: 0503499844"). This is the most reliable
               method on the UZ801 and is preferred over the service call
               result when both are available.

        Returns:
            The phone number as a string (e.g. ``"0503499844"`` or
            ``"+972503499844"``), or ``""`` if not found.

        Note:
            The UZ801's modem firmware cannot read EF_MSISDN from the SIM
            (``AT+CRSM`` returns "file not found" for file 0x6F40). The
            ``service call`` method returns a factory default, not the real
            assigned number. **The phone number is extracted from the
            carrier's welcome SMS**, not from the SIM's own storage. This
            means the SIM must have received at least one SMS from the
            carrier that mentions the phone number.
        """
        # Method 1: AT+CNUM (SIM-stored MSISDN)
        cnum_raw = self._at_command("AT+CNUM")
        match = re.search(r'\+CNUM:\s*"[^"]*","([^"]+)"', cnum_raw)
        if match:
            return match.group(1)

        # Method 2: Android service call (may return factory default)
        service_result = ""
        for code in range(1, 21):
            raw = self._adb.shell(f"service call iphonesubinfo {code} 2>/dev/null")
            if not raw or "Error" in raw or "ffffff" in raw:
                continue
            parsed = _parse_parcel_string(raw)
            cleaned = parsed.strip()
            if cleaned and (
                (cleaned.startswith("+") and len(cleaned) >= 8 and cleaned[1:].isdigit())
                or (cleaned.isdigit() and len(cleaned) >= 8 and len(cleaned) <= 15)
            ):
                service_result = cleaned
                break

        # Method 3: Parse carrier welcome SMS (most reliable on UZ801)
        sms_result = self._extract_number_from_sms()

        # Prefer SMS result (actual assigned number) over service call (factory default)
        if sms_result:
            return sms_result
        return service_result

    def _extract_number_from_sms(self) -> str:
        """Search SMS inbox for a carrier welcome message with a phone number.

        Looks for SMS containing keywords like "number", "your number",
        "phone number" and extracts the digits.

        Returns the phone number as a string, or empty string if not found.
        """
        messages = self.read_sms("inbox")
        if not messages:
            return ""

        # Patterns to match phone numbers in SMS text
        # Israeli numbers: 0XX-XXX-XXXX or 0XXXXXXXXX or +972XXXXXXXXX
        number_patterns = [
            # "your number: 0503499844" / "number: 0503499844"
            re.compile(r'number[:\s]+(0\d{8,9})', re.IGNORECASE),
            re.compile(r'number[:\s]+(\+972\d{8,9})', re.IGNORECASE),
            # "Your Pelephone number: 0503499844"
            re.compile(r'(\d{10})', re.IGNORECASE),  # 10-digit Israeli mobile
            # Generic: any 9-10 digit sequence starting with 0 or +972
            re.compile(r'(\+972\d{8,9})'),
            re.compile(r'(0[5-9]\d{7,8})'),  # Israeli mobile: 05X/06X/07X/08X/09X
        ]

        # Keywords that indicate a welcome/activation SMS
        keywords = ["number", "your", "welcome", "congratulations",
                    "activation", "activated"]

        for sms in messages:
            body = sms.body or ""
            body_lower = body.lower()

            # Check if this SMS looks like a carrier welcome message
            if not any(kw in body_lower for kw in keywords):
                continue

            # Try each number pattern
            for pattern in number_patterns:
                match = pattern.search(body)
                if match:
                    number = match.group(1)
                    # Validate: Israeli mobile numbers are 10 digits starting with 0
                    # or international format +972 + 9 digits
                    if number.startswith("0") and len(number) == 10:
                        return number
                    elif number.startswith("+972") and len(number) >= 12:
                        return number

        return ""

    # ================================================================
    #  READ SMS
    # ================================================================

    def read_sms(
        self,
        filter: Literal["all", "inbox", "unread", "sent"] = "all",
    ) -> list[SMS]:
        """Read SMS messages from the dongle.

        Args:
            filter: Which messages to read.
                - ``"all"``: All messages (default).
                - ``"inbox"``: Only received messages.
                - ``"unread"``: Only unread received messages.
                - ``"sent"``: Only sent messages.

        Returns:
            List of :class:`SMS` objects, newest first.
        """
        if filter == "inbox":
            cmd = (
                f"content query --uri {constants.URI_SMS_INBOX} "
                f"--projection {constants.FIELD_ID}:{constants.FIELD_ADDRESS}:"
                f"{constants.FIELD_BODY}:{constants.FIELD_DATE}:{constants.FIELD_READ}:"
                f"{constants.FIELD_TYPE}:{constants.FIELD_SERVICE_CENTER}:"
                f"{constants.FIELD_THREAD_ID} --sort '{constants.FIELD_DATE} DESC'"
            )
        elif filter == "unread":
            cmd = (
                f"content query --uri {constants.URI_SMS_INBOX} "
                f"--projection {constants.FIELD_ID}:{constants.FIELD_ADDRESS}:"
                f"{constants.FIELD_BODY}:{constants.FIELD_DATE}:{constants.FIELD_READ}:"
                f"{constants.FIELD_TYPE}:{constants.FIELD_SERVICE_CENTER} "
                f"--where \"read=0\" --sort '{constants.FIELD_DATE} DESC'"
            )
        elif filter == "sent":
            cmd = (
                f"content query --uri {constants.URI_SMS_SENT} "
                f"--projection {constants.FIELD_ID}:{constants.FIELD_ADDRESS}:"
                f"{constants.FIELD_BODY}:{constants.FIELD_DATE}:{constants.FIELD_TYPE} "
                f"--sort '{constants.FIELD_DATE} DESC'"
            )
        else:
            cmd = (
                f"content query --uri {constants.URI_SMS_ALL} "
                f"--projection {constants.FIELD_ID}:{constants.FIELD_ADDRESS}:"
                f"{constants.FIELD_BODY}:{constants.FIELD_DATE}:{constants.FIELD_READ}:"
                f"{constants.FIELD_TYPE}:{constants.FIELD_SERVICE_CENTER}:"
                f"{constants.FIELD_THREAD_ID} --sort '{constants.FIELD_DATE} DESC'"
            )

        output = self._adb.shell(cmd, timeout=20)
        if not output or output.startswith("Error"):
            return []

        rows = parse_content_query(output)
        return rows_to_sms(rows)

    # ================================================================
    #  SEND SMS
    # ================================================================

    def send_sms(self, phone: str, message: str, wait: bool = True) -> bool:
        """Send an SMS.

        Args:
            phone: Recipient phone number with country code (e.g. ``"+972501234567"``).
            message: Message text.
            wait: If True, wait and check whether the message was sent.

        Returns:
            ``True`` if the message was successfully queued or sent.

        Raises:
            SMSError: If the content provider rejects the message.
        """
        # Escape for shell
        phone_esc = phone.replace("'", "\\'")
        msg_esc = message.replace("'", "\\'").replace('"', '\\"')

        cmd = (
            f"content insert --uri {constants.URI_SMS_OUTBOX} "
            f"--bind {constants.FIELD_ADDRESS}:s:'{phone_esc}' "
            f"--bind {constants.FIELD_BODY}:s:'{msg_esc}' "
            f"--bind {constants.FIELD_TYPE}:i:2 "
            f"--bind {constants.FIELD_DATE}:l:{int(time.time())} "
            f"--bind {constants.FIELD_READ}:i:1 "
            f"--bind delivery_report:i:1"
        )

        output = self._adb.shell(cmd, timeout=15)

        if output and ("Error" in output or "ERROR" in output):
            raise SMSError(f"Failed to insert SMS into outbox: {output}")

        if not wait:
            return True

        # Wait for Android to send it
        time.sleep(5)

        # Check: the message should have moved from outbox to sent
        check = self._adb.shell(
            f"content query --uri {constants.URI_SMS_SENT} "
            f"--projection {constants.FIELD_ID}:{constants.FIELD_ADDRESS}:{constants.FIELD_BODY}:{constants.FIELD_TYPE} "
            f"--where \"{constants.FIELD_ADDRESS}='{phone_esc}'\" --sort '{constants.FIELD_DATE} DESC'",
            timeout=10,
        )

        # If we find a sent message with matching content, success
        if phone_esc.replace("\\", "") in check and message[:20] in check:
            return True

        # Check if it's still in outbox (pending)
        outbox = self._adb.shell(
            f"content query --uri {constants.URI_SMS_OUTBOX} "
            f"--projection {constants.FIELD_ID}:{constants.FIELD_ADDRESS} "
            f"--where \"{constants.FIELD_ADDRESS}='{phone_esc}'\"",
            timeout=10,
        )

        if outbox and "Row:" in outbox:
            print("[uz801_sms] SMS is still in outbox (may be sending or failed to send)")
            return False

        # Check failed
        failed = self._adb.shell(
            f"content query --uri content://sms/failed "
            f"--projection {constants.FIELD_ID}:{constants.FIELD_ADDRESS} "
            f"--where \"{constants.FIELD_ADDRESS}='{phone_esc}'\"",
            timeout=10,
        )

        if failed and "Row:" in failed:
            raise SMSError(f"SMS send failed (found in failed folder)")

        # No trace found — might have been sent successfully
        return True

    # ================================================================
    #  DELETE SMS
    # ================================================================

    def delete_sms(self, sms_id: int) -> bool:
        """Delete a single SMS by its ID.

        Args:
            sms_id: The message ID (from ``SMS.id``).

        Returns:
            ``True`` if deleted successfully.
        """
        output = self._adb.shell(
            f"content delete --uri {constants.URI_SMS_ALL} "
            f"--where \"_id={sms_id}\"",
            timeout=10,
        )
        return "Error" not in output

    def delete_all_sms(self) -> int:
        """Delete ALL SMS messages from the dongle.

        Returns:
            Number of messages that were deleted.
        """
        count = len(self.read_sms())
        if count == 0:
            return 0
        self._adb.shell(f"content delete --uri {constants.URI_SMS_ALL}", timeout=15)
        return count

    def mark_read(self, sms_id: int) -> bool:
        """Mark a message as read."""
        output = self._adb.shell(
            f"content update --uri {constants.URI_SMS_ALL} "
            f"--bind read:i:1 --where \"_id={sms_id}\"",
            timeout=10,
        )
        return "Error" not in output

    # ================================================================
    #  MONITOR (blocking + thread-based)
    # ================================================================

    def monitor(
        self,
        callback: OnSMSCallback,
        interval: float = 3.0,
        auto_delete: bool = False,
        auto_mark_read: bool = True,
    ) -> None:
        """Block forever, calling ``callback`` for each new incoming SMS.

        Args:
            callback: Function called with an :class:`SMS` object for each
                      new message.
            interval: Polling interval in seconds (default 3).
            auto_delete: Delete messages after reading (default False).
            auto_mark_read: Mark messages as read after the callback returns
                           (default True).

        Example::

            def on_sms(sms):
                print(f"From {sms.sender}: {sms.body}")

            dongle.monitor(on_sms)
        """
        self._monitoring = True

        # Track seen IDs so we only fire for new messages
        seen: set[str] = set()
        initial = self.read_sms("inbox")
        for sms in initial:
            seen.add(str(sms.id))

        print(f"[uz801_sms] Monitoring started ({len(seen)} existing messages, "
              f"polling every {interval}s). Press Ctrl+C to stop.")

        try:
            while self._monitoring:
                messages = self.read_sms("inbox")
                for sms in messages:
                    if str(sms.id) not in seen:
                        seen.add(str(sms.id))
                        try:
                            callback(sms)
                        except Exception as e:
                            print(f"[uz801_sms] Callback error: {e}")

                        if auto_mark_read:
                            self.mark_read(sms.id)
                        if auto_delete:
                            self.delete_sms(sms.id)
                            seen.discard(str(sms.id))

                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[uz801_sms] Monitoring stopped.")
        finally:
            self._monitoring = False

    def monitor_async(
        self,
        callback: OnSMSCallback,
        interval: float = 3.0,
        auto_delete: bool = False,
        auto_mark_read: bool = True,
    ) -> threading.Thread:
        """Start monitoring in a background thread (non-blocking).

        Returns the thread object. Call ``thread.stop()`` or set
        ``dongle._monitoring = False`` to stop.

        Example::

            thread = dongle.monitor_async(on_sms)
            # ... do other things ...
            dongle.stop_monitor()
        """
        self._monitoring = True
        thread = threading.Thread(
            target=self.monitor,
            args=(callback, interval, auto_delete, auto_mark_read),
            daemon=True,
        )
        thread.start()
        return thread

    def stop_monitor(self) -> None:
        """Stop a monitor started with :meth:`monitor_async`."""
        self._monitoring = False

    # ================================================================
    #  SMS POLLER (on-device interceptor)
    # ================================================================

    def start_poller(self) -> bool:
        """Start the on-device SmsPoller process.

        The SmsPoller is a small Java program that runs directly on the
        dongle (via ``app_process``) and polls ``content://sms`` every
        500ms. It writes incoming SMS to ``/data/local/tmp/sms_hook/``
        before the Mms app can delete them (~2s window).

        This is necessary because the UZ801's Mms app auto-deletes
        incoming SMS shortly after receipt. The poller captures the
        full message (including multi-part and unicode) before deletion.

        Prerequisites:
            - The smshook.dex file must be deployed to the dongle.
              Call :meth:`deploy_poller` first if not already deployed.

        Returns:
            ``True`` if the poller is running, ``False`` if deployment failed.
        """
        # Check if already running
        ps = self._adb.shell("ps | grep app_process 2>/dev/null")
        if "com.godwhitelight.smshook.SmsPoller" in ps:
            return True

        # Check if dex is deployed
        check = self._adb.shell("ls /data/local/tmp/smshook.dex 2>/dev/null")
        if "No such file" in check or not check.strip():
            if not self.deploy_poller():
                return False

        # Start the poller in background
        self._adb.shell(
            "export ANDROID_DATA=/data && "
            "export CLASSPATH=/data/local/tmp/smshook.dex && "
            "app_process /data/local/tmp com.godwhitelight.smshook.SmsPoller "
            "> /data/local/tmp/smshook.log 2>&1 &",
            timeout=5
        )

        # Wait for it to start
        time.sleep(3)
        log = self._adb.shell("cat /data/local/tmp/smshook.log 2>/dev/null")
        if "SmsPoller: Starting" in log or "Polling every" in log:
            print("[uz801_sms] SmsPoller running on dongle")
            return True
        print(f"[uz801_sms] SmsPoller failed to start. Log: {log}")
        return False

    def stop_poller(self) -> bool:
        """Kill the SmsPoller process on the dongle.

        Returns:
            ``True`` if the process was found and killed.
        """
        # Find and kill the poller process
        ps = self._adb.shell("ps | grep SmsPoller 2>/dev/null")
        if not ps.strip():
            return False
        self._adb.shell("pkill -f SmsPoller 2>/dev/null || killall app_process 2>/dev/null")
        time.sleep(1)
        return True

    def deploy_poller(self) -> bool:
        """Deploy the smshook.dex file to the dongle.

        The pre-compiled DEX is bundled with this library. It's pushed to
        ``/data/local/tmp/smshook.dex`` on the dongle.

        Returns:
            ``True`` if deployment succeeded.
        """
        import os

        # Find the DEX file bundled with the library
        lib_dir = os.path.dirname(os.path.abspath(__file__))
        dex_path = os.path.join(lib_dir, "smshook.dex")

        if not os.path.exists(dex_path):
            # Try parent directory (repo root)
            dex_path = os.path.join(os.path.dirname(lib_dir), "smshook.dex")

        if not os.path.exists(dex_path):
            print("[uz801_sms] smshook.dex not found. See smshook/README.md for build instructions.")
            return False

        # Push to dongle
        adb = self._adb.adb_path
        import subprocess
        result = subprocess.run(
            [adb, "push", dex_path, "/data/local/tmp/smshook.dex"],
            capture_output=True, timeout=10
        )
        if result.returncode != 0:
            print(f"[uz801_sms] Failed to push smshook.dex")
            return False

        # Create output directory
        self._adb.shell("mkdir -p /data/local/tmp/sms_hook")
        self._adb.shell("chmod 777 /data/local/tmp/sms_hook")

        print("[uz801_sms] smshook.dex deployed")
        return True

    def read_captured(self) -> list[SMS]:
        """Read SMS captured by the on-device SmsPoller.

        Returns SMS messages written to ``/data/local/tmp/sms_hook/``
        by the poller. These are messages that may have been deleted
        from the content provider before :meth:`read_sms` could see them.

        Returns:
            List of :class:`SMS` objects from captured files.
        """
        # Read the _latest.txt file
        raw = self._adb.shell("cat /data/local/tmp/sms_hook/_latest.txt 2>/dev/null")
        if not raw.strip():
            return []

        messages = []
        # Entries are separated by "---"
        for block in raw.split("---"):
            block = block.strip()
            if not block:
                continue
            sms = self._parse_captured_block(block)
            if sms:
                messages.append(sms)

        return messages

    def _parse_captured_block(self, block: str) -> Optional[SMS]:
        """Parse a key=value block from the SmsPoller's _latest.txt."""
        fields = {}
        for line in block.split("\n"):
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                fields[k.strip()] = v.strip()

        if "id" not in fields:
            return None

        try:
            sms_id = int(fields.get("id", 0))
        except ValueError:
            return None

        try:
            ts = int(fields.get("timestamp", 0))
        except ValueError:
            ts = 0

        return SMS(
            id=sms_id,
            sender=fields.get("sender", ""),
            body=fields.get("body", ""),
            timestamp=ts,
            status=SMSStatus.INBOX,
            read=ReadState.UNREAD,
            service_center=fields.get("service_center", ""),
            raw=fields,
        )

    def monitor_with_poller(
        self,
        callback: OnSMSCallback,
        interval: float = 1.0,
        auto_delete: bool = True,
    ) -> None:
        """Monitor for new SMS using the on-device poller.

        This is the recommended way to receive SMS on the UZ801. It uses
        the on-device SmsPoller to capture messages before the Mms app
        deletes them, then polls the captured files.

        Args:
            callback: Called with each new :class:`SMS`.
            interval: Polling interval in seconds (default 1).
            auto_delete: Clear captured files after reading (default True).

        Example::

            dongle.start_poller()

            def on_sms(sms):
                print(f"From {sms.sender}: {sms.body}")

            dongle.monitor_with_poller(on_sms)
        """
        # Ensure poller is running
        if not self.start_poller():
            print("[uz801_sms] Could not start poller. Falling back to content provider.")
            return self.monitor(callback, interval=interval, auto_delete=auto_delete)

        seen_ids: set[int] = set()
        print(f"[uz801_sms] Monitoring with on-device poller (interval={interval}s)")

        try:
            while self._monitoring:
                captured = self.read_captured()
                for sms in captured:
                    if sms.id not in seen_ids:
                        seen_ids.add(sms.id)
                        try:
                            callback(sms)
                        except Exception as e:
                            print(f"[uz801_sms] Callback error: {e}")

                if auto_delete:
                    self._adb.shell(
                        "echo '' > /data/local/tmp/sms_hook/_latest.txt 2>/dev/null"
                    )
                    seen_ids.clear()

                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[uz801_sms] Monitoring stopped.")
        finally:
            self._monitoring = False

    # ================================================================
    #  LOW-LEVEL
    # ================================================================

    def _at_command(self, cmd: str) -> str:
        """Send an AT command to the modem via the SMD port (best-effort).

        This is a low-level method. Not all AT commands are supported by the
        UZ801's modem firmware. Useful for querying signal, operator, etc.
        """
        shell_cmd = (
            f"echo -e '{cmd}\\r' > /dev/smd11 & "
            f"cat /dev/smd11 & "
            f"sleep 3; "
            f"kill %2 2>/dev/null; wait"
        )
        return self._adb.shell(shell_cmd, timeout=10)

    def _clean_at(self, cmd: str) -> str:
        """Send an AT command and clean up the response (remove echo/OK)."""
        raw = self._at_command(cmd)
        lines = [l.strip() for l in raw.splitlines()
                 if l.strip() and not l.strip().startswith("AT")
                 and l.strip() != "OK" and "echo" not in l.lower()]
        return "\n".join(lines) if lines else raw

    def _get_imei(self) -> str:
        """Get the device IMEI from Android service call."""
        raw = self._adb.shell("service call iphonesubinfo 1 2>/dev/null")
        parsed = _parse_parcel_string(raw)
        digits = re.sub(r"[^0-9]", "", parsed)
        return digits[:15] if len(digits) >= 14 else ""

    def shell(self, cmd: str) -> str:
        """Run an arbitrary shell command on the dongle. Power users only."""
        return self._adb.shell(cmd)

    def reboot(self) -> None:
        """Reboot the dongle."""
        self._adb.reboot()
