"""Diagnostic sensors for the in-lite Bluetooth gateway."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import InliteConfigEntry
from .const import CONF_GARDEN_ID, CONF_TRANSFORMERS, DOMAIN
from .coordinator import InliteCoordinator

PARALLEL_UPDATES = 0

RSSI_SENSOR_DESCRIPTION = SensorEntityDescription(
    key="bluetooth_signal_strength",
    translation_key="bluetooth_signal_strength",
    device_class=SensorDeviceClass.SIGNAL_STRENGTH,
    native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InliteConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Bluetooth signal-strength sensor."""
    transformers = entry.data[CONF_TRANSFORMERS]
    if not transformers:
        return

    async_add_entities(
        [
            InliteBluetoothSignalStrengthSensor(
                coordinator=entry.runtime_data,
                garden_id=entry.data[CONF_GARDEN_ID],
                device_id=transformers[0]["device_id"],
            )
        ]
    )


class InliteBluetoothSignalStrengthSensor(
    CoordinatorEntity[InliteCoordinator], SensorEntity
):
    """Represent the signal strength of the shared Bluetooth gateway."""

    entity_description = RSSI_SENSOR_DESCRIPTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: InliteCoordinator,
        garden_id: str,
        device_id: int,
    ) -> None:
        """Initialize the Bluetooth signal-strength sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{garden_id}_bluetooth_rssi"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{garden_id}_{device_id}")},
        )

    @property
    def native_value(self) -> int | None:
        """Return the latest RSSI reported by Home Assistant Bluetooth."""
        return self.coordinator.rssi

    @property
    def available(self) -> bool:
        """Return whether a connectable scanner can currently see the gateway."""
        address = self.coordinator.ble_address
        return (
            self.coordinator.rssi is not None
            and address is not None
            and bluetooth.async_address_present(
                self.coordinator.hass, address, connectable=True
            )
        )
