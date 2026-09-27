"""Tests for Bluetooth config-flow entry association."""

from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.inlite.config_flow import InliteConfigFlow  # noqa: E402
from custom_components.inlite.const import CONF_BLE_ADDRESS  # noqa: E402


class FlowAborted(Exception):
    """Signal the point where Home Assistant aborts a duplicate flow."""


@pytest.mark.asyncio
async def test_bluetooth_discovery_associates_existing_garden_entry() -> None:
    """Rediscovery updates the transport address through the existing entry."""
    flow = object.__new__(InliteConfigFlow)
    entry = SimpleNamespace(unique_id="garden-id")
    unique_ids: list[str] = []
    captured_updates: dict[str, str] | None = None

    flow._async_current_entries = lambda: [entry]

    async def set_unique_id(unique_id: str) -> None:
        unique_ids.append(unique_id)

    flow.async_set_unique_id = set_unique_id

    def capture_abort(*, updates: dict[str, str] | None = None) -> None:
        nonlocal captured_updates
        captured_updates = updates
        raise FlowAborted

    flow._abort_if_unique_id_configured = capture_abort

    with pytest.raises(FlowAborted):
        await flow.async_step_bluetooth(SimpleNamespace(address="AA:BB"))

    assert unique_ids == ["garden-id"]
    assert captured_updates == {CONF_BLE_ADDRESS: "AA:BB"}
