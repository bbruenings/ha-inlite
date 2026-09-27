"""The in-lite integration."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Make the bundled inlite_ble package importable as a top-level module.
# This allows `from inlite_ble.hub import ...` to work without pip-installing.
_LIB_DIR = str(Path(__file__).parent / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothScanningMode
from homeassistant.components.bluetooth.match import BluetoothCallbackMatcher
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import BLE_LOCAL_NAME, DOMAIN
from .coordinator import InliteCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT]

type InliteConfigEntry = ConfigEntry[InliteCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: InliteConfigEntry) -> bool:
    """Set up in-lite from a config entry."""
    coordinator = InliteCoordinator(hass, entry)

    # Register a BLE callback that:
    # 1. Suppresses future discovery notifications for this device
    # 2. Keeps the BLE device reference fresh (critical for ESPHome proxies)
    @callback
    def _async_update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Update the cached BLE device from advertisement data."""
        coordinator.update_ble_service_info(service_info)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble,
            BluetoothCallbackMatcher(local_name=BLE_LOCAL_NAME),
            BluetoothScanningMode.PASSIVE,
        )
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except UpdateFailed as err:
        raise ConfigEntryNotReady("Hub not reachable") from err

    entry.runtime_data = coordinator

    # Disconnect hubs when the config entry is unloaded
    entry.async_on_unload(coordinator.async_shutdown)

    # Also disconnect as early as possible on HA shutdown (e.g. a Core update).
    # Config-entry unload isn't guaranteed to run to completion before the
    # process is killed, and an unclean BLE disconnect can leave the hub's
    # single connection slot stuck until it's power-cycled.
    async def _async_handle_hass_stop(event: Event) -> None:
        await coordinator.async_shutdown()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_handle_hass_stop)
    )

    # Reload integration when options change (scan interval, idle disconnect)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: InliteConfigEntry
) -> None:
    """Reload when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: InliteConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
