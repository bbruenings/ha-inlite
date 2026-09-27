"""Constants for the in-lite integration."""

from __future__ import annotations

DOMAIN = "inlite"
CONFIG_ENTRY_VERSION = 2

# Config entry data keys
CONF_GARDEN_ID = "garden_id"
CONF_GARDEN_NAME = "garden_name"
CONF_BLE_ADDRESS = "ble_address"
CONF_PASSWORD = "password"
CONF_TRANSFORMERS = "transformers"

# Options flow keys
CONF_SCAN_INTERVAL = "scan_interval"
CONF_IDLE_DISCONNECT = "idle_disconnect"

# Coordinator defaults
DEFAULT_SCAN_INTERVAL = 30  # seconds between BLE state polls
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 300

# BLE
BLE_LOCAL_NAME = "inlitebt"

# Connection management defaults
# Disconnect by default after every operation. This avoids leaving the hub's
# single BLE connection slot occupied across Home Assistant restarts. Users can
# opt into a longer-lived connection for real-time OOB updates.
DEFAULT_IDLE_DISCONNECT_SECONDS = 0
MIN_IDLE_DISCONNECT_SECONDS = 0
MAX_IDLE_DISCONNECT_SECONDS = 7200
