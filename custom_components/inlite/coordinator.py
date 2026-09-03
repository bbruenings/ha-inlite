"""DataUpdateCoordinator for in-lite integration.

Manages a persistent BLE connection with a connection lock to serialize
all hub communication. Connects once and queries all hubs before disconnecting.
Includes retry-with-reconnect for both commands and polling.
Receives OOB broadcast notifications for real-time state updates.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from inlite_ble.hub import InliteHub, ZoneState

from .const import (
    BLE_LOCAL_NAME,
    CONF_IDLE_DISCONNECT,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TRANSFORMERS,
    DEFAULT_IDLE_DISCONNECT_SECONDS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

MAX_COMMAND_ATTEMPTS = 3
MAX_POLL_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 0.5


class InliteCoordinator(DataUpdateCoordinator[dict[int, dict[int, ZoneState]]]):
    """Coordinator that manages BLE communication with in-lite hubs.

    Key reliability features:
    - asyncio.Lock serializes all BLE operations (prevents race conditions)
    - Persistent connection (connect once, reuse across polls and commands)
    - Single BLE connection shared across all hubs (they share a gateway)
    - Retry with disconnect-reconnect on command/poll failure
    - Cached BLE device reference from advertisement callbacks
    - OOB broadcast callback for real-time state push from the hub
    - Proper cleanup on unload
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.entry = entry
        self._hubs: dict[int, InliteHub] = {}
        self._available = False
        self._ble_lock = asyncio.Lock()
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self._ble_service_info: bluetooth.BluetoothServiceInfoBleak | None = None
        self._idle_disconnect_seconds = entry.options.get(
            CONF_IDLE_DISCONNECT, DEFAULT_IDLE_DISCONNECT_SECONDS
        )

        password = entry.data[CONF_PASSWORD]
        for tx_data in entry.data[CONF_TRANSFORMERS]:
            device_id = tx_data["device_id"]
            hub = InliteHub(
                device_id=device_id,
                passphrase=password,
                on_state_update=self._handle_oob_state_update,
            )
            self._hubs[device_id] = hub

    @property
    def hubs(self) -> dict[int, InliteHub]:
        return self._hubs

    @property
    def available(self) -> bool:
        return self._available

    def update_ble_service_info(
        self, service_info: bluetooth.BluetoothServiceInfoBleak
    ) -> None:
        """Update the cached BLE device from an advertisement callback.

        Called by the BLE callback registered in __init__.py. Keeps the device
        reference fresh so _ensure_connected always uses the latest advertisement
        (critical for ESPHome BLE proxy failover).
        """
        self._ble_service_info = service_info

    def _handle_oob_state_update(self) -> None:
        """Handle an OOB broadcast notification from a hub.

        Called (on the event loop via call_soon_threadsafe) when the hub receives
        a state change broadcast (e.g., physical button press, timer trigger).
        Builds the full state dict from all hubs and pushes it to HA entities.
        """
        all_states: dict[int, dict[int, ZoneState]] = {}
        for device_id, hub in self._hubs.items():
            if hub.zone_states:
                all_states[device_id] = hub.zone_states

        if all_states:
            _LOGGER.debug("OOB state update received, pushing to HA entities")
            self._available = True
            self.async_set_updated_data(all_states)

    def _find_ble_device(self) -> bluetooth.BluetoothServiceInfoBleak | None:
        """Find the hub from current HA discovery, with callback fallback.

        ESPHome proxy service info can be stale across an HA restart. Refresh
        the lookup whenever a connection is needed, while retaining callback
        info as a fallback until HA has populated its discovery cache.
        """
        for info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
            if info.name and info.name.lower() == BLE_LOCAL_NAME:
                self._ble_service_info = info
                return info
        return self._ble_service_info

    async def _ensure_connected(self, hub: InliteHub) -> None:
        """Ensure the hub has an active BLE connection, reconnecting if needed."""
        if hub.is_connected:
            return

        info = self._find_ble_device()
        if info is None:
            raise ConnectionError("in-lite hub not found in bluetooth scanner")

        _LOGGER.debug(
            "Connecting to %s via HA bluetooth (source: %s)",
            info.address, getattr(info, "source", "unknown"),
        )
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                info.device,
                info.address,
                max_attempts=3,
            )
        except Exception:
            # The cached advertisement may be stale (e.g. after an ESPHome
            # proxy restart) — force a fresh scanner lookup on the next
            # attempt instead of repeatedly retrying the same bad reference.
            self._ble_service_info = None
            raise

        connected = await hub.connect(client=client)
        if not connected:
            self._ble_service_info = None
            raise ConnectionError("Hub notification setup failed")

    def _schedule_idle_disconnect(self) -> None:
        """Schedule a disconnect after the idle timeout."""
        self._cancel_idle_disconnect()
        self._disconnect_timer = self.hass.loop.call_later(
            self._idle_disconnect_seconds,
            lambda: self.hass.async_create_task(self._idle_disconnect()),
        )

    def _cancel_idle_disconnect(self) -> None:
        """Cancel pending idle disconnect."""
        if self._disconnect_timer is not None:
            self._disconnect_timer.cancel()
            self._disconnect_timer = None

    async def _idle_disconnect(self) -> None:
        """Disconnect all hubs after idle timeout."""
        async with self._ble_lock:
            for hub in self._hubs.values():
                await hub.disconnect()
            _LOGGER.debug("Idle disconnect completed")

    async def _async_update_data(self) -> dict[int, dict[int, ZoneState]]:
        """Poll all hubs for zone states.

        Connects once, queries all hubs, then schedules idle disconnect.
        Retries once per hub on failure (disconnect-reconnect between attempts).
        All operations are serialized under the BLE lock.
        """
        async with self._ble_lock:
            self._cancel_idle_disconnect()
            all_states: dict[int, dict[int, ZoneState]] = {}

            for device_id, hub in self._hubs.items():
                for attempt in range(MAX_POLL_ATTEMPTS):
                    try:
                        await self._ensure_connected(hub)
                        states = await hub.query_zone_states()
                        all_states[device_id] = states
                        self._available = True
                        break
                    except Exception as err:
                        last_attempt = attempt == MAX_POLL_ATTEMPTS - 1
                        _LOGGER.warning(
                            "Poll attempt %d/%d for hub 0x%04X failed: %s",
                            attempt + 1, MAX_POLL_ATTEMPTS, device_id, err,
                            exc_info=err if last_attempt else None,
                        )
                        await hub.disconnect()
                        # Do not retry a possibly stale proxy/service-info
                        # pair. The next attempt must use HA's latest lookup.
                        self._ble_service_info = None
                        if not last_attempt:
                            await asyncio.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))

            self._schedule_idle_disconnect()

            if not all_states and self._hubs:
                self._available = False
                raise UpdateFailed("Could not connect to any hub")

            return all_states

    async def async_send_command(
        self, device_id: int, output_id: int, on: bool
    ) -> bool:
        """Send an ON/OFF command to a specific zone.

        Retries up to MAX_COMMAND_ATTEMPTS times with disconnect-reconnect
        between attempts and increasing backoff. The BLE lock is released
        between retries so polling can still proceed.
        """
        hub = self._hubs.get(device_id)
        if hub is None:
            _LOGGER.error("No hub with device_id 0x%04X", device_id)
            return False

        last_error: Exception | None = None
        for attempt in range(MAX_COMMAND_ATTEMPTS):
            async with self._ble_lock:
                self._cancel_idle_disconnect()
                try:
                    await self._ensure_connected(hub)
                    result = await hub.set_outlet_mode(output_id, on)
                    if result:
                        self._schedule_idle_disconnect()
                        return True
                    # Command sent but hub didn't ACK — disconnect and retry
                    _LOGGER.debug(
                        "Command attempt %d/%d for hub 0x%04X zone %d: no ACK",
                        attempt + 1, MAX_COMMAND_ATTEMPTS, device_id, output_id,
                    )
                    await hub.disconnect()
                except Exception as err:
                    last_error = err
                    _LOGGER.debug(
                        "Command attempt %d/%d for hub 0x%04X zone %d failed: %s",
                        attempt + 1, MAX_COMMAND_ATTEMPTS, device_id, output_id, err,
                    )
                    await hub.disconnect()
                    # Force the next connection attempt through HA Bluetooth
                    # discovery instead of reusing stale service information.
                    self._ble_service_info = None

            # Backoff between retries (lock released so other operations can proceed)
            if attempt < MAX_COMMAND_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))

        _LOGGER.error(
            "Command to hub 0x%04X zone %d failed after %d attempts: %s",
            device_id, output_id, MAX_COMMAND_ATTEMPTS, last_error,
        )
        self._schedule_idle_disconnect()
        return False

    async def async_shutdown(self) -> None:
        """Disconnect all hubs (called on unload)."""
        self._cancel_idle_disconnect()
        async with self._ble_lock:
            for hub in self._hubs.values():
                await hub.disconnect()
            _LOGGER.debug("All hubs disconnected")
