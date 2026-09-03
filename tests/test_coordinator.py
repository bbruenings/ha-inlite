"""Tests for coordinator Bluetooth discovery recovery."""

import asyncio
import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("bleak_retry_connector")

from custom_components.inlite.coordinator import InliteCoordinator  # noqa: E402
from custom_components.inlite.const import (
    CONF_STARTUP_DELAY,
    DEFAULT_STARTUP_DELAY_SECONDS,
)


class ServiceInfo:
    """Small service-info stand-in for the discovery tests."""

    def __init__(self, name: str, address: str) -> None:
        self.name = name
        self.address = address
        self.device = object()


class TestInliteCoordinatorBluetooth:
    """Tests for current service info selection."""

    def test_find_refreshes_cached_service_info(self, monkeypatch) -> None:
        """A reconnect uses newly discovered proxy information."""
        coordinator = object.__new__(InliteCoordinator)
        coordinator.hass = object()
        stale = ServiceInfo("inlitebt", "stale")
        current = ServiceInfo("inlitebt", "current")
        coordinator._ble_service_info = stale

        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_discovered_service_info",
            lambda hass, connectable: [current],
        )

        assert coordinator._find_ble_device() is current
        assert coordinator._ble_service_info is current

    def test_find_falls_back_to_callback_info_until_discovery_catches_up(
        self, monkeypatch
    ) -> None:
        """A callback result remains usable while HA discovery is still empty."""
        coordinator = object.__new__(InliteCoordinator)
        coordinator.hass = object()
        callback_info = ServiceInfo("inlitebt", "proxy")
        coordinator._ble_service_info = callback_info

        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_discovered_service_info",
            lambda hass, connectable: [],
        )

        assert coordinator._find_ble_device() is callback_info


class TestInliteCoordinatorStartupDelay:
    """Tests for the startup delay feature."""

    @pytest.mark.asyncio
    async def test_startup_delay_applied_once(self, monkeypatch) -> None:
        """Startup delay is applied only on the first refresh."""
        coordinator = object.__new__(InliteCoordinator)
        coordinator.hass = object()
        coordinator._startup_delay_seconds = 5
        coordinator._startup_delay_applied = False
        coordinator._ble_lock = asyncio.Lock()
        coordinator._cancel_idle_disconnect = lambda: None
        coordinator._hubs = {}
        coordinator._available = True
        coordinator._schedule_idle_disconnect = lambda: None

        sleep_times = []
        original_sleep = asyncio.sleep

        async def capture_sleep(delay):
            sleep_times.append(delay)
            return await original_sleep(0)  # Skip actual delay in test

        monkeypatch.setattr("asyncio.sleep", capture_sleep)

        # First call should apply delay
        await coordinator._async_update_data()
        assert len(sleep_times) == 1
        assert sleep_times[0] == 5
        assert coordinator._startup_delay_applied is True

        # Second call should not apply delay
        sleep_times.clear()
        await coordinator._async_update_data()
        assert len(sleep_times) == 0

    @pytest.mark.asyncio
    async def test_startup_delay_skipped_when_zero(self, monkeypatch) -> None:
        """No delay is applied when startup_delay_seconds is 0."""
        coordinator = object.__new__(InliteCoordinator)
        coordinator.hass = object()
        coordinator._startup_delay_seconds = 0
        coordinator._startup_delay_applied = False
        coordinator._ble_lock = asyncio.Lock()
        coordinator._cancel_idle_disconnect = lambda: None
        coordinator._hubs = {}
        coordinator._available = True
        coordinator._schedule_idle_disconnect = lambda: None

        sleep_times = []
        original_sleep = asyncio.sleep

        async def capture_sleep(delay):
            sleep_times.append(delay)
            return await original_sleep(0)

        monkeypatch.setattr("asyncio.sleep", capture_sleep)

        await coordinator._async_update_data()
        assert len(sleep_times) == 0
        assert coordinator._startup_delay_applied is False
