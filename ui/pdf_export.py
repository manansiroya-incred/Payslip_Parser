"""
Loan File PDF Export — generates a professional credit document.

Uses reportlab to create a PDF with:
- Employee snapshot, key metrics, earnings/deductions tables
- Authenticity score, tax compliance, employer signals (when available)
- Data quality notes and disclaimer footer
"""

from datetime import datetime
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ---------------------------------------------------------------------------
# Indian number formatting (mirror of ui/components.py _fmt_indian)
# ---------------------------------------------------------------------------
def _fmt_inr(val) -> str:
    if val is None:
        return "N/A"
    val = float(val)
    negative = val < 0
    val = abs(val)
    int_part = int(val)
    dec_str = f"{val:.2f}".split(".")[1]
    s = str(int_part)
    if len(s) <= 3:
        formatted = s
    else:
        last_three = s[-3:]
        remaining = s[:-3]
        groups = []
        while len(remaining) > 2:
            groups.append(remaining[-2:])
            remaining = remaining[:-2]
        if remaining:
            groups.append(remaining)
        groups.reverse()
        formatted = ",".join(groups) + "," + last_three
    return ("- " if negative else "") + "\u20b9" + formatted + "." + dec_str


def _safe_get(data: dict, *keys):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------
def generate_loan_file_pdf(
    data: dict,
    insights: dict,
    version: str = "B",
    authenticity: Optional[dict] = None,
    tax_compliance: Optional[dict] = None,
    employer_signals: Optional[dict] = None,
    loan_params: Optional[dict] = None,
    consistency: Optional[dict] = None,
) -> BytesIO:
    """Generate a professional 1-page credit document as PDF.

    Returns a BytesIO buffer ready for Streamlit's download_button.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=14, spaceAfter=2 * mm)
    heading_style = ParagraphStyle("SectionHead", parent=styles["Heading2"], fontSize=11, spaceAfter=2 * mm, spaceBefore=4 * mm)
    normal = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9, leading=12)
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, leading=10, textColor=colors.grey)
    bold_style = ParagraphStyle("Bold", parent=normal, fontName="Helvetica-Bold")

    elements = []

    # --- Header ---
    version_label = "A (Gemini end-to-end)" if version == "A" else "B (Gemini + Python)"
    now = datetime.now().strftime("%d %B %Y, %H:%M")
    elements.append(Paragraph(f"InCred Finance | Payslip Analysis Report", title_style))
    elements.append(Paragraph(f"Generated: {now} | Processing Version: {version_label}", small))
    elements.append(Spacer(1, 3 * mm))

    # --- Employee snapshot ---
    employee = data.get("employee", {})
    employer = data.get("employer", {})
    doc_meta = data.get("document_meta", {})

    snapshot_data = [
        ["Employee", employee.get("name") or "N/A", "Employer", employer.get("name") or "N/A"],
        ["Employee ID", employee.get("employee_id") or "N/A", "Pay Period", doc_meta.get("pay_period_label") or "N/A"],
        ["Job Title", employee.get("job_title") or "N/A", "Frequency", (doc_meta.get("salary_frequency") or "monthly").title()],
    ]
    snapshot_table = Table(snapshot_data, colWidths=[70, 130, 70, 130])
    snapshot_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(snapshot_table)
    elements.append(Spacer(1, 3 * mm))

    # --- Key Metrics ---
    elements.append(Paragraph("Key Metrics", heading_style))
    annual = insights.get("monthly_to_annual_conversion") or {}
    th = insights.get("take_home_ratio") or {}
    metrics_data = [
        ["Monthly Net", _fmt_inr(_safe_get(data, "net_pay", "net_salary"))],
        ["Monthly Gross", _fmt_inr(_safe_get(data, "earnings", "gross_salary"))],
        ["Annual CTC", _fmt_inr(annual.get("annual_gross"))],
        ["Take-Home Ratio", th.get("take_home_pct", "N/A")],
    ]
    mt = Table(metrics_data, colWidths=[120, 200])
    mt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(mt)
    elements.append(Spacer(1, 3 * mm))

    # --- Earnings & Deductions summary ---
    elements.append(Paragraph("Earnings & Deductions", heading_style))
    ed_rows = [["Component", "Amount", "Type"]]
    earnings = data.get("earnings", {})
    for label, key in [("Basic Salary", "basic_salary"), ("HRA", "hra"), ("Overtime", "overtime"),
                        ("Special Allowance", "special_allowance"), ("Bonus", "bonus")]:
        val = earnings.get(key)
        if val is not None:
            ed_rows.append([label, _fmt_inr(val), "Earning"])
    other_earn = earnings.get("other_earnings", {})
    if isinstance(other_earn, dict):
        for k, v in other_earn.items():
            if v is not None and isinstance(v, (int, float)):
                ed_rows.append([k.replace("_", " ").title(), _fmt_inr(v), "Earning"])

    deductions = data.get("deductions", {})
    for label, key in [("TDS / Income Tax", "tds_income_tax"), ("PF / EPF", "pf_epf"),
                        ("Professional Tax", "professional_tax"), ("Gratuity", "gratuity"),
                        ("ESIC", "esic")]:
        val = deductions.get(key)
        if val is not None and isinstance(val, (int, float)):
            ed_rows.append([label, _fmt_inr(val), "Deduction"])
    other_ded = deductions.get("other_deductions", {})
    if isinstance(other_ded, dict):
        for k, v in other_ded.items():
            if v is not None and isinstance(v, (int, float)):
                ed_rows.append([k.replace("_", " ").title(), _fmt_inr(v), "Deduction"])

    ed_rows.append(["Gross Salary", _fmt_inr(earnings.get("gross_salary")), "Total"])
    ed_rows.append(["Total Deductions", _fmt_inr(deductions.get("total_deductions")), "Total"])
    ed_rows.append(["Net Salary", _fmt_inr(_safe_get(data, "net_pay", "net_salary")), "Net"])

    ed_table = Table(ed_rows, colWidths=[150, 120, 80])
    ed_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(ed_table)
    elements.append(Spacer(1, 3 * mm))

    # --- Authenticity Score (E1) ---
    if authenticity:
        score = authenticity.get("score", 0)
        label = authenticity.get("label", "Unknown")
        elements.append(Paragraph(f"Authenticity Score: {score}/100 ({label})", heading_style))
        for flag in authenticity.get("flags", []):
            if flag.get("pass") is None:
                continue
            icon = "PASS" if flag["pass"] else "FLAG"
            elements.append(Paragraph(f"[{icon}] {flag['check'].replace('_', ' ').title()}: {flag['message']}", normal))
        elements.append(Spacer(1, 2 * mm))

    # --- Tax Compliance (E4) ---
    if tax_compliance:
        elements.append(Paragraph(f"Tax Compliance: {tax_compliance.get('verdict', 'N/A').replace('_', ' ').title()}", heading_style))
        rng = tax_compliance.get("expected_tds_range", {})
        elements.append(Paragraph(
            f"Expected TDS: {_fmt_inr(rng.get('low'))} - {_fmt_inr(rng.get('high'))} | "
            f"Actual: {_fmt_inr(tax_compliance.get('actual_annual_tds'))}",
            normal
        ))
        elements.append(Spacer(1, 2 * mm))

    # --- Employer Signals (E5) ---
    if employer_signals:
        pos = employer_signals.get("positive_count", 0)
        total = employer_signals.get("total_assessable", 0)
        elements.append(Paragraph(f"Employer Compliance: {pos}/{total} signals positive", heading_style))
        for sig in employer_signals.get("signals", []):
            if sig.get("category") == "batch_required":
                continue
            icon = "YES" if sig.get("present") else "NO"
            elements.append(Paragraph(f"[{icon}] {sig['label']}: {sig['detail'][:80]}", normal))
        elements.append(Spacer(1, 2 * mm))

    # --- Affordability (if loan params provided) ---
    if loan_params and loan_params.get("loan_amount") and loan_params["loan_amount"] > 0:
        elements.append(Paragraph("Loan Affordability", heading_style))
        loan_type = loan_params.get("loan_type", "Personal Loan")
        amount = loan_params["loan_amount"]
        tenure = loan_params.get("loan_tenure", 60)
        rate = loan_params.get("loan_rate", 12.0)
        if rate > 0 and tenure > 0:
            r = rate / 100 / 12
            emi = amount * r * (1 + r) ** tenure / ((1 + r) ** tenure - 1)
            net = _safe_get(data, "net_pay", "net_salary")
            foir = emi / net * 100 if net and net > 0 else 0
            elements.append(Paragraph(
                f"Loan: {_fmt_inr(amount)} ({loan_type}) over {tenure} months @ {rate}% p.a. | "
                f"EMI: {_fmt_inr(round(emi, 2))} | FOIR: {foir:.1f}%",
                normal
            ))
        elements.append(Spacer(1, 2 * mm))

    # --- Consistency (batch) ---
    if consistency:
        label = consistency.get("consistency_label", "").replace("_", " ").title()
        cv = consistency.get("consistency_coefficient", 0) * 100
        elements.append(Paragraph(f"Salary Consistency: {label} ({cv:.1f}% variation)", heading_style))
        elements.append(Spacer(1, 2 * mm))

    # --- Footer ---
    elements.append(Spacer(1, 5 * mm))
    elements.append(Paragraph(
        "This report is generated from applicant-submitted documents and is for internal use only. "
        "All values are subject to verification against original documents and Form 16.",
        small
    ))

    doc.build(elements)
    buffer.seek(0)
    return buffer
