"""Tests for integration setup and config-entry migration."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("homeassistant")

from custom_components.inlite import async_migrate_entry  # noqa: E402
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
