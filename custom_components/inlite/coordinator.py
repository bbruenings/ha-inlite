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
    CONF_BLE_ADDRESS,
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
MAX_BLE_CANDIDATES = 5
RETRY_BACKOFF_SECONDS = 0.5
SHUTDOWN_DISCONNECT_TIMEOUT_SECONDS = 10


class InliteCoordinator(DataUpdateCoordinator[dict[int, dict[int, ZoneState]]]):
    """Coordinator that manages BLE communication with in-lite hubs.

    Key reliability features:
    - asyncio.Lock serializes all BLE operations (prevents race conditions)
    - Configurable connection retention (disconnects after each operation by default)
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
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.entry = entry
        self._hubs: dict[int, InliteHub] = {}
        self._available = False
        self._ble_lock = asyncio.Lock()
        self._shutdown_lock = asyncio.Lock()
        self._active_ble_task: asyncio.Task | None = None
        self._stopping = False
        self._shutdown_complete = False
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self._ble_service_info: bluetooth.BluetoothServiceInfoBleak | None = None
        self._ble_address: str | None = entry.data.get(CONF_BLE_ADDRESS)
        self._ble_candidates: dict[
            str, bluetooth.BluetoothServiceInfoBleak
        ] = {}
        self._active_ble_address: str | None = None
        self._rssi: int | None = None
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

    @property
    def ble_address(self) -> str | None:
        """Return the configured Bluetooth transport address, if known."""
        return self._ble_address

    @property
    def rssi(self) -> int | None:
        """Return the most recently observed Bluetooth signal strength."""
        return self._rssi

    def update_ble_service_info(
        self, service_info: bluetooth.BluetoothServiceInfoBleak
    ) -> None:
        """Remember an in-lite advertisement without trusting its identity.

        All in-lite gateways advertise the same local name. A new address is
        therefore only a candidate until a command encrypted with this garden's
        passphrase receives a valid mesh response.
        """
        self._remember_ble_candidate(service_info)
        if service_info.address == self._ble_address or (
            self._ble_service_info is not None
            and service_info.address == self._ble_service_info.address
        ):
            self._select_ble_service_info(service_info)

    def _remember_ble_candidate(
        self, service_info: bluetooth.BluetoothServiceInfoBleak
    ) -> None:
        """Keep the freshest HA route for a possible gateway address."""
        self._ble_candidates[service_info.address] = service_info

    def _select_ble_service_info(
        self, service_info: bluetooth.BluetoothServiceInfoBleak
    ) -> None:
        """Select a route for the current connection attempt without saving it."""
        self._remember_ble_candidate(service_info)
        self._ble_service_info = service_info
        if service_info.address == self._ble_address:
            self._rssi = service_info.rssi

    def _set_ble_address(self, address: str) -> None:
        """Persist an address after a valid encrypted mesh exchange."""
        self._ble_address = address
        if service_info := self._ble_candidates.get(address):
            self._select_ble_service_info(service_info)
        if self.entry.data.get(CONF_BLE_ADDRESS) == address:
            return
        self.hass.config_entries.async_update_entry(
            self.entry,
            data={**self.entry.data, CONF_BLE_ADDRESS: address},
        )

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

    def _refresh_ble_candidates(self) -> None:
        """Refresh the candidate pool from Home Assistant's discovery cache."""
        for info in bluetooth.async_discovered_service_info(
            self.hass, connectable=True
        ):
            if info.name and info.name.lower() == BLE_LOCAL_NAME:
                self._remember_ble_candidate(info)

    def _service_info_for_address(
        self, address: str
    ) -> bluetooth.BluetoothServiceInfoBleak | None:
        """Resolve one address without switching to a different candidate."""
        if info := bluetooth.async_last_service_info(
            self.hass, address, connectable=True
        ):
            self._remember_ble_candidate(info)
            return info
        if (
            self._ble_service_info is not None
            and self._ble_service_info.address == address
        ):
            return self._ble_service_info
        return self._ble_candidates.get(address)

    def _find_ble_device(
        self, excluded_addresses: set[str] | None = None
    ) -> bluetooth.BluetoothServiceInfoBleak | None:
        """Select a connectable gateway candidate for the next attempt.

        The last address that completed a valid mesh exchange is preferred even
        when another advertiser has stronger RSSI. Failed addresses can be
        excluded so retries rotate through the remaining candidates.
        """
        excluded = excluded_addresses or set()
        self._refresh_ble_candidates()

        if self._ble_address is not None and self._ble_address not in excluded:
            if info := self._service_info_for_address(self._ble_address):
                self._select_ble_service_info(info)
                return info

        candidates = [
            info
            for address, info in self._ble_candidates.items()
            if address not in excluded
        ]
        if not candidates:
            return None

        info = max(
            candidates,
            key=lambda candidate: (
                candidate.rssi if candidate.rssi is not None else -999,
                candidate.address,
            ),
        )
        self._select_ble_service_info(info)
        return info

    def _candidate_attempt_count(self) -> int:
        """Return a bounded retry count that can cover visible candidates."""
        self._refresh_ble_candidates()
        addresses = set(self._ble_candidates)
        if self._ble_address is not None:
            addresses.add(self._ble_address)
        return min(
            MAX_BLE_CANDIDATES,
            max(MAX_POLL_ATTEMPTS, len(addresses)),
        )

    async def _ensure_connected(
        self,
        hub: InliteHub,
        excluded_addresses: set[str] | None = None,
    ) -> str:
        """Ensure the hub has an active BLE connection, reconnecting if needed."""
        if hub.is_connected:
            if address := self._active_ble_address or self._ble_address:
                return address
            raise ConnectionError("Connected hub has no Bluetooth address")

        info = self._find_ble_device(excluded_addresses)
        if info is None:
            raise ConnectionError("in-lite hub not found in bluetooth scanner")
        self._active_ble_address = info.address

        _LOGGER.debug(
            "Connecting to %s via HA bluetooth (source: %s)",
            info.address, getattr(info, "source", "unknown"),
        )
        try:
            def _fresh_ble_device():
                refreshed = self._service_info_for_address(info.address)
                return refreshed.device if refreshed is not None else info.device

            client = await establish_connection(
                BleakClientWithServiceCache,
                info.device,
                info.address,
                # The coordinator owns retries so each attempt re-resolves the
                # current Home Assistant/ESPHome proxy route.
                max_attempts=1,
                ble_device_callback=_fresh_ble_device,
            )
        except Exception:
            # The cached advertisement may be stale (e.g. after an ESPHome
            # proxy restart) — force a fresh scanner lookup on the next
            # attempt. Keep the attempted address until the caller records it
            # as failed so the retry can rotate to another candidate.
            self._ble_service_info = None
            raise

        connected = await hub.connect(client=client)
        if not connected:
            self._ble_service_info = None
            raise ConnectionError("Hub notification setup failed")
        return info.address

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
            self._active_ble_address = None
            _LOGGER.debug("Idle disconnect completed")

    async def _async_update_data(self) -> dict[int, dict[int, ZoneState]]:
        """Poll all hubs for zone states.

        Connects once, queries all hubs, then schedules idle disconnect.
        Retries across a bounded set of gateway candidates on failure.
        All operations are serialized under the BLE lock.
        A missing advertisement fails quickly so Home Assistant can put the
        config entry into SETUP_RETRY and retry it when Bluetooth discovery sees
        the hub, instead of blocking config-entry setup in a long sleep.
        """
        if self._stopping:
            raise UpdateFailed("Coordinator is shutting down")
        if self._find_ble_device() is None:
            self._available = False
            raise UpdateFailed("in-lite hub not discovered")

        async with self._ble_lock:
            self._active_ble_task = asyncio.current_task()
            try:
                self._cancel_idle_disconnect()
                all_states: dict[int, dict[int, ZoneState]] = {}
                last_error: Exception | None = None
                failed_addresses: set[str] = set()
                attempt_count = self._candidate_attempt_count()

                for device_id, hub in self._hubs.items():
                    for attempt in range(attempt_count):
                        attempt_address: str | None = None
                        try:
                            attempt_address = await self._ensure_connected(
                                hub, failed_addresses
                            )
                            states = await hub.query_zone_states()
                            if not hub.last_query_successful:
                                raise ConnectionError(
                                    "Gateway did not return an authenticated "
                                    "zone-state response"
                                )
                            self._set_ble_address(attempt_address)
                            all_states[device_id] = states
                            self._available = True
                            break
                        except Exception as err:
                            last_error = err
                            _LOGGER.debug(
                                "Poll attempt %d/%d for hub 0x%04X failed: %s",
                                attempt + 1,
                                attempt_count,
                                device_id,
                                err,
                                exc_info=attempt == attempt_count - 1,
                            )
                            if attempt_address is None:
                                attempt_address = self._active_ble_address
                            if attempt_address is not None:
                                failed_addresses.add(attempt_address)
                            await hub.disconnect()
                            self._active_ble_address = None
                            # Do not retry a possibly stale proxy/service-info
                            # pair. The next attempt must use HA's latest lookup.
                            self._ble_service_info = None
                            if attempt < attempt_count - 1:
                                await asyncio.sleep(
                                    RETRY_BACKOFF_SECONDS * (attempt + 1)
                                )

                self._schedule_idle_disconnect()

                if not all_states and self._hubs:
                    self._available = False
                    raise UpdateFailed("Could not connect to any hub") from last_error

                return all_states
            finally:
                if self._active_ble_task is asyncio.current_task():
                    self._active_ble_task = None

    async def async_send_command(
        self, device_id: int, output_id: int, on: bool
    ) -> bool:
        """Send an ON/OFF command to a specific zone.

        Retries across a bounded set of gateway candidates with
        disconnect-reconnect and increasing backoff. The BLE lock is released
        between retries so polling can still proceed.
        """
        hub = self._hubs.get(device_id)
        if self._stopping:
            _LOGGER.debug("Ignoring command while coordinator is shutting down")
            return False
        if hub is None:
            _LOGGER.error("No hub with device_id 0x%04X", device_id)
            return False

        last_error: Exception | None = None
        failed_addresses: set[str] = set()
        attempt_count = min(
            MAX_BLE_CANDIDATES,
            max(MAX_COMMAND_ATTEMPTS, self._candidate_attempt_count()),
        )
        for attempt in range(attempt_count):
            attempt_address: str | None = None
            async with self._ble_lock:
                self._active_ble_task = asyncio.current_task()
                try:
                    self._cancel_idle_disconnect()
                    attempt_address = await self._ensure_connected(
                        hub, failed_addresses
                    )
                    result = await hub.set_outlet_mode(output_id, on)
                    if result:
                        self._set_ble_address(attempt_address)
                        self._schedule_idle_disconnect()
                        return True
                    # Command sent but hub didn't ACK — disconnect and retry
                    _LOGGER.debug(
                        "Command attempt %d/%d for hub 0x%04X zone %d: no ACK",
                        attempt + 1, attempt_count, device_id, output_id,
                    )
                    failed_addresses.add(attempt_address)
                    await hub.disconnect()
                    self._active_ble_address = None
                except Exception as err:
                    last_error = err
                    _LOGGER.debug(
                        "Command attempt %d/%d for hub 0x%04X zone %d failed: %s",
                        attempt + 1, attempt_count, device_id, output_id, err,
                    )
                    if attempt_address is None:
                        attempt_address = self._active_ble_address
                    if attempt_address is not None:
                        failed_addresses.add(attempt_address)
                    await hub.disconnect()
                    self._active_ble_address = None
                    # Force the next connection attempt through HA Bluetooth
                    # discovery instead of reusing stale service information.
                    self._ble_service_info = None
                finally:
                    if self._active_ble_task is asyncio.current_task():
                        self._active_ble_task = None

            # Backoff between retries (lock released so other operations can proceed)
            if attempt < attempt_count - 1:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))

        _LOGGER.error(
            "Command to hub 0x%04X zone %d failed after %d attempts: %s",
            device_id, output_id, attempt_count, last_error,
        )
        self._schedule_idle_disconnect()
        return False

    async def async_shutdown(self) -> None:
        """Stop coordinator work and disconnect all hubs within a bounded time."""
        async with self._shutdown_lock:
            if self._shutdown_complete:
                return

            self._stopping = True
            await super().async_shutdown()
            self._cancel_idle_disconnect()

            current_task = asyncio.current_task()
            if (
                self._active_ble_task is not None
                and self._active_ble_task is not current_task
                and not self._active_ble_task.done()
            ):
                self._active_ble_task.cancel("in-lite coordinator is shutting down")
                try:
                    await self._active_ble_task
                except asyncio.CancelledError:
                    pass

            try:
                async with asyncio.timeout(SHUTDOWN_DISCONNECT_TIMEOUT_SECONDS):
                    async with self._ble_lock:
                        await asyncio.gather(
                            *(hub.disconnect() for hub in self._hubs.values())
                        )
                        self._active_ble_address = None
            except TimeoutError:
                _LOGGER.warning(
                    "Timed out disconnecting in-lite hubs during shutdown"
                )
            finally:
                self._shutdown_complete = True

            _LOGGER.debug("All hubs disconnected")
