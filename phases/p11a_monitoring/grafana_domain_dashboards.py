"""Domain-specific Grafana dashboard JSON templates.

Each function returns a ready-to-write Grafana dashboard dict for a specific domain.
Called from task_agent.py when a domain is detected in the build context.
"""
from __future__ import annotations

from typing import Dict, Any


def _panel(title: str, expr: str, panel_type: str = "graph", x: int = 0, y: int = 0, w: int = 12, h: int = 8) -> dict:
    return {
        "title": title, "type": panel_type,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"expr": expr, "legendFormat": title}],
    }


def _dashboard(title: str, uid: str, panels: list) -> Dict[str, Any]:
    return {
        "title": title, "uid": uid, "schemaVersion": 36, "version": 1,
        "refresh": "30s", "time": {"from": "now-1h", "to": "now"},
        "panels": panels,
    }


def ecommerce_dashboard(project_name: str) -> Dict[str, Any]:
    """E-commerce domain: orders, GMV, cart abandonment, inventory."""
    slug = project_name.lower().replace(" ", "_")
    return _dashboard(f"{project_name} — E-Commerce KPIs", f"{slug}_ecom", [
        _panel("Orders / min", f'sum(rate(http_requests_total{{handler=~"/api/orders.*",status="201"}}[5m])) * 60', x=0, y=0),
        _panel("GMV (last 1h)", f'sum(increase(order_value_total[1h]))', x=12, y=0),
        _panel("Cart Abandonment Rate", f'1 - (sum(rate(http_requests_total{{handler="/api/orders",status="201"}}[5m])) / sum(rate(http_requests_total{{handler="/api/cart",status="200"}}[5m])))', x=0, y=8),
        _panel("P95 Checkout Latency (ms)", f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{handler=~"/api/checkout.*"}}[5m])) by (le)) * 1000', x=12, y=8),
        _panel("Active Products (inventory > 0)", f'sum(inventory_stock_level > 0)', "stat", x=0, y=16, w=8, h=4),
        _panel("Out-of-Stock Items", f'sum(inventory_stock_level == 0)', "stat", x=8, y=16, w=8, h=4),
        _panel("Payment Errors / 5m", f'sum(increase(http_requests_total{{handler=~"/api/payment.*",status=~"4..|5.."}}[5m]))', "stat", x=16, y=16, w=8, h=4),
        _panel("Top Products by Orders", f'topk(5, sum by (product_id) (increase(http_requests_total{{handler=~"/api/orders.*"}}[1h])))', "table", x=0, y=20, w=24, h=8),
    ])


def fintech_dashboard(project_name: str) -> Dict[str, Any]:
    """Fintech domain: transactions, fraud rate, P99 latency, compliance."""
    slug = project_name.lower().replace(" ", "_")
    return _dashboard(f"{project_name} — FinTech KPIs", f"{slug}_fintech", [
        _panel("Transactions / min", f'sum(rate(http_requests_total{{handler=~"/api/transactions.*",status="201"}}[5m])) * 60', x=0, y=0),
        _panel("Transaction Volume (USD, last 1h)", f'sum(increase(transaction_value_total[1h]))', x=12, y=0),
        _panel("P99 Transaction Latency (ms)", f'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{{handler=~"/api/transactions.*"}}[5m])) by (le)) * 1000', x=0, y=8),
        _panel("Fraud Flagged / 5m", f'sum(increase(fraud_flagged_total[5m]))', "stat", x=12, y=8, w=12, h=8),
        _panel("Failed Auth Attempts / 5m", f'sum(increase(http_requests_total{{handler="/api/auth/login",status="401"}}[5m]))', "stat", x=0, y=16, w=8, h=4),
        _panel("Compliance Checks Passed", f'sum(compliance_check_passed_total)', "stat", x=8, y=16, w=8, h=4),
        _panel("Active Sessions", f'sum(active_user_sessions)', "stat", x=16, y=16, w=8, h=4),
        _panel("Error Rate by Endpoint", f'sum by (handler) (rate(http_requests_total{{status=~"5.."}}[5m]))', "table", x=0, y=20, w=24, h=8),
    ])


def healthcare_dashboard(project_name: str) -> Dict[str, Any]:
    """Healthcare domain: appointments, patient load, HIPAA audit events."""
    slug = project_name.lower().replace(" ", "_")
    return _dashboard(f"{project_name} — Healthcare KPIs", f"{slug}_health", [
        _panel("Appointments Created / hr", f'sum(increase(http_requests_total{{handler=~"/api/appointments.*",status="201"}}[1h]))', x=0, y=0),
        _panel("Active Patient Records", f'sum(http_requests_total{{handler=~"/api/patients.*",status="200"}}) by (handler)', x=12, y=0),
        _panel("P95 EHR Query Latency (ms)", f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{handler=~"/api/patients.*"}}[5m])) by (le)) * 1000', x=0, y=8),
        _panel("HIPAA Audit Events / 5m", f'sum(increase(audit_action_total[5m]))', "stat", x=12, y=8, w=12, h=8),
        _panel("Failed Auth / 5m (HIPAA)", f'sum(increase(http_requests_total{{handler=~"/api/auth.*",status="401"}}[5m]))', "stat", x=0, y=16, w=8, h=4),
        _panel("Data Export Requests / hr", f'sum(increase(audit_action_total{{action="DATA_EXPORT"}}[1h]))', "stat", x=8, y=16, w=8, h=4),
        _panel("API Uptime (SLA)", 'avg_over_time(up[1h]) * 100', "gauge", x=16, y=16, w=8, h=4),
        _panel("Top Accessed Resources", f'topk(10, sum by (handler) (rate(http_requests_total[5m])))', "table", x=0, y=20, w=24, h=8),
    ])


def marketplace_dashboard(project_name: str) -> Dict[str, Any]:
    """Marketplace domain: listings, bids, escrow conversion."""
    slug = project_name.lower().replace(" ", "_")
    return _dashboard(f"{project_name} — Marketplace KPIs", f"{slug}_marketplace", [
        _panel("New Listings / hr", f'sum(increase(http_requests_total{{handler="/api/marketplace/listings",method="POST",status="201"}}[1h]))', x=0, y=0),
        _panel("Bids Placed / hr", f'sum(increase(http_requests_total{{handler=~"/api/marketplace/listings/.*/bids",method="POST"}}[1h]))', x=12, y=0),
        _panel("Escrow Funded / hr", f'sum(increase(http_requests_total{{handler=~"/api/marketplace/escrow/.*/fund"}}[1h]))', x=0, y=8),
        _panel("Escrow Released / hr", f'sum(increase(http_requests_total{{handler=~"/api/marketplace/escrow/.*/release"}}[1h]))', x=12, y=8),
        _panel("Dispute Rate", f'sum(increase(http_requests_total{{handler=~"/api/marketplace/escrow/.*/dispute"}}[1h])) / (sum(increase(http_requests_total{{handler=~"/api/marketplace/escrow/.*/fund"}}[1h])) + 1)', "gauge", x=0, y=16, w=8, h=4),
        _panel("Active Listings", f'sum(http_requests_total{{handler="/api/marketplace/listings",method="GET",status="200"}})', "stat", x=8, y=16, w=8, h=4),
        _panel("API Error Rate", f'sum(rate(http_requests_total{{status=~"5.."}}[5m])) / sum(rate(http_requests_total[5m]))', "stat", x=16, y=16, w=8, h=4),
    ])


def saas_dashboard(project_name: str) -> Dict[str, Any]:
    """SaaS domain: active tenants, API usage, feature adoption."""
    slug = project_name.lower().replace(" ", "_")
    return _dashboard(f"{project_name} — SaaS KPIs", f"{slug}_saas", [
        _panel("Active Tenants", f'count(count by (org_id) (http_requests_total{{status="200"}}))', "stat", x=0, y=0, w=6, h=4),
        _panel("API Requests / min", f'sum(rate(http_requests_total[5m])) * 60', "stat", x=6, y=0, w=6, h=4),
        _panel("New Sign-ups / hr", f'sum(increase(http_requests_total{{handler="/api/auth/register",status="201"}}[1h]))', "stat", x=12, y=0, w=6, h=4),
        _panel("P95 API Latency (ms)", f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le)) * 1000', "stat", x=18, y=0, w=6, h=4),
        _panel("Requests by Tenant (top 10)", f'topk(10, sum by (org_id) (rate(http_requests_total[5m])))', "table", x=0, y=4, w=24, h=8),
        _panel("Error Rate", f'sum(rate(http_requests_total{{status=~"5.."}}[5m])) / sum(rate(http_requests_total[5m]))', x=0, y=12),
        _panel("Token Refresh Rate / 5m", f'sum(increase(http_requests_total{{handler="/api/auth/refresh"}}[5m]))', x=12, y=12),
    ])


def erp_dashboard(project_name: str) -> Dict[str, Any]:
    """ERP/Procurement domain: purchase requests, approval queue depth, cycle time."""
    slug = project_name.lower().replace(" ", "_")
    return _dashboard(f"{project_name} — ERP/Procurement KPIs", f"{slug}_erp", [
        _panel("Purchase Requests / day", f'sum(increase(http_requests_total{{handler="/api/approvals/requests",method="POST",status="201"}}[24h]))', x=0, y=0),
        _panel("Approval Queue Depth", f'sum(http_requests_total{{handler="/api/approvals/queue",status="200"}})', "stat", x=12, y=0, w=12, h=8),
        _panel("Requests Approved / hr", f'sum(increase(http_requests_total{{handler=~"/api/approvals/requests/.*/approve",status="200"}}[1h]))', x=0, y=8),
        _panel("Requests Rejected / hr", f'sum(increase(http_requests_total{{handler=~"/api/approvals/requests/.*/approve",status="422"}}[1h]))', x=12, y=8),
        _panel("Avg Approval Cycle Time (P95)", f'histogram_quantile(0.95, sum(rate(approval_cycle_time_seconds_bucket[1h])) by (le))', x=0, y=16),
        _panel("API Error Rate", f'sum(rate(http_requests_total{{status=~"5.."}}[5m])) / sum(rate(http_requests_total[5m]))', x=12, y=16),
    ])


_DOMAIN_DASHBOARD_MAP = {
    "ecommerce": ecommerce_dashboard,
    "fintech": fintech_dashboard,
    "healthcare": healthcare_dashboard,
    "marketplace": marketplace_dashboard,
    "saas": saas_dashboard,
    "erp": erp_dashboard,
    "hrm": erp_dashboard,
    "procurement": erp_dashboard,
}


def get_domain_dashboard(domain: str, project_name: str) -> Dict[str, Any] | None:
    """Return domain-specific dashboard dict, or None if domain is unsupported."""
    fn = _DOMAIN_DASHBOARD_MAP.get(domain.lower().replace("-", "_").replace(" ", "_"))
    if fn:
        return fn(project_name)
    return None
