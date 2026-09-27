"""Tests for inlite_ble hub module — ZoneState and notification safety."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from inlite_ble.hub import InliteHub, ZoneState
from inlite_ble.protocol import OPCODE_GET_INFO_DEVICES, OPCODE_OOB_ALL_OUTLETS


def run_async(coroutine):
    """Run a coroutine without changing pytest's process-wide loop policy."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()


class TestZoneState:
    """Tests for ZoneState."""

    def test_is_on_when_state_set(self) -> None:
        zs = ZoneState(output_id=0, output_state=0x01)
        assert zs.is_on is True

    def test_is_off_when_state_clear(self) -> None:
        zs = ZoneState(output_id=0, output_state=0x00)
        assert zs.is_on is False

    def test_is_off_in_auto_mode_when_state_clear(self) -> None:
        """Auto/dusk-to-dawn mode (0x01) with the output currently off.

        Regression test: the physical button can leave output_mode at
        0x01 (auto) while output_state correctly drops to 0 — is_on must
        follow output_state, not the mode bit.
        """
        zs = ZoneState(output_id=0, output_mode=0x01, output_state=0x00)
        assert zs.is_on is False

    def test_is_on_in_auto_mode_when_state_set(self) -> None:
        zs = ZoneState(output_id=0, output_mode=0x01, output_state=0x01)
        assert zs.is_on is True

    def test_is_on_with_other_state_bits(self) -> None:
        zs = ZoneState(output_id=0, output_state=0x03)
        assert zs.is_on is True

    def test_repr(self) -> None:
        zs = ZoneState(output_id=1, output_mode=0x01, output_state=0x10)
        r = repr(zs)
        assert "id=1" in r
        assert "ON" in r


class TestInliteHub:
    """Tests for InliteHub initialization and properties."""

    def test_passphrase_required(self) -> None:
        hub = InliteHub(device_id=0x1234, passphrase="test_pass")
        assert hub.device_id == 0x1234

    def test_not_connected_initially(self) -> None:
        hub = InliteHub(device_id=1, passphrase="test")
        assert hub.is_connected is False

    def test_zone_states_empty_initially(self) -> None:
        hub = InliteHub(device_id=1, passphrase="test")
        assert hub.zone_states == {}

    def test_disconnect_calls_client_even_when_reported_disconnected(self) -> None:
        """Shutdown still asks a remote proxy to release the hub connection."""
        hub = InliteHub(device_id=1, passphrase="test")
        client = SimpleNamespace(is_connected=False, disconnect=AsyncMock())
        hub._client = client

        run_async(hub.disconnect())

        client.disconnect.assert_awaited_once_with()
        assert hub._client is None

    def test_loop_stored_on_connect(self) -> None:
        """Verify _loop is set during connect (needed for thread-safe callbacks)."""
        hub = InliteHub(device_id=1, passphrase="test")
        assert hub._loop is None

    def test_notification_uses_call_soon_threadsafe(self) -> None:
        """Verify the notification handler references call_soon_threadsafe."""
        import inspect
        source = inspect.getsource(InliteHub._on_notification)
        assert "call_soon_threadsafe" in source

    def test_scheduled_off_oob_update_reports_zone_off(self) -> None:
        """A timer update can turn the output off without changing auto mode."""
        updates: list[bool] = []
        hub = InliteHub(
            device_id=1,
            passphrase="test",
            on_state_update=lambda: updates.append(True),
        )
        hub._zone_states[0] = ZoneState(
            output_id=0,
            output_mode=0x01,
            output_state=0x01,
        )
        payload = bytes(
            [
                0x03,
                OPCODE_OOB_ALL_OUTLETS & 0xFF,
                (OPCODE_OOB_ALL_OUTLETS >> 8) & 0xFF,
                0x00,  # output ID
                0x01,  # output mode remains auto/on
                0x00,  # actual output state is off
                0x00,  # RTC timer
            ]
        )

        hub._parse_oob_broadcast(payload)

        state = hub.zone_states[0]
        assert state.output_mode == 0x01
        assert state.output_state == 0x00
        assert state.is_on is False
        assert updates == [True]

    def test_scheduled_off_poll_reports_zone_off(self) -> None:
        """Polling uses actual output state when auto mode remains enabled."""
        hub = InliteHub(device_id=1, passphrase="test")
        response = bytes(
            [
                0x00,
                0x00,  # stream offset
                0x02,  # response command type
                OPCODE_GET_INFO_DEVICES & 0xFF,
                (OPCODE_GET_INFO_DEVICES >> 8) & 0xFF,
                0x00,  # vendor ID
                0x00,  # product ID
                0x00,  # firmware
                0x00,  # status
                0x01,  # number of zones
                0x00,  # output ID
                0x00,  # output type
                0x00,  # capability mask
                0x01,  # output mode remains auto/on
                0x00,  # dusk-to-dawn setting 1
                0x00,  # dusk-to-dawn setting 2
                0x00,  # actual output state is off
            ]
        )

        async def scheduled_off_response(*args, **kwargs) -> bytes:
            return response

        hub._send_acknowledged_command = scheduled_off_response

        states = run_async(hub.query_zone_states())

        assert states[0].output_mode == 0x01
        assert states[0].output_state == 0x00
        assert states[0].is_on is False

    def test_successful_commands_update_cached_output_state(self) -> None:
        """Optimistic command state follows the field used by is_on."""
        hub = InliteHub(device_id=1, passphrase="test")
        hub._zone_states[0] = ZoneState(
            output_id=0,
            output_mode=0x01,
            output_state=0x01,
        )

        async def successful_command(*args, **kwargs) -> bool:
            return True

        hub._send_command = successful_command

        assert run_async(hub.set_outlet_mode(0, False)) is True
        assert hub.zone_states[0].is_on is False
        assert hub.zone_states[0].output_state == 0x00

        assert run_async(hub.set_outlet_mode(0, True)) is True
        assert hub.zone_states[0].is_on is True
        assert hub.zone_states[0].output_state != 0x00
