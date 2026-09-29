"""Tests for Home Assistant UI translations that do not need HA installed."""

import json
from pathlib import Path


def test_connection_retention_has_a_translated_label() -> None:
    """Home Assistant should not render the raw option key in the UI."""
    component_path = Path(__file__).parents[1] / "custom_components/inlite"
    expected_labels = {
        "strings.json": "Connection retention after activity (seconds)",
        "translations/en.json": "Connection retention after activity (seconds)",
        "translations/de.json": "Verbindung nach Aktivität halten (Sekunden)",
    }

    for filename, expected_label in expected_labels.items():
        strings = json.loads((component_path / filename).read_text())
        assert (
            strings["options"]["step"]["init"]["data"]["idle_disconnect"]
            == expected_label
        )
        assert (
            "startup_delay_seconds"
            not in strings["options"]["step"]["init"]["data"]
        )


def test_bluetooth_signal_strength_has_a_translated_name() -> None:
    """The diagnostic RSSI sensor has English and German names."""
    component_path = Path(__file__).parents[1] / "custom_components/inlite"
    expected_names = {
        "strings.json": "Bluetooth signal strength",
        "translations/en.json": "Bluetooth signal strength",
        "translations/de.json": "Bluetooth-Signalstärke",
    }

    for filename, expected_name in expected_names.items():
        strings = json.loads((component_path / filename).read_text())
        assert (
            strings["entity"]["sensor"]["bluetooth_signal_strength"]["name"]
            == expected_name
        )
