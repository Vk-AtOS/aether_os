"""Trading / Capital Markets domain knowledge pack — MiFID II, SEC 15c3-5, FINRA 4511."""
from __future__ import annotations

from aether_os.core.domain_knowledge.base import (
    BusinessProcessPipeline, ComplianceRule, DomainKnowledgePack,
    EntityTemplate, FieldDef, ProcessStep, WorkflowTemplate,
)

PACK = DomainKnowledgePack(
    domain="trading",
    display_name="Trading / Capital Markets / HFT",

    entities=[
        EntityTemplate(
            name="Order", table="orders",
            description="Capital markets order — must pass risk pre-checks before routing",
            fields=[
                FieldDef("order_id", "string"),
                FieldDef("symbol", "string"),
                FieldDef("side", "string"),               # buy | sell
                FieldDef("order_type", "string"),         # market | limit | stop
                FieldDef("quantity", "float"),
                FieldDef("price", "float"),
                FieldDef("status", "string"),
                FieldDef("client_order_id", "string", pii=True),
                FieldDef("trader_id", "fk"),
                FieldDef("account_id", "fk"),
                FieldDef("time_in_force", "string"),      # DAY | GTC | IOC | FOK
                FieldDef("created_at", "datetime"),
                FieldDef("filled_quantity", "float"),
                FieldDef("avg_fill_price", "float"),
            ],
            indexes=["symbol", "status", "trader_id", "client_order_id"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Execution", table="executions",
            description="Immutable execution report — never updated after creation",
            fields=[
                FieldDef("execution_id", "string"),
                FieldDef("order_id", "fk"),
                FieldDef("execution_type", "string"),     # new | partial_fill | fill | cancelled
                FieldDef("price", "float"),
                FieldDef("quantity", "float"),
                FieldDef("timestamp", "datetime"),
                FieldDef("venue", "string"),              # exchange/ECN identifier
                FieldDef("commission_cents", "int"),
                FieldDef("status", "string"),
            ],
            indexes=["order_id", "timestamp", "venue"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Position", table="positions",
            description="Real-time account position — reconciled end-of-day",
            fields=[
                FieldDef("account_id", "fk"),
                FieldDef("symbol", "string"),
                FieldDef("quantity", "float"),
                FieldDef("avg_cost_price", "float"),
                FieldDef("market_value", "float"),
                FieldDef("unrealized_pnl", "float"),
                FieldDef("realized_pnl", "float"),
                FieldDef("last_updated", "datetime"),
            ],
            indexes=["account_id", "symbol"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="RiskLimit", table="risk_limits",
            description="Pre-trade risk controls — must be checked before order routing",
            fields=[
                FieldDef("account_id", "fk"),
                FieldDef("limit_type", "string"),         # position | loss | notional
                FieldDef("max_value", "float"),
                FieldDef("current_value", "float"),
                FieldDef("status", "string"),             # active | breached | disabled
                FieldDef("breached_at", "datetime", required=False),
            ],
            indexes=["account_id", "limit_type"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="MarketData", table="market_data",
            description="Real-time market data snapshot — high-volume, append-only",
            fields=[
                FieldDef("symbol", "string"),
                FieldDef("timestamp", "datetime"),
                FieldDef("bid", "float"),
                FieldDef("ask", "float"),
                FieldDef("last_price", "float"),
                FieldDef("volume", "float"),
                FieldDef("vwap", "float"),
                FieldDef("source", "string"),             # exchange / data vendor
            ],
            indexes=["symbol", "timestamp"],
            audit_trail=False,
        ),
    ],

    workflows=[
        WorkflowTemplate(
            name="OrderLifecycle",
            entity="Order", field="status",
            states=[
                "new", "pending_new", "acknowledged",
                "partially_filled", "filled", "cancelled", "rejected",
            ],
            transitions={
                "new":              ["pending_new"],
                "pending_new":      ["acknowledged", "rejected"],
                "acknowledged":     ["partially_filled", "filled", "cancelled"],
                "partially_filled": ["filled", "cancelled"],
                "filled":           [],
                "cancelled":        [],
                "rejected":         [],
            },
            terminal_states=["filled", "cancelled", "rejected"],
            description="FIX protocol-aligned order state machine",
        ),
    ],

    compliance=[
        ComplianceRule(
            "MiFID II",
            "Best execution reporting required for all orders",
            ["execution_id", "price", "venue", "timestamp"],
            "mandatory",
            "Record venue, price, timestamp on every execution; generate RTS 27/28 reports",
        ),
        ComplianceRule(
            "SEC Rule 15c3-5",
            "Risk controls required before order routing — Market Access Rule",
            ["risk_limit_id", "max_value"],
            "mandatory",
            "Check RiskLimit before any order leaves the system; reject if limit breached",
        ),
        ComplianceRule(
            "FINRA 4511",
            "Books and records retention for 6 years",
            ["order_id", "execution_id"],
            "mandatory",
            "Archive all orders and executions in immutable cold storage for 6 years",
        ),
        ComplianceRule(
            "Market Abuse Regulation",
            "Suspicious transaction reporting to regulator",
            ["order_id", "trader_id"],
            "mandatory",
            "Flag wash trades, layering, spoofing patterns; file STR within 24 hours",
        ),
    ],

    api_patterns=[
        "Order routing with risk pre-checks",
        "Position reconciliation endpoints",
        "Real-time market data streaming (WebSocket)",
        "Execution report callbacks",
        "End-of-day P&L calculation",
    ],

    pipelines=[
        BusinessProcessPipeline(
            name="OrderRoutingFlow",
            trigger="user_action",
            trigger_entity="Order",
            trigger_condition="status == 'new'",
            description="Pre-trade risk validation, venue routing, acknowledgment, and status update.",
            services_required=[
                "RiskService", "OrderRouterService", "VenueService", "OrderService",
            ],
            integrations_required=[],
            steps=[
                ProcessStep(
                    name="validate_risk_limits",
                    action_type="service_call",
                    service="RiskService",
                    method="check_pre_trade",
                    input_mapping={
                        "account_id": "entity.account_id",
                        "symbol": "entity.symbol",
                        "quantity": "entity.quantity",
                        "order_type": "entity.order_type",
                    },
                    on_success="route_to_venue",
                    on_failure="FAIL",
                    timeout_seconds=5,
                    description="Validate all RiskLimits before routing — SEC 15c3-5 mandatory",
                ),
                ProcessStep(
                    name="route_to_venue",
                    action_type="external_api",
                    service="VenueService",
                    method="submit_order",
                    input_mapping={
                        "order_id": "entity.order_id",
                        "symbol": "entity.symbol",
                        "side": "entity.side",
                        "quantity": "entity.quantity",
                        "price": "entity.price",
                    },
                    on_success="receive_acknowledgment",
                    on_failure="FAIL",
                    compensation="cancel_order_at_venue",
                    timeout_seconds=10,
                    retry_count=1,
                    description="Route order to best execution venue via FIX/REST",
                ),
                ProcessStep(
                    name="receive_acknowledgment",
                    action_type="service_call",
                    service="VenueService",
                    method="await_ack",
                    input_mapping={"order_id": "entity.order_id"},
                    on_success="update_order_status",
                    on_failure="FAIL",
                    timeout_seconds=15,
                    description="Wait for venue acknowledgment (pending_new → acknowledged)",
                ),
                ProcessStep(
                    name="update_order_status",
                    action_type="state_transition",
                    service="Order",
                    method="status",
                    input_mapping={"status": "'acknowledged'"},
                    on_success="END",
                    on_failure="FAIL",
                    description="Update order status in the system after venue ack",
                ),
            ],
        ),
    ],

    prompt_injection=(
        "This is a capital markets / HFT system. All orders must pass risk checks before routing. "
        "Executions are immutable. Positions must reconcile daily. "
        "Latency-sensitive paths: no blocking I/O in order routing. "
        "Use async queues (asyncio.Queue or NATS) for order events. "
        "MiFID II best execution reporting is mandatory."
    ),
)
