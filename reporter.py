"""
Session Report Generator.

After each analysis run, generates a Markdown report in data/sessions/.
The report captures everything shown in the UI so Version A and B outputs
can be compared side-by-side by diffing two report files.
"""

import json
from datetime import date, datetime
from pathlib import Path

REPORTS_DIR = Path(__file__).parent / "data" / "sessions"


# ---------------------------------------------------------------------------
# Formatting helpers (plain text, no Streamlit dependency)
# ---------------------------------------------------------------------------
def _fmt(val, prefix="", suffix="", fallback="Not specified"):
    if val is None:
        return fallback
    return f"{prefix}{val}{suffix}"


def _fmt_money(val, currency="INR", fallback="Not specified"):
    if val is None:
        return fallback
    symbols = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
    cs = symbols.get(str(currency).upper(), currency)

    # Indian comma style for ₹, Western for others
    if cs == "₹":
        return f"₹{_indian_fmt(float(val))}"
    return f"{cs}{float(val):,.2f}"


def _indian_fmt(val: float) -> str:
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
    return ("-" if negative else "") + formatted + "." + dec_str


def _pct(ratio, fallback="N/A"):
    if ratio is None:
        return fallback
    try:
        return f"{float(ratio) * 100:.1f}%"
    except (ValueError, TypeError):
        return fallback


def _section(title, level=2):
    hashes = "#" * level
    return f"\n{hashes} {title}\n"


def _table(headers: list, rows: list) -> str:
    """Render a simple Markdown table."""
    sep = " | "
    header_row = sep.join(headers)
    divider = sep.join(["---"] * len(headers))
    lines = [f"| {header_row} |", f"| {divider} |"]
    for row in rows:
        lines.append("| " + sep.join(str(c) for c in row) + " |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------
def _render_session_header(version: str, timestamp: str, files: list) -> str:
    lines = [
        "# Payslip Analysis Report",
        "",
        f"**Processing Version:** {'A — Gemini end-to-end (single call)' if version == 'A' else 'B — Gemini extraction + Python calculation (two calls)'}",
        f"**Generated:** {timestamp}",
        f"**Files processed:** {', '.join(files) if files else 'Unknown'}",
        "",
        "---",
    ]
    return "\n".join(lines)


def _render_version_note(version: str) -> str:
    if version == "A":
        return (
            "> **Version A Note:** Extraction and insight generation were performed "
            "in a single Gemini call. Python computed `monthly_to_annual_conversion` "
            "and `take_home_ratio` post-hoc; all other insights came from Gemini "
            "directly and may use non-standard key names.\n"
        )
    return (
        "> **Version B Note:** Extraction used Call 1 (Gemini Vision). "
        "Call 2 (Gemini Prescriber) decided which of the 12 Python insight "
        "functions to run. Python executed the approved functions with "
        "deterministic math. Non-standard components were Gemini-computed.\n"
    )


def _render_document_meta(data: dict) -> str:
    meta = data.get("document_meta", {})
    lines = [_section("Document Metadata", 3)]
    rows = [
        ("Pay period", _fmt(meta.get("pay_period_label"))),
        ("Pay period start", _fmt(meta.get("pay_period_start"))),
        ("Pay period end", _fmt(meta.get("pay_period_end"))),
        ("Date of issue", _fmt(meta.get("date_of_issue"))),
        ("Salary frequency", _fmt(meta.get("salary_frequency"), fallback="monthly")),
        ("Currency", _fmt(meta.get("currency"), fallback="INR")),
    ]
    for label, val in rows:
        lines.append(f"- **{label}:** {val}")
    return "\n".join(lines)


def _render_employee_employer(data: dict) -> str:
    emp = data.get("employee", {})
    employer = data.get("employer", {})
    lines = [_section("Employee & Employer", 3)]
    rows = [
        ("Employee name", _fmt(emp.get("name"))),
        ("Employee ID", _fmt(emp.get("employee_id"))),
        ("Job title", _fmt(emp.get("job_title"))),
        ("Date of birth", _fmt(emp.get("date_of_birth"))),
        ("Employment date", _fmt(emp.get("employment_date"))),
        ("Bank account", _fmt(emp.get("bank_account"))),
        ("Employer", _fmt(employer.get("name"))),
        ("Employer address", _fmt(employer.get("address"))),
        ("Department", _fmt(employer.get("department"))),
    ]
    for label, val in rows:
        lines.append(f"- **{label}:** {val}")
    return "\n".join(lines)


def _render_attendance(data: dict) -> str:
    att = data.get("attendance", {})
    if not any(att.values()):
        return ""
    currency = data.get("document_meta", {}).get("currency", "INR")
    lines = [_section("Attendance", 3)]
    fields = [
        ("Days worked", att.get("days_worked")),
        ("Hours worked", att.get("hours_worked")),
        ("Days in period", att.get("days_in_period")),
        ("Hourly rate", _fmt_money(att.get("hourly_rate"), currency) if att.get("hourly_rate") else None),
    ]
    for label, val in fields:
        if val is not None:
            lines.append(f"- **{label}:** {val}")
    return "\n".join(lines)


def _render_earnings(data: dict) -> str:
    earnings = data.get("earnings", {})
    currency = data.get("document_meta", {}).get("currency", "INR")
    gross = earnings.get("gross_salary") or 0
    lines = [_section("Earnings", 3)]

    headers = ["Component", "Amount", "% of Gross"]
    rows = []

    standard = [
        ("Basic Salary", "basic_salary"),
        ("HRA", "hra"),
        ("LTA", "lta"),
        ("Special Allowance", "special_allowance"),
        ("Overtime", "overtime"),
        ("Bonus", "bonus"),
    ]
    for label, key in standard:
        val = earnings.get(key)
        if val is not None:
            pct = f"{val / gross * 100:.1f}%" if gross > 0 else "N/A"
            rows.append([label, _fmt_money(val, currency), pct])

    other = earnings.get("other_earnings", {})
    if isinstance(other, dict):
        for name, val in other.items():
            if val is not None and isinstance(val, (int, float)):
                pct = f"{val / gross * 100:.1f}%" if gross > 0 else "N/A"
                rows.append([name.replace("_", " ").title(), _fmt_money(val, currency), pct])

    if gross > 0:
        rows.append(["**Total Gross**", f"**{_fmt_money(gross, currency)}**", "**100%**"])

    if rows:
        lines.append(_table(headers, rows))
    else:
        lines.append("_No earnings data extracted._")

    return "\n".join(lines)


def _render_deductions(data: dict) -> str:
    deductions = data.get("deductions", {})
    currency = data.get("document_meta", {}).get("currency", "INR")
    gross = data.get("earnings", {}).get("gross_salary") or 0
    total_ded = deductions.get("total_deductions")
    lines = [_section("Deductions", 3)]

    headers = ["Component", "Amount", "% of Gross"]
    rows = []

    standard = [
        ("TDS / Income Tax", "tds_income_tax"),
        ("PF / EPF", "pf_epf"),
        ("Professional Tax", "professional_tax"),
        ("Gratuity", "gratuity"),
        ("ESIC", "esic"),
        ("Loan Deduction", "loan_deduction"),
    ]
    for label, key in standard:
        val = deductions.get(key)
        if val is not None and isinstance(val, (int, float)):
            pct = f"{val / gross * 100:.1f}%" if gross > 0 else "N/A"
            rows.append([label, _fmt_money(val, currency), pct])

    other = deductions.get("other_deductions", {})
    if isinstance(other, dict):
        for name, val in other.items():
            if val is not None and isinstance(val, (int, float)):
                pct = f"{val / gross * 100:.1f}%" if gross > 0 else "N/A"
                rows.append([name.replace("_", " ").title(), _fmt_money(val, currency), pct])

    if total_ded is not None:
        pct = f"{total_ded / gross * 100:.1f}%" if gross > 0 else "N/A"
        rows.append(["**Total Deductions**", f"**{_fmt_money(total_ded, currency)}**", f"**{pct}**"])

    if rows:
        lines.append(_table(headers, rows))
    else:
        lines.append("_No deduction data extracted._")

    return "\n".join(lines)


def _render_net_pay(data: dict) -> str:
    net = data.get("net_pay", {})
    currency = data.get("document_meta", {}).get("currency", "INR")
    lines = [_section("Net Pay", 3)]
    lines.append(f"- **Net Salary:** {_fmt_money(net.get('net_salary'), currency)}")
    if net.get("ctc_mentioned"):
        lines.append(f"- **CTC (stated in document):** {_fmt_money(net.get('ctc_mentioned'), currency)}")
    return "\n".join(lines)


def _render_insights(insights: dict, version: str, currency: str) -> str:
    lines = [_section("Computed Insights", 3)]

    # --- Salary figures ---
    annual = insights.get("monthly_to_annual_conversion") or {}
    if annual and not annual.get("error"):
        lines.append("**Annualised Figures**")
        lines.append(f"- Monthly Gross: {_fmt_money(annual.get('monthly_gross'), currency)}")
        lines.append(f"- Monthly Net: {_fmt_money(annual.get('monthly_net'), currency)}")
        lines.append(f"- Annual Gross: {_fmt_money(annual.get('annual_gross'), currency)}")
        lines.append(f"- Annual Net: {_fmt_money(annual.get('annual_net'), currency)}")
        if annual.get("is_estimated"):
            lines.append(f"- ⚠️ Estimated: {annual.get('assumption', '')}")
        lines.append("")

    # --- Take-home ratio ---
    th = insights.get("take_home_ratio") or {}
    if th and not th.get("error"):
        lines.append(f"**Take-Home Ratio:** {th.get('take_home_pct', 'N/A')} "
                     f"(ratio: {th.get('take_home_ratio', 'N/A')})")
        lines.append("")

    # --- TDS rate ---
    # Bug 6: Version A uses Gemini's {value, unit} format; Version B uses Python's {tds_pct} format
    tds = insights.get("effective_tds_rate") or {}
    if tds and not tds.get("error") and not tds.get("skipped"):
        tds_pct = tds.get("tds_pct")
        if not tds_pct and tds.get("value") is not None:
            tds_pct = f"{tds['value']} {tds.get('unit', '% of gross')}"
        tds_amount = tds.get("tds_amount")
        if tds_pct:
            amt_str = f" ({_fmt_money(tds_amount, currency)})" if tds_amount else ""
            # If tds_pct already contains "of gross" (Gemini format), don't append it again
            if "of gross" in str(tds_pct).lower():
                lines.append(f"**Effective TDS Rate:** {tds_pct}{amt_str}")
            else:
                lines.append(f"**Effective TDS Rate:** {tds_pct} of gross{amt_str}")
            lines.append("")

    # --- PF ratio ---
    pf = insights.get("pf_as_pct_of_basic") or {}
    if pf and not pf.get("error") and not pf.get("skipped"):
        lines.append(f"**PF as % of Basic:** {pf.get('pf_basic_pct', 'N/A')} "
                     f"({_fmt_money(pf.get('pf_amount'), currency)}/month)")
        lines.append("")

    # --- Deduction breakdown ---
    ded_bk = insights.get("deduction_breakdown") or {}
    if ded_bk and not ded_bk.get("error") and not ded_bk.get("skipped"):
        lines.append("**Deduction Breakdown (% of Gross)**")
        for k, v in ded_bk.items():
            if isinstance(v, dict) and "pct_of_gross" in v:
                label = k.replace("_", " ").title()
                lines.append(f"  - {label}: {_fmt_money(v.get('amount'), currency)} "
                              f"({_pct(v.get('pct_of_gross'))})")
        lines.append("")

    # --- Overtime ---
    ot = insights.get("overtime_analysis") or {}
    if ot and not ot.get("error") and not ot.get("skipped"):
        lines.append(f"**Overtime:** {_fmt_money(ot.get('overtime_amount'), currency)} "
                     f"({_pct(ot.get('overtime_pct_of_gross'))} of gross)")
        lines.append("")

    # --- HRA ---
    hra = insights.get("hra_as_pct_of_gross") or {}
    if hra and not hra.get("error") and not hra.get("skipped"):
        lines.append(f"**HRA:** {_fmt_money(hra.get('hra_amount'), currency)} "
                     f"({_pct(hra.get('hra_pct_of_gross'))} of gross)")
        lines.append("")

    # --- LTA ---
    lta = insights.get("lta_as_pct_of_gross") or {}
    if lta and not lta.get("error") and not lta.get("skipped"):
        lines.append(f"**LTA:** {_fmt_money(lta.get('lta_amount'), currency)} "
                     f"({_pct(lta.get('lta_pct_of_gross'))} of gross)")
        lines.append("")

    # --- Professional tax ---
    pt = insights.get("professional_tax_check") or {}
    if pt and not pt.get("error") and not pt.get("skipped"):
        lines.append(f"**Professional Tax:** {_fmt_money(pt.get('professional_tax_monthly'), currency)}/month "
                     f"({_fmt_money(pt.get('professional_tax_annual'), currency)}/year)")
        lines.append("")

    # --- Gratuity ---
    gr = insights.get("gratuity_accrual_estimate") or {}
    if gr and not gr.get("error") and not gr.get("skipped"):
        lines.append(f"**Gratuity Accrual:** {_fmt_money(gr.get('gratuity_per_year'), currency)}/year "
                     f"({_fmt_money(gr.get('gratuity_monthly_accrual'), currency)}/month accrual)")
        if gr.get("tenure_years"):
            lines.append(f"  - Tenure: {gr['tenure_years']:.1f} years")
        if gr.get("gratuity_accrued_to_date"):
            lines.append(f"  - Accrued to date: {_fmt_money(gr.get('gratuity_accrued_to_date'), currency)}")
        if gr.get("tenure_years") and gr["tenure_years"] < 5:
            lines.append(f"  > Note: Gratuity is payable only after 5 years of continuous service under the Payment of Gratuity Act, 1972. Current tenure of {gr['tenure_years']:.1f} years does not meet this threshold. Figures shown are theoretical accrual rates only and should not be counted as an asset for lending purposes.")
        lines.append("")

    # --- Gemini-computed (Version B non-standard) ---
    gemini_comp = insights.get("gemini_computed") or {}
    if isinstance(gemini_comp, dict) and gemini_comp:
        lines.append("**Gemini-Computed Non-Standard Insights** _(Version B only)_")
        for key, val in gemini_comp.items():
            if isinstance(val, dict):
                label = val.get("label", key.replace("_", " ").title())
                value = val.get("value", "")
                unit = val.get("unit", "")
                desc = val.get("description", "")
                lines.append(f"  - **{label}:** {value} {unit}")
                if desc:
                    lines.append(f"    _{desc}_")
        lines.append("")

    # --- Version A extra Gemini insights (any keys not already handled above) ---
    if version == "A":
        handled_keys = {
            "monthly_to_annual_conversion", "take_home_ratio", "effective_tds_rate",
            "pf_as_pct_of_basic", "deduction_breakdown", "overtime_analysis",
            "hra_as_pct_of_gross", "lta_as_pct_of_gross", "professional_tax_check",
            "gratuity_accrual_estimate", "gemini_computed", "_prescription",
            "salary_consistency", "hourly_normalisation",
        }

        def _is_duplicate_insight(val):
            """Bug 5: Filter out Gemini insights that duplicate Python's annualisation."""
            if not isinstance(val, dict):
                return False
            label = val.get("label", "").lower()
            unit = val.get("unit", "").lower()
            # Annualisation, frequency classification, and deduction totals already shown
            return (
                "annual" in label or "annuali" in label
                or "year" in unit
                or "frequency" in label or "classification" in label
                or "total deduction" in label or "deduction rate" in label
            )

        extra = {
            k: v for k, v in insights.items()
            if k not in handled_keys and v and not _is_duplicate_insight(v)
        }
        if extra:
            lines.append("**Additional Gemini Insights (Version A raw output)**")
            for key, val in extra.items():
                if isinstance(val, dict):
                    label = val.get("label", key.replace("_", " ").title())
                    value = val.get("value", "")
                    unit = val.get("unit", "")
                    desc = val.get("description", "")
                    lines.append(f"  - **{label}:** {value} {unit}")
                    if desc:
                        lines.append(f"    _{desc}_")
                else:
                    lines.append(f"  - **{key}:** {val}")
            lines.append("")

    if len(lines) == 1:
        lines.append("_No computed insights available._")

    return "\n".join(lines)


def _render_authenticity(authenticity: dict) -> str:
    """Render authenticity score and flags."""
    if not authenticity:
        return ""
    score = authenticity.get("score", 0)
    label = authenticity.get("label", "Unknown")
    lines = [_section("Authenticity Score", 3)]
    lines.append(f"**Score: {score}/100 ({label})**\n")
    for flag in authenticity.get("flags", []):
        if flag.get("pass") is None:
            continue
        icon = "PASS" if flag["pass"] else "FLAG"
        lines.append(f"- [{icon}] **{flag['check'].replace('_', ' ').title()}**: {flag['message']}")
    return "\n".join(lines)


def _render_tax_compliance_report(tax_compliance: dict, currency: str) -> str:
    """Render tax compliance verification."""
    if not tax_compliance:
        return ""
    lines = [_section("Tax Compliance Verification", 3)]
    lines.append(f"**Verdict: {tax_compliance.get('verdict', 'N/A').replace('_', ' ').title()}**\n")
    rng = tax_compliance.get("expected_tds_range", {})
    rows = [
        ("Annualised Gross", _fmt_money(tax_compliance.get("annual_gross"), currency)),
        ("Standard Deduction", _fmt_money(tax_compliance.get("standard_deduction"), currency)),
        ("Est. HRA Exemption", _fmt_money(tax_compliance.get("hra_exemption_estimate"), currency)),
        ("Expected TDS Range", f"{_fmt_money(rng.get('low'), currency)} – {_fmt_money(rng.get('high'), currency)}"),
        ("Actual Annual TDS", _fmt_money(tax_compliance.get("actual_annual_tds"), currency)),
    ]
    for label, val in rows:
        lines.append(f"- **{label}:** {val}")
    lines.append(f"\n{tax_compliance.get('verdict_detail', '')}")
    return "\n".join(lines)


def _render_employer_signals_report(employer_signals: dict) -> str:
    """Render employer compliance signals."""
    if not employer_signals:
        return ""
    pos = employer_signals.get("positive_count", 0)
    total = employer_signals.get("total_assessable", 0)
    lines = [_section("Employer Compliance Signals", 3)]
    lines.append(f"**{pos} of {total} assessable signals positive**\n")
    for sig in employer_signals.get("signals", []):
        if sig.get("present") is True:
            icon = "YES"
        elif sig.get("present") is False:
            icon = "NO"
        else:
            icon = "N/A"
        lines.append(f"- [{icon}] **{sig['label']}** — {sig['detail']}")
    return "\n".join(lines)


def _render_income_projection_report(projection: dict, currency: str) -> str:
    """Render income projection summary."""
    if not projection:
        return ""
    lines = [_section("Income Trend Projection", 3)]
    trajectory = projection.get("trajectory", "Flat")
    arrows = {"Positive": "UP", "Flat": "FLAT", "Declining": "DOWN"}
    lines.append(f"**Trajectory: {trajectory} ({arrows.get(trajectory, 'FLAT')})**\n")
    lines.append(f"- Growth rate: {projection.get('monthly_growth_pct', 0) * 100:.1f}%/month")
    lines.append(f"- Current net: {_fmt_money(projection.get('current_net'), currency)}")
    lines.append(f"- Projected net (12 months): {_fmt_money(projection.get('projected_net_12m'), currency)}")
    lines.append(f"- Data points: {projection.get('data_points', 0)}")
    lines.append(f"- R-squared: {projection.get('r_squared', 0):.3f}")
    return "\n".join(lines)


def _render_prescription(prescription: dict) -> str:
    """Version B only — show what Gemini approved, skipped, and why."""
    if not prescription:
        return ""
    lines = [_section("Prescription Details (Version B)", 3)]

    run = prescription.get("run_hardcoded", {})
    skip_reasons = prescription.get("skip_reasons", {})

    if run:
        approved = [k for k, v in run.items() if v]
        skipped = [k for k, v in run.items() if not v]
        lines.append(f"**Approved to run ({len(approved)}):** {', '.join(approved) if approved else 'none'}")
        lines.append(f"**Skipped ({len(skipped)}):** {', '.join(skipped) if skipped else 'none'}")
        lines.append("")

    if skip_reasons:
        lines.append("**Skip Reasons**")
        for key, reason in skip_reasons.items():
            lines.append(f"  - `{key}`: {reason}")
        lines.append("")

    return "\n".join(lines)


def _render_raw_extras(data: dict) -> str:
    extras = data.get("raw_extras", {})
    if not extras:
        return ""
    lines = [_section("Other Extracted Fields", 3)]
    for k, v in extras.items():
        lines.append(f"- **{k}:** {v}")
    return "\n".join(lines)


_CONF_SECTION_MAP = {
    "employer_details": "employer",
    "employee_details": "employee",
    "pay_period": "attendance",
}


def _get_value_for_conf_path(data: dict, conf_path: str):
    """Map a Gemini confidence path to the normalised data value."""
    parts = conf_path.split(".")
    first = _CONF_SECTION_MAP.get(parts[0], parts[0])
    current = data
    for part in [first] + parts[1:]:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _render_confidence(data: dict) -> str:
    confidence = data.get("_confidence", {})
    if not confidence:
        return ""

    low_fields = []

    def _collect(conf, prefix=""):
        for k, v in conf.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                _collect(v, path)
            elif v == "low":
                low_fields.append(path)

    _collect(confidence)

    # Bug 2: only keep fields whose value is actually non-null in the data.
    # Null fields with "low" confidence = Gemini was confident the field wasn't there.
    # That is NOT the same as a hard-to-read value that needs verification.
    low_fields = [f for f in low_fields if _get_value_for_conf_path(data, f) is not None]

    if not low_fields:
        return ""

    lines = [_section("Low-Confidence Extractions", 3)]
    lines.append("These fields were extracted with low confidence and should be verified:")
    for f in low_fields:
        lines.append(f"  - `{f}`")
    return "\n".join(lines)


def _render_batch_analysis(results: list, consistency: dict) -> str:
    if len(results) < 2:
        return ""
    lines = [_section("Batch Analysis (Month-on-Month)", 2)]

    headers = ["Pay Period", "Gross", "Net", "Total Deductions", "Take-Home %"]
    rows = []
    for p in results:
        label = (p.get("document_meta", {}).get("pay_period_label")
                 or p.get("_source_file", "?"))
        currency = p.get("document_meta", {}).get("currency", "INR")
        gross = p.get("earnings", {}).get("gross_salary")
        net = p.get("net_pay", {}).get("net_salary")
        ded = p.get("deductions", {}).get("total_deductions")
        th = f"{net / gross * 100:.1f}%" if gross and net else "N/A"
        rows.append([
            label,
            _fmt_money(gross, currency),
            _fmt_money(net, currency),
            _fmt_money(ded, currency),
            th,
        ])
    lines.append(_table(headers, rows))

    if consistency:
        label = consistency.get("consistency_label", "unknown").replace("_", " ").title()
        cv = consistency.get("consistency_coefficient", 0)
        avg = consistency.get("avg_monthly_net", 0)
        currency = results[0].get("document_meta", {}).get("currency", "INR") if results else "INR"
        lines.append(f"\n**Consistency verdict:** {label} (CV: {cv * 100:.1f}%)")
        lines.append(f"**Average monthly net:** {_fmt_money(avg, currency)}")

    return "\n".join(lines)


def _render_loan_signals(data: dict, insights: dict, consistency: dict) -> str:
    currency = data.get("document_meta", {}).get("currency", "INR")
    annual = insights.get("monthly_to_annual_conversion") or {}
    monthly_net = annual.get("monthly_net") or data.get("net_pay", {}).get("net_salary")
    monthly_gross = annual.get("monthly_gross") or data.get("earnings", {}).get("gross_salary")
    annual_gross = annual.get("annual_gross")
    pf_amount = data.get("deductions", {}).get("pf_epf")
    freq = data.get("document_meta", {}).get("salary_frequency", "monthly")
    # Bug 1: assumption is None for monthly payslips — provide a sensible default
    annual_source = annual.get("assumption") or f"{freq} gross × {12 if freq == 'monthly' else '?'}"
    employment_date_str = data.get("employee", {}).get("employment_date")

    tenure_str = "Not specified"
    if employment_date_str:
        try:
            emp_dt = date.fromisoformat(employment_date_str)
            months = round((date.today() - emp_dt).days / 30.44, 1)
            tenure_str = f"{months} months"
        except (ValueError, TypeError):
            pass

    consistency_str = "Single payslip — N/A"
    if consistency:
        lbl = consistency.get("consistency_label", "").replace("_", " ").title()
        cv = consistency.get("consistency_coefficient", 0)
        consistency_str = f"{lbl} ({cv * 100:.1f}% variation)"

    lines = [_section("Loan Pre-Screening Signals", 2)]
    headers = ["Signal", "Value", "Source"]
    is_avg = data.get("_is_batch_average", False)
    salary_src = "Batch average" if is_avg else "Extracted / estimated"
    rows = [
        ["Monthly net take-home", _fmt_money(monthly_net, currency), salary_src],
        ["Monthly gross salary", _fmt_money(monthly_gross, currency), salary_src],
        ["Annual CTC", _fmt_money(annual_gross, currency), f"Calculated ({annual_source})"],
        ["Employer", data.get("employer", {}).get("name") or "Not specified", "Extracted"],
        ["Employment date", employment_date_str or "Not specified", "Extracted"],
        ["Calculated tenure", tenure_str, "Calculated"],
        ["Salary frequency", freq.title(), "Detected"],
        ["Salary consistency", consistency_str, "Calculated" if consistency else "N/A"],
        ["PF deduction confirmed",
         f"Yes — {_fmt_money(pf_amount, currency)}/month" if pf_amount else "Not detected",
         "Extracted"],
    ]
    lines.append(_table(headers, rows))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def generate_report(
    version: str,
    results: list,
    insights_list: list,
    prescriptions_list: list,
    consistency: dict,
    processing_time: float,
    *,
    authenticity_scores: list = None,
    tax_compliance_results: list = None,
    employer_signals_results: list = None,
    income_projection: dict = None,
) -> Path:
    """
    Generate a Markdown report for the current session.

    Returns the path to the saved report file.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = REPORTS_DIR / f"report_v{version}_{timestamp}.md"

    source_files = [r.get("_source_file", "unknown") for r in results]
    sections = []

    # --- Header ---
    sections.append(_render_session_header(version, timestamp.replace("_", " "), source_files))
    sections.append(_render_version_note(version))
    sections.append(f"**Processing time:** {processing_time:.1f}s  \n")

    # --- Per-payslip sections ---
    for i, (data, insights) in enumerate(zip(results, insights_list)):
        source = data.get("_source_file", f"Payslip {i + 1}")
        pay_period = data.get("document_meta", {}).get("pay_period_label", "")
        title = f"Payslip {i + 1}: {source}" + (f" ({pay_period})" if pay_period else "")
        sections.append(_section(title, 2))

        sections.append(_render_document_meta(data))
        sections.append(_render_employee_employer(data))
        att = _render_attendance(data)
        if att:
            sections.append(att)
        sections.append(_render_earnings(data))
        sections.append(_render_deductions(data))
        sections.append(_render_net_pay(data))
        sections.append(_render_insights(insights, version, data.get("document_meta", {}).get("currency", "INR")))

        # Enhancement sections
        currency = data.get("document_meta", {}).get("currency", "INR")
        if authenticity_scores and i < len(authenticity_scores) and authenticity_scores[i]:
            sections.append(_render_authenticity(authenticity_scores[i]))
        if tax_compliance_results and i < len(tax_compliance_results) and tax_compliance_results[i]:
            sections.append(_render_tax_compliance_report(tax_compliance_results[i], currency))
        if employer_signals_results and i < len(employer_signals_results) and employer_signals_results[i]:
            sections.append(_render_employer_signals_report(employer_signals_results[i]))

        # Version B prescription
        prescription = None
        if prescriptions_list and i < len(prescriptions_list):
            prescription = prescriptions_list[i]
        if version == "B" and prescription:
            sections.append(_render_prescription(prescription))

        extras = _render_raw_extras(data)
        if extras:
            sections.append(extras)

        conf = _render_confidence(data)
        if conf:
            sections.append(conf)

        sections.append("\n---")

    # --- Batch analysis ---
    batch = _render_batch_analysis(results, consistency)
    if batch:
        sections.append(batch)

    # Income projection (batch, 3+ payslips)
    if income_projection:
        currency = results[0].get("document_meta", {}).get("currency", "INR") if results else "INR"
        sections.append(_render_income_projection_report(income_projection, currency))

    if batch or income_projection:
        sections.append("\n---")

    # --- Loan signals (use batch average if multiple payslips) ---
    if results and insights_list:
        if len(results) > 1:
            nets = [r.get("net_pay", {}).get("net_salary") for r in results if r.get("net_pay", {}).get("net_salary")]
            grosses = [r.get("earnings", {}).get("gross_salary") for r in results if r.get("earnings", {}).get("gross_salary")]
            avg_data = dict(results[0])
            avg_data["net_pay"] = dict(results[0].get("net_pay", {}))
            avg_data["earnings"] = dict(results[0].get("earnings", {}))
            if nets:
                avg_data["net_pay"]["net_salary"] = round(sum(nets) / len(nets), 2)
            if grosses:
                avg_data["earnings"]["gross_salary"] = round(sum(grosses) / len(grosses), 2)
            from calculator.insights import compute_annual_figures, compute_take_home_ratio
            avg_insights = {
                "monthly_to_annual_conversion": compute_annual_figures(avg_data),
                "take_home_ratio": compute_take_home_ratio(avg_data),
            }
            sections.append(_render_loan_signals(avg_data, avg_insights, consistency))
        else:
            sections.append(_render_loan_signals(results[0], insights_list[0], consistency))

    # Write file
    content = "\n".join(sections)
    filename.write_text(content, encoding="utf-8")
    return filename
