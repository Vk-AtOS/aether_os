"""
AetherOS Compliance PDF Report Generator.

Generates a timestamped, professional PDF compliance report from scan results.
Falls back to a plain-text report if fpdf2 is not installed.
"""
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .code_scanner import ComplianceScanResult

SEVERITY_COLORS = {
    "critical": (220, 38, 38),
    "high":     (234, 88, 12),
    "medium":   (202, 138, 4),
    "low":      (37, 99, 235),
    "pass":     (22, 163, 74),
}


def _safe(text: str) -> str:
    """
    Replace characters outside the latin-1 range so fpdf Helvetica doesn't choke.
    Common substitutions: em-dash -> hyphen, en-dash -> hyphen, fancy quotes -> plain.
    Everything else outside latin-1 is dropped.
    """
    replacements = {
        "—": "-",   # em dash
        "–": "-",   # en dash
        "‘": "'",   # left single quote
        "’": "'",   # right single quote
        "“": '"',   # left double quote
        "”": '"',   # right double quote
        "…": "...", # ellipsis
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", errors="ignore").decode("latin-1")


def generate_pdf(result: "ComplianceScanResult", output_path: Path) -> Path:
    """
    Generate a PDF compliance report and write it to output_path.
    Returns the actual path written (may have .txt suffix if fpdf2 is absent).
    """
    try:
        from fpdf import FPDF
    except ImportError:
        txt_path = output_path.with_suffix(".txt")
        _write_text_report(result, txt_path)
        return txt_path

    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    # Compute usable width once so multi_cell never gets width=0
    _W = pdf.w - pdf.l_margin - pdf.r_margin

    # ── Header ────────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(25, 25, 112)
    pdf.cell(0, 12, "Compliance Assessment Report", ln=True)

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 6, _safe(f"Project: {result.project_name}"), ln=True)
    pdf.cell(0, 6, _safe(f"Domain: {result.domain.upper()}"), ln=True)
    pdf.cell(0, 6, f"Generated: {result.scan_timestamp[:19].replace('T', ' ')} UTC", ln=True)
    pdf.cell(0, 6, _safe(f"Source: {Path(result.scanned_file).name}"), ln=True)
    pdf.ln(4)

    # ── Score badge ───────────────────────────────────────────────────────────
    if result.score >= 80:
        score_color = (22, 163, 74)
    elif result.score >= 60:
        score_color = (202, 138, 4)
    else:
        score_color = (220, 38, 38)

    grade = (
        "A" if result.score >= 90
        else "B" if result.score >= 80
        else "C" if result.score >= 70
        else "D" if result.score >= 60
        else "F"
    )

    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(*score_color)
    pdf.cell(0, 10, f"Compliance Score: {result.score}/100  (Grade {grade})", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    # ── Finding summary ───────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Summary", ln=True)
    pdf.set_font("Helvetica", "", 10)

    severity_counts: dict = {}
    for f in result.findings:
        severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1

    for sev in ("critical", "high", "medium", "low", "pass"):
        count = severity_counts.get(sev, 0)
        if count:
            r_c, g_c, b_c = SEVERITY_COLORS[sev]
            pdf.set_text_color(r_c, g_c, b_c)
            pdf.cell(40, 6, f"  {sev.upper()}:", ln=False)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(0, 6, str(count), ln=True)

    pdf.ln(4)

    # ── Route analysis table ──────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, f"Routes Analyzed: {len(result.routes)}", ln=True)

    if result.routes:
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font("Helvetica", "B", 9)
        col_widths = [20, 60, 22, 22, 22, 22]
        headers = ["Method", "Path", "Auth", "Rate Lmt", "Validated", "Audited"]
        for w, h in zip(col_widths, headers):
            pdf.cell(w, 7, h, border=1, fill=True)
        pdf.ln()

        pdf.set_font("Helvetica", "", 8)
        for route in result.routes[:30]:
            pdf.set_text_color(0, 0, 0)
            pdf.cell(col_widths[0], 6, route.method, border=1)
            path_str = (
                route.path[:35] + "..." if len(route.path) > 35 else route.path
            )
            pdf.cell(col_widths[1], 6, path_str, border=1)
            checks = [
                (route.has_auth, col_widths[2]),
                (route.has_rate_limit, col_widths[3]),
                (route.has_input_validation, col_widths[4]),
                (route.has_audit_log, col_widths[5]),
            ]
            for val, w in checks:
                color = (22, 163, 74) if val else (220, 38, 38)
                pdf.set_text_color(*color)
                pdf.cell(w, 6, "OK" if val else "NO", border=1, align="C")
            pdf.set_text_color(0, 0, 0)
            pdf.ln()

    pdf.ln(6)

    # ── Findings detail ───────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Findings Detail", ln=True)

    non_pass = [f for f in result.findings if f.severity != "pass"]
    if not non_pass:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(22, 163, 74)
        pdf.cell(0, 8, "No compliance issues found. All checks passed.", ln=True)
        pdf.set_text_color(0, 0, 0)
    else:
        for finding in non_pass:
            r_c, g_c, b_c = SEVERITY_COLORS.get(finding.severity, (0, 0, 0))

            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(r_c, g_c, b_c)
            label = _safe(f"[{finding.severity.upper()}] {finding.rule_id} - {finding.rule_name}")
            pdf.cell(0, 6, label, ln=True)

            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(40, 40, 40)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(_W, 5, _safe(f"Framework: {finding.framework}"))
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(_W, 5, _safe(f"Issue: {finding.description}"))
            if finding.routes_affected:
                affected = ", ".join(finding.routes_affected[:5])
                if len(finding.routes_affected) > 5:
                    affected += f" (+{len(finding.routes_affected) - 5} more)"
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(_W, 5, _safe(f"Affected: {affected}"))
            if finding.remediation:
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(_W, 5, _safe(f"Fix: {finding.remediation}"))
            pdf.set_text_color(0, 0, 0)
            pdf.ln(3)

    # ── Passed checks ─────────────────────────────────────────────────────────
    passed = [f for f in result.findings if f.severity == "pass"]
    if passed:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Passed Checks", ln=True)
        pdf.set_font("Helvetica", "", 9)
        for finding in passed:
            pdf.set_text_color(22, 163, 74)
            pdf.cell(0, 5, _safe(f"  [PASS] {finding.rule_id} - {finding.rule_name}"), ln=True)
        pdf.set_text_color(0, 0, 0)

    # ── Footer ────────────────────────────────────────────────────────────────
    pdf.set_y(-20)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(
        0, 5,
        (
            f"AetherOS Compliance Scanner - {result.scan_timestamp[:10]} - "
            "This report is auto-generated and does not constitute legal advice."
        ),
        ln=True,
        align="C",
    )

    pdf.output(str(output_path))
    return output_path


# ---------------------------------------------------------------------------
# Text fallback
# ---------------------------------------------------------------------------

def _write_text_report(result: "ComplianceScanResult", output_path: Path) -> None:
    """Fallback plain-text report when fpdf2 is not available."""
    lines = [
        "COMPLIANCE ASSESSMENT REPORT",
        f"Project: {result.project_name}",
        f"Domain: {result.domain}",
        f"Score: {result.score}/100",
        f"Generated: {result.scan_timestamp}",
        f"Routes analyzed: {len(result.routes)}",
        "",
        "FINDINGS:",
    ]
    for f in result.findings:
        if f.severity != "pass":
            lines.append(f"[{f.severity.upper()}] {f.rule_id}: {f.description}")
            if f.remediation:
                lines.append(f"  Fix: {f.remediation}")
    lines.append("")
    lines.append("PASSED CHECKS:")
    for f in result.findings:
        if f.severity == "pass":
            lines.append(f"[PASS] {f.rule_id}: {f.rule_name}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
