# Reverse Engineering Guide

This guide is for contributors who want to add support for in-lite devices
they don't physically own. By capturing traffic from someone who _does_ have
the hardware (or from your own setup with a different device), you can
understand the cloud API and BLE mesh commands without needing every product
on your desk.

---

## Prerequisites

| Tool | Purpose | Install |
|------|---------|---------|
| [mitmproxy](https://mitmproxy.org/) | HTTP/S traffic interception | `brew install mitmproxy` or `pip install mitmproxy` |
| [Xcode](https://developer.apple.com/xcode/) | Includes PacketLogger | Mac App Store |
| Apple Bluetooth logging profile | Enables BLE capture from iOS | [Apple Bug Reporting → Profiles](https://developer.apple.com/bug-reporting/profiles-and-logs/?name=bluetooth) |

---

## Part 1: HTTP Traffic Capture (mitmproxy)

Use mitmproxy to intercept the in-lite app's cloud API calls. This reveals
endpoint URLs, request/response payloads, authentication flows, and device
metadata.

### 1.1 Install mitmproxy

```bash
# macOS (Homebrew)
brew install mitmproxy

# Or via pip
pip install mitmproxy
```

### 1.2 Start the proxy

```bash
mitmproxy --listen-port 8080
```

This starts an interactive terminal UI. Alternatively, use `mitmweb` for a
browser-based interface:

```bash
mitmweb --listen-port 8080
```

### 1.3 Find your Mac's local IP

```bash
ipconfig getifaddr en0
```

Note the IP (e.g., `192.168.1.42`). Your phone will use this as its proxy.

### 1.4 Configure your phone to use the proxy

#### iOS

1. Open **Settings → Wi-Fi** → tap the ⓘ next to your network
2. Scroll to **HTTP Proxy** → select **Manual**
3. Set:
   - **Server:** your Mac's IP (e.g., `192.168.1.42`)
   - **Port:** `8080`
   - **Authentication:** off

#### Android

1. Open **Settings → Network & Internet → Wi-Fi**
2. Long-press your network → **Modify network** → **Advanced options**
3. Set **Proxy** to **Manual**
4. Enter your Mac's IP and port `8080`

### 1.5 Install the mitmproxy CA certificate

With the proxy configured, open a browser on your phone and navigate to:

```
http://mitm.it
```

This page provides platform-specific certificate downloads.

#### iOS

1. Tap the Apple icon to download the profile
2. Go to **Settings → General → VPN & Device Management** → install the
   downloaded profile
3. Go to **Settings → General → About → Certificate Trust Settings** →
   enable full trust for the mitmproxy certificate

#### Android

1. Tap the Android icon to download the certificate
2. Go to **Settings → Security → Install a certificate → CA certificate**
3. Select the downloaded file

> [!NOTE]
> On Android 7+, user-installed CA certificates are not trusted by apps by
> default. You may need a rooted device or a repackaged app with
> `networkSecurityConfig` allowing user CAs.

### 1.6 Capture in-lite app traffic

1. Open the in-lite app on your phone
2. Perform the actions you want to capture (login, discover devices, control
   lights, etc.)
3. Watch requests appear in the mitmproxy UI

### 1.7 Filter for relevant traffic

In the mitmproxy interactive view, press `f` to set a filter:

```
~d api.inlite.coffeeit.nl
```

This shows only requests to the in-lite cloud API.

### 1.8 Export captures

Press `E` in mitmproxy to export flows, or use the command-line:

```bash
mitmdump --listen-port 8080 -w capture.mitm
```

Share `.mitm` files or copy relevant request/response bodies when filing
issues or PRs.

### 1.9 Clean up

Remove the proxy settings from your phone and delete the CA certificate when
done:

- **iOS:** Settings → General → VPN & Device Management → remove mitmproxy
  profile
- **Android:** Settings → Security → Trusted credentials → User → remove
  mitmproxy

---

## Part 2: BLE Capture — iOS (Remote Logging)

Apple's PacketLogger can capture Bluetooth traffic from a connected iPhone.
This is useful for capturing how the in-lite app communicates with the hub
over BLE.

### 2.1 Install the Bluetooth logging profile on iPhone

1. Visit [Apple's Profiles and Logs page](https://developer.apple.com/bug-reporting/profiles-and-logs/?name=bluetooth)
   on your iPhone's Safari browser
2. Download and install the **Bluetooth** logging profile
3. Go to **Settings → General → VPN & Device Management** and confirm the
   profile is installed
4. Restart your iPhone

> [!IMPORTANT]
> The profile expires periodically. Check the expiry date and reinstall if
> needed.

### 2.2 Connect iPhone to Mac

1. Connect your iPhone to your Mac via USB cable
2. If prompted, tap **Trust** on the iPhone
3. Verify the connection in Finder (macOS Ventura+) or iTunes

### 2.3 Open PacketLogger

1. Open Xcode
2. From the menu bar: **Xcode → Open Developer Tool → PacketLogger**
   - If PacketLogger isn't listed, install the "Additional Tools for Xcode"
     package from [Apple Developer Downloads](https://developer.apple.com/download/all/?q=Additional%20Tools)

### 2.4 Select the iPhone as capture source

1. In PacketLogger, go to **File → New iOS Trace** (or **File → New Remote Trace**)
2. Select your connected iPhone from the device list
3. Click **Start**

### 2.5 Capture BLE traffic

1. Open the in-lite app on your iPhone
2. Perform the actions you want to analyze (connect to hub, control lights)
3. PacketLogger will display all Bluetooth packets in real-time

### 2.6 Filter for in-lite traffic

Use the filter bar to narrow results:

- Filter by **Type:** `ATT` or `GATT` to see attribute-level communication
- Search for the in-lite service UUID: `0000fef1-0000-1000-8000-00805f9b34fb`
- Filter by device name: `inlitebt`

### 2.7 Save the capture

1. **File → Save** to save as `.pklg` file
2. Share this file in your PR or issue for others to analyze

### 2.8 Clean up

Remove the Bluetooth logging profile from your iPhone when done:

- **Settings → General → VPN & Device Management** → tap the profile →
  **Remove Profile**
- Restart your iPhone

---

## Part 3: BLE Capture — macOS (Native)

If the in-lite hub is within Bluetooth range of your Mac, you can capture BLE
traffic directly without an iPhone.

### 3.1 Open PacketLogger

1. Open Xcode
2. **Xcode → Open Developer Tool → PacketLogger**

### 3.2 Start a local capture

1. **File → New macOS Trace** (or simply **File → New Trace**)
2. Click **Start** — PacketLogger begins capturing all local Bluetooth
   activity

### 3.3 Trigger BLE activity

If you have a hub nearby, use the Home Assistant integration or the in-lite
app on a nearby phone to trigger commands. PacketLogger on the Mac captures
all BLE advertisements and GATT operations visible to the Mac's Bluetooth
adapter.

### 3.4 Filter for in-lite hub

Use the filter bar:

- Service UUID: `0000fef1-0000-1000-8000-00805f9b34fb`
- Device name: `inlitebt`
- Characteristic UUIDs:
  - Write/Notify: `c4edc000-9daf-11e3-8004-00025b000b00`
  - Continuation: `c4edc000-9daf-11e3-8003-00025b000b00`

### 3.5 Save and share

Save captures as `.pklg` files via **File → Save**. Attach them to your
GitHub issue or PR.

---

## Tips

### What to look for in captures

- **GATT Write commands** to the characteristic UUIDs listed above — these
  are mesh commands sent to the hub
- **Notify responses** from the hub on the same characteristics
- **Advertising data** — useful for identifying new hub models
- **HTTP responses** containing device lists, zone configurations, or
  firmware version info

### Sharing captures with maintainers

When opening an issue or PR with captured data:

1. Export and attach the raw capture file (`.mitm` for HTTP, `.pklg` for BLE)
2. Include a summary of what actions you performed during capture
3. Note your device model, app version, and iOS/macOS version
4. **Strip personal data** — remove or redact email addresses, tokens, and
   garden names before sharing

### Useful mitmproxy commands

| Key | Action |
|-----|--------|
| `f` | Set display filter |
| `e` | Edit a request/response |
| `E` | Export flows |
| `q` | Quit |
| `?` | Help |

### PacketLogger column reference

| Column | Meaning |
|--------|---------|
| **Timestamp** | When the packet was captured |
| **Type** | Protocol layer (HCI, L2CAP, ATT, GATT, etc.) |
| **Channel** | L2CAP channel ID |
| **Data** | Raw packet bytes |
| **Summary** | Human-readable decode |
