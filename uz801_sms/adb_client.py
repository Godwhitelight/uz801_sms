"""ADB wrapper — download, detect, and communicate with the dongle."""

from __future__ import annotations

import os
import subprocess
import time
import urllib.request
import zipfile
import io
from typing import Optional

from uz801_sms import constants
from uz801_sms.exceptions import ADBNotFoundError, DongleNotFoundError


class ADBClient:
    """Thin wrapper around the ``adb`` command-line tool.

    Handles:
      * Downloading ADB if it's not present.
      * Starting the ADB server.
      * Detecting connected UZ801 devices.
      * Running shell commands on the dongle.
    """

    def __init__(self, adb_path: Optional[str] = None):
        self.adb_path = adb_path or constants.ADB_PATH
        self._verified = False

    # ---- installation ----

    def ensure_installed(self) -> str:
        """Download ADB if it's not already on disk. Returns the path."""
        if os.path.exists(self.adb_path):
            return self.adb_path

        print("[uz801_sms] ADB not found. Downloading Android platform-tools...")

        # Download
        tmp_zip = os.path.join(os.path.dirname(self.adb_path), "..", "_platform_tools.zip")
        tmp_zip = os.path.normpath(tmp_zip)
        os.makedirs(os.path.dirname(tmp_zip), exist_ok=True)

        try:
            urllib.request.urlretrieve(constants.ADB_DOWNLOAD_URL, tmp_zip)
        except Exception as e:
            raise ADBNotFoundError(
                f"Could not download ADB automatically: {e}\n"
                f"Download manually from {constants.ADB_DOWNLOAD_URL} "
                f"and extract to {os.path.dirname(self.adb_path)}"
            )

        # Extract
        extract_dir = os.path.dirname(os.path.dirname(self.adb_path))
        with zipfile.ZipFile(tmp_zip, "r") as z:
            z.extractall(extract_dir)
        os.remove(tmp_zip)

        if not os.path.exists(self.adb_path):
            raise ADBNotFoundError(
                f"ADB extraction succeeded but {self.adb_path} not found."
            )

        print(f"[uz801_sms] ADB installed at {self.adb_path}")
        return self.adb_path

    # ---- low-level ----

    def _run(self, args: list[str], timeout: int = constants.ADB_TIMEOUT) -> str:
        """Execute an adb command and return stdout (utf-8, errors replaced)."""
        full = [self.adb_path] + args
        try:
            result = subprocess.run(full, capture_output=True, timeout=timeout)
            return result.stdout.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return ""
        except FileNotFoundError:
            raise ADBNotFoundError(
                f"ADB not found at {self.adb_path}. Call UZ801.setup() first."
            )

    # ---- server ----

    def start_server(self) -> None:
        self._run(["start-server"], timeout=10)
        time.sleep(1)

    # ---- device detection ----

    def get_device_serial(self) -> Optional[str]:
        """Return the serial of the first connected ADB device, or None."""
        output = self._run(["devices"], timeout=10)
        for line in output.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                return parts[0]
        return None

    def wait_for_device(self, timeout: int = 60) -> str:
        """Block until a device shows up. Returns the serial."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            serial = self.get_device_serial()
            if serial:
                return serial
            time.sleep(2)
        raise DongleNotFoundError(
            "No ADB device detected. Make sure the dongle is plugged in "
            "and debug mode is enabled (call UZ801.setup())."
        )

    # ---- shell ----

    def shell(self, cmd: str, timeout: int = constants.ADB_TIMEOUT) -> str:
        """Run a shell command on the dongle, return stdout."""
        return self._run(["shell", cmd], timeout=timeout).strip()

    def root(self) -> None:
        """Request ADB root access."""
        self._run(["root"], timeout=10)
        time.sleep(2)

    # ---- reboot ----

    def reboot(self) -> None:
        self._run(["reboot"], timeout=5)
