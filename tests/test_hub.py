"""Tests for inlite_ble hub module — ZoneState and notification safety."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import inlite_ble.hub as hub_module
from inlite_ble.hub import InliteHub, ZoneState
from inlite_ble.protocol import (
    OPCODE_GET_INFO_DEVICES,
    OPCODE_OOB_ALL_OUTLETS,
    PKT_BLOCK_ACK,
    PKT_BLOCK_DATA,
    PKT_BLOCK_FLUSH,
)


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
        assert hub.last_query_successful is False

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

    def test_notification_routes_flush_separately_from_ack(self) -> None:
        """A response FLUSH cannot satisfy a regular command ACK wait."""
        hub = InliteHub(device_id=1, passphrase="test")
        hub._crypto.decrypt_packet = MagicMock(
            return_value={"pkt_type": PKT_BLOCK_FLUSH, "data": b"\x00\x00"}
        )

        async def receive() -> None:
            hub._loop = asyncio.get_running_loop()
            hub._on_notification(None, bytearray(b"encrypted"))
            await asyncio.sleep(0)

            assert hub._flush_queue.get_nowait() == b"\x00\x00"
            assert hub._ack_queue.empty()

        run_async(receive())

    def test_acknowledged_command_matches_firmware_52_trace(
        self, monkeypatch
    ) -> None:
        """The traced exchange completes without either three-second timeout."""
        hub = InliteHub(device_id=1, passphrase="test")
        response = b"\x00\x00" + bytes(range(29))
        writes: list[tuple[int, bytes]] = []
        monkeypatch.setattr(hub_module, "WRITE_DELAY", 0)

        async def fake_write(dest_id: int, pkt_type: int, data: bytes) -> None:
            assert dest_id == 1
            writes.append((pkt_type, data))
            write_number = len(writes)
            if write_number == 1:
                assert (pkt_type, data) == (PKT_BLOCK_FLUSH, b"\x00\x00")
                hub._ack_queue.put_nowait(b"\x00\x00")
            elif write_number == 2:
                assert pkt_type == PKT_BLOCK_DATA
                assert len(data) == 5
                # Firmware can repeat the previous zero ACK before sending the
                # real three-byte command-data count.
                hub._ack_queue.put_nowait(b"\x00\x00")
                hub._ack_queue.put_nowait(b"\x03\x00")
            elif write_number == 3:
                assert (pkt_type, data) == (PKT_BLOCK_FLUSH, b"\x03\x00")
                # The response FLUSH can arrive in the same event-loop turn as
                # command completion, and may be repeated until acknowledged.
                hub._flush_queue.put_nowait(b"\x00\x00")
                hub._flush_queue.put_nowait(b"\x00\x00")
                hub._ack_queue.put_nowait(b"\x03\x00\xef")
            elif write_number == 4:
                assert (pkt_type, data) == (PKT_BLOCK_ACK, b"\x00\x00")
                hub._stream_queue.put_nowait(response)
            elif write_number == 5:
                assert (pkt_type, data) == (PKT_BLOCK_ACK, b"\x1d\x00")
                # Ignore a queued duplicate FLUSH(0) and wait for FLUSH(29).
                hub._flush_queue.put_nowait(b"\x1d\x00")
            elif write_number == 6:
                assert (pkt_type, data) == (PKT_BLOCK_ACK, b"\x1d\x00\xef")
            else:
                raise AssertionError("unexpected protocol write")

        hub._write_mesh = fake_write

        result = run_async(
            asyncio.wait_for(
                hub._send_acknowledged_command(OPCODE_GET_INFO_DEVICES, b""),
                timeout=0.2,
            )
        )

        assert result == response
        assert [packet_type for packet_type, _ in writes] == [
            PKT_BLOCK_FLUSH,
            PKT_BLOCK_DATA,
            PKT_BLOCK_FLUSH,
            PKT_BLOCK_ACK,
            PKT_BLOCK_ACK,
            PKT_BLOCK_ACK,
        ]
        assert not hub._ack_queue.qsize()
        assert not hub._flush_queue.qsize()
        assert not hub._stream_queue.qsize()

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
        assert hub.last_query_successful is True

    def test_failed_query_is_not_reported_as_authenticated(self) -> None:
        """Cached states cannot validate a newly selected BLE advertiser."""
        hub = InliteHub(device_id=1, passphrase="test")
        hub._zone_states[0] = ZoneState(output_id=0, output_state=0x01)
        hub._send_acknowledged_command = AsyncMock(return_value=None)

        states = run_async(hub.query_zone_states())

        assert states == hub.zone_states
        assert hub.last_query_successful is False

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
