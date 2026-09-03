"""Tests for Home Assistant UI translations that do not need HA installed."""

import json
from pathlib import Path


def test_startup_discovery_timeout_has_a_translated_label() -> None:
    """Home Assistant should not render the raw option key in the UI."""
    strings_path = Path(__file__).parents[1] / "custom_components/inlite/strings.json"
    strings = json.loads(strings_path.read_text())

    assert (
        strings["options"]["step"]["init"]["data"]["startup_delay_seconds"]
        == "Startup discovery timeout (seconds)"
    )
