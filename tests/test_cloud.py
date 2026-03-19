"""Tests for inlite_ble cloud module."""

from inlite_ble.cloud import Garden, Transformer, LightZone


class TestLightZone:
    """Tests for LightZone data model."""

    def test_basic_creation(self) -> None:
        lz = LightZone({"outputId": 2, "name": "Front", "outputMode": 1})
        assert lz.output_id == 2
        assert lz.name == "Front"
        assert lz.is_on is True

    def test_default_values(self) -> None:
        lz = LightZone({})
        assert lz.output_id == 0
        assert lz.name == "Zone 1"
        assert lz.is_on is False

    def test_repr(self) -> None:
        lz = LightZone({"outputId": 0, "name": "Test", "outputMode": 0})
        assert "OFF" in repr(lz)


class TestTransformer:
    """Tests for Transformer data model."""

    def test_basic_creation(self) -> None:
        t = Transformer({
            "_id": "abc",
            "deviceId": 0x1234,
            "name": "Hub 1",
            "lightZones": [{"outputId": 0, "name": "Zone 1"}],
        })
        assert t.device_id == 0x1234
        assert len(t.light_zones) == 1

    def test_default_name(self) -> None:
        t = Transformer({"deviceId": 5})
        assert "5" in t.name


class TestGarden:
    """Tests for Garden data model."""

    def test_basic_creation(self) -> None:
        g = Garden({
            "_id": "garden1",
            "name": "My Garden",
            "password": "secret",
            "transformers": [
                {"deviceId": 1, "lightZones": []},
            ],
        })
        assert g.id == "garden1"
        assert g.name == "My Garden"
        assert g.password == "secret"
        assert len(g.transformers) == 1

    def test_async_functions_exist(self) -> None:
        """Verify async API functions are importable."""
        from inlite_ble.cloud import async_send_code, async_login
        assert callable(async_send_code)
        assert callable(async_login)
