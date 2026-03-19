"""Constants for the in-lite integration."""

from __future__ import annotations

DOMAIN = "inlite"

# Config entry data keys
CONF_GARDEN_ID = "garden_id"
CONF_GARDEN_NAME = "garden_name"
CONF_PASSWORD = "password"
CONF_TRANSFORMERS = "transformers"

# Coordinator
DEFAULT_SCAN_INTERVAL = 120  # seconds between BLE state polls

# BLE
BLE_LOCAL_NAME = "inlitebt"

# Connection management
BLE_IDLE_DISCONNECT_SECONDS = 300  # disconnect after 5 min idle
