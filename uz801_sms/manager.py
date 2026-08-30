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
        """Return device info (IMEI, firmware, model, network, etc.)."""
        info = {}
        info["model"] = self._adb.shell("getprop ro.product.model")
        info["firmware"] = self._adb.shell("getprop ro.build.display.id")
        info["android_version"] = self._adb.shell("getprop ro.build.version.release")
        info["imei"] = self._adb.shell("service call iphonesubinfo 1 2>/dev/null")
        # Clean up IMEI (service call returns hex)
        if info["imei"]:
            imei_match = re.findall(r"[0-9]", info["imei"])
            if imei_match:
                info["imei"] = "".join(imei_match)[:15]
        info["network"] = self._at_command("AT+COPS?")
        info["signal"] = self._at_command("AT+CSQ")
        return {k: v for k, v in info.items() if v}

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

    def shell(self, cmd: str) -> str:
        """Run an arbitrary shell command on the dongle. Power users only."""
        return self._adb.shell(cmd)

    def reboot(self) -> None:
        """Reboot the dongle."""
        self._adb.reboot()
