from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class DomainProfile:
    name: str
    preferred_db: str
    required_patterns: List[str]
    security_requirements: List[str]
    suggested_tech_stack: Dict[str, str]
    compliance_notes: List[str]
    example_entities: List[str]
    description: str = ""


DOMAIN_PROFILES: Dict[str, DomainProfile] = {
    "general": DomainProfile(
        name="General Purpose",
        description="Standard FastAPI + SQLite stack for general applications.",
        preferred_db="sqlite",
        required_patterns=["RESTful API", "Service Layer"],
        security_requirements=["JWT Auth", "CORS"],
        suggested_tech_stack={
            "backend": "FastAPI",
            "frontend": "React",
            "database": "SQLite",
            "orm": "SQLAlchemy"
        },
        compliance_notes=["Standard Data Protection"],
        example_entities=["User", "Item", "Setting"]
    ),
    "industrial": DomainProfile(
        name="Industrial / IoT",
        description="SCADA-aware, OPC-UA protocols, and real-time sensor data management.",
        preferred_db="timescaledb",
        required_patterns=[
            "SCADA-aware architecture (OPC-UA)",
            "Real-time sensor data streaming (TimescaleDB)",
            "Alarm management system",
            "Redundancy patterns"
        ],
        security_requirements=[
            "Network isolation",
            "Hardware-based roots of trust",
            "Encrypted Modbus/TCP"
        ],
        suggested_tech_stack={
            "backend": "FastAPI / Python",
            "database": "TimescaleDB",
            "messaging": "MQTT / RabbitMQ",
            "protocols": "OPC-UA, Modbus"
        },
        compliance_notes=["IEC 62443", "NIST SP 800-82"],
        example_entities=["Sensor", "Gateway", "TelemetryEntry", "Alarm", "PLC"]
    ),
    "fintech": DomainProfile(
        name="FinTech",
        description="High-integrity financial systems with double-entry bookkeeping and audit trails.",
        preferred_db="postgres",
        required_patterns=[
            "Double-entry bookkeeping",
            "Idempotency keys for transactions",
            "Audit trails",
            "Reconciliation workflows"
        ],
        security_requirements=[
            "PCI-DSS compliance patterns",
            "Transaction isolation (Serializable)",
            "Hardware Security Modules (HSM) integration"
        ],
        suggested_tech_stack={
            "backend": "FastAPI",
            "database": "PostgreSQL (with transaction isolation)",
            "cache": "Redis",
            "audit": "Immutable Ledger"
        },
        compliance_notes=["PCI-DSS", "SOX", "GDPR"],
        example_entities=["Account", "Transaction", "LedgerEntry", "ReconciliationBatch"]
    ),
    "healthcare": DomainProfile(
        name="Healthcare",
        description="HL7/FHIR compliant systems with strict patient privacy and HIPAA awareness.",
        preferred_db="postgres",
        required_patterns=[
            "HL7/FHIR data modelling",
            "Patient data anonymisation",
            "Clinical workflow patterns",
            "Consent management"
        ],
        security_requirements=[
            "HIPAA-aware data handling",
            "Strict Audit Logs (BTP)",
            "Encryption at rest and in transit"
        ],
        suggested_tech_stack={
            "backend": "FastAPI",
            "database": "PostgreSQL",
            "standards": "HL7, FHIR",
            "identity": "OAuth2 / OpenID Connect"
        },
        compliance_notes=["HIPAA", "HITECH", "GDPR"],
        example_entities=["Patient", "Practitioner", "Encounter", "Observation", "Appointment"]
    ),
    "saas_multitenant": DomainProfile(
        name="SaaS Multi-tenant",
        description="Scalable multi-tenant architecture with row-level security and usage metering.",
        preferred_db="postgres",
        required_patterns=[
            "Row-level security (RLS)",
            "Organisation isolation",
            "Usage metering and quotas",
            "Webhook system"
        ],
        security_requirements=[
            "Tenant-scoped JWT claims",
            "Rate limiting per tenant",
            "Org-based RBAC"
        ],
        suggested_tech_stack={
            "backend": "FastAPI",
            "database": "PostgreSQL",
            "billing": "Stripe Hooks",
            "monitoring": "Prometheus per-tenant"
        },
        compliance_notes=["SOC2", "GDPR"],
        example_entities=["Organisation", "TenantConfig", "UsageRecord", "WebhookSubscription"]
    ),
    "ecommerce": DomainProfile(
        name="E-commerce",
        description="Full-featured commerce engine with order state machines and payment integrations.",
        preferred_db="postgres",
        required_patterns=[
            "Order state machine",
            "Cart abandonment tracking",
            "Inventory management",
            "Fulfilment workflows"
        ],
        security_requirements=[
            "Payment gateway integration security",
            "Anti-fraud checks",
            "Secure Checkout"
        ],
        suggested_tech_stack={
            "backend": "FastAPI",
            "database": "PostgreSQL",
            "search": "Elasticsearch / Meilisearch",
            "payments": "Stripe / Razorpay"
        },
        compliance_notes=["PCI-DSS", "GDPR"],
        example_entities=["Product", "Order", "Cart", "Payment", "ShippingLabel"]
    ),
    "logistics": DomainProfile(
        name="Logistics",
        description="Supply chain and tracking systems with route optimisation and carrier integrations.",
        preferred_db="postgres",
        required_patterns=[
            "Route optimisation hooks",
            "Tracking event stream",
            "ETA calculation engine",
            "Carrier API abstraction"
        ],
        security_requirements=[
            "Asset tracking security",
            "Proof of delivery verification",
            "Geofencing"
        ],
        suggested_tech_stack={
            "backend": "FastAPI",
            "database": "PostgreSQL (PostGIS)",
            "maps": "Google Maps / Mapbox",
            "tracking": "Real-time WebSockets"
        },
        compliance_notes=["TAPA", "GDPR"],
        example_entities=["Shipment", "Vehicle", "Route", "Waypoint", "Courier"]
    ),
    "education": DomainProfile(
        name="Education / LMS",
        description="Learning management systems with enrollment, progress tracking, and assessments.",
        preferred_db="postgres",
        required_patterns=[
            "Course/Enrollment/Progress models",
            "Assessment engine",
            "Certificate generation",
            "LMS integration patterns"
        ],
        security_requirements=[
            "Student data privacy (FERPA)",
            "Plagiarism detection hooks",
            "Secure assessments"
        ],
        suggested_tech_stack={
            "backend": "FastAPI",
            "database": "PostgreSQL",
            "files": "AWS S3 / Cloudflare R2",
            "video": "Mux / YouTube API"
        },
        compliance_notes=["FERPA", "COPPA", "GDPR"],
        example_entities=["Course", "Lesson", "Enrollment", "Assignment", "Certificate"]
    ),
    "crm": DomainProfile(
        name="CRM / Sales",
        description="Customer relationship management with deal pipelines, contact management, and sales analytics.",
        preferred_db="sqlite",
        required_patterns=[
            "Deal pipeline state machine (Lead→Qualified→Proposal→Closed)",
            "Contact/Account hierarchy",
            "Activity timeline per contact",
            "Pipeline analytics and win-rate calculation"
        ],
        security_requirements=[
            "Role-based access (Admin, Sales Rep, Viewer)",
            "JWT Auth",
            "CORS",
            "Audit log for deal status changes"
        ],
        suggested_tech_stack={
            "backend": "FastAPI",
            "frontend": "React",
            "database": "SQLite",
            "orm": "SQLAlchemy"
        },
        compliance_notes=["GDPR (contact data)", "Data retention policies"],
        example_entities=["Contact", "Deal", "PipelineStage", "Activity", "Product", "Order"]
    )
}


def get_domain_profile(domain_name: str) -> DomainProfile:
    """Return the profile for a given domain, defaulting to 'general'."""
    return DOMAIN_PROFILES.get(domain_name, DOMAIN_PROFILES["general"])
