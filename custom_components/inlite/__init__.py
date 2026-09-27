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

from .const import (
    BLE_LOCAL_NAME,
    CONFIG_ENTRY_VERSION,
    CONF_IDLE_DISCONNECT,
    DEFAULT_IDLE_DISCONNECT_SECONDS,
    DOMAIN,
)
from .coordinator import InliteCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT]

type InliteConfigEntry = ConfigEntry[InliteCoordinator]

LEGACY_CONF_STARTUP_DELAY = "startup_delay_seconds"


async def async_migrate_entry(
    hass: HomeAssistant, entry: InliteConfigEntry
) -> bool:
    """Migrate legacy startup retry and persistent-connection defaults."""
    if entry.version >= CONFIG_ENTRY_VERSION:
        return True

    options = dict(entry.options)
    options.pop(LEGACY_CONF_STARTUP_DELAY, None)
    # Beta 3 saved a one-hour connection retention whenever its options form
    # was submitted. Reset it so existing installations receive Beta 4's
    # restart-safe behavior; users can explicitly opt back in afterward.
    options[CONF_IDLE_DISCONNECT] = DEFAULT_IDLE_DISCONNECT_SECONDS
    hass.config_entries.async_update_entry(
        entry,
        options=options,
        version=CONFIG_ENTRY_VERSION,
    )
    return True


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

    matcher = (
        BluetoothCallbackMatcher(address=coordinator.ble_address)
        if coordinator.ble_address is not None
        else BluetoothCallbackMatcher(local_name=BLE_LOCAL_NAME)
    )
    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble,
            matcher,
            BluetoothScanningMode.PASSIVE,
        )
    )

    # Also disconnect as early as possible on HA shutdown (e.g. a Core update).
    # Config-entry unload isn't guaranteed to run to completion before the
    # process is killed, and an unclean BLE disconnect can leave the hub's
    # single connection slot stuck until it's power-cycled.
    async def _async_handle_hass_stop(event: Event) -> None:
        await coordinator.async_shutdown()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_handle_hass_stop)
    )

    # DataUpdateCoordinator turns a failed first refresh into ConfigEntryNotReady,
    # allowing Home Assistant (and a later Bluetooth discovery) to retry setup.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

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
