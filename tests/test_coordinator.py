"""Tests for coordinator Bluetooth lifecycle recovery."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("bleak_retry_connector")

from custom_components.inlite.coordinator import InliteCoordinator  # noqa: E402
from homeassistant.helpers.update_coordinator import (  # noqa: E402
    DataUpdateCoordinator,
    UpdateFailed,
)


class ServiceInfo:
    """Small service-info stand-in for Bluetooth tests."""

    def __init__(self, name: str, address: str, rssi: int = -60) -> None:
        self.name = name
        self.address = address
        self.rssi = rssi
        self.device = object()


class TestInliteCoordinatorBluetooth:
    """Tests for current service info selection."""

    def test_find_refreshes_configured_address_route(self, monkeypatch) -> None:
        """A reconnect asks Home Assistant for the current proxy route."""
        coordinator = object.__new__(InliteCoordinator)
        coordinator.hass = object()
        coordinator._ble_address = "hub-address"
        coordinator._ble_candidates = {}
        stale = ServiceInfo("inlitebt", "hub-address")
        current = ServiceInfo("inlitebt", "hub-address")
        coordinator._ble_service_info = stale

        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_last_service_info",
            lambda hass, address, connectable: current,
        )
        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_discovered_service_info",
            lambda hass, connectable: [],
        )

        assert coordinator._find_ble_device() is current
        assert coordinator._ble_service_info is current
        assert coordinator.rssi == -60

    def test_find_falls_back_to_callback_info_until_discovery_catches_up(
        self, monkeypatch
    ) -> None:
        """A matching callback result remains usable while discovery catches up."""
        coordinator = object.__new__(InliteCoordinator)
        coordinator.hass = object()
        coordinator._ble_address = "hub-address"
        coordinator._ble_candidates = {}
        callback_info = ServiceInfo("inlitebt", "hub-address")
        coordinator._ble_service_info = callback_info

        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_last_service_info",
            lambda hass, address, connectable: None,
        )
        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_discovered_service_info",
            lambda hass, connectable: [],
        )

        assert coordinator._find_ble_device() is callback_info

    def test_legacy_entry_selects_but_does_not_persist_unverified_address(
        self, monkeypatch
    ) -> None:
        """Discovery alone cannot prove that a gateway belongs to the garden."""
        coordinator = object.__new__(InliteCoordinator)
        update_entry = Mock()
        coordinator.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry)
        )
        coordinator.entry = SimpleNamespace(data={})
        coordinator._ble_address = None
        coordinator._ble_candidates = {}
        coordinator._ble_service_info = None
        coordinator._rssi = None
        current = ServiceInfo("inlitebt", "hub-address")

        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_discovered_service_info",
            lambda hass, connectable: [current],
        )

        assert coordinator._find_ble_device() is current
        assert coordinator._ble_address is None
        update_entry.assert_not_called()

    def test_callback_retains_alternate_without_replacing_configured_hub(self) -> None:
        """Alternate advertisements remain candidates without becoming trusted."""
        coordinator = object.__new__(InliteCoordinator)
        coordinator._ble_address = "configured"
        coordinator._ble_candidates = {}
        coordinator._rssi = -55
        coordinator.entry = SimpleNamespace(data={"ble_address": "configured"})
        coordinator.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=Mock())
        )
        configured = ServiceInfo("inlitebt", "configured")
        coordinator._ble_service_info = configured

        other = ServiceInfo("inlitebt", "other", rssi=-40)
        coordinator.update_ble_service_info(other)

        assert coordinator._ble_service_info is configured
        assert coordinator.rssi == -55
        assert coordinator._ble_candidates == {"other": other}
        coordinator.hass.config_entries.async_update_entry.assert_not_called()

    def test_callback_caches_rssi_for_configured_hub(self) -> None:
        """A matching advertisement updates the diagnostic RSSI value."""
        coordinator = object.__new__(InliteCoordinator)
        coordinator._ble_address = "configured"
        coordinator._ble_candidates = {}
        coordinator._rssi = None
        coordinator.entry = SimpleNamespace(data={"ble_address": "configured"})
        coordinator.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=Mock())
        )

        current = ServiceInfo("inlitebt", "configured", rssi=-72)
        coordinator.update_ble_service_info(current)

        assert coordinator._ble_service_info is current
        assert coordinator.rssi == -72

    def test_find_prefers_configured_address_over_stronger_candidate(
        self, monkeypatch
    ) -> None:
        """RSSI cannot override the last gateway validated by the garden."""
        coordinator = object.__new__(InliteCoordinator)
        coordinator.hass = object()
        coordinator._ble_address = "configured"
        coordinator._ble_candidates = {}
        coordinator._ble_service_info = None
        coordinator._rssi = None
        configured = ServiceInfo("inlitebt", "configured", rssi=-80)
        stronger = ServiceInfo("inlitebt", "neighbor", rssi=-35)

        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_last_service_info",
            lambda hass, address, connectable: configured,
        )
        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_discovered_service_info",
            lambda hass, connectable: [stronger],
        )

        assert coordinator._find_ble_device() is configured

    def test_find_uses_strongest_alternate_after_configured_address_fails(
        self, monkeypatch
    ) -> None:
        """A failed stored address can fall back to another visible advertiser."""
        coordinator = object.__new__(InliteCoordinator)
        coordinator.hass = object()
        coordinator._ble_address = "configured"
        coordinator._ble_candidates = {}
        coordinator._ble_service_info = None
        coordinator._rssi = None
        weak = ServiceInfo("inlitebt", "weak", rssi=-85)
        strong = ServiceInfo("inlitebt", "strong", rssi=-50)

        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_last_service_info",
            lambda hass, address, connectable: None,
        )
        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_discovered_service_info",
            lambda hass, connectable: [weak, strong],
        )

        assert coordinator._find_ble_device({"configured"}) is strong
        assert coordinator.rssi is None

    @pytest.mark.asyncio
    async def test_connection_failure_keeps_attempted_address_for_rotation(
        self, monkeypatch
    ) -> None:
        """The retry loop can exclude an address that failed to connect."""
        coordinator = object.__new__(InliteCoordinator)
        candidate = ServiceInfo("inlitebt", "unreachable")
        coordinator._active_ble_address = None
        coordinator._ble_service_info = candidate
        coordinator._find_ble_device = lambda excluded_addresses=None: candidate
        coordinator._service_info_for_address = lambda address: candidate
        hub = SimpleNamespace(is_connected=False)
        connect = AsyncMock(side_effect=ConnectionError("unreachable"))
        monkeypatch.setattr(
            "custom_components.inlite.coordinator.establish_connection", connect
        )

        with pytest.raises(ConnectionError, match="unreachable"):
            await coordinator._ensure_connected(hub)

        assert coordinator._active_ble_address == "unreachable"

    def test_route_reset_does_not_erase_last_rssi(self) -> None:
        """Connection retries retain signal data for troubleshooting."""
        coordinator = object.__new__(InliteCoordinator)
        coordinator._rssi = -68
        coordinator._ble_service_info = None

        assert coordinator.rssi == -68


class TestInliteCoordinatorLifecycle:
    """Tests for setup and shutdown behavior."""

    @pytest.mark.asyncio
    async def test_missing_discovery_fails_without_sleeping(self, monkeypatch) -> None:
        """Initial setup delegates retries to Home Assistant without blocking."""
        coordinator = object.__new__(InliteCoordinator)
        coordinator._stopping = False
        coordinator._available = True
        coordinator._find_ble_device = lambda: None
        sleep = AsyncMock()
        monkeypatch.setattr("asyncio.sleep", sleep)

        with pytest.raises(UpdateFailed, match="not discovered"):
            await coordinator._async_update_data()

        sleep.assert_not_awaited()
        assert coordinator._available is False

    @pytest.mark.asyncio
    async def test_poll_persists_only_candidate_with_valid_mesh_response(
        self, monkeypatch
    ) -> None:
        """A neighbor is rejected before the working garden gateway is saved."""
        coordinator = object.__new__(InliteCoordinator)
        update_entry = Mock()
        coordinator.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry)
        )
        coordinator.entry = SimpleNamespace(data={"ble_address": "old"})
        coordinator._stopping = False
        coordinator._available = False
        coordinator._ble_lock = asyncio.Lock()
        coordinator._active_ble_task = None
        coordinator._disconnect_timer = None
        coordinator._ble_address = "old"
        coordinator._ble_candidates = {}
        coordinator._ble_service_info = None
        coordinator._active_ble_address = None
        coordinator._rssi = None
        coordinator._find_ble_device = lambda excluded_addresses=None: ServiceInfo(
            "inlitebt", "old"
        )
        coordinator._candidate_attempt_count = lambda: 2
        coordinator._schedule_idle_disconnect = Mock()
        zone_state = object()

        hub = SimpleNamespace(
            last_query_successful=False,
            disconnect=AsyncMock(),
        )
        coordinator._hubs = {1: hub}
        addresses = iter(("neighbor", "working"))

        async def ensure_connected(candidate_hub, excluded_addresses=None):
            address = next(addresses)
            coordinator._active_ble_address = address
            candidate_hub.last_query_successful = address == "working"
            return address

        async def query_zone_states():
            return {0: zone_state}

        coordinator._ensure_connected = ensure_connected
        hub.query_zone_states = query_zone_states
        sleep = AsyncMock()
        monkeypatch.setattr("asyncio.sleep", sleep)

        states = await coordinator._async_update_data()

        assert states == {1: {0: zone_state}}
        update_entry.assert_called_once_with(
            coordinator.entry,
            data={"ble_address": "working"},
        )
        hub.disconnect.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_active_ble_work_before_disconnect(
        self, monkeypatch
    ) -> None:
        """Shutdown cannot wait indefinitely behind an active BLE operation."""
        coordinator = object.__new__(InliteCoordinator)
        coordinator._stopping = False
        coordinator._shutdown_complete = False
        coordinator._active_ble_task = None
        coordinator._ble_lock = asyncio.Lock()
        coordinator._shutdown_lock = asyncio.Lock()
        coordinator._disconnect_timer = None
        hub = SimpleNamespace(disconnect=AsyncMock())
        coordinator._hubs = {1: hub}
        base_shutdown = AsyncMock()
        monkeypatch.setattr(DataUpdateCoordinator, "async_shutdown", base_shutdown)

        operation_started = asyncio.Event()

        async def blocked_operation() -> None:
            async with coordinator._ble_lock:
                coordinator._active_ble_task = asyncio.current_task()
                operation_started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    coordinator._active_ble_task = None

        operation = asyncio.create_task(blocked_operation())
        await operation_started.wait()

        await coordinator.async_shutdown()

        assert operation.cancelled()
        base_shutdown.assert_awaited_once_with()
        hub.disconnect.assert_awaited_once_with()
        assert coordinator._shutdown_complete is True
