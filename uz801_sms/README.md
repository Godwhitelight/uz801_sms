# uz801_sms

**Send, receive, and monitor SMS on the UZ801 4G LTE USB dongle — from Python.**

`uz801_sms` is a pure-Python library that talks to the ubiquitous $8 UZ801 4G LTE USB dongle (Qualcomm MSM8916) via ADB and Android's content-provider system. No AT commands, no serial drivers, no firmware hacking — just plug in the dongle and use Python.

---

## Why this library exists

The UZ801 is a $7-10 USB stick from AliExpress that contains a full Qualcomm Snapdragon 410 SoC running Android 4.4. It accepts a SIM card and connects to 4G LTE networks. While it's sold as a simple WiFi hotspot, it's actually a tiny Android phone without a screen.

The modem firmware on this device has a **stripped AT command set** — the standard SMS commands (`AT+CMGS`, `AT+CMGL`, `AT+CMGR`) are not available. However, since the dongle runs Android, we can use Android's built-in SMS content provider (`content://sms`) via ADB to read, send, and monitor SMS messages. This library wraps that interaction into a clean Python API.

---

## Installation

```bash
pip install -e .
```

Or just copy the `uz801_sms/` folder into your project. The only dependency is Python 3.10+ (no pip packages required — ADB is auto-downloaded).

---

## Quick Start

```python
from uz801_sms import UZ801

# Connect to the dongle (auto-downloads ADB if needed)
dongle = UZ801()

# One-time setup: enable ADB debug mode on the dongle
# (only needed the first time you plug it in)
dongle.setup()

# Read all SMS messages
for sms in dongle.read_sms():
    print(f"[{sms.datetime}] From {sms.sender}: {sms.body}")

# Send an SMS
dongle.send_sms("+972501234567", "Hello from UZ801!")

# Monitor for new SMS (blocking)
def on_new_sms(sms):
    print(f"NEW SMS from {sms.sender}: {sms.body}")

dongle.monitor(on_new_sms)
```

---

## Architecture

```
Your Python Code
       │
       ▼
  uz801_sms.UZ801
       │
       ├── ADBClient  ──► adb.exe ──► USB ──► UZ801 dongle
       │
       └── Parser      ──► parses `content query` output
                               │
                               ▼
                      Android content://sms
                      (SMS database on dongle)
```

The library communicates with the dongle through **ADB** (Android Debug Bridge), which is a standard USB protocol. No serial ports, no COM drivers, no AT commands. ADB is automatically downloaded on first use.

---

## API Reference

### `UZ801`

The main class. One instance = one dongle.

#### `UZ801(adb_path=None)`

Create a manager instance.

- **adb_path**: Optional path to `adb.exe`. If `None`, uses the bundled copy (auto-downloaded by `setup()`).

#### `setup()`

One-time setup. Call this once after plugging in a new dongle. It:
1. Downloads ADB if not present
2. Enables the ADB debug backdoor on the dongle
3. Waits for the dongle to reboot into ADB mode

If the dongle is already in ADB mode, this is a no-op.

```python
dongle = UZ801()
dongle.setup()  # only needed once per dongle
```

#### `is_connected() -> bool`

Returns `True` if the dongle is reachable via ADB.

#### `read_sms(filter="all") -> list[SMS]`

Read SMS messages from the dongle.

- **filter**: `"all"` (default), `"inbox"`, `"unread"`, or `"sent"`

```python
# All messages
all_msgs = dongle.read_sms()

# Only inbox
inbox = dongle.read_sms("inbox")

# Only unread
unread = dongle.read_sms("unread")
```

#### `send_sms(phone, message, wait=True) -> bool`

Send an SMS.

- **phone**: Recipient number with country code (e.g. `"+972501234567"`)
- **message**: Message text
- **wait**: If `True`, wait and verify the message was sent (default `True`)

```python
dongle.send_sms("+972501234567", "Hello!")
```

#### `monitor(callback, interval=3.0, auto_delete=False, auto_mark_read=True)`

Block forever, calling `callback` for each new incoming SMS.

- **callback**: `Callable[[SMS], None]` — called with each new message
- **interval**: Polling interval in seconds (default 3)
- **auto_delete**: Delete messages after reading (default `False`)
- **auto_mark_read**: Mark messages as read after callback (default `True`)

```python
def on_sms(sms):
    print(f"From {sms.sender}: {sms.body}")

dongle.monitor(on_sms)
```

#### `monitor_async(callback, ...) -> threading.Thread`

Same as `monitor()` but runs in a background thread (non-blocking).

```python
thread = dongle.monitor_async(on_sms)
# ... do other things ...
dongle.stop_monitor()
```

#### `stop_monitor()`

Stop a monitor started with `monitor_async()`.

#### `delete_sms(sms_id) -> bool`

Delete a single SMS by its ID.

#### `delete_all_sms() -> int`

Delete all SMS. Returns the count of deleted messages.

#### `mark_read(sms_id) -> bool`

Mark a message as read.

#### `get_info() -> dict`

Returns device info: IMEI, firmware version, network operator, signal strength.

#### `reboot()`

Reboot the dongle.

#### `shell(cmd) -> str`

Run an arbitrary shell command on the dongle. For advanced users.

---

### `SMS`

Dataclass representing a single SMS message.

| Field | Type | Description |
|---|---|---|
| `id` | `int` | Database row ID |
| `sender` | `str` | Sender phone number (incoming) |
| `recipient` | `str` | Recipient phone number (outgoing) |
| `body` | `str` | Message text |
| `timestamp` | `int` | Unix epoch (seconds) |
| `status` | `SMSStatus` | INBOX, SENT, DRAFT, OUTBOX, FAILED, QUEUED |
| `read` | `ReadState` | READ or UNREAD |
| `service_center` | `str` | SMSC that delivered the message |
| `thread_id` | `int\|None` | Android conversation thread ID |
| `raw` | `dict` | Raw content provider row (all fields) |

**Properties:**
- `sms.is_incoming` — True if received (INBOX)
- `sms.is_unread` — True if not yet read
- `sms.datetime` — Human-readable datetime string

---

### Exceptions

| Exception | When |
|---|---|
| `UZ801Error` | Base exception |
| `DongleNotFoundError` | Dongle not detected via ADB |
| `ADBNotFoundError` | ADB not installed and couldn't be downloaded |
| `DebugModeError` | Could not enable ADB debug mode |
| `SMSError` | SMS send/read/delete failed |

---

## Examples

### Basic: Read all SMS

```python
from uz801_sms import UZ801

dongle = UZ801()
dongle.setup()

for sms in dongle.read_sms():
    status = "READ" if not sms.is_unread else "UNREAD"
    print(f"[{sms.id}] {status} from {sms.sender}")
    print(f"  {sms.body}")
    print()
```

### Send an SMS

```python
from uz801_sms import UZ801

dongle = UZ801()
dongle.setup()

if dongle.send_sms("+972501234567", "Test from uz801_sms!"):
    print("Sent!")
else:
    print("Failed — check signal, SIM balance, etc.")
```

### SMS listener (blocking)

```python
from uz801_sms import UZ801

dongle = UZ801()
dongle.setup()

def on_sms(sms):
    print(f"\n{'='*40}")
    print(f"From:    {sms.sender}")
    print(f"Time:    {sms.datetime}")
    print(f"Message: {sms.body}")
    print(f"{'='*40}")

print("Listening for incoming SMS... (Ctrl+C to stop)")
dongle.monitor(on_sms, interval=3)
```

### Async listener + webhook forwarding

```python
import requests
from uz801_sms import UZ801

dongle = UZ801()
dongle.setup()

WEBHOOK_URL = "http://localhost:8080/sms"

def on_sms(sms):
    # Forward to your server
    requests.post(WEBHOOK_URL, json={
        "sender": sms.sender,
        "body": sms.body,
        "timestamp": sms.timestamp,
    })
    print(f"Forwarded SMS from {sms.sender}")

# Non-blocking monitor
thread = dongle.monitor_async(on_sms, interval=3)

# Your app continues running here...
# ...
dongle.stop_monitor()
```

### Multiple dongles

If you have 5 dongles plugged in via a USB hub, create 5 `UZ801` instances.
Each dongle appears as a separate ADB device. Use `setup()` on each one individually.

```python
from uz801_sms import UZ801

# After all 5 dongles are plugged in and debug mode enabled:
dongles = [UZ801() for _ in range(5)]

for i, dongle in enumerate(dongles):
    print(f"Dongle {i}: {dongle.get_info()['imei']}")
    dongle.monitor_async(
        callback=lambda sms, i=i: print(f"[Dongle {i}] {sms.sender}: {sms.body}"),
        interval=3,
    )
```

---

## How it works

### Step 1: Enabling ADB

The UZ801 ships with a hidden web page at `http://192.168.100.1/usbdebug.html`. Visiting this page in a browser enables the ADB debug backdoor. The dongle reboots, and ADB becomes available over USB. `setup()` does this automatically.

### Step 2: Reading SMS

The dongle runs Android 4.4.4 (KitKat). SMS messages are stored in Android's content provider database at `content://sms`. The library uses `adb shell content query --uri content://sms` to read messages and parses the output.

### Step 3: Sending SMS

To send an SMS, the library inserts a message into Android's outbox at `content://sms/outbox`. Android's SMS manager picks it up and sends it over the cellular network.

### Step 4: Monitoring

`monitor()` polls `content://sms/inbox` at a configurable interval and fires a callback for any new message IDs it hasn't seen before.

---

## Troubleshooting

### "No ADB device detected"

1. Make sure the dongle is plugged into a USB port
2. Check that you see a green/blue LED on the dongle
3. Run `dongle.setup()` — this enables ADB debug mode
4. If that fails, manually visit `http://192.168.100.1/usbdebug.html` in your browser
5. Wait 20 seconds for the dongle to reboot, then try again

### "Could not enable debug mode"

The dongle's web UI might not be reachable. Check:
1. In Windows Device Manager, look for "Remote NDIS based Internet Sharing Device" under Network Adapters
2. If you see a yellow exclamation mark, right-click → Update Driver → Browse → Let me pick → Network Adapters → Microsoft → "Remote NDIS based Internet Sharing Device"
3. Try `http://192.168.100.1` in your browser — it should show the dongle's web UI

### "SMS send failed"

- Check signal: `dongle._at_command("AT+CSQ")` — should return `+CSQ: 20+` (higher is better)
- Check network: `dongle._at_command("AT+COPS?")` — should show your carrier name
- Check SIM balance — prepaid SIMs need credit to send SMS
- Some carriers require IMS to be enabled for SMS over LTE

### Dongle reboots randomly

The UZ801 can be unstable under continuous load. If it reboots, just call `dongle.setup()` again to reconnect.

### Clock is wrong

The dongle has no battery, so its clock resets to 1970 on every boot. SMS timestamps may be incorrect. The `SMS.timestamp` field contains the raw epoch value from the device.

---

## Requirements

- Python 3.10+
- Windows (ADB auto-download works on Windows; for Linux/Mac, install `android-tools-adb` manually)
- UZ801 4G LTE USB dongle (or any MSM8916-based stick: UFI003, UFI001, etc.)
- An active SIM card with SMS capability
- USB port

---

## License

MIT
