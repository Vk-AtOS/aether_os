"""KAN-75: the wildcard-certificate checker and the shipped renewal config."""
import importlib.util
import ssl
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_preview_origin", ROOT / "scripts/check_preview_origin.py")
chk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chk)

NOW = ssl.cert_time_to_seconds("Jan  1 00:00:00 2030 GMT")


def cert(*names, after="Mar  1 00:00:00 2030 GMT"):
    return {"subjectAltName": tuple(("DNS", n) for n in names), "notAfter": after}


def test_wildcard_covers_one_label_only():
    c = cert("preview.example.com", "*.preview.example.com")
    assert chk.check_cert(c, "abc.preview.example.com", 14, NOW) == []
    assert chk.check_cert(c, "a.b.preview.example.com", 14, NOW)      # a wildcard is one label
    assert chk.check_cert(c, "abc.other.example.com", 14, NOW)


def test_bare_host_certificate_is_rejected_for_run_hosts():
    # the failure this check exists for: a certificate without the wildcard SAN
    assert chk.check_cert(cert("preview.example.com"), "abc.preview.example.com", 14, NOW)


def test_near_expiry_is_reported():
    c = cert("*.p.example.com", after="Jan 10 00:00:00 2030 GMT")
    assert any("expires" in p for p in chk.check_cert(c, "x.p.example.com", 14, NOW))


def test_http_origin_is_refused():
    ok, problems = chk.run("http://preview.example.com")
    assert not ok and problems


def test_renewal_files_request_wildcard_and_reload_nginx():
    sh = (ROOT / "deploy/preview/issue-wildcard-cert.sh").read_text()
    assert '-d "*.$PREVIEW_DOMAIN"' in sh and "nginx -t && systemctl reload nginx" in sh
    docs = list(yaml.safe_load_all((ROOT / "deploy/kubernetes/preview-certificate.yaml").read_text()))
    cert_doc = next(d for d in docs if d["kind"] == "Certificate")
    assert any(n.startswith("*.") for n in cert_doc["spec"]["dnsNames"])
    assert cert_doc["spec"]["renewBefore"]
