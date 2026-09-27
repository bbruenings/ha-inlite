"""Tests for integration setup and config-entry migration."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("homeassistant")

from custom_components.inlite import (  # noqa: E402
    _remove_legacy_gateway_device,
    async_migrate_entry,
)
from custom_components.inlite.const import (  # noqa: E402
    CONF_IDLE_DISCONNECT,
    DEFAULT_IDLE_DISCONNECT_SECONDS,
)


@pytest.mark.asyncio
async def test_migration_removes_startup_delay_and_resets_retention() -> None:
    """Beta 3 options migrate to the restart-safe Beta 4 defaults."""
    update_entry = Mock()
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=update_entry)
    )
    entry = SimpleNamespace(
        version=1,
        options={
            "startup_delay_seconds": 120,
            CONF_IDLE_DISCONNECT: 3600,
            "scan_interval": 30,
        },
    )

    assert await async_migrate_entry(hass, entry) is True

    update_entry.assert_called_once_with(
        entry,
        options={
            CONF_IDLE_DISCONNECT: DEFAULT_IDLE_DISCONNECT_SECONDS,
            "scan_interval": 30,
        },
        version=2,
    )


def test_removes_obsolete_standalone_gateway_device(monkeypatch) -> None:
    """The old RSSI-only device is removed after the sensor moves to the hub."""
    device_registry = Mock()
    device_registry.async_get_device.return_value = SimpleNamespace(
        id="legacy-gateway-device"
    )
    monkeypatch.setattr(
        "custom_components.inlite.dr.async_get",
        lambda hass: device_registry,
    )

    _remove_legacy_gateway_device(object(), "garden-1")

    device_registry.async_get_device.assert_called_once_with(
        identifiers={("inlite", "garden-1_bluetooth_gateway")}
    )
    device_registry.async_remove_device.assert_called_once_with(
        "legacy-gateway-device"
    )


def test_legacy_gateway_cleanup_is_idempotent(monkeypatch) -> None:
    """Setup succeeds when the obsolete gateway device is already absent."""
    device_registry = Mock()
    device_registry.async_get_device.return_value = None
    monkeypatch.setattr(
        "custom_components.inlite.dr.async_get",
        lambda hass: device_registry,
    )

    _remove_legacy_gateway_device(object(), "garden-1")

    device_registry.async_remove_device.assert_not_called()
