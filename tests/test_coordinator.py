"""Tests for coordinator Bluetooth discovery recovery."""

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("bleak_retry_connector")

from custom_components.inlite.coordinator import InliteCoordinator  # noqa: E402


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
