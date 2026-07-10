"""IoT time-series ingestion and fleet management pattern.

Model names are hard-coded to canonical defaults (Device, SensorReading,
Alert, Command).  To resolve names from the actual IR entities, use
generate_iot_pattern() from pattern_name_resolver instead of this constant.

Template code lives in iot_timeseries_templates.py (extracted to stay under
the 600-line file limit).
"""
from __future__ import annotations

try:
    from aether_os.phases.patterns.iot_timeseries_templates import _build_iot_code
except ImportError:
    from phases.patterns.iot_timeseries_templates import _build_iot_code  # type: ignore[no-redef]

IOT_TIMESERIES_REQUIREMENTS = ["paho-mqtt>=1.6", "influxdb-client>=1.39"]

# Default canonical model names used when the caller does not supply an entity_map.
_IOT_DEFAULT_ENTITY_MAP: dict = {
    "device": "Device",
    "reading": "SensorReading",
    "alert": "Alert",
    "command": "Command",
}


def get_iot_code(entity_map: dict | None = None) -> str:
    """Return the IoT router source code with model names resolved from entity_map.

    Parameters
    ----------
    entity_map:
        Maps canonical role names to actual IR entity names.
        Example: {"device": "Sensor", "reading": "Measurement"}
        Unrecognised keys fall back to the canonical defaults.
        Pass None (default) to use canonical names.
    """
    em = dict(_IOT_DEFAULT_ENTITY_MAP)
    if entity_map:
        em.update(entity_map)
    device = em.get("device", "Device")
    reading = em.get("reading", "SensorReading")
    alert = em.get("alert", "Alert")
    command = em.get("command", "Command")
    return _build_iot_code(device, reading, alert, command)


# Backward-compatible constant — uses canonical (default) model names.
IOT_TIMESERIES_CODE = get_iot_code()

__all__ = ["IOT_TIMESERIES_CODE", "IOT_TIMESERIES_REQUIREMENTS", "get_iot_code"]
