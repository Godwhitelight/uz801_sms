# How It Works

## The Problem

You have a $8 USB stick from AliExpress. It has a SIM card slot, connects to 4G LTE, and can send/receive SMS. You want to read and send SMS from Python. How hard could it be?

### What doesn't work

**AT commands.** The UZ801 is based on the Qualcomm MSM8916 (Snapdragon 410). The modem firmware exposes a serial AT command port at `/dev/smd11`, and basic commands like `AT`, `ATI`, `AT+CSQ`, `AT+CREG?`, `AT+COPS?` all work fine. However, the firmware has a **stripped command set** — running `AT+CLAC` (list all commands) reveals that the standard SMS commands are missing:

```
✅ AT+CMGF   — set SMS text mode          (present, but just a stub)
❌ AT+CMGS   — send SMS                   (NOT in firmware)
❌ AT+CMGL   — list SMS                   (NOT in firmware)
❌ AT+CMGR   — read SMS                   (NOT in firmware)
❌ AT+CMGD   — delete SMS                 (NOT in firmware)
❌ AT+CNMI   — new SMS notification       (NOT in firmware)
```

The modem module on this device was configured for a WiFi hotspot product, not a general-purpose modem. Qualcomm's SMS over AT commands were compiled out of the firmware to save space. Sending `AT+CMGL="ALL"` returns `ERROR`. There's no way around this without flashing custom modem firmware (a risky, device-specific process).

### What also doesn't work

**The web UI.** The dongle has a web interface at `http://192.168.100.1` (login: `admin`/`admin`). It exposes an HTTP API with `funcNo`-based endpoints (see the [bxdoan/dongle-lte-api](https://github.com/bxdoan/dongle-lte-api) project). But this API only covers WiFi settings, device info, and reboot — there is no SMS page in the web UI and no SMS endpoints.

## The Solution

The UZ801 isn't just a modem — it's a **tiny Android phone** running Android 4.4.4 (KitKat) on a Qualcomm Snapdragon 410 SoC with 512MB RAM and 4GB flash. It has no screen, but it has:

- A full Android telephony stack (RIL, TelephonyManager, SMSManager)
- Android's content provider system (the same `content://sms` database that every Android SMS app uses)
- ADB (Android Debug Bridge) access via a hidden debug backdoor

Instead of talking to the modem directly, we let Android handle SMS and read/write through Android's own database.

### Step 1: Enable ADB

The dongle ships with ADB disabled. There's a hidden web page that enables it:

```
http://192.168.100.1/usbdebug.html
```

Visiting this URL triggers a reboot, after which ADB is available over USB. The `setup()` method automates this — it sends an HTTP GET to that URL, waits for the dongle to reboot, and confirms ADB connectivity.

From that point on, the dongle exposes itself as an ADB device (USB VID `05c6`, PID `90b6`). Windows recognizes it as "Android" and ADB can connect. No special drivers needed — ADB uses its own USB protocol.

### Step 2: Read SMS

Android stores all SMS in a content provider database accessible at `content://sms`. We query it via ADB shell:

```bash
adb shell content query --uri content://sms \
    --projection _id:address:body:date:read:type:service_center \
    --sort 'date DESC'
```

Output looks like:

```
Row: 0 _id=3, address=+972501234567, body=Hello, date=1395041066, read=0, type=1
Row: 1 _id=2, address=999, body=Welcome, date=1395039890, read=0, type=1
```

The `parser` module converts this into `SMS` dataclass objects. The `type` field tells us if it's incoming (1=INBOX), sent (2=SENT), draft (3=DRAFT), etc.

### Step 3: Send SMS

To send, we insert a message into Android's outbox:

```bash
adb shell content insert --uri content://sms/outbox \
    --bind address:s:'+972501234567' \
    --bind body:s:'Hello World' \
    --bind type:i:2 \
    --bind date:l:1395041066 \
    --bind read:i:1 \
    --bind delivery_report:i:1
```

Android's SMS manager picks up the outbox entry and sends it through the RIL layer to the modem, which transmits it over the LTE network. No AT commands needed — Android handles the entire SMS stack, including PDU encoding, SMSC negotiation, delivery reports, and retries.

### Step 4: Monitor for new SMS

The `monitor()` method polls `content://sms/inbox` at a configurable interval (default 3 seconds). It tracks seen message IDs and fires a callback for each new message. This works just like a webhook — you provide a function, and it gets called with an `SMS` object every time a new message arrives.

## Architecture

```
  Your Python code
       │
       ▼
  ┌─────────────────────────┐
  │    uz801_sms.UZ801      │   High-level API: read_sms(), send_sms(), monitor()
  └───────────┬─────────────┘
              │
       ┌──────┴──────┐
       ▼             ▼
  ┌─────────┐  ┌───────────┐
  │ ADBClient│  │  Parser   │   adb shell wrapper   parses `content query` output
  └────┬────┘  └───────────┘
       │
       ▼
  ┌─────────────┐
  │   adb.exe   │   Auto-downloaded from Google on first use
  └─────┬───────┘
        │ USB
        ▼
  ┌─────────────────────────────┐
  │     UZ801 Dongle (Android)  │
  │  ┌───────────────────────┐  │
  │  │  content://sms DB     │  │   Android's SMS database
  │  └───────────┬───────────┘  │
  │              │              │
  │  ┌───────────┴───────────┐  │
  │  │  Android Telephony    │  │   RIL → Qualcomm modem → LTE network
  │  └───────────────────────┘  │
  └─────────────────────────────┘
```

### Why this approach is better than AT commands

| | AT Commands | uz801_sms (Android content provider) |
|---|---|---|
| SMS send | `AT+CMGS` — PDU encoding needed | `content insert` — Android handles it |
| SMS read | `AT+CMGL` — parse PDU/TEXT | `content query` — clean structured output |
| New SMS alerts | `AT+CNMI` — requires serial monitoring | Polling `content://sms/inbox` |
| Delivery reports | `AT+CNMA` — manual acknowledgment | Android handles automatically |
| Unicode (Hebrew) | PDU mode only, manual encoding | Android handles UTF-8 natively |
| Long SMS (concatenated) | Manual UDH construction | Android reassembles automatically |
| SIM vs phone storage | `AT+CPMS` — must manage manually | Android manages transparently |
| Driver needed | Qualcomm USB serial (MI_02/MI_03) | None — ADB uses standard USB |

## Limitations

1. **No real-time push.** Monitoring is poll-based (every N seconds). A push-based approach would require running a service on the dongle itself that listens for `android.provider.Telephony.SMS_RECEIVED` broadcasts and forwards them over USB. This is possible but requires installing an APK on the dongle.

2. **Clock drift.** The dongle has no RTC battery, so its clock resets to a default date on every boot. SMS timestamps reflect the dongle's clock, not the actual send/receive time. If you need accurate timestamps, use the `date_sent` field from the SMSC (which has its own clock).

3. **Send speed.** Inserting into the outbox and waiting for Android to process it takes ~5 seconds per message. For bulk sending, you could insert multiple messages in rapid succession and let Android's SMS queue handle delivery.

4. **One dongle at a time per ADB instance.** If you have 5 dongles, they all appear as separate ADB devices. The library currently targets the first device found. For multi-dongle setups, you'd need to extend `ADBClient` to target specific device serials.

5. **Firmware dependency.** This approach relies on the `content` command being available on the dongle's Android system. It's present on all known UZ801 firmware versions, but if someone flashed a minimal Linux (like OpenStick/OpenWRT), the content provider wouldn't exist.
