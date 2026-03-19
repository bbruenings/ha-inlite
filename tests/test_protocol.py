"""Tests for inlite_ble protocol module."""

from inlite_ble.protocol import (
    build_ack_payload,
    build_block_data_payload,
    build_discovery_payload,
    build_flush_payload,
    build_outlet_mode_data,
    OPCODE_SET_OUTLET_MODE,
    OPCODE_DISCOVER,
)


class TestBuildOutletModeData:
    """Tests for build_outlet_mode_data."""

    def test_turn_on(self) -> None:
        result = build_outlet_mode_data(0, True)
        assert result == bytes([0x00, 0x01, 0x01])

    def test_turn_off(self) -> None:
        result = build_outlet_mode_data(0, False)
        assert result == bytes([0x00, 0x00, 0x01])

    def test_zone_id_preserved(self) -> None:
        result = build_outlet_mode_data(2, True)
        assert result[0] == 2

    def test_mode_mask_always_0x01(self) -> None:
        for on in (True, False):
            result = build_outlet_mode_data(0, on)
            assert result[2] == 0x01


class TestBuildBlockDataPayload:
    """Tests for build_block_data_payload."""

    def test_structure(self) -> None:
        result = build_block_data_payload(OPCODE_SET_OUTLET_MODE, b"\x00\x01\x01")
        # offset_lo, offset_hi, cmd_type=1, opcode_lo, opcode_hi, data...
        assert result[0] == 0x00  # offset lo
        assert result[1] == 0x00  # offset hi
        assert result[2] == 0x01  # cmd_type
        assert result[3] == OPCODE_SET_OUTLET_MODE & 0xFF
        assert result[4] == (OPCODE_SET_OUTLET_MODE >> 8) & 0xFF
        assert result[5:] == b"\x00\x01\x01"

    def test_empty_data(self) -> None:
        result = build_block_data_payload(0x0005, b"")
        assert len(result) == 5


class TestBuildFlushPayload:
    """Tests for build_flush_payload."""

    def test_zero(self) -> None:
        assert build_flush_payload(0) == bytes([0x00, 0x00])

    def test_nonzero(self) -> None:
        result = build_flush_payload(0x0105)
        assert result == bytes([0x05, 0x01])


class TestBuildAckPayload:
    """Tests for build_ack_payload."""

    def test_without_end(self) -> None:
        result = build_ack_payload(5, end=False)
        assert result == bytes([0x05, 0x00])

    def test_with_end(self) -> None:
        result = build_ack_payload(5, end=True)
        assert result == bytes([0x05, 0x00, 0xEF])


class TestBuildDiscoveryPayload:
    """Tests for build_discovery_payload."""

    def test_structure(self) -> None:
        result = build_discovery_payload()
        assert result[0] == 0x01
        assert result[1] == OPCODE_DISCOVER & 0xFF
        assert result[2] == (OPCODE_DISCOVER >> 8) & 0xFF
