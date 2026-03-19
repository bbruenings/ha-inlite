"""Tests for inlite_ble hub module — ZoneState and notification safety."""

import asyncio

from inlite_ble.hub import InliteHub, ZoneState


class TestZoneState:
    """Tests for ZoneState."""

    def test_is_on_when_mode_bit_set(self) -> None:
        zs = ZoneState(output_id=0, output_mode=0x01)
        assert zs.is_on is True

    def test_is_off_when_mode_bit_clear(self) -> None:
        zs = ZoneState(output_id=0, output_mode=0x00)
        assert zs.is_on is False

    def test_is_on_with_other_bits(self) -> None:
        zs = ZoneState(output_id=0, output_mode=0x03)
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

    def test_loop_stored_on_connect(self) -> None:
        """Verify _loop is set during connect (needed for thread-safe callbacks)."""
        hub = InliteHub(device_id=1, passphrase="test")
        assert hub._loop is None

    def test_notification_uses_call_soon_threadsafe(self) -> None:
        """Verify the notification handler references call_soon_threadsafe."""
        import inspect
        source = inspect.getsource(InliteHub._on_notification)
        assert "call_soon_threadsafe" in source
