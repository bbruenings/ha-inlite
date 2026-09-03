"""Constants for the in-lite integration."""

from __future__ import annotations

DOMAIN = "inlite"

# Config entry data keys
CONF_GARDEN_ID = "garden_id"
CONF_GARDEN_NAME = "garden_name"
CONF_PASSWORD = "password"
CONF_TRANSFORMERS = "transformers"

# Options flow keys
CONF_SCAN_INTERVAL = "scan_interval"
CONF_IDLE_DISCONNECT = "idle_disconnect"
CONF_STARTUP_DELAY = "startup_delay_seconds"

# Coordinator defaults
DEFAULT_SCAN_INTERVAL = 30  # seconds between BLE state polls
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 300

# Startup delay for slow Bluetooth discovery (e.g., ESPHome proxies)
DEFAULT_STARTUP_DELAY_SECONDS = 0
MIN_STARTUP_DELAY_SECONDS = 0
MAX_STARTUP_DELAY_SECONDS = 30

# BLE
BLE_LOCAL_NAME = "inlitebt"

# Connection management defaults
DEFAULT_IDLE_DISCONNECT_SECONDS = 3600  # 1 hour — keeps connection alive for OOB updates
MIN_IDLE_DISCONNECT_SECONDS = 60
MAX_IDLE_DISCONNECT_SECONDS = 7200
