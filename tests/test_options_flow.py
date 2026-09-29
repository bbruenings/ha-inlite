"""Tests for integration options exposed to Home Assistant."""

from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

import voluptuous as vol  # noqa: E402

from custom_components.inlite.config_flow import InliteOptionsFlow  # noqa: E402
from custom_components.inlite.const import (  # noqa: E402
    CONF_IDLE_DISCONNECT,
    CONF_SCAN_INTERVAL,
    DEFAULT_IDLE_DISCONNECT_SECONDS,
    DEFAULT_SCAN_INTERVAL,
)


@pytest.mark.asyncio
async def test_connection_retention_defaults_to_disconnect_after_activity() -> None:
    """Connection retention defaults to the restart-safe value of zero."""
    flow = InliteOptionsFlow(SimpleNamespace(options={}))

    result = await flow.async_step_init()
    schema = result["data_schema"]

    assert schema(
        {
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_IDLE_DISCONNECT: DEFAULT_IDLE_DISCONNECT_SECONDS,
        }
    )[CONF_IDLE_DISCONNECT] == 0

    with pytest.raises(vol.Invalid):
        schema(
            {
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                CONF_IDLE_DISCONNECT: -1,
            }
        )
