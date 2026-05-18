"""Config flow for in-lite integration.

Supports three entry points:
- User-initiated: email → code → select garden
- Bluetooth discovery: HA finds "inlitebt" → user confirms → email flow
- Reauth: re-run email/code flow to update credentials
- Options: configure scan interval and idle disconnect timeout
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from inlite_ble.cloud import (
    ApiError,
    AuthenticationError,
    Garden,
    async_login,
    async_send_code,
)

from .const import (
    CONF_GARDEN_ID,
    CONF_GARDEN_NAME,
    CONF_IDLE_DISCONNECT,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TRANSFORMERS,
    DEFAULT_IDLE_DISCONNECT_SECONDS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_IDLE_DISCONNECT_SECONDS,
    MAX_SCAN_INTERVAL,
    MIN_IDLE_DISCONNECT_SECONDS,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class InliteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the in-lite config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._email: str | None = None
        self._gardens: list[Garden] = []
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._reauth_entry: ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> InliteOptionsFlow:
        """Get the options flow handler."""
        return InliteOptionsFlow(config_entry)

    # ------------------------------------------------------------------
    # Bluetooth discovery entry point
    # ------------------------------------------------------------------

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle Bluetooth discovery of an in-lite hub."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        # The BLE device is a shared gateway — if ANY inlite entry exists,
        # the gateway is already in use. Abort to suppress repeated discovery.
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        self._discovery_info = discovery_info
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm Bluetooth discovery, then start the cloud login flow."""
        if user_input is not None:
            return await self.async_step_user()

        self._set_confirm_only()
        return self.async_show_form(step_id="bluetooth_confirm")

    # ------------------------------------------------------------------
    # User-initiated flow: email → code → select garden
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: User enters their in-lite email address."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input["email"].strip()
            try:
                session = async_get_clientsession(self.hass)
                await async_send_code(session, self._email)
                return await self.async_step_verify()
            except ApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error sending verification code")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("email"): str,
            }),
            errors=errors,
        )

    async def async_step_verify(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: User enters the 6-digit verification code."""
        errors: dict[str, str] = {}

        if user_input is not None:
            code = user_input["code"].strip()
            try:
                session = async_get_clientsession(self.hass)
                self._gardens = await async_login(session, self._email, code)
                if not self._gardens:
                    errors["base"] = "no_gardens"
                elif len(self._gardens) == 1:
                    return await self._create_entry(self._gardens[0])
                else:
                    return await self.async_step_select_garden()
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except ApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during login")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="verify",
            data_schema=vol.Schema({
                vol.Required("code"): str,
            }),
            errors=errors,
            description_placeholders={"email": self._email},
        )

    async def async_step_select_garden(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: User selects a garden (only shown if >1 garden)."""
        if user_input is not None:
            garden_name = user_input["garden"]
            for g in self._gardens:
                if g.name == garden_name:
                    return await self._create_entry(g)

        garden_names = [g.name for g in self._gardens]
        return self.async_show_form(
            step_id="select_garden",
            data_schema=vol.Schema({
                vol.Required("garden"): vol.In(garden_names),
            }),
        )

    async def _create_entry(self, garden: Garden) -> ConfigFlowResult:
        """Create a config entry for the selected garden."""
        await self.async_set_unique_id(garden.id)
        self._abort_if_unique_id_configured()

        transformers = []
        for t in garden.transformers:
            zones = []
            for z in t.light_zones:
                zones.append({
                    "output_id": z.output_id,
                    "name": z.name,
                })
            transformers.append({
                "device_id": t.device_id,
                "name": t.name,
                "firmware_version": t.firmware_version,
                "zones": zones,
            })

        data = {
            "email": self._email,
            CONF_GARDEN_ID: garden.id,
            CONF_GARDEN_NAME: garden.name,
            CONF_PASSWORD: garden.password,
            CONF_TRANSFORMERS: transformers,
        }

        # If this is a reauth, update the existing entry
        if self._reauth_entry is not None:
            self.hass.config_entries.async_update_entry(
                self._reauth_entry, data=data
            )
            await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        return self.async_create_entry(
            title="in-lite %s" % garden.name,
            data=data,
        )

    # ------------------------------------------------------------------
    # Reauth flow
    # ------------------------------------------------------------------

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when credentials become invalid."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._email = entry_data.get("email")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauth and restart the email/code flow."""
        if user_input is not None:
            return await self.async_step_user()

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"email": self._email or ""},
        )


class InliteOptionsFlow(OptionsFlow):
    """Handle in-lite options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_scan = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        current_idle = self._config_entry.options.get(
            CONF_IDLE_DISCONNECT, DEFAULT_IDLE_DISCONNECT_SECONDS
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=current_scan
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                    vol.Required(
                        CONF_IDLE_DISCONNECT, default=current_idle
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_IDLE_DISCONNECT_SECONDS,
                            max=MAX_IDLE_DISCONNECT_SECONDS,
                        ),
                    ),
                }
            ),
        )
