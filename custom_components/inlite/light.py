"""Light platform for in-lite integration.

Creates one LightEntity per zone per transformer.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import InliteConfigEntry
from .const import CONF_GARDEN_ID, CONF_GARDEN_NAME, CONF_TRANSFORMERS, DOMAIN
from .coordinator import InliteCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InliteConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up in-lite light entities from a config entry."""
    coordinator = entry.runtime_data
    garden_id = entry.data[CONF_GARDEN_ID]
    garden_name = entry.data[CONF_GARDEN_NAME]

    entities: list[InliteLightEntity] = []
    for tx_data in entry.data[CONF_TRANSFORMERS]:
        device_id = tx_data["device_id"]
        tx_name = tx_data["name"]
        firmware = tx_data.get("firmware_version", "unknown")

        for zone_data in tx_data["zones"]:
            entities.append(
                InliteLightEntity(
                    coordinator=coordinator,
                    garden_id=garden_id,
                    garden_name=garden_name,
                    device_id=device_id,
                    tx_name=tx_name,
                    firmware=firmware,
                    output_id=zone_data["output_id"],
                    zone_name=zone_data["name"],
                )
            )

    async_add_entities(entities)


class InliteLightEntity(CoordinatorEntity[InliteCoordinator], LightEntity):
    """Represents a single in-lite light zone."""

    _attr_has_entity_name = True
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(
        self,
        coordinator: InliteCoordinator,
        garden_id: str,
        garden_name: str,
        device_id: int,
        tx_name: str,
        firmware: Any,
        output_id: int,
        zone_name: str,
    ) -> None:
        """Initialize the light entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._output_id = output_id
        self._attr_name = zone_name
        self._attr_unique_id = f"{garden_id}_{device_id}_{output_id}"

        # Device groups zones under the transformer
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{garden_id}_{device_id}")},
            name=tx_name,
            manufacturer="in-lite",
            model=tx_name,
            sw_version=str(firmware),
            suggested_area=garden_name,
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if the light is on."""
        if self.coordinator.data is None:
            return None
        hub_states = self.coordinator.data.get(self._device_id, {})
        zone_state = hub_states.get(self._output_id)
        if zone_state is None:
            return None
        return zone_state.is_on

    @property
    def available(self) -> bool:
        """Return True if the hub is reachable."""
        return self.coordinator.available and super().available

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        previous_state = self.is_on
        self._attr_is_on = True
        self.async_write_ha_state()

        success = await self.coordinator.async_send_command(
            self._device_id, self._output_id, True
        )
        if success:
            # Update coordinator data directly from hub's internal state
            self.coordinator.async_set_updated_data(self.coordinator.data)
        else:
            # Roll back optimistic update on failure
            self._attr_is_on = previous_state
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        previous_state = self.is_on
        self._attr_is_on = False
        self.async_write_ha_state()

        success = await self.coordinator.async_send_command(
            self._device_id, self._output_id, False
        )
        if success:
            # Update coordinator data directly from hub's internal state
            self.coordinator.async_set_updated_data(self.coordinator.data)
        else:
            # Roll back optimistic update on failure
            self._attr_is_on = previous_state
            self.async_write_ha_state()
