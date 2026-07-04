"""
IoT Dashboard Domain Pack for AetherOS.

Carries canonical entity graph, constraints, integrations, and architecture
notes for generating correct IoT device management backends and frontends.
"""
from __future__ import annotations

from aether_os.core.domain_packs import (
    DomainPack,
    EntitySpec,
    IntegrationSpec,
)

# ── Entities ──────────────────────────────────────────────────────────────────

_ENTITIES = [
    EntitySpec(
        name="DeviceType",
        description=(
            "A template describing a class of IoT devices sharing the same "
            "protocol, manufacturer, and sensor capabilities. slug is the "
            "normalized URL-safe identifier. sensor_types is a JSON array of "
            "sensor type name strings (e.g. ['temperature', 'humidity'])."
        ),
        typical_fields=[
            "id", "name", "slug", "description", "manufacturer",
            "model_number", "protocol", "sensor_types", "created_at",
        ],
        unique_fields=["slug"],
        fk_relationships=[],
        compliance_fields=[],
        indexes=["slug"],
    ),
    EntitySpec(
        name="Device",
        description=(
            "A physical IoT device registered in the system. device_key is a "
            "UUID used as the device's auth token for sensor ingestion — treat "
            "as a secret. lat/lng enable geo-based dashboards. metadata stores "
            "device-specific configuration as JSON. status is cached in Redis "
            "and set to 'offline' if last_seen_at > 5 minutes ago."
        ),
        typical_fields=[
            "id", "device_type_id", "name", "device_key", "location",
            "lat", "lng", "firmware_version", "status", "last_seen_at",
            "metadata", "created_at", "updated_at",
        ],
        unique_fields=["device_key"],
        fk_relationships=["device_type_id -> DeviceType.id"],
        compliance_fields=["lat", "lng", "location"],  # geo data is PII in some jurisdictions
        indexes=["status", "device_type_id", "last_seen_at"],
    ),
    EntitySpec(
        name="DeviceGroup",
        description=(
            "A logical grouping of devices (e.g. 'Building A', 'Floor 3'). "
            "Devices belong to groups via the DeviceGroupMember join table, "
            "allowing many-to-many membership."
        ),
        typical_fields=[
            "id", "name", "description", "created_at",
        ],
        unique_fields=[],
        fk_relationships=[],
        compliance_fields=[],
        indexes=[],
    ),
    EntitySpec(
        name="DeviceGroupMember",
        description=(
            "Join table linking Devices to DeviceGroups. Unique constraint on "
            "(device_id, group_id) prevents duplicate membership."
        ),
        typical_fields=[
            "id", "device_id", "group_id",
        ],
        unique_fields=[],  # composite unique: (device_id, group_id)
        fk_relationships=[
            "device_id -> Device.id",
            "group_id -> DeviceGroup.id",
        ],
        compliance_fields=[],
        indexes=["device_id", "group_id"],
    ),
    EntitySpec(
        name="SensorReading",
        description=(
            "A single time-series measurement from a device sensor. This is the "
            "highest-volume table — it MUST be partitioned by month in production "
            "(TimescaleDB hypertable or PostgreSQL declarative partitioning). "
            "Bulk insert via POST /readings/bulk (max 1000 per request). "
            "Readings older than 90 days must be archived, not deleted (compliance). "
            "quality indicates measurement reliability: good/bad/uncertain."
        ),
        typical_fields=[
            "id", "device_id", "sensor_type", "value", "unit",
            "quality", "recorded_at",
        ],
        unique_fields=[],
        fk_relationships=["device_id -> Device.id"],
        compliance_fields=[],
        indexes=["device_id", "recorded_at", "sensor_type"],
    ),
    EntitySpec(
        name="Alert",
        description=(
            "An alert triggered when a sensor value crosses a threshold, "
            "a device goes offline, or an anomaly is detected. "
            "severity drives notification routing: critical→SMS+email, "
            "high→email, medium/low→in-app only. resolved_at set when "
            "status transitions to 'resolved'."
        ),
        typical_fields=[
            "id", "device_id", "alert_type", "severity", "sensor_type",
            "trigger_value", "threshold_value", "message",
            "status", "created_at", "resolved_at",
        ],
        unique_fields=[],
        fk_relationships=["device_id -> Device.id"],
        compliance_fields=[],
        indexes=["device_id", "status", "severity"],
    ),
    EntitySpec(
        name="Command",
        description=(
            "A control command queued for delivery to a device. payload is a "
            "JSON object with command-specific parameters. Commands must be "
            "acknowledged within 30 seconds or auto-marked as failed by a "
            "background task. executed_at set by the device on acknowledgement."
        ),
        typical_fields=[
            "id", "device_id", "command_type", "payload",
            "status", "created_at", "executed_at",
        ],
        unique_fields=[],
        fk_relationships=["device_id -> Device.id"],
        compliance_fields=[],
        indexes=["device_id", "status"],
    ),
    EntitySpec(
        name="FirmwareVersion",
        description=(
            "A firmware release for a DeviceType. download_url points to the "
            "firmware binary (S3/CDN). is_stable=False for release candidates. "
            "Unique constraint on (device_type_id, version) prevents duplicate "
            "version numbers per device type."
        ),
        typical_fields=[
            "id", "device_type_id", "version", "release_notes",
            "download_url", "is_stable", "released_at",
        ],
        unique_fields=[],  # composite unique: (device_type_id, version)
        fk_relationships=["device_type_id -> DeviceType.id"],
        compliance_fields=[],
        indexes=["device_type_id", "is_stable"],
    ),
]

# ── Integrations ──────────────────────────────────────────────────────────────

_INTEGRATIONS = [
    IntegrationSpec(
        name="mqtt",
        purpose="Lightweight pub/sub messaging protocol for device-to-cloud communication via Mosquitto broker",
        env_vars=["MQTT_BROKER_HOST", "MQTT_BROKER_PORT", "MQTT_USERNAME", "MQTT_PASSWORD"],
        typical_methods=[
            "client.connect",
            "client.publish",
            "client.subscribe",
            "client.on_message",
        ],
    ),
    IntegrationSpec(
        name="influxdb",
        purpose="Time-series storage for high-volume SensorReading data with efficient downsampling queries",
        env_vars=["INFLUXDB_URL", "INFLUXDB_TOKEN", "INFLUXDB_ORG", "INFLUXDB_BUCKET"],
        typical_methods=[
            "write_api.write",
            "query_api.query",
            "query_api.query_stream",
        ],
    ),
    IntegrationSpec(
        name="twilio",
        purpose="SMS alerts for critical and high severity device alerts",
        env_vars=["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"],
        typical_methods=["client.messages.create"],
    ),
    IntegrationSpec(
        name="sendgrid",
        purpose="Email alerts for device thresholds, offline events, and daily digest reports",
        env_vars=["SENDGRID_API_KEY", "SENDGRID_FROM_EMAIL"],
        typical_methods=[
            "send_alert_email",
            "send_daily_digest",
            "send_firmware_update_notice",
        ],
    ),
    IntegrationSpec(
        name="aws-iot",
        purpose="AWS IoT Core integration for cloud-connected devices using X.509 certificates",
        env_vars=["AWS_IOT_ENDPOINT", "AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
        typical_methods=[
            "boto3.client('iot')",
            "boto3.client('iot-data')",
            "publish_to_topic",
        ],
    ),
]

# ── Constraints ───────────────────────────────────────────────────────────────

_CONSTRAINTS = [
    "Device authentication for sensor ingestion uses X-Device-Key header matched "
    "against Device.device_key — NOT a user JWT. Ingestion endpoints are device-auth only.",
    "SensorReading bulk insert: POST /readings/bulk accepts a list of readings, "
    "max 1000 per request. Validate limit and reject with 422 if exceeded.",
    "Alert threshold values MUST be validated as numeric before saving — "
    "reject non-numeric threshold_value with 422.",
    "Device status MUST be set to 'offline' if last_seen_at > 5 minutes — "
    "enforced by a background task running every 60 seconds.",
    "SensorReadings older than 90 days MUST be archived (moved to cold storage), "
    "not deleted. Hard delete only on explicit compliance erasure request.",
    "All device Commands MUST be acknowledged within 30 seconds or auto-marked "
    "as 'failed' by a background task. Record executed_at on acknowledgement.",
    "DeviceGroupMember: enforce UNIQUE constraint on (device_id, group_id) to "
    "prevent duplicate group membership.",
    "FirmwareVersion: enforce UNIQUE constraint on (device_type_id, version) to "
    "prevent version collisions per device type.",
    "SensorReading.recorded_at MUST be indexed — this column is the primary filter "
    "for all time-range queries. Use a composite index (device_id, recorded_at).",
    "Never expose device_key in list endpoints — it is a secret auth token. "
    "Return it only in the device creation response and on explicit rotate action.",
    "lat/lng fields on Device are PII in some jurisdictions — include in GDPR "
    "data export and erasure workflows.",
    "SensorReading: in production, partition this table by month (TimescaleDB "
    "hypertable or PostgreSQL declarative partitioning) to maintain query performance "
    "as data volume grows to billions of rows.",
]

# ── Seed patterns ─────────────────────────────────────────────────────────────

_SEED_PATTERNS = {
    "slug": "{entity_lower}-{i}",
    "device_key": "dk-{i:036x}",
    "firmware_version": "1.{i}.0",
    "url": "https://firmware.example.com/v1.{i}.0/firmware.bin",
    "location": "Building {i}, Floor {i % 5 + 1}",
    "email": "ops{i}@example.com",
    "phone": "+1555{i:07d}",
}

# ── Architecture notes ────────────────────────────────────────────────────────

_ARCHITECTURE_NOTES = [
    "Time-series storage: use TimescaleDB (PostgreSQL extension) or InfluxDB for "
    "SensorReading. Keep PostgreSQL for all relational entities (Device, Alert, Command).",
    "Ingestion vs query isolation: run a separate FastAPI process (or Gunicorn worker "
    "pool) for the ingestion endpoint (/iot/readings) to avoid I/O contention with "
    "dashboard query endpoints.",
    "Device status cache: store current device status in Redis (key: device:{id}:status) "
    "with 10-minute TTL. Background task refreshes from DB every 60 seconds.",
    "MQTT: subscribe to device/{device_key}/readings topic for inbound readings. "
    "Publish to device/{device_key}/commands for outbound control commands.",
    "Real-time dashboard: use Server-Sent Events (SSE) or WebSocket to push "
    "live sensor readings to the frontend without polling.",
    "Alert fanout: critical alerts trigger immediate SMS (Twilio) + email (SendGrid); "
    "high alerts trigger email only; medium/low alerts are in-app only.",
    "Firmware OTA: store firmware binaries in S3/CDN. The Command entity carries "
    "the firmware download URL in its payload JSON. Device downloads and self-updates.",
    "Downsampling: for historical trend charts, use time-bucket aggregation "
    "(1-minute buckets for last 24 hours, 1-hour buckets for last 30 days) "
    "to reduce data volume in chart queries.",
]

# ── Pack instance ─────────────────────────────────────────────────────────────

IOT_PACK = DomainPack(
    domain="iot",
    display_name="IoT Dashboard",
    description=(
        "IoT device management platform supporting device registration, real-time "
        "sensor data ingestion, time-series storage, alerting, remote commands, "
        "and fleet monitoring dashboards."
    ),
    typical_entities=_ENTITIES,
    constraints=_CONSTRAINTS,
    compliance_standards=["GDPR"],
    typical_integrations=_INTEGRATIONS,
    seed_patterns=_SEED_PATTERNS,
    architecture_notes=_ARCHITECTURE_NOTES,
)

__all__ = ["IOT_PACK"]
