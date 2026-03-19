"""in-lite cloud API client — email+code login, fetches garden config and BLE passphrase.

Provides both synchronous (urllib) and asynchronous (aiohttp) interfaces.
The HA integration uses the async versions; standalone scripts can use the sync ones.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

try:
    import aiohttp

    _HAS_AIOHTTP = True
except ImportError:
    _HAS_AIOHTTP = False

_LOGGER = logging.getLogger(__name__)

API_BASE = "https://api.inlite.coffeeit.nl"
DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Accept-Language": "en",
    "X-App-Version": "iOS/3.18.0",
}


class AuthenticationError(Exception):
    """Raised on invalid or expired verification code."""


class ApiError(Exception):
    """Raised on unexpected API errors."""


class LightZone:
    """Represents a controllable light zone on a hub."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.output_id: int = data.get("outputId", 0)
        self.name: str = data.get("name", "Zone %d" % (self.output_id + 1))
        self.output_type: int = data.get("outputType", 0)
        self.output_mode: int = data.get("outputMode", 0)
        self.output_state: int = data.get("outputState", 0)
        self.icon_id: int = data.get("iconId", 0)

    @property
    def is_on(self) -> bool:
        return (self.output_mode & 0x01) != 0

    def __repr__(self) -> str:
        state = "ON" if self.is_on else "OFF"
        return "LightZone(%r, id=%d, %s)" % (self.name, self.output_id, state)


class Transformer:
    """Represents a SMART HUB transformer."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.id: str = data.get("_id", "")
        self.device_id: int = data.get("deviceId", 0)
        self.name: str = data.get("name", "SMART HUB %d" % self.device_id)
        self.firmware_version: int = data.get("firmwareVersion", 0)
        self.hardware_id: str = data.get("hardwareId", "")
        self.light_zones: list[LightZone] = [
            LightZone(lz) for lz in data.get("lightZones", [])
        ]

    def __repr__(self) -> str:
        return "Transformer(%r, id=0x%04X, zones=%d)" % (
            self.name, self.device_id, len(self.light_zones)
        )


class Garden:
    """Represents an in-lite garden with its network passphrase and devices."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.id: str = data.get("_id", "")
        self.name: str = data.get("name", "")
        self.password: str = data.get("password", "")
        self.timezone: str = data.get("timeZone", "")
        self.transformers: list[Transformer] = [
            Transformer(t) for t in data.get("transformers", [])
        ]

    def __repr__(self) -> str:
        return "Garden(%r, hubs=%d)" % (self.name, len(self.transformers))


# ---------------------------------------------------------------------------
# Synchronous API (urllib) — for standalone scripts
# ---------------------------------------------------------------------------


def _api_request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> Any:
    """Make a synchronous API request and return parsed JSON."""
    url = API_BASE + path
    headers = dict(DEFAULT_HEADERS)
    if token:
        headers["Authorization"] = token

    data = json.dumps(body).encode("utf-8") if body else None
    req = Request(url, data=data, headers=headers, method=method)

    try:
        with urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace") if e.fp else ""
        if e.code == 401:
            raise AuthenticationError("Invalid or expired verification code") from e
        raise ApiError("API %s %s → %d: %s" % (method, path, e.code, body_text)) from e


def send_code(email: str, language: str = "en") -> None:
    """Request a verification code be sent to the user's email (sync)."""
    _api_request("POST", "/user/send-code", {"email": email, "language": language})
    _LOGGER.info("Verification code sent to %s", email)


def login(email: str, code: str) -> list[Garden]:
    """Login with email + verification code, return list of gardens (sync)."""
    result = _api_request("POST", "/user/login", {"email": email, "code": code})
    gardens = [Garden(g) for g in result.get("gardens", [])]
    _LOGGER.info("Logged in as %s, found %d garden(s)", email, len(gardens))
    return gardens


# ---------------------------------------------------------------------------
# Asynchronous API (aiohttp) — for HA integration
# ---------------------------------------------------------------------------


async def _async_api_request(
    session: aiohttp.ClientSession,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> Any:
    """Make an async API request and return parsed JSON."""
    url = API_BASE + path
    headers = dict(DEFAULT_HEADERS)
    if token:
        headers["Authorization"] = token

    async with session.request(method, url, json=body, headers=headers) as resp:
        if resp.status == 401:
            raise AuthenticationError("Invalid or expired verification code")
        if resp.status >= 400:
            body_text = await resp.text()
            raise ApiError("API %s %s → %d: %s" % (method, path, resp.status, body_text))
        raw = await resp.read()
        return json.loads(raw) if raw else {}


async def async_send_code(
    session: aiohttp.ClientSession, email: str, language: str = "en"
) -> None:
    """Request a verification code be sent to the user's email (async)."""
    await _async_api_request(session, "POST", "/user/send-code", {"email": email, "language": language})
    _LOGGER.info("Verification code sent to %s", email)


async def async_login(
    session: aiohttp.ClientSession, email: str, code: str
) -> list[Garden]:
    """Login with email + verification code, return list of gardens (async)."""
    result = await _async_api_request(session, "POST", "/user/login", {"email": email, "code": code})
    gardens = [Garden(g) for g in result.get("gardens", [])]
    _LOGGER.info("Logged in as %s, found %d garden(s)", email, len(gardens))
    return gardens


# ---------------------------------------------------------------------------
# Convenience stateful client (sync, for standalone scripts)
# ---------------------------------------------------------------------------


class InliteCloudClient:
    """Stateful client that holds login results for convenience."""

    def __init__(self) -> None:
        self._gardens: list[Garden] = []

    @property
    def gardens(self) -> list[Garden]:
        return self._gardens

    def send_code(self, email: str) -> None:
        """Request verification code."""
        send_code(email)

    def login(self, email: str, code: str) -> list[Garden]:
        """Login and store gardens."""
        self._gardens = login(email, code)
        return self._gardens

    def get_garden_by_id(self, garden_id: str) -> Garden | None:
        """Find a garden by ID."""
        for g in self._gardens:
            if g.id == garden_id:
                return g
        return None

    def get_garden_by_name(self, name: str) -> Garden | None:
        """Find a garden by name (case-insensitive)."""
        for g in self._gardens:
            if g.name.lower() == name.lower():
                return g
        return None
