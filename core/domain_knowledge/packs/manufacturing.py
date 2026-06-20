"""Manufacturing / MES domain knowledge pack — ISO 9001, FDA 21 CFR Part 820, OEE."""
from __future__ import annotations

from aether_os.core.domain_knowledge.base import (
    BusinessProcessPipeline, ComplianceRule, DomainKnowledgePack,
    EntityTemplate, FieldDef, ProcessStep, WorkflowTemplate,
)

PACK = DomainKnowledgePack(
    domain="manufacturing",
    display_name="Manufacturing / MES (Manufacturing Execution System)",

    entities=[
        EntityTemplate(
            name="WorkOrder", table="work_orders",
            description="Production work order — quantity tracking must always reconcile",
            fields=[
                FieldDef("work_order_id", "string"),
                FieldDef("product_id", "fk"),
                FieldDef("quantity_ordered", "int"),
                FieldDef("quantity_completed", "int"),
                FieldDef("quantity_rejected", "int"),
                FieldDef("status", "string"),             # planned | released | in_progress | quality_hold | completed | cancelled
                FieldDef("priority", "string"),           # normal | urgent | expedite
                FieldDef("scheduled_start", "datetime"),
                FieldDef("scheduled_end", "datetime"),
                FieldDef("actual_start", "datetime", required=False),
                FieldDef("actual_end", "datetime", required=False),
                FieldDef("production_line", "string"),
                FieldDef("shift", "string"),
            ],
            indexes=["status", "production_line", "scheduled_start"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="BillOfMaterials", table="bills_of_materials",
            description="Product recipe — versioned and approved before production use",
            fields=[
                FieldDef("bom_id", "string"),
                FieldDef("product_id", "fk"),
                FieldDef("version", "string"),
                FieldDef("status", "string"),             # draft | approved | obsolete
                FieldDef("effective_from", "datetime"),
                FieldDef("effective_to", "datetime", required=False),
            ],
            indexes=["product_id", "status", "version"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="BOMLine", table="bom_lines",
            description="Individual component within a Bill of Materials",
            fields=[
                FieldDef("bom_id", "fk"),
                FieldDef("component_id", "fk"),
                FieldDef("quantity", "float"),
                FieldDef("unit_of_measure", "string"),
                FieldDef("substitutable", "bool"),
                FieldDef("critical", "bool"),
            ],
            indexes=["bom_id", "component_id"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="QualityInspection", table="quality_inspections",
            description="Quality gate — quality holds block further production until resolved",
            fields=[
                FieldDef("work_order_id", "fk"),
                FieldDef("inspection_type", "string"),    # in_process | final | incoming
                FieldDef("inspector_id", "fk"),
                FieldDef("status", "string"),             # pending | pass | fail | conditional
                FieldDef("defect_count", "int"),
                FieldDef("sample_size", "int"),
                FieldDef("inspected_at", "datetime", required=False),
                FieldDef("disposition", "string"),        # accept | reject | rework
            ],
            indexes=["work_order_id", "status", "inspection_type"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="NonConformanceReport", table="nonconformance_reports",
            description="NCR — documents defects and drives corrective action",
            fields=[
                FieldDef("inspection_id", "fk"),
                FieldDef("ncr_number", "string"),
                FieldDef("defect_description", "text"),
                FieldDef("root_cause", "text", required=False),
                FieldDef("corrective_action", "text", required=False),
                FieldDef("status", "string"),             # open | in_review | closed
                FieldDef("severity", "string"),           # minor | major | critical
            ],
            indexes=["inspection_id", "status", "severity"],
            audit_trail=True, soft_delete=False,
        ),
        EntityTemplate(
            name="ProductionRun", table="production_runs",
            description="Actual production execution — good + scrap must equal total produced",
            fields=[
                FieldDef("work_order_id", "fk"),
                FieldDef("machine_id", "string"),
                FieldDef("start_time", "datetime"),
                FieldDef("end_time", "datetime", required=False),
                FieldDef("good_count", "int"),
                FieldDef("scrap_count", "int"),
                FieldDef("operator_id", "fk"),
                FieldDef("oee_score", "float", required=False),
            ],
            indexes=["work_order_id", "machine_id", "start_time"],
            audit_trail=True,
        ),
    ],

    workflows=[
        WorkflowTemplate(
            name="WorkOrderFlow",
            entity="WorkOrder", field="status",
            states=["planned", "released", "in_progress", "quality_hold", "completed", "cancelled"],
            transitions={
                "planned":       ["released", "cancelled"],
                "released":      ["in_progress", "cancelled"],
                "in_progress":   ["quality_hold", "completed"],
                "quality_hold":  ["in_progress", "completed"],
                "completed":     [],
                "cancelled":     [],
            },
            terminal_states=["completed", "cancelled"],
            description="Work order must clear quality hold before completing",
        ),
        WorkflowTemplate(
            name="NCRFlow",
            entity="NonConformanceReport", field="status",
            states=["open", "in_review", "root_cause_analysis", "corrective_action", "verification", "closed"],
            transitions={
                "open":                ["in_review"],
                "in_review":           ["root_cause_analysis"],
                "root_cause_analysis": ["corrective_action"],
                "corrective_action":   ["verification"],
                "verification":        ["closed"],
                "closed":              [],
            },
            terminal_states=["closed"],
            description="NCR linear resolution workflow — each step must be documented",
        ),
    ],

    compliance=[
        ComplianceRule(
            "ISO 9001:2015",
            "All quality inspections must be documented with disposition",
            ["QualityInspection.disposition", "QualityInspection.inspected_at"],
            "mandatory",
            "Every inspection must record inspector_id, timestamp, sample_size, and disposition",
        ),
        ComplianceRule(
            "FDA 21 CFR Part 820",
            "Device history records required for medical device production",
            ["WorkOrder.work_order_id", "ProductionRun.good_count"],
            "mandatory",
            "Maintain complete Device History Record (DHR) for each production lot",
        ),
        ComplianceRule(
            "ISO 14001",
            "Scrap rates must be tracked and reported for environmental management",
            ["ProductionRun.scrap_count"],
            "recommended",
            "Report scrap rates monthly; trigger review if scrap_count / total_produced > 5%",
        ),
    ],

    api_patterns=[
        "OEE (Overall Equipment Effectiveness) calculation",
        "Material requirements planning integration",
        "ERP synchronization endpoints",
        "Real-time production metrics (WebSocket)",
        "NCR escalation workflows",
    ],

    pipelines=[
        BusinessProcessPipeline(
            name="WorkOrderCompletionFlow",
            trigger="state_transition",
            trigger_entity="WorkOrder",
            trigger_condition="status == 'in_progress'",
            description="Final quality inspection, OEE calculation, and work order closure.",
            services_required=[
                "QualityService", "OEEService", "WorkOrderService", "ERPService",
            ],
            integrations_required=[],
            steps=[
                ProcessStep(
                    name="trigger_final_inspection",
                    action_type="service_call",
                    service="QualityService",
                    method="create_final_inspection",
                    input_mapping={
                        "work_order_id": "entity.work_order_id",
                        "quantity_completed": "entity.quantity_completed",
                    },
                    on_success="calculate_oee",
                    on_failure="FAIL",
                    description="Create QualityInspection record for final inspection gate",
                ),
                ProcessStep(
                    name="calculate_oee",
                    action_type="service_call",
                    service="OEEService",
                    method="calculate",
                    input_mapping={
                        "work_order_id": "entity.work_order_id",
                        "good_count": "entity.quantity_completed",
                        "scrap_count": "entity.quantity_rejected",
                    },
                    on_success="close_work_order",
                    on_failure="SKIP",
                    description="Calculate OEE score (Availability × Performance × Quality)",
                ),
                ProcessStep(
                    name="close_work_order",
                    action_type="state_transition",
                    service="WorkOrder",
                    method="status",
                    input_mapping={"status": "'completed'"},
                    on_success="sync_to_erp",
                    on_failure="FAIL",
                    description="Transition work order to completed after quality pass",
                ),
                ProcessStep(
                    name="sync_to_erp",
                    action_type="external_api",
                    service="ERPService",
                    method="post_production_order",
                    input_mapping={
                        "work_order_id": "entity.work_order_id",
                        "quantity_completed": "entity.quantity_completed",
                    },
                    on_success="END",
                    on_failure="SKIP",
                    retry_count=3,
                    description="Post completed quantities to ERP for inventory update",
                ),
            ],
        ),
    ],

    prompt_injection=(
        "This is a manufacturing execution system. "
        "Production quantities must be tracked precisely — good_count + scrap_count must always "
        "reconcile to total produced. Quality holds must block further production until resolved. "
        "Work order status transitions must be logged with timestamps for traceability. "
        "ISO 9001 requires documented evidence of all quality decisions."
    ),
)
