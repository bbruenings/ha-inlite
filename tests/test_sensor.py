"""Tests for the Bluetooth signal-strength diagnostic sensor."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("homeassistant")

from custom_components.inlite.sensor import (  # noqa: E402
    InliteBluetoothSignalStrengthSensor,
    async_setup_entry,
)
from homeassistant.components.sensor import (  # noqa: E402
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT  # noqa: E402
from homeassistant.helpers.entity import EntityCategory  # noqa: E402


def _coordinator(rssi: int | None = -67, address: str | None = "hub-address"):
    """Build the minimum coordinator surface needed by the entity."""
    return SimpleNamespace(
        rssi=rssi,
        ble_address=address,
        hass=object(),
    )


@pytest.mark.asyncio
async def test_setup_creates_one_sensor_for_shared_gateway() -> None:
    """Multiple transformers still share one Bluetooth RSSI sensor."""
    coordinator = _coordinator()
    entry = SimpleNamespace(
        runtime_data=coordinator,
        data={
            "garden_id": "garden-1",
            "garden_name": "Back garden",
            "transformers": [{"device_id": 1}, {"device_id": 2}],
        },
    )
    add_entities = Mock()

    await async_setup_entry(object(), entry, add_entities)

    entities = add_entities.call_args.args[0]
    assert len(entities) == 1
    assert isinstance(entities[0], InliteBluetoothSignalStrengthSensor)
    assert entities[0].device_info["identifiers"] == {
        ("inlite", "garden-1_1")
    }


def test_sensor_reports_gateway_rssi_and_metadata(monkeypatch) -> None:
    """The sensor exposes Home Assistant's current gateway RSSI."""
    coordinator = _coordinator()
    monkeypatch.setattr(
        "custom_components.inlite.sensor.bluetooth.async_address_present",
        lambda hass, address, connectable: True,
    )

    sensor = InliteBluetoothSignalStrengthSensor(
        coordinator, garden_id="garden-1", device_id=1
    )

    assert sensor.native_value == -67
    assert sensor.available is True
    assert sensor.unique_id == "garden-1_bluetooth_rssi"
    assert sensor.device_class is SensorDeviceClass.SIGNAL_STRENGTH
    assert sensor.native_unit_of_measurement == SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    assert sensor.state_class is SensorStateClass.MEASUREMENT
    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor.entity_registry_enabled_default is False
    assert sensor.device_info["identifiers"] == {
        ("inlite", "garden-1_1")
    }


@pytest.mark.parametrize(
    ("rssi", "address", "present"),
    [
        (None, "hub-address", True),
        (-67, None, True),
        (-67, "hub-address", False),
    ],
)
def test_sensor_is_unavailable_without_current_bluetooth_presence(
    monkeypatch, rssi, address, present
) -> None:
    """RSSI availability reflects advertisements, not mesh poll success."""
    coordinator = _coordinator(rssi=rssi, address=address)
    monkeypatch.setattr(
        "custom_components.inlite.sensor.bluetooth.async_address_present",
        lambda hass, checked_address, connectable: present,
    )

    sensor = InliteBluetoothSignalStrengthSensor(
        coordinator, garden_id="garden-1", device_id=1
    )

    assert sensor.available is False
