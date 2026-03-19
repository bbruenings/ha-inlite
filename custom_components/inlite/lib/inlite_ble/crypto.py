"""CSRmesh cryptography: key derivation, AES-OFB encryption, HMAC-SHA256 checksums."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from Cryptodome.Cipher import AES


class CsrMeshCrypto:
    """CSRmesh encryption/decryption engine.

    Handles packet encryption, decryption, checksum computation,
    and sequence number management for the in-lite BLE mesh protocol.
    """

    def __init__(self, passphrase: str) -> None:
        self._tx_seq_nr = secrets.randbelow(0xFFFFFF)
        self._controller_address = 0x8000 + secrets.randbelow(0xFFFD - 0x8000)
        self._enc_key = self._derive_key(passphrase)

    @property
    def controller_address(self) -> int:
        return self._controller_address

    @staticmethod
    def _derive_key(passphrase: str) -> bytes:
        """Derive 16-byte AES key: SHA-256(UTF-8(passphrase + '\\x00MCP')), reversed."""
        raw = (passphrase + "\x00MCP").encode("utf-8")
        digest = hashlib.sha256(raw).digest()
        return bytes(digest[len(digest) - 1 - i] for i in range(16))

    @staticmethod
    def _generate_iv(seq_nr: int, src_id: int) -> bytes:
        iv = bytearray(16)
        iv[0] = seq_nr & 0xFF
        iv[1] = (seq_nr >> 8) & 0xFF
        iv[2] = (seq_nr >> 16) & 0xFF
        iv[4] = src_id & 0xFF
        iv[5] = (src_id >> 8) & 0xFF
        return bytes(iv)

    def _get_checksum(self, seq_nr: int, src_id: int, encrypted: bytes) -> bytes:
        buf = bytearray(8)  # 8 zero bytes
        buf.append(seq_nr & 0xFF)
        buf.append((seq_nr >> 8) & 0xFF)
        buf.append((seq_nr >> 16) & 0xFF)
        buf.append(src_id & 0xFF)
        buf.append((src_id >> 8) & 0xFF)
        buf.extend(encrypted)
        h = hmac.new(self._enc_key, bytes(buf), hashlib.sha256).digest()
        return bytes(h[len(h) - 1 - i] for i in range(8))

    def encrypt_packet(  # noqa: D417
        self, dest_id: int, pkt_type: int, data: bytes, ttl: int = 5
    ) -> bytes:
        """Encrypt and build a CSRmesh packet ready for BLE transmission."""
        self._tx_seq_nr = (self._tx_seq_nr + 1) % 0x1000000
        seq = self._tx_seq_nr
        src = self._controller_address

        # Build header: seq(3 LE) + src(2 LE)
        header = bytearray()
        header.append(seq & 0xFF)
        header.append((seq >> 8) & 0xFF)
        header.append((seq >> 16) & 0xFF)
        header.append(src & 0xFF)
        header.append((src >> 8) & 0xFF)

        # Build plaintext: dest(2 LE) + pkt_type(1) + data
        plaintext = bytearray()
        plaintext.append(dest_id & 0xFF)
        plaintext.append((dest_id >> 8) & 0xFF)
        plaintext.append(pkt_type)
        plaintext.extend(data)

        # Encrypt with AES-OFB
        iv = self._generate_iv(seq, src)
        cipher = AES.new(self._enc_key, AES.MODE_OFB, iv=iv)
        encrypted = cipher.encrypt(bytes(plaintext))

        # Build checksum
        checksum = self._get_checksum(seq, src, encrypted)

        # Assemble: header + encrypted + checksum + ttl
        packet = bytearray(header)
        packet.extend(encrypted)
        packet.extend(checksum)
        packet.append(ttl)
        return bytes(packet)

    def decrypt_packet(self, raw: bytes) -> dict | None:
        """Decrypt a CSRmesh packet. Returns dict or None if checksum fails."""
        if len(raw) < 14:
            return None

        seq = raw[0] | (raw[1] << 8) | (raw[2] << 16)
        src = raw[3] | (raw[4] << 8)
        ttl = raw[-1]
        checksum = raw[-9:-1]
        encrypted = raw[5:-9]

        if len(encrypted) < 3:
            return None

        expected = self._get_checksum(seq, src, encrypted)
        if checksum != expected:
            return None

        iv = self._generate_iv(seq, src)
        cipher = AES.new(self._enc_key, AES.MODE_OFB, iv=iv)
        dec = cipher.decrypt(encrypted)

        return {
            "seq_nr": seq,
            "src_id": src,
            "dest_id": dec[0] | (dec[1] << 8),
            "pkt_type": dec[2],
            "ttl": ttl,
            "data": dec[3:],
        }
