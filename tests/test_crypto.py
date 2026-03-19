"""Tests for inlite_ble crypto module."""

from inlite_ble.crypto import CsrMeshCrypto


class TestCsrMeshCrypto:
    """Tests for CsrMeshCrypto."""

    def test_passphrase_required(self) -> None:
        """Passphrase must be provided (no default)."""
        import inspect
        sig = inspect.signature(CsrMeshCrypto.__init__)
        param = sig.parameters["passphrase"]
        assert param.default is inspect.Parameter.empty

    def test_key_derivation_deterministic(self) -> None:
        """Same passphrase should produce the same key."""
        c1 = CsrMeshCrypto("test123")
        c2 = CsrMeshCrypto("test123")
        assert c1._enc_key == c2._enc_key

    def test_different_passphrases_different_keys(self) -> None:
        c1 = CsrMeshCrypto("password_a")
        c2 = CsrMeshCrypto("password_b")
        assert c1._enc_key != c2._enc_key

    def test_key_is_16_bytes(self) -> None:
        c = CsrMeshCrypto("test")
        assert len(c._enc_key) == 16

    def test_controller_address_in_range(self) -> None:
        """Controller address should be in [0x8000, 0xFFFD]."""
        for _ in range(50):
            c = CsrMeshCrypto("test")
            assert 0x8000 <= c.controller_address <= 0xFFFD

    def test_encrypt_decrypt_roundtrip(self) -> None:
        """Encrypting then decrypting should return the original data."""
        crypto = CsrMeshCrypto("roundtrip_test")
        dest_id = 0x1234
        pkt_type = 0x71
        data = b"\x01\x02\x03"

        packet = crypto.encrypt_packet(dest_id, pkt_type, data)
        result = crypto.decrypt_packet(packet)

        assert result is not None
        assert result["dest_id"] == dest_id
        assert result["pkt_type"] == pkt_type
        assert bytes(result["data"]) == data

    def test_decrypt_invalid_packet_returns_none(self) -> None:
        crypto = CsrMeshCrypto("test")
        assert crypto.decrypt_packet(b"\x00" * 5) is None

    def test_decrypt_bad_checksum_returns_none(self) -> None:
        crypto = CsrMeshCrypto("test")
        packet = crypto.encrypt_packet(0x0001, 0x71, b"\x01")
        # Corrupt one byte of the checksum
        corrupted = bytearray(packet)
        corrupted[-5] ^= 0xFF
        assert crypto.decrypt_packet(bytes(corrupted)) is None

    def test_sequence_number_increments(self) -> None:
        crypto = CsrMeshCrypto("seq_test")
        p1 = crypto.encrypt_packet(1, 0x71, b"")
        p2 = crypto.encrypt_packet(1, 0x71, b"")
        # First 3 bytes are seq number — they should differ
        assert p1[:3] != p2[:3]

    def test_uses_secrets_not_random(self) -> None:
        """Verify we use the secrets module (no 'random' import)."""
        import inlite_ble.crypto as mod
        import inspect
        source = inspect.getsource(mod)
        assert "import secrets" in source
        assert "import random" not in source
