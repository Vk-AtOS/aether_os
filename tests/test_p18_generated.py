"""KAN-99/KAN-100: generated metering middleware matches the routes the backend serves and ignores X-Tenant-Id."""
import importlib.util

from aether_os.phases.p18_billing_metering.metering_generator import generate_metering_middleware


def _load(tmp_path):
    f = tmp_path / "metering_mw.py"
    f.write_text(generate_metering_middleware([{"table": "invoice"}, {"table": "order_items"}], "demo"))
    spec = importlib.util.spec_from_file_location("metering_mw", f)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_prefixes_match_served_paths(tmp_path):
    m = _load(tmp_path)
    assert m._extract_entity("/api/invoice") == "invoice"
    assert m._extract_entity("/api/invoice/42") == "invoice"
    assert m._extract_entity("/api/order_items/") == "order_items"
    assert m._extract_entity("/api/invoices_other") is None
    assert m._extract_entity("/invoices") is None


def test_tenant_header_is_not_trusted(tmp_path):
    m = _load(tmp_path)

    class Req:
        headers = {"X-Tenant-Id": "victim"}
    assert m._get_tenant_id(Req()) == "unknown"
