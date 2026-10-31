"""InliteHub — BLE controller for in-lite SMART HUB transformers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from inlite_ble.crypto import CsrMeshCrypto
from inlite_ble.protocol import (
    SERVICE_UUID,
    CHAR_WRITE_UUID,
    CHAR_CONTINUATION_UUID,
    PKT_BLOCK_FLUSH,
    PKT_BLOCK_DATA,
    PKT_BLOCK_ACK,
    PKT_BLOCK_DATA_BLK,
    PKT_BLOCK_STREAM,
    OPCODE_SET_OUTLET_MODE,
    OPCODE_GET_INFO_DEVICES,
    OPCODE_OOB_ALL_OUTLETS,
    build_outlet_mode_data,
    build_block_data_payload,
    build_flush_payload,
    build_ack_payload,
    build_discovery_payload,
)

_LOGGER = logging.getLogger(__name__)

WRITE_DELAY = 0.06  # 60ms between BLE writes (matches app timing)
ACK_TIMEOUT = 2.0   # seconds to wait for hub ACK
STREAM_TIMEOUT = 3.0  # seconds to wait for STREAM response


class ZoneState:
    """Current state of a single light zone."""

    def __init__(
        self,
        output_id: int,
        output_type: int = 0,
        cap_mask: int = 0,
        output_mode: int = 0,
        dtd1: int = 0,
        dtd2: int = 0,
        output_state: int = 0,
    ) -> None:
        self.output_id = output_id
        self.output_type = output_type
        self.cap_mask = cap_mask
        self.output_mode = output_mode
        self.dtd1 = dtd1
        self.dtd2 = dtd2
        self.output_state = output_state

    @property
    def is_on(self) -> bool:
        return self.output_state != 0

    def __repr__(self) -> str:
        return "ZoneState(id=%d, %s, mode=0x%02X, state=0x%02X)" % (
            self.output_id,
            "ON" if self.is_on else "OFF",
            self.output_mode,
            self.output_state,
        )


class InliteHub:
    """Controls an in-lite SMART HUB via BLE mesh.

    The BLE device acts as a gateway to the CSRmesh network; the device_id
    is the mesh destination address for a specific transformer.

    Args:
        device_id: The hub's mesh device ID (from cloud API transformers[].deviceId)
        passphrase: The garden's network passphrase (from cloud API gardens[].password)
        ble_address: BLE device address or name (e.g., 'inlitebt' or a MAC/UUID)
        on_state_update: Optional callback invoked when OOB broadcast updates zone states.
    """

    def __init__(
        self,
        device_id: int,
        passphrase: str,
        ble_address: str = "inlitebt",
        on_state_update: Callable[[], None] | None = None,
    ) -> None:
        self._device_id = device_id
        self._crypto = CsrMeshCrypto(passphrase)
        self._ble_address = ble_address
        self._client: BleakClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ack_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._flush_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._stream_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._zone_states: dict[int, ZoneState] = {}
        self._last_query_successful = False
        self._notification_callback: Callable[[dict[str, Any]], None] | None = None
        self._on_state_update = on_state_update

    @property
    def device_id(self) -> int:
        return self._device_id

    @property
    def controller_address(self) -> int:
        return self._crypto.controller_address

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def zone_states(self) -> dict[int, ZoneState]:
        return self._zone_states

    @property
    def last_query_successful(self) -> bool:
        """Return whether the latest zone query had a valid mesh response."""
        return self._last_query_successful

    async def scan(self, timeout: float = 10.0) -> BLEDevice | None:
        """Scan for the in-lite hub by name or address."""
        _LOGGER.info("Scanning for %s...", self._ble_address)
        devices = await BleakScanner.discover(timeout=timeout)
        for d in devices:
            if (d.name and d.name.lower() == self._ble_address.lower()) or \
               str(d.address).lower() == self._ble_address.lower():
                _LOGGER.info("Found hub: %s (%s)", d.name, d.address)
                return d
        return None

    async def connect(
        self,
        device: BLEDevice | None = None,
        client: BleakClient | None = None,
    ) -> bool:
        """Connect to the hub and enable notifications.

        Args:
            device: BLEDevice to connect to (scans if None and no client given).
            client: Pre-established BleakClient (for HA integration). If given,
                    we use it directly and subscribe notifications.
        """
        # Store reference to the running event loop for thread-safe callbacks
        self._loop = asyncio.get_running_loop()

        if client is not None:
            self._client = client
        else:
            if device is None:
                device = await self.scan()
                if device is None:
                    _LOGGER.error("Hub not found")
                    return False
            self._client = BleakClient(device)
            await self._client.connect()

        if not self._client.is_connected:
            _LOGGER.error("Client not connected after setup")
            self._client = None
            return False

        _LOGGER.info("Connected")

        # Subscribe to notifications on both bidirectional characteristics
        await self._client.start_notify(CHAR_WRITE_UUID, self._on_notification)
        await self._client.start_notify(CHAR_CONTINUATION_UUID, self._on_notification)
        _LOGGER.info("Notifications enabled")

        return True

    async def disconnect(self) -> None:
        """Disconnect from the hub."""
        if self._client:
            try:
                # Disconnect unconditionally. During Home Assistant shutdown a
                # remote proxy can report is_connected=False before it has sent
                # the GATT disconnect to the hub.
                await self._client.disconnect()
            except Exception as err:
                _LOGGER.debug("Disconnect error (ignoring): %s", err)
            finally:
                self._client = None
                self._loop = None
                _LOGGER.info("Disconnected")

    def _on_notification(self, sender: Any, data: bytearray) -> None:
        """Handle incoming BLE notifications.

        Bleak calls this from a background thread, so we use
        call_soon_threadsafe to schedule event-loop work safely.
        """
        raw = bytes(data)
        decrypted = self._crypto.decrypt_packet(raw)
        if decrypted is None:
            return

        pkt_type = decrypted["pkt_type"]
        payload = decrypted["data"]

        loop = self._loop
        if loop is None or loop.is_closed():
            return

        if pkt_type == PKT_BLOCK_ACK:
            loop.call_soon_threadsafe(self._ack_queue.put_nowait, payload)
        elif pkt_type == PKT_BLOCK_FLUSH:
            loop.call_soon_threadsafe(self._flush_queue.put_nowait, payload)
        elif pkt_type == PKT_BLOCK_STREAM:
            loop.call_soon_threadsafe(self._stream_queue.put_nowait, payload)
        elif pkt_type == PKT_BLOCK_DATA_BLK:
            loop.call_soon_threadsafe(self._parse_oob_broadcast, payload)

        if self._notification_callback:
            loop.call_soon_threadsafe(self._notification_callback, decrypted)

    def _parse_oob_broadcast(self, payload: bytes) -> None:
        """Parse OOB_ALL_OUTLETS_MODE_UPDATE broadcast to update zone states."""
        if len(payload) < 3:
            return
        cmd_type = payload[0]
        opcode = payload[1] | (payload[2] << 8)
        if cmd_type != 0x03 or opcode != OPCODE_OOB_ALL_OUTLETS:
            return

        data = payload[3:]
        i = 0
        changed = False
        while i + 3 < len(data):
            outlet_id = data[i]
            output_mode = data[i + 1]
            output_state = data[i + 2]
            # data[i + 3] = rtcTimer
            if outlet_id in self._zone_states:
                old = self._zone_states[outlet_id]
                if old.output_mode != output_mode or old.output_state != output_state:
                    changed = True
                old.output_mode = output_mode
                old.output_state = output_state
            else:
                self._zone_states[outlet_id] = ZoneState(
                    output_id=outlet_id,
                    output_mode=output_mode,
                    output_state=output_state,
                )
                changed = True
            _LOGGER.debug("OOB update: zone %d mode=0x%02X state=0x%02X",
                          outlet_id, output_mode, output_state)
            i += 4

        if changed and self._on_state_update is not None:
            self._on_state_update()

    async def _write(self, packet: bytes) -> None:
        """Write an encrypted packet to the hub."""
        if not self._client or not self._client.is_connected:
            raise ConnectionError("Not connected to hub")
        await self._client.write_gatt_char(CHAR_WRITE_UUID, packet, response=True)

    async def _write_mesh(self, dest_id: int, pkt_type: int, data: bytes) -> None:
        """Encrypt and write a mesh packet."""
        packet = self._crypto.encrypt_packet(dest_id, pkt_type, data)
        await self._write(packet)

    @staticmethod
    def _packet_count(payload: bytes) -> int | None:
        """Return a block packet's count, when it carries one."""
        if len(payload) < 2:
            return None
        return int.from_bytes(payload[:2], "little")

    @staticmethod
    def _is_completion_ack(payload: bytes) -> bool:
        """Return whether an ACK carries the protocol completion marker."""
        return len(payload) >= 3 and payload[-1] == 0xEF

    @classmethod
    def _is_start_ack(cls, payload: bytes) -> bool:
        """Match a regular ACK for the initial zero-count FLUSH."""
        count = cls._packet_count(payload)
        return not cls._is_completion_ack(payload) and count in (None, 0)

    @classmethod
    def _is_data_ack(cls, payload: bytes) -> bool:
        """Match a regular ACK that advances past the command's data."""
        count = cls._packet_count(payload)
        return not cls._is_completion_ack(payload) and (count is None or count > 0)

    @classmethod
    def _matches_count(cls, expected: int) -> Callable[[bytes], bool]:
        """Return a packet matcher for an exact little-endian count."""
        return lambda payload: cls._packet_count(payload) == expected

    @staticmethod
    def _block_data_count(payload: bytes) -> int:
        """Return cumulative data bytes, excluding the two-byte offset header."""
        if len(payload) < 2:
            return 0
        return int.from_bytes(payload[:2], "little") + len(payload) - 2

    @staticmethod
    def _drain_queue(queue: asyncio.Queue[bytes]) -> None:
        """Discard packets left by a completed protocol exchange."""
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return

    def _begin_exchange(self) -> None:
        """Start with empty protocol queues while retaining OOB notifications."""
        self._drain_queue(self._ack_queue)
        self._drain_queue(self._flush_queue)
        self._drain_queue(self._stream_queue)

    async def _wait_packet(
        self,
        queue: asyncio.Queue[bytes],
        timeout: float,
        packet_name: str,
        matcher: Callable[[bytes], bool] | None = None,
    ) -> bytes:
        """Wait for the next packet matching the active protocol phase."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                _LOGGER.warning("%s timeout after %.1fs", packet_name, timeout)
                return b""
            try:
                payload = await asyncio.wait_for(queue.get(), remaining)
            except asyncio.TimeoutError:
                _LOGGER.warning("%s timeout after %.1fs", packet_name, timeout)
                return b""
            if matcher is None or matcher(payload):
                return payload
            _LOGGER.debug(
                "Ignoring %s with count=%s while waiting for matching phase",
                packet_name,
                self._packet_count(payload),
            )

    async def _wait_ack(
        self,
        timeout: float = ACK_TIMEOUT,
        matcher: Callable[[bytes], bool] | None = None,
        phase: str = "ACK",
    ) -> bytes:
        """Wait for an ACK matching the current command phase."""
        return await self._wait_packet(
            self._ack_queue, timeout, phase, matcher
        )

    async def _wait_flush(
        self,
        timeout: float = STREAM_TIMEOUT,
        matcher: Callable[[bytes], bool] | None = None,
        phase: str = "FLUSH",
    ) -> bytes:
        """Wait for a hub FLUSH packet matching the response phase."""
        return await self._wait_packet(
            self._flush_queue, timeout, phase, matcher
        )

    async def _wait_stream(self, timeout: float = STREAM_TIMEOUT) -> bytes:
        """Wait for a hub STREAM response."""
        return await self._wait_packet(
            self._stream_queue, timeout, "STREAM"
        )

    async def _send_command(
        self, opcode: int, command_data: bytes, acknowledged: bool = True
    ) -> bool:
        """Send a command using the block streaming protocol.

        Flow:
        1. BLK_FLUSH(0x0000) → wait ACK
        2. BLK_DATA(offset, opcode, data) → wait ACK with byte count
        3. BLK_FLUSH(byte_count) → wait ACK with 'ef' suffix (done)
        4. ACK the hub's response
        """
        dest = self._device_id
        self._begin_exchange()

        # Step 1: Flush (start)
        await self._write_mesh(dest, PKT_BLOCK_FLUSH, build_flush_payload(0))
        await self._wait_ack(matcher=self._is_start_ack, phase="start ACK")

        # Step 2: Send command data
        block_data = build_block_data_payload(opcode, command_data)
        await self._write_mesh(dest, PKT_BLOCK_DATA, block_data)
        ack = await self._wait_ack(matcher=self._is_data_ack, phase="data ACK")

        # Parse acked byte count
        if len(ack) >= 2:
            acked_bytes = ack[0] | (ack[1] << 8)
        else:
            acked_bytes = self._block_data_count(block_data)

        # Step 3: Flush (end)
        await self._write_mesh(dest, PKT_BLOCK_FLUSH, build_flush_payload(acked_bytes))
        ack = await self._wait_ack(
            matcher=self._is_completion_ack, phase="completion ACK"
        )

        # Check for completion marker (0xef suffix)
        success = len(ack) >= 3 and ack[-1] == 0xEF
        if success:
            _LOGGER.info("Command 0x%04X sent successfully", opcode)
        else:
            _LOGGER.warning("Command 0x%04X: no completion ACK", opcode)

        # ACK the hub's response flush
        await asyncio.sleep(WRITE_DELAY)
        await self._write_mesh(dest, PKT_BLOCK_ACK, build_ack_payload(0))

        return success

    async def _send_acknowledged_command(
        self, opcode: int, command_data: bytes
    ) -> bytes | None:
        """Send a command that expects a STREAM response (e.g., GET_INFO_DEVICES).

        Flow:
        1. Send command via block streaming (same as _send_command)
        2. Hub responds: FLUSH(0) → STREAM(data) → FLUSH(n)
        3. We ACK each step and return the STREAM data

        Returns:
            The STREAM payload bytes, or None on failure.
        """
        dest = self._device_id
        self._begin_exchange()

        # Step 1: Send command via block streaming
        await self._write_mesh(dest, PKT_BLOCK_FLUSH, build_flush_payload(0))
        await self._wait_ack(matcher=self._is_start_ack, phase="start ACK")

        block_data = build_block_data_payload(opcode, command_data)
        await self._write_mesh(dest, PKT_BLOCK_DATA, block_data)
        ack = await self._wait_ack(matcher=self._is_data_ack, phase="data ACK")

        if len(ack) >= 2:
            acked_bytes = ack[0] | (ack[1] << 8)
        else:
            acked_bytes = self._block_data_count(block_data)

        await self._write_mesh(dest, PKT_BLOCK_FLUSH, build_flush_payload(acked_bytes))
        ack = await self._wait_ack(
            matcher=self._is_completion_ack, phase="completion ACK"
        )

        success = len(ack) >= 3 and ack[-1] == 0xEF
        if not success:
            _LOGGER.warning("Acknowledged command 0x%04X: no completion ACK", opcode)
            return None

        # Step 2: Hub sends FLUSH(0) — ACK it
        flush = await self._wait_flush(
            matcher=self._matches_count(0), phase="response-start FLUSH"
        )
        if not flush:
            return None
        # ACK the hub's flush with 0
        await asyncio.sleep(WRITE_DELAY)
        await self._write_mesh(dest, PKT_BLOCK_ACK, build_ack_payload(0))

        # Step 3: Hub sends STREAM(data) — collect and ACK
        stream_data = await self._wait_stream()
        if not stream_data:
            _LOGGER.warning("No STREAM data for command 0x%04X", opcode)
            return None

        # The count excludes the STREAM's two-byte offset header. For a
        # 31-byte offset-zero response the hub therefore expects ACK(29).
        stream_bytes = self._block_data_count(stream_data)

        # ACK the stream data
        await asyncio.sleep(WRITE_DELAY)
        await self._write_mesh(dest, PKT_BLOCK_ACK, build_ack_payload(stream_bytes))

        # Step 4: Hub sends FLUSH(n) — ACK with completion marker
        flush = await self._wait_flush(
            matcher=self._matches_count(stream_bytes),
            phase="response-final FLUSH",
        )
        if not flush:
            return None
        flush_count = self._packet_count(flush)
        assert flush_count is not None
        await asyncio.sleep(WRITE_DELAY)
        await self._write_mesh(
            dest, PKT_BLOCK_ACK,
            build_ack_payload(flush_count, end=True)
        )

        _LOGGER.info("Acknowledged command 0x%04X: got %d bytes", opcode, len(stream_data))
        return bytes(stream_data)

    async def query_zone_states(self) -> dict[int, ZoneState]:
        """Query all zone states from the hub using GET_INFO_DEVICES.

        Returns:
            Dict mapping output_id → ZoneState for each zone.
        """
        self._last_query_successful = False
        stream = await self._send_acknowledged_command(
            OPCODE_GET_INFO_DEVICES, b""
        )
        if stream is None:
            _LOGGER.warning("Failed to query zone states")
            return self._zone_states

        # Parse STREAM response:
        # [offset(2), cmd_type=0x02, opcode(2), vendorId, productId, firmware, status,
        #  numZones, then per zone(7 bytes): outputId, outputType, capMask, outputMode,
        #  dtd1, dtd2, outputState]
        if len(stream) < 10:
            _LOGGER.warning("STREAM too short: %d bytes", len(stream))
            return self._zone_states

        offset = stream[0] | (stream[1] << 8)
        cmd_type = stream[2]
        opcode = stream[3] | (stream[4] << 8)

        if cmd_type != 0x02 or opcode != OPCODE_GET_INFO_DEVICES:
            _LOGGER.warning("Unexpected opcode in STREAM: 0x%04X", opcode)
            return self._zone_states

        # A matching decrypted response proves this advertiser belongs to the
        # configured garden, so the coordinator may trust its BLE address.
        self._last_query_successful = True

        # vendor_id = stream[5]
        # product_id = stream[6]
        # firmware = stream[7]
        # status = stream[8]
        num_zones = stream[9]

        zones: dict[int, ZoneState] = {}
        zone_start = 10
        for i in range(num_zones):
            pos = zone_start + i * 7
            if pos + 7 > len(stream):
                break
            zs = ZoneState(
                output_id=stream[pos],
                output_type=stream[pos + 1],
                cap_mask=stream[pos + 2],
                output_mode=stream[pos + 3],
                dtd1=stream[pos + 4],
                dtd2=stream[pos + 5],
                output_state=stream[pos + 6],
            )
            zones[zs.output_id] = zs
            _LOGGER.debug("Zone %d: %s", zs.output_id, zs)

        self._zone_states = zones
        return zones

    async def set_outlet_mode(self, output_id: int, on: bool) -> bool:
        """Turn a light zone on or off.

        Args:
            output_id: Zone number (0=zone 1, 1=zone 2, 2=zone 3)
            on: True to turn on, False to turn off
        """
        data = build_outlet_mode_data(output_id, on)
        _LOGGER.info(
            "Setting zone %d %s (device 0x%04X)",
            output_id, "ON" if on else "OFF", self._device_id,
        )
        success = await self._send_command(OPCODE_SET_OUTLET_MODE, data)

        # Update local state immediately on success
        if success and output_id in self._zone_states:
            zs = self._zone_states[output_id]
            if on:
                zs.output_mode = zs.output_mode | 0x01
                zs.output_state = zs.output_state | 0x01
            else:
                zs.output_mode = zs.output_mode & ~0x01
                zs.output_state = 0

        return success

    async def turn_on(self, output_id: int = 0) -> bool:
        """Turn on a light zone."""
        return await self.set_outlet_mode(output_id, True)

    async def turn_off(self, output_id: int = 0) -> bool:
        """Turn off a light zone."""
        return await self.set_outlet_mode(output_id, False)

    async def send_discovery(self) -> None:
        """Send a discovery broadcast (also serves as keepalive)."""
        data = build_discovery_payload()
        await self._write_mesh(0x0000, PKT_BLOCK_DATA_BLK, data)
