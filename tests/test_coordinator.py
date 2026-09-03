"""Tests for coordinator Bluetooth discovery recovery."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("bleak_retry_connector")

from custom_components.inlite.coordinator import InliteCoordinator  # noqa: E402
from custom_components.inlite.const import (
    CONF_STARTUP_DELAY,
    DEFAULT_STARTUP_DELAY_SECONDS,
)
from homeassistant.helpers.update_coordinator import UpdateFailed  # noqa: E402


class ServiceInfo:
    """Small service-info stand-in for the discovery tests."""

    def __init__(self, name: str, address: str) -> None:
        self.name = name
        self.address = address
        self.device = object()


class Clock:
    """Controllable event-loop clock for discovery recovery tests."""

    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        """Return the current simulated monotonic time."""
        return self.now


class HassWithClock:
    """Minimal Home Assistant stand-in that provides an event loop clock."""

    def __init__(self, clock: Clock) -> None:
        self.loop = clock


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


class TestInliteCoordinatorStartupDiscovery:
    """Tests for initial Bluetooth discovery recovery."""

    @pytest.mark.asyncio
    async def test_initial_discovery_retries_until_hub_appears(self, monkeypatch) -> None:
        """Startup recovery polls discovery until a proxy reports the hub."""
        coordinator = object.__new__(InliteCoordinator)
        clock = Clock()
        coordinator.hass = HassWithClock(clock)
        coordinator._startup_delay_seconds = 5
        coordinator._startup_delay_applied = False
        coordinator._ble_service_info = None
        current = ServiceInfo("inlitebt", "current")
        discovery_calls = 0

        def discovered(hass, connectable):
            nonlocal discovery_calls
            discovery_calls += 1
            return [] if discovery_calls < 3 else [current]

        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_discovered_service_info",
            discovered,
        )

        sleep_times = []

        async def capture_sleep(delay):
            sleep_times.append(delay)
            clock.now += delay

        monkeypatch.setattr("asyncio.sleep", capture_sleep)

        assert await coordinator._async_wait_for_initial_discovery() is True
        assert sleep_times == [2, 3]
        assert coordinator._startup_delay_applied is True
        assert coordinator._ble_service_info is current

    @pytest.mark.asyncio
    async def test_initial_discovery_stops_when_timeout_expires(self, monkeypatch) -> None:
        """Startup recovery is bounded by the configured timeout."""
        coordinator = object.__new__(InliteCoordinator)
        clock = Clock()
        coordinator.hass = HassWithClock(clock)
        coordinator._startup_delay_seconds = 5
        coordinator._startup_delay_applied = False
        coordinator._ble_service_info = None

        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_discovered_service_info",
            lambda hass, connectable: [],
        )

        sleep_times = []

        async def capture_sleep(delay):
            sleep_times.append(delay)
            clock.now += delay

        monkeypatch.setattr("asyncio.sleep", capture_sleep)

        assert await coordinator._async_wait_for_initial_discovery() is False
        assert sleep_times == [2, 3]
        assert coordinator._startup_delay_applied is True

    @pytest.mark.asyncio
    async def test_initial_discovery_timeout_causes_update_failure(self, monkeypatch) -> None:
        """An unavailable proxy leaves setup retryable after the bounded wait."""
        coordinator = object.__new__(InliteCoordinator)
        clock = Clock()
        coordinator.hass = HassWithClock(clock)
        coordinator._startup_delay_seconds = 5
        coordinator._startup_delay_applied = False
        coordinator._ble_service_info = None
        coordinator._ble_lock = asyncio.Lock()
        coordinator._hubs = {1: SimpleNamespace(disconnect=AsyncMock())}
        coordinator._available = False
        coordinator._cancel_idle_disconnect = lambda: None
        coordinator._schedule_idle_disconnect = lambda: None

        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_discovered_service_info",
            lambda hass, connectable: [],
        )

        async def capture_sleep(delay):
            clock.now += delay

        async def cannot_connect(hub):
            raise ConnectionError("in-lite hub not found in bluetooth scanner")

        monkeypatch.setattr("asyncio.sleep", capture_sleep)
        coordinator._ensure_connected = cannot_connect

        with pytest.raises(UpdateFailed, match="Could not connect to any hub"):
            await coordinator._async_update_data()

    @pytest.mark.asyncio
    async def test_initial_discovery_is_skipped_when_disabled(self, monkeypatch) -> None:
        """A timeout of zero preserves the opt-out behavior."""
        coordinator = object.__new__(InliteCoordinator)
        clock = Clock()
        coordinator.hass = HassWithClock(clock)
        coordinator._startup_delay_seconds = 0
        coordinator._startup_delay_applied = False
        coordinator._ble_service_info = None

        monkeypatch.setattr(
            "custom_components.inlite.coordinator.bluetooth.async_discovered_service_info",
            lambda hass, connectable: [],
        )

        assert await coordinator._async_wait_for_initial_discovery() is False
        assert coordinator._startup_delay_applied is True
