"""Tests for Home Assistant UI translations that do not need HA installed."""

import json
from pathlib import Path


def test_startup_discovery_timeout_has_a_translated_label() -> None:
    """Home Assistant should not render the raw option key in the UI."""
    component_path = Path(__file__).parents[1] / "custom_components/inlite"
    expected_labels = {
        "strings.json": "Startup discovery timeout (seconds)",
        "translations/en.json": "Startup discovery timeout (seconds)",
        "translations/de.json": "Start-Erkennungszeitlimit (Sekunden)",
    }

    for filename, expected_label in expected_labels.items():
        strings = json.loads((component_path / filename).read_text())
        assert (
            strings["options"]["step"]["init"]["data"]["startup_delay_seconds"]
            == expected_label
        )
