"""Logistics domain knowledge pack — fleet, routes, shipments, geofencing, carrier abstraction."""
from __future__ import annotations

from aether_os.core.domain_knowledge.base import (
    ComplianceRule, DomainKnowledgePack, EntityTemplate, FieldDef, WorkflowTemplate,
)

PACK = DomainKnowledgePack(
    domain="logistics",
    display_name="Logistics / Supply Chain",

    entities=[
        EntityTemplate(
            name="Shipment", table="shipments",
            description="A consignment moving from origin to destination",
            fields=[
                FieldDef("tracking_number", "string"),
                FieldDef("shipper_id", "fk"),
                FieldDef("consignee_id", "fk"),
                FieldDef("carrier_id", "fk"),
                FieldDef("origin_address_id", "fk"),
                FieldDef("destination_address_id", "fk"),
                FieldDef("status", "string"),
                FieldDef("weight_grams", "int"),
                FieldDef("volume_cm3", "int"),
                FieldDef("declared_value_cents", "int"),
                FieldDef("service_level", "string"),      # standard | express | same_day | freight
                FieldDef("scheduled_pickup_at", "datetime"),
                FieldDef("estimated_delivery_at", "datetime", required=False),
                FieldDef("actual_delivery_at", "datetime", required=False),
                FieldDef("signature_required", "bool"),
            ],
            indexes=["tracking_number", "carrier_id", "status", "scheduled_pickup_at"],
            audit_trail=True, soft_delete=False,
        ),
        EntityTemplate(
            name="ShipmentEvent", table="shipment_events",
            description="Immutable tracking scan / status event on a shipment",
            fields=[
                FieldDef("shipment_id", "fk"),
                FieldDef("event_type", "string"),         # picked_up | in_transit | out_for_delivery | delivered | failed | exception
                FieldDef("location_lat", "float"),
                FieldDef("location_lng", "float"),
                FieldDef("location_name", "string"),
                FieldDef("description", "string"),
                FieldDef("occurred_at", "datetime"),
                FieldDef("carrier_code", "string"),
            ],
            indexes=["shipment_id", "occurred_at"],
            soft_delete=False,                            # events are append-only
        ),
        EntityTemplate(
            name="Route", table="routes",
            description="Planned path for a vehicle or courier covering multiple stops",
            fields=[
                FieldDef("name", "string"),
                FieldDef("vehicle_id", "fk"),
                FieldDef("driver_id", "fk"),
                FieldDef("date", "datetime"),
                FieldDef("status", "string"),             # planned | in_progress | completed | cancelled
                FieldDef("total_distance_km", "float", required=False),
                FieldDef("estimated_duration_minutes", "int", required=False),
                FieldDef("start_lat", "float"),
                FieldDef("start_lng", "float"),
            ],
            indexes=["vehicle_id", "driver_id", "date", "status"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="RouteStop", table="route_stops",
            description="Individual delivery/pickup stop on a route (ordered)",
            fields=[
                FieldDef("route_id", "fk"),
                FieldDef("shipment_id", "fk"),
                FieldDef("sequence", "int"),
                FieldDef("address_id", "fk"),
                FieldDef("stop_type", "string"),          # pickup | delivery
                FieldDef("status", "string"),             # pending | arrived | completed | skipped
                FieldDef("eta", "datetime", required=False),
                FieldDef("arrived_at", "datetime", required=False),
                FieldDef("completed_at", "datetime", required=False),
                FieldDef("lat", "float"),
                FieldDef("lng", "float"),
            ],
            indexes=["route_id", "sequence"],
        ),
        EntityTemplate(
            name="Vehicle", table="vehicles",
            description="Fleet vehicle or carrier asset",
            fields=[
                FieldDef("registration", "string"),
                FieldDef("type", "string"),               # van | truck | motorcycle | drone
                FieldDef("capacity_kg", "float"),
                FieldDef("capacity_cm3", "int"),
                FieldDef("carrier_id", "fk"),
                FieldDef("status", "string"),             # available | on_route | maintenance | retired
                FieldDef("current_lat", "float", required=False),
                FieldDef("current_lng", "float", required=False),
                FieldDef("last_ping_at", "datetime", required=False),
            ],
            indexes=["registration", "carrier_id", "status"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Carrier", table="carriers",
            description="Shipping provider — internal fleet or 3PL",
            fields=[
                FieldDef("name", "string"),
                FieldDef("carrier_code", "string"),       # e.g. UPS, FEDEX, DHL, INTERNAL
                FieldDef("api_endpoint", "string"),
                FieldDef("api_key", "string", encrypted_at_rest=True),
                FieldDef("tracking_url_template", "string"),
                FieldDef("supported_service_levels", "text"),  # JSON array
                FieldDef("status", "string"),
            ],
            indexes=["carrier_code", "status"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Geofence", table="geofences",
            description="Geographic boundary for alerts, zone pricing, and compliance",
            fields=[
                FieldDef("name", "string"),
                FieldDef("type", "string"),               # restricted | delivery_zone | warehouse | customs
                FieldDef("center_lat", "float"),
                FieldDef("center_lng", "float"),
                FieldDef("radius_meters", "int"),         # circle geofence; use polygon_wkt for complex shapes
                FieldDef("polygon_wkt", "text", required=False),
                FieldDef("metadata", "text"),
                FieldDef("status", "string"),
            ],
            indexes=["type", "status"],
        ),
    ],

    workflows=[
        WorkflowTemplate(
            name="ShipmentLifecycle",
            entity="Shipment", field="status",
            states=["created", "label_printed", "picked_up", "in_transit",
                    "out_for_delivery", "delivered", "delivery_failed",
                    "return_in_transit", "returned", "lost", "cancelled"],
            transitions={
                "created":           ["label_printed", "cancelled"],
                "label_printed":     ["picked_up", "cancelled"],
                "picked_up":         ["in_transit"],
                "in_transit":        ["out_for_delivery", "delivery_failed", "lost"],
                "out_for_delivery":  ["delivered", "delivery_failed"],
                "delivered":         [],
                "delivery_failed":   ["out_for_delivery", "return_in_transit"],
                "return_in_transit": ["returned"],
                "returned":          [],
                "lost":              [],
                "cancelled":         [],
            },
            terminal_states=["delivered", "returned", "lost"],
            description="End-to-end shipment tracking lifecycle",
        ),
        WorkflowTemplate(
            name="RouteExecution",
            entity="Route", field="status",
            states=["planned", "dispatched", "in_progress", "completed", "cancelled"],
            transitions={
                "planned":     ["dispatched", "cancelled"],
                "dispatched":  ["in_progress", "cancelled"],
                "in_progress": ["completed", "cancelled"],
                "completed":   [],
                "cancelled":   ["planned"],
            },
            terminal_states=["completed", "cancelled"],
            description="Driver route from dispatch to completion",
        ),
    ],

    compliance=[
        ComplianceRule("CUSTOMS", "Cross-border shipments must carry declared value and commodity codes",
                       ["declared_value_cents"], "mandatory",
                       "HS code and declared value required for international shipments"),
        ComplianceRule("GDPR", "Consignee PII (name, address) must be exportable and erasable",
                       ["consignee_id", "destination_address_id"], "mandatory",
                       "Pseudonymisation on GDPR erasure request; mask in tracking UI"),
        ComplianceRule("DATA_RESIDENCY", "Carrier API keys must be encrypted at rest",
                       ["api_key"], "mandatory",
                       "Store via KMS or AES-256; never log or return in API responses"),
        ComplianceRule("SAFETY", "Dangerous goods shipments require hazmat metadata and carrier approval",
                       ["metadata"], "mandatory",
                       "Validate hazmat flag; reject if carrier does not support hazmat"),
        ComplianceRule("AUDIT", "All shipment events are immutable — append only",
                       [], "mandatory",
                       "ShipmentEvent table must not support UPDATE or DELETE"),
    ],

    api_patterns=[
        "POST /shipments — create shipment with carrier selection and label generation",
        "GET /shipments/{tracking_number} — tracking detail with events",
        "POST /shipments/{id}/events — append tracking scan (carrier webhook)",
        "POST /routes — create optimised route from a list of stops",
        "PUT /routes/{id}/dispatch — assign driver and vehicle, change status",
        "PATCH /routes/{id}/stops/{stop_id} — mark stop completed with timestamp",
        "GET /vehicles/{id}/location — real-time GPS position",
        "POST /geofences/check — check if lat/lng is inside a named zone",
        "GET /carriers/{id}/rates?weight=&from=&to= — rate shopping across carriers",
    ],

    prompt_injection="""LOGISTICS DOMAIN RULES (mandatory):
1. ShipmentEvent records are IMMUTABLE and APPEND-ONLY — never UPDATE or DELETE tracking events.
2. Store all coordinates as float (latitude, longitude) — use PostGIS or equivalent for geo queries.
3. Carrier API keys MUST be encrypted at rest — never return in API responses or log at any level.
4. Cross-border shipments require declared_value_cents and HS commodity codes — validate before label creation.
5. Route optimisation must respect vehicle capacity (weight_kg and volume_cm3) — reject over-capacity routes.
6. Geofence checks must run server-side — never trust client-provided zone status.
7. Shipment status transitions must emit webhook events to shipper and consignee notification endpoints.
8. ETA calculations must use real-time traffic and weather data where available — not static averages.
9. Dangerous goods (hazmat) shipments require explicit hazmat_class field and carrier approval gate.
10. Track real-time vehicle GPS via last_ping_at — flag as stale if > 5 minutes without update.
""",
)
