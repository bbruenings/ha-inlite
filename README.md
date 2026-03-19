# in-lite Outdoor Lighting for Home Assistant

[![HACS][hacs-badge]][hacs-url]
[![GitHub Release][release-badge]][release-url]
[![License][license-badge]][license-url]
[![Validate][validate-badge]][validate-url]
[![Tests][tests-badge]][tests-url]

Custom [Home Assistant](https://www.home-assistant.io/) integration for
**in-lite outdoor lighting** systems. Controls lights via Bluetooth Low
Energy (BLE) mesh using the CSRmesh protocol.

> [!NOTE]
> **Disclaimer:** This project is not affiliated with, endorsed by, or
> connected to in-lite Design BV. "in-lite" is a trademark of in-lite
> Design BV. This integration was developed independently through
> protocol analysis.

## Features

- 💡 Turn lights on/off per zone through Home Assistant
- 📡 Bluetooth Low Energy (BLE) mesh control — no cloud dependency for operation
- ☁️ One-time cloud login for initial pairing (retrieves encryption keys)
- 🔄 Automatic BLE discovery of the in-lite hub
- 🔁 Reliable command delivery with retry and reconnect logic
- 🔌 Persistent BLE connection with idle disconnect to save resources

## Requirements

- **Home Assistant** 2024.12.0 or newer
- **Bluetooth adapter** — built-in, USB dongle, or [ESPHome Bluetooth Proxy](https://esphome.github.io/bluetooth-proxies/)
- **in-lite SMART HUB-150** with BLE gateway (device advertises as `inlitebt`)
- **in-lite cloud account** — needed once during setup to retrieve the encryption passphrase

## Supported Devices

| Device | Status |
|--------|--------|
| in-lite SMART HUB-150 | ✅ Tested |

The integration controls all transformer zones connected to the hub. If you
have tested additional hardware, please
[open an issue](https://github.com/bbruenings/ha-inlite/issues) to let us know.

## Installation

### HACS (Recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance
2. Add this repository as a custom repository:
   - Go to **HACS** → **Integrations** → **⋮** (top right) → **Custom repositories**
   - Enter `https://github.com/bbruenings/ha-inlite` and select **Integration**
   - Click **Add**
3. Search for **in-lite Outdoor Lighting** in HACS and click **Download**
4. Restart Home Assistant

### Manual Installation

1. Download the [latest release](https://github.com/bbruenings/ha-inlite/releases/latest)
2. Copy the `custom_components/inlite/` folder to your Home Assistant
   `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

The integration is configured through the Home Assistant UI. No YAML configuration needed.

### Automatic Discovery

If your in-lite hub is powered on and within Bluetooth range, Home Assistant
will automatically discover it and prompt you to set it up.

### Manual Setup

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **in-lite Outdoor Lighting**
3. Enter the email address associated with your in-lite cloud account
4. Check your email for a verification code and enter it
5. If you have multiple gardens, select the one to configure
6. The integration will connect to your hub and create light entities for each zone

### Entities Created

For each transformer zone, the integration creates a **Light** entity:
- `light.inlite_<hub_name>_zone_<N>` — supports on/off control

## Troubleshooting

### Hub not discovered

- Ensure the in-lite hub is powered on and within Bluetooth range
- Check that your Bluetooth adapter is working: **Settings** → **Devices & Services** → **Bluetooth**
- If using an ESPHome BLE proxy, ensure it's online and connected

### Commands fail intermittently

The integration automatically retries commands up to 3 times with
disconnect-reconnect between attempts. If commands still fail:

- Move the Bluetooth adapter closer to the hub
- Consider using an [ESPHome Bluetooth Proxy](https://esphome.github.io/bluetooth-proxies/) positioned near the hub
- Check Home Assistant logs for BLE connection errors

### Enable debug logging

Add the following to your `configuration.yaml` for detailed logs:

```yaml
logger:
  default: warning
  logs:
    custom_components.inlite: debug
    inlite_ble: debug
```

## Contributing

Contributions are welcome! Please:

1. [Open an issue](https://github.com/bbruenings/ha-inlite/issues) to discuss your idea first
2. Fork the repository and create a feature branch
3. Submit a pull request

## License

This project is licensed under the [MIT License](LICENSE).

---

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-orange.svg
[hacs-url]: https://github.com/hacs/integration
[release-badge]: https://img.shields.io/github/v/release/bbruenings/ha-inlite
[release-url]: https://github.com/bbruenings/ha-inlite/releases
[license-badge]: https://img.shields.io/github/license/bbruenings/ha-inlite
[license-url]: https://github.com/bbruenings/ha-inlite/blob/main/LICENSE
[validate-badge]: https://github.com/bbruenings/ha-inlite/actions/workflows/validate.yml/badge.svg
[validate-url]: https://github.com/bbruenings/ha-inlite/actions/workflows/validate.yml
[tests-badge]: https://github.com/bbruenings/ha-inlite/actions/workflows/tests.yml/badge.svg
[tests-url]: https://github.com/bbruenings/ha-inlite/actions/workflows/tests.yml
