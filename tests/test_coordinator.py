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
        stale = ServiceInfo("inlitebt", "hub-address")
        current = ServiceInfo("inlitebt", "hub-address")
        coordinator._ble_service_info = stale

        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_last_service_info",
            lambda hass, address, connectable: current,
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
        callback_info = ServiceInfo("inlitebt", "hub-address")
        coordinator._ble_service_info = callback_info

        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_last_service_info",
            lambda hass, address, connectable: None,
        )

        assert coordinator._find_ble_device() is callback_info

    def test_legacy_entry_learns_address_from_local_name(self, monkeypatch) -> None:
        """An entry created before address persistence learns the hub address."""
        coordinator = object.__new__(InliteCoordinator)
        update_entry = Mock()
        coordinator.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry)
        )
        coordinator.entry = SimpleNamespace(data={})
        coordinator._ble_address = None
        coordinator._ble_service_info = None
        current = ServiceInfo("inlitebt", "hub-address")

        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_discovered_service_info",
            lambda hass, connectable: [current],
        )

        assert coordinator._find_ble_device() is current
        assert coordinator._ble_address == "hub-address"
        update_entry.assert_called_once_with(
            coordinator.entry,
            data={"ble_address": "hub-address"},
        )

    def test_callback_ignores_a_different_configured_hub(self) -> None:
        """Advertisements for another hub do not replace the configured route."""
        coordinator = object.__new__(InliteCoordinator)
        coordinator._ble_address = "configured"
        coordinator._rssi = -55
        coordinator.entry = SimpleNamespace(data={"ble_address": "configured"})
        coordinator.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=Mock())
        )
        configured = ServiceInfo("inlitebt", "configured")
        coordinator._ble_service_info = configured

        coordinator.update_ble_service_info(
            ServiceInfo("inlitebt", "other", rssi=-90)
        )

        assert coordinator._ble_service_info is configured
        assert coordinator.rssi == -55

    def test_callback_caches_rssi_for_configured_hub(self) -> None:
        """A matching advertisement updates the diagnostic RSSI value."""
        coordinator = object.__new__(InliteCoordinator)
        coordinator._ble_address = "configured"
        coordinator._rssi = None
        coordinator.entry = SimpleNamespace(data={"ble_address": "configured"})
        coordinator.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=Mock())
        )

        current = ServiceInfo("inlitebt", "configured", rssi=-72)
        coordinator.update_ble_service_info(current)

        assert coordinator._ble_service_info is current
        assert coordinator.rssi == -72

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
