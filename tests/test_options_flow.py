"""Tests for integration options exposed to Home Assistant."""

from types import SimpleNamespace

import pytest
import voluptuous as vol

pytest.importorskip("homeassistant")

from custom_components.inlite.config_flow import InliteOptionsFlow  # noqa: E402
from custom_components.inlite.const import (  # noqa: E402
    CONF_IDLE_DISCONNECT,
    CONF_SCAN_INTERVAL,
    CONF_STARTUP_DELAY,
    DEFAULT_IDLE_DISCONNECT_SECONDS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STARTUP_DELAY_SECONDS,
    MAX_STARTUP_DELAY_SECONDS,
)


@pytest.mark.asyncio
async def test_startup_discovery_timeout_defaults_and_validates() -> None:
    """The startup discovery timeout is a normal bounded numeric option."""
    flow = InliteOptionsFlow(SimpleNamespace(options={}))

    result = await flow.async_step_init()
    schema = result["data_schema"]

    assert schema({
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        CONF_IDLE_DISCONNECT: DEFAULT_IDLE_DISCONNECT_SECONDS,
        CONF_STARTUP_DELAY: DEFAULT_STARTUP_DELAY_SECONDS,
    })[CONF_STARTUP_DELAY] == DEFAULT_STARTUP_DELAY_SECONDS

    assert schema({
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        CONF_IDLE_DISCONNECT: DEFAULT_IDLE_DISCONNECT_SECONDS,
        CONF_STARTUP_DELAY: MAX_STARTUP_DELAY_SECONDS,
    })[CONF_STARTUP_DELAY] == MAX_STARTUP_DELAY_SECONDS

    with pytest.raises(vol.Invalid):
        schema({
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_IDLE_DISCONNECT: DEFAULT_IDLE_DISCONNECT_SECONDS,
            CONF_STARTUP_DELAY: MAX_STARTUP_DELAY_SECONDS + 1,
        })
