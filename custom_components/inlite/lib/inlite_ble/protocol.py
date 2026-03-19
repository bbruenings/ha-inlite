"""Protocol constants and command builders for in-lite mesh."""

from __future__ import annotations

# Packet types (block streaming layer)
PKT_BLOCK_FLUSH = 0x70     # 112
PKT_BLOCK_DATA = 0x71      # 113
PKT_BLOCK_ACK = 0x72       # 114
PKT_BLOCK_DATA_BLK = 0x73  # 115
PKT_BLOCK_STREAM = 0x74    # 116 — hub response to acknowledged commands

# Opcodes
OPCODE_DISCOVER = 0x000C
OPCODE_GET_INFO_DEVICES = 0x0005
OPCODE_SET_OUTLET_MODE = 0x1007   # 4103
OPCODE_OOB_ALL_OUTLETS = 0x0021   # broadcast after state changes

# Output states
OUTPUT_OFF = 0x00
OUTPUT_ON_AUTO = 0x01       # dusk-to-dawn mode
OUTPUT_ON_MANUAL = 0x03     # forced on

# GATT UUIDs
SERVICE_UUID = "0000fef1-0000-1000-8000-00805f9b34fb"
# The "MTL Complete CP" characteristic — bidirectional (write + notify)
CHAR_WRITE_UUID = "c4edc000-9daf-11e3-8004-00025b000b00"
# The "MTL Continuation CP" characteristic — bidirectional (write + notify)
CHAR_CONTINUATION_UUID = "c4edc000-9daf-11e3-8003-00025b000b00"


def build_outlet_mode_data(output_id: int, on: bool) -> bytes:
    """Build SET_OUTLET_MODE payload: [outputId, modeByte, modeMaskByte].

    When on=True:  modeByte=0x01 (bit 0 = on), modeMask=0x01
    When on=False: modeByte=0x00,               modeMask=0x01
    """
    mode_byte = 0x01 if on else 0x00
    mode_mask = 0x01  # only the 'on' bit is being changed
    return bytes([output_id, mode_byte, mode_mask])


def build_block_data_payload(opcode: int, command_data: bytes) -> bytes:
    """Build BLK_DATA inner payload: [offset_lo, offset_hi, cmd_type=1, opcode_lo, opcode_hi, data...]."""
    return bytes([
        0x00, 0x00,                     # offset = 0 (start of stream)
        0x01,                           # cmd_type = 1 (standard command)
        opcode & 0xFF, (opcode >> 8) & 0xFF,
    ]) + command_data


def build_flush_payload(byte_count: int = 0) -> bytes:
    """Build BLK_FLUSH payload."""
    return bytes([byte_count & 0xFF, (byte_count >> 8) & 0xFF])


def build_ack_payload(byte_count: int, end: bool = False) -> bytes:
    """Build BLK_ACK payload."""
    result = bytes([byte_count & 0xFF, (byte_count >> 8) & 0xFF])
    if end:
        result += b'\xef'
    return result


def build_discovery_payload() -> bytes:
    """Build BLK_DATA_BLK discovery packet."""
    return bytes([0x01, OPCODE_DISCOVER & 0xFF, (OPCODE_DISCOVER >> 8) & 0xFF])
