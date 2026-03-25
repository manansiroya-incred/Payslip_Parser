"""
Reusable Streamlit UI components for the Payslip Parser.

All functions render directly into the active Streamlit context.
Data is passed as arguments — no direct session_state access.
"""

import json
import streamlit as st
import pandas as pd
from typing import Optional

from .charts import earnings_stacked_bar, deductions_donut, salary_trend_line


# ---------------------------------------------------------------------------
# Human-readable field labels (Issue 3B fix)
# ---------------------------------------------------------------------------
FIELD_LABELS = {
    "employer_details.name": "Employer name",
    "employer_details.address": "Employer address",
    "employer_details.department": "Department",
    "employee_details.name": "Employee name",
    "employee_details.employee_id": "Employee ID",
    "employee_details.date_of_birth": "Date of birth",
    "employee_details.address": "Employee address",
    "employee_details.job_title": "Job title",
    "employee_details.employment_date": "Employment date",
    "employee_details.bank_account": "Bank account",
    "document_meta.date_of_issue": "Date of issue",
    "document_meta.pay_period_label": "Pay period",
    "document_meta.pay_period_start": "Pay period start",
    "document_meta.pay_period_end": "Pay period end",
    "document_meta.salary_frequency": "Salary frequency",
    "pay_period.days_worked": "Days worked",
    "pay_period.hours_worked": "Hours worked",
    "pay_period.hourly_rate": "Hourly rate",
    "pay_period.days_in_period": "Days in period",
    "earnings.basic_salary": "Basic salary",
    "earnings.hra": "HRA",
    "earnings.lta": "LTA",
    "earnings.special_allowance": "Special allowance",
    "earnings.overtime": "Overtime",
    "earnings.bonus": "Bonus",
    "earnings.gross_salary": "Gross salary",
    "deductions.tds_income_tax": "TDS / Income tax",
    "deductions.pf_epf": "PF / EPF",
    "deductions.professional_tax": "Professional tax",
    "deductions.gratuity": "Gratuity",
    "deductions.esic": "ESIC",
    "deductions.loan_deduction": "Loan deduction",
    "deductions.total_deductions": "Total deductions",
    "net_pay.net_salary": "Net salary",
    "net_pay.ctc_mentioned": "CTC mentioned",
    # Normalised schema paths (after normaliser renames sections)
    "employer.name": "Employer name",
    "employer.address": "Employer address",
    "employer.department": "Department",
    "employee.name": "Employee name",
    "employee.employee_id": "Employee ID",
    "employee.date_of_birth": "Date of birth",
    "employee.address": "Employee address",
    "employee.job_title": "Job title",
    "employee.employment_date": "Employment date",
    "employee.bank_account": "Bank account",
    "attendance.days_worked": "Days worked",
    "attendance.hours_worked": "Hours worked",
    "attendance.hourly_rate": "Hourly rate",
    "attendance.days_in_period": "Days in period",
}


def _field_label(path: str) -> str:
    """Convert an internal field path to a human-readable label."""
    if path in FIELD_LABELS:
        return FIELD_LABELS[path]
    # Fallback: take the last segment and title-case it
    return path.split(".")[-1].replace("_", " ").title()


def _get_frequency_label(data: dict) -> str:
    """Get the capitalised frequency label for column headers."""
    freq = data.get("document_meta", {}).get("salary_frequency", "monthly") or "monthly"
    return freq.capitalize()


# ---------------------------------------------------------------------------
# Currency symbols
# ---------------------------------------------------------------------------
_CURRENCY_SYMBOLS = {
    "INR": "\u20b9",
    "USD": "$",
    "EUR": "\u20ac",
    "GBP": "\u00a3",
}


def _get_currency_symbol(data: dict) -> str:
    """Get the currency symbol from document metadata."""
    currency = data.get("document_meta", {}).get("currency", "INR") or "INR"
    return _CURRENCY_SYMBOLS.get(currency.upper(), currency)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fmt_indian(val: float) -> str:
    """Format a number using Indian comma placement (e.g. 1116000 → 11,16,000.00)."""
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


def _fmt_currency(val, symbol: str = "\u20b9") -> str:
    """Format a number as currency string. Uses Indian comma style for ₹."""
    if val is None:
        return "Not specified"
    try:
        f = float(val)
    except (ValueError, TypeError):
        return str(val)
    if symbol == "\u20b9":
        return f"\u20b9{_fmt_indian(f)}"
    return f"{symbol}{f:,.2f}"


def _fmt_pct(val) -> str:
    """Format a ratio (0-1) as percentage string."""
    if val is None:
        return "N/A"
    try:
        return f"{float(val) * 100:.1f}%"
    except (ValueError, TypeError):
        return str(val)


# ---------------------------------------------------------------------------
# Tab 1, Section 1: Employee and employer header
# ---------------------------------------------------------------------------
def render_employee_header(data: dict):
    """Render employee name, job title, employer, pay period as a header card."""
    employee = data.get("employee", {})
    employer = data.get("employer", {})
    doc_meta = data.get("document_meta", {})

    name = employee.get("name") or "Unknown Employee"
    job_title = employee.get("job_title") or ""
    department = employer.get("department") or ""
    employer_name = employer.get("name") or ""
    pay_period = doc_meta.get("pay_period_label") or ""
    frequency = (doc_meta.get("salary_frequency") or "monthly").title()

    subtitle_parts = [p for p in [job_title, department] if p]
    subtitle = " | ".join(subtitle_parts) if subtitle_parts else ""

    st.markdown(f"""
    <div class="employee-header">
        <h2>{name}</h2>
        <div class="subtitle">{subtitle}</div>
        <div class="meta">
            <div class="meta-item"><strong>Employer:</strong> {employer_name}</div>
            <div class="meta-item"><strong>Pay Period:</strong> {pay_period}</div>
            <div class="meta-item"><strong>Frequency:</strong> {frequency}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Tab 1, Section 2: Salary summary
# ---------------------------------------------------------------------------
def render_salary_summary(data: dict, insights: dict):
    """4 metric cards + narrative summary sentence."""
    cs = _get_currency_symbol(data)
    net = data.get("net_pay", {}).get("net_salary")
    gross = data.get("earnings", {}).get("gross_salary")
    freq = data.get("document_meta", {}).get("salary_frequency", "monthly") or "monthly"
    freq_label = freq.capitalize()

    # Get annual from insights
    annual_data = insights.get("monthly_to_annual_conversion") or {}
    annual_ctc = annual_data.get("annual_gross")
    monthly_net = annual_data.get("monthly_net")
    monthly_gross = annual_data.get("monthly_gross")
    is_estimated = annual_data.get("is_estimated", False)
    assumption = annual_data.get("assumption")

    # Take-home ratio
    th_data = insights.get("take_home_ratio") or {}
    th_pct = th_data.get("take_home_pct", "N/A")

    # CTC label changes based on whether it's stated or estimated
    ctc_label = "Annual CTC (est.)" if is_estimated else "Annual CTC"

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if is_estimated and monthly_net:
            st.metric("Monthly Net (est.)", _fmt_currency(monthly_net, cs),
                      help=f"Estimated from {freq_label.lower()} net of {_fmt_currency(net, cs)}")
        else:
            st.metric("Monthly Net", _fmt_currency(net, cs), help="Take-home pay")
    with col2:
        if is_estimated and monthly_gross:
            st.metric("Monthly Gross (est.)", _fmt_currency(monthly_gross, cs),
                      help=f"Estimated from {freq_label.lower()} gross of {_fmt_currency(gross, cs)}")
        else:
            st.metric("Monthly Gross", _fmt_currency(gross, cs), help="Before deductions")
    with col3:
        st.metric(ctc_label, _fmt_currency(annual_ctc, cs),
                  help=f"Estimated: {assumption}" if assumption else "Annualised")
    with col4:
        st.metric("Take-Home", th_pct, help="% of gross")

    # Show assumption note for non-monthly payslips
    if is_estimated and assumption:
        st.caption(f"Estimated: {assumption}")

    # Narrative sentence
    display_net = monthly_net if is_estimated else net
    display_gross = monthly_gross if is_estimated else gross
    if display_net and display_gross and annual_ctc:
        est_note = " (estimated)" if is_estimated else ""
        st.markdown(
            f"> This employee takes home **{_fmt_currency(display_net, cs)}** per month{est_note} "
            f"after deductions, representing **{th_pct}** of their gross salary "
            f"of **{_fmt_currency(display_gross, cs)}**. Their annualised income is "
            f"**{_fmt_currency(annual_ctc, cs)}**{est_note}."
        )


# ---------------------------------------------------------------------------
# Tab 1, Section 3: Earnings breakdown
# ---------------------------------------------------------------------------
def render_earnings_breakdown(data: dict):
    """Stacked bar chart (left) + earnings table (right)."""
    earnings = data.get("earnings", {})
    gross = earnings.get("gross_salary") or 0
    freq_label = _get_frequency_label(data)
    cs = _get_currency_symbol(data)
    amount_col = f"{freq_label} ({cs})"

    col_chart, col_table = st.columns([3, 2])

    with col_chart:
        fig = earnings_stacked_bar(earnings, cs)
        st.plotly_chart(fig, use_container_width=True)

    with col_table:
        rows = []
        standard_fields = [
            ("Basic Salary", "basic_salary"),
            ("HRA", "hra"),
            ("LTA", "lta"),
            ("Special Allowance", "special_allowance"),
            ("Overtime", "overtime"),
            ("Bonus", "bonus"),
        ]
        for label, key in standard_fields:
            val = earnings.get(key)
            if val is not None:
                pct = f"{val / gross * 100:.1f}%" if gross > 0 else "N/A"
                rows.append({"Component": label, amount_col: f"{val:,.2f}", "% of Gross": pct})

        # Other earnings
        other = earnings.get("other_earnings", {})
        if isinstance(other, dict):
            for name, val in other.items():
                if val is not None and isinstance(val, (int, float)):
                    pct = f"{val / gross * 100:.1f}%" if gross > 0 else "N/A"
                    rows.append({
                        "Component": name.replace("_", " ").title(),
                        amount_col: f"{val:,.2f}",
                        "% of Gross": pct,
                    })

        if gross > 0:
            rows.append({
                "Component": "**Total (Gross)**",
                amount_col: f"**{gross:,.2f}**",
                "% of Gross": "**100%**",
            })

        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Tab 1, Section 4: Deductions analysis
# ---------------------------------------------------------------------------
def render_deductions_analysis(data: dict, insights: dict):
    """Donut chart (left) + deductions table (right) + commentary."""
    deductions = data.get("deductions", {})
    gross = data.get("earnings", {}).get("gross_salary") or 0
    total_ded = deductions.get("total_deductions")
    freq_label = _get_frequency_label(data)
    cs = _get_currency_symbol(data)
    amount_col = f"{freq_label} ({cs})"

    col_chart, col_table = st.columns([3, 2])

    with col_chart:
        fig = deductions_donut(deductions, total_ded, cs)
        st.plotly_chart(fig, use_container_width=True)

    with col_table:
        rows = []
        standard_fields = [
            ("TDS / Income Tax", "tds_income_tax"),
            ("PF / EPF", "pf_epf"),
            ("Professional Tax", "professional_tax"),
            ("Gratuity", "gratuity"),
            ("ESIC", "esic"),
            ("Loan Deduction", "loan_deduction"),
        ]
        for label, key in standard_fields:
            val = deductions.get(key)
            if val is not None and isinstance(val, (int, float)):
                pct = f"{val / gross * 100:.1f}%" if gross > 0 else "N/A"
                rows.append({"Component": label, amount_col: f"{val:,.2f}", "% of Gross": pct})

        # Other deductions
        other = deductions.get("other_deductions", {})
        if isinstance(other, dict):
            for name, val in other.items():
                if val is not None and isinstance(val, (int, float)):
                    pct = f"{val / gross * 100:.1f}%" if gross > 0 else "N/A"
                    rows.append({
                        "Component": name.replace("_", " ").title(),
                        amount_col: f"{val:,.2f}",
                        "% of Gross": pct,
                    })

        if total_ded:
            pct = f"{total_ded / gross * 100:.1f}%" if gross > 0 else "N/A"
            rows.append({
                "Component": "**Total Deductions**",
                amount_col: f"**{total_ded:,.2f}**",
                "% of Gross": f"**{pct}**",
            })

        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Deduction commentary
    commentary_parts = []
    tds_data = insights.get("effective_tds_rate")
    if tds_data and not tds_data.get("error") and not tds_data.get("skipped"):
        # Handle Python format (tds_pct) and Gemini Version A format (value + unit)
        tds_pct = tds_data.get("tds_pct")
        if not tds_pct and tds_data.get("value") is not None:
            # Gemini format already includes unit like "% of gross" — use as-is
            tds_pct = f"{tds_data['value']} {tds_data.get('unit', '% of gross')}"
        if tds_pct:
            # If tds_pct already contains "of gross" (Gemini format), don't append it again
            if "of gross" in str(tds_pct).lower():
                commentary_parts.append(f"Effective TDS rate is {tds_pct}.")
            else:
                commentary_parts.append(f"Effective TDS rate is {tds_pct} of gross salary.")
    pf_data = insights.get("pf_as_pct_of_basic")
    if pf_data and not pf_data.get("error") and not pf_data.get("skipped"):
        # Handle Python format (pf_basic_pct) and Gemini Version A format (value + unit)
        pf_pct = pf_data.get("pf_basic_pct")
        pf_amount = pf_data.get("pf_amount")
        if not pf_pct and pf_data.get("value") is not None:
            pf_pct = f"{pf_data['value']} {pf_data.get('unit', '% of basic')}"
        if pf_pct:
            cs = _get_currency_symbol(data)
            amt_str = f" ({_fmt_currency(pf_amount, cs)}/month)" if pf_amount else ""
            commentary_parts.append(f"PF contribution is {pf_pct} of basic salary{amt_str}.")
    if commentary_parts:
        st.info(" ".join(commentary_parts))


# ---------------------------------------------------------------------------
# Tab 1, Section 5: Employment profile
# ---------------------------------------------------------------------------
def render_employment_profile(data: dict, insights: dict):
    """Two-column fact sheet."""
    employee = data.get("employee", {})
    attendance = data.get("attendance", {})
    gratuity_data = insights.get("gratuity_accrual_estimate") or {}

    fields = [
        ("Employment Date", employee.get("employment_date") or "Not specified"),
        ("Tenure", f"{gratuity_data['tenure_years']:.1f} years" if gratuity_data.get("tenure_years") else "Not specified"),
        ("Bank Account", employee.get("bank_account") or "Not specified"),
        ("Days Worked", f"{attendance.get('days_worked') or 'Not specified'}" +
            (f" of {int(attendance['days_in_period'])}" if attendance.get("days_in_period") else "")),
        ("Hours Worked", attendance.get("hours_worked") or "Not specified"),
        ("Hourly Rate", _fmt_currency(attendance.get("hourly_rate")) if attendance.get("hourly_rate") else "Not specified"),
    ]

    col1, col2 = st.columns(2)
    for i, (label, value) in enumerate(fields):
        with col1 if i % 2 == 0 else col2:
            st.markdown(f"**{label}:** {value}")


# ---------------------------------------------------------------------------
# Tab 1, Section 6: Non-standard components
# ---------------------------------------------------------------------------
def render_non_standard_components(data: dict, gemini_computed: dict):
    """Show non-standard components with Gemini's insights.

    Only renders when gemini_computed_insights contains entries that are
    NOT already shown in the earnings or deductions tables. Items that
    appear in other_earnings or other_deductions are already displayed
    in the breakdown tables — do not duplicate them here.
    """
    # Filter gemini_computed to only items NOT already in the tables
    # (other_earnings and other_deductions are already shown in Sections 3 & 4)
    other_earn_keys = set()
    other_ded_keys = set()
    other_earn = data.get("earnings", {}).get("other_earnings", {})
    other_ded = data.get("deductions", {}).get("other_deductions", {})
    if isinstance(other_earn, dict):
        other_earn_keys = set(other_earn.keys())
    if isinstance(other_ded, dict):
        other_ded_keys = set(other_ded.keys())

    already_shown = other_earn_keys | other_ded_keys

    # Only show gemini_computed insights that aren't duplicates
    unique_insights = {}
    if isinstance(gemini_computed, dict):
        for key, insight in gemini_computed.items():
            # Skip if this key matches something already in the tables
            if key not in already_shown:
                unique_insights[key] = insight

    if not unique_insights:
        return

    st.markdown("### Additional Components Found")
    st.markdown('<div class="non-standard-card">', unsafe_allow_html=True)

    for key, insight in unique_insights.items():
        if isinstance(insight, dict):
            label = insight.get("label", key.replace("_", " ").title())
            desc = insight.get("description", "")
            value = insight.get("value")
            unit = insight.get("unit", "")
            if value is not None:
                st.markdown(f"- **{label}** — {value} {unit}")
                if desc:
                    st.caption(f"  {desc}")
            elif desc:
                st.markdown(f"- **{label}** — {desc}")

    st.markdown('</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Tab 1, Section 7: Data quality notice
# ---------------------------------------------------------------------------
def render_data_quality_notice(data: dict):
    """Show missing/low-confidence field warnings. Only if there are issues."""
    confidence = data.get("_confidence", {})
    if not confidence:
        return

    low_confidence_paths = []
    _collect_low_confidence(confidence, "", low_confidence_paths)

    # Only keep fields that are actually non-null in the data.
    # A null field with "low" confidence means Gemini was confident it wasn't there
    # — not that it was hard to read. These must not appear as warnings.
    low_confidence_paths = [
        p for p in low_confidence_paths
        if _get_value_for_conf_path(data, p) is not None
    ]

    # Convert raw paths to human-readable labels
    low_confidence_labels = [_field_label(path) for path in low_confidence_paths]
    # Deduplicate while preserving order
    seen = set()
    low_confidence_labels = [
        x for x in low_confidence_labels
        if not (x in seen or seen.add(x))
    ]

    # Check for missing critical fields
    missing = []
    critical_paths = [
        ("Employee name", data.get("employee", {}).get("name")),
        ("Gross salary", data.get("earnings", {}).get("gross_salary")),
        ("Net salary", data.get("net_pay", {}).get("net_salary")),
    ]
    for label, val in critical_paths:
        if not val:
            missing.append(label)

    if missing:
        st.warning(f"Some fields could not be extracted: {', '.join(missing)}")

    if low_confidence_labels:
        st.info(f"These values should be verified against the original: {', '.join(low_confidence_labels)}")


def _collect_low_confidence(conf: dict, prefix: str, results: list):
    """Recursively collect fields with low confidence."""
    for k, v in conf.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            _collect_low_confidence(v, path, results)
        elif v == "low":
            results.append(path)


# Gemini's confidence keys use pre-normalisation names; map to normalised data keys
_CONF_SECTION_MAP = {
    "employer_details": "employer",
    "employee_details": "employee",
    "pay_period": "attendance",
}


def _get_value_for_conf_path(data: dict, conf_path: str):
    """Look up the actual data value for a confidence key path.

    Confidence uses Gemini's raw key names (employer_details, pay_period, etc.)
    while the normalised data uses shorter names (employer, attendance, etc.).
    """
    parts = conf_path.split(".")
    first = _CONF_SECTION_MAP.get(parts[0], parts[0])
    current = data
    for part in [first] + parts[1:]:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


# ---------------------------------------------------------------------------
# Tab 2: Consistency verdict card
# ---------------------------------------------------------------------------
def render_consistency_verdict(consistency: dict):
    """Render green/amber verdict card for salary consistency."""
    if not consistency:
        return

    label = consistency.get("consistency_label", "unknown")
    cv = consistency.get("consistency_coefficient", 0)
    avg = consistency.get("avg_monthly_net", 0)
    n = consistency.get("num_payslips", 0)

    if label == "consistent":
        css_class = "verdict-good"
        icon = "✅"
        title = "SALARY IS CONSISTENT"
    elif label == "minor_variation":
        css_class = "verdict-warn"
        icon = "⚠️"
        title = "SALARY SHOWS MINOR VARIATION"
    else:
        css_class = "verdict-bad"
        icon = "⚠️"
        title = "SALARY SHOWS SIGNIFICANT VARIATION"

    st.markdown(f"""
    <div class="verdict-card {css_class}">
        <div style="font-size: 1.2rem;">{icon} {title}</div>
        <div>Variation: {cv * 100:.1f}% across {n} months</div>
        <div>Average monthly take-home: {_fmt_currency(avg)}</div>
    </div>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Tab 2: Month-by-month comparison table
# ---------------------------------------------------------------------------
def render_month_comparison_table(payslips: list[dict]):
    """Comparison table with Gross/Net/TDS/PF/Total/Take-home% per month."""
    rows = []
    for p in payslips:
        label = (
            p.get("document_meta", {}).get("pay_period_label")
            or p.get("_source_file", "Unknown")
        )
        gross = p.get("earnings", {}).get("gross_salary") or 0
        net = p.get("net_pay", {}).get("net_salary") or 0
        tds = p.get("deductions", {}).get("tds_income_tax") or 0
        pf = p.get("deductions", {}).get("pf_epf") or 0
        total_ded = p.get("deductions", {}).get("total_deductions") or 0
        th_pct = f"{net / gross * 100:.1f}%" if gross > 0 else "N/A"

        rows.append({
            "Month": label,
            "Gross (₹)": f"{gross:,.0f}",
            "Net (₹)": f"{net:,.0f}",
            "TDS (₹)": f"{tds:,.0f}",
            "PF (₹)": f"{pf:,.0f}",
            "Total Deductions (₹)": f"{total_ded:,.0f}",
            "Take-home %": th_pct,
        })

    # Average row
    if len(rows) >= 2:
        avg_gross = sum(p.get("earnings", {}).get("gross_salary") or 0 for p in payslips) / len(payslips)
        avg_net = sum(p.get("net_pay", {}).get("net_salary") or 0 for p in payslips) / len(payslips)
        avg_tds = sum(p.get("deductions", {}).get("tds_income_tax") or 0 for p in payslips) / len(payslips)
        avg_pf = sum(p.get("deductions", {}).get("pf_epf") or 0 for p in payslips) / len(payslips)
        avg_ded = sum(p.get("deductions", {}).get("total_deductions") or 0 for p in payslips) / len(payslips)
        avg_th = f"{avg_net / avg_gross * 100:.1f}%" if avg_gross > 0 else "N/A"

        rows.append({
            "Month": "**Average**",
            "Gross (₹)": f"**{avg_gross:,.0f}**",
            "Net (₹)": f"**{avg_net:,.0f}**",
            "TDS (₹)": f"**{avg_tds:,.0f}**",
            "PF (₹)": f"**{avg_pf:,.0f}**",
            "Total Deductions (₹)": f"**{avg_ded:,.0f}**",
            "Take-home %": f"**{avg_th}**",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Tab 3: Loan signals
# ---------------------------------------------------------------------------
def render_loan_signals(data: dict, insights: dict, consistency: Optional[dict], commentary: str):
    """Pre-fill values table + loan parameters + EMI calculation + commentary."""
    cs = _get_currency_symbol(data)
    st.caption("Data for loan pre-screening — these values will be used to pre-fill the loan eligibility application.")

    from datetime import date as _date
    annual_data = insights.get("monthly_to_annual_conversion") or {}
    th_data = insights.get("take_home_ratio") or {}

    # Read PF directly from extracted data — don't depend on insight being run
    pf_amount = data.get("deductions", {}).get("pf_epf")

    # Compute tenure directly — don't rely on gratuity insight being run
    employment_date_str = data.get("employee", {}).get("employment_date")
    tenure_display = "Not specified"
    if employment_date_str:
        try:
            emp_dt = _date.fromisoformat(employment_date_str)
            months = round((_date.today() - emp_dt).days / 30.44, 1)
            tenure_display = f"{months} months"
        except (ValueError, TypeError):
            pass

    # Use monthly net from annual_data (handles frequency conversion)
    monthly_net = annual_data.get("monthly_net") or data.get("net_pay", {}).get("net_salary")

    signals = [
        ("Monthly net take-home", _fmt_currency(monthly_net, cs), "Extracted / estimated"),
        ("Monthly gross salary", _fmt_currency(annual_data.get("monthly_gross") or data.get("earnings", {}).get("gross_salary"), cs), "Extracted / estimated"),
        ("Annual CTC", _fmt_currency(annual_data.get("annual_gross"), cs), f"Calculated ({annual_data.get('assumption', 'gross x 12')})"),
        ("Employer name", data.get("employer", {}).get("name") or "Not specified", "Extracted"),
        ("Employment date", employment_date_str or "Not specified", "Extracted"),
        ("Calculated tenure", tenure_display, "Calculated"),
        ("Salary consistency", f"{consistency['consistency_label'].replace('_', ' ').title()} ({consistency['consistency_coefficient'] * 100:.1f}% variation)" if consistency else "Single payslip — N/A", "Calculated" if consistency else "N/A"),
        ("Salary frequency", (data.get("document_meta", {}).get("salary_frequency") or "monthly").title(), "Detected"),
        ("PF deduction confirmed", f"Yes — {_fmt_currency(pf_amount, cs)}/month" if pf_amount else "Not detected", "Extracted"),
    ]

    # Show YTD data if available
    ytd_gross = data.get("raw_extras", {}).get("YTD GROSS") or data.get("raw_extras", {}).get("YTD_GROSS")
    ytd_net = data.get("raw_extras", {}).get("YTD NET PAY") or data.get("raw_extras", {}).get("YTD_NET_PAY")
    if ytd_gross:
        signals.append(("YTD Gross", _fmt_currency(ytd_gross, cs), "Extracted from payslip"))
    if ytd_net:
        signals.append(("YTD Net Pay", _fmt_currency(ytd_net, cs), "Extracted from payslip"))

    df = pd.DataFrame(signals, columns=["Signal", "Value", "Source"])
    st.dataframe(df, use_container_width=True, hide_index=True)

    # --- Loan Parameters & EMI Calculation ---
    st.markdown("### Loan Parameters")
    col1, col2, col3 = st.columns(3)
    with col1:
        loan_amount = st.number_input(
            "Loan amount sought",
            min_value=0, max_value=100_000_000, value=500_000, step=50_000,
            key="loan_amount",
        )
    with col2:
        tenure_months = st.number_input(
            "Tenure (months)",
            min_value=1, max_value=360, value=60, step=6,
            key="loan_tenure",
        )
    with col3:
        interest_rate = st.number_input(
            "Annual interest rate (%)",
            min_value=0.0, max_value=50.0, value=12.0, step=0.5,
            key="loan_rate",
        )

    if loan_amount > 0 and tenure_months > 0 and interest_rate > 0:
        # EMI = P * r * (1+r)^n / ((1+r)^n - 1)
        monthly_rate = interest_rate / 100 / 12
        emi = loan_amount * monthly_rate * (1 + monthly_rate) ** tenure_months / (
            (1 + monthly_rate) ** tenure_months - 1
        )
        emi = round(emi, 2)
        total_payable = round(emi * tenure_months, 2)
        total_interest = round(total_payable - loan_amount, 2)

        col_emi1, col_emi2, col_emi3 = st.columns(3)
        with col_emi1:
            st.metric("Monthly EMI", _fmt_currency(emi, cs))
        with col_emi2:
            st.metric("Total Interest", _fmt_currency(total_interest, cs))
        with col_emi3:
            st.metric("Total Payable", _fmt_currency(total_payable, cs))

        # Affordability check against monthly net income
        if monthly_net and monthly_net > 0:
            emi_to_income = emi / monthly_net
            remaining = monthly_net - emi

            if emi_to_income <= 0.40:
                st.success(
                    f"EMI of {_fmt_currency(emi, cs)} is **{emi_to_income * 100:.1f}%** of monthly net income "
                    f"({_fmt_currency(monthly_net, cs)}). Remaining after EMI: {_fmt_currency(remaining, cs)}. "
                    f"Within the 40% FOIR threshold."
                )
            elif emi_to_income <= 0.55:
                st.warning(
                    f"EMI of {_fmt_currency(emi, cs)} is **{emi_to_income * 100:.1f}%** of monthly net income. "
                    f"Remaining: {_fmt_currency(remaining, cs)}. Borderline — exceeds 40% FOIR but below 55%."
                )
            else:
                st.error(
                    f"EMI of {_fmt_currency(emi, cs)} is **{emi_to_income * 100:.1f}%** of monthly net income. "
                    f"Remaining: {_fmt_currency(remaining, cs)}. Exceeds affordable threshold."
                )

    # Eligibility commentary
    if commentary:
        st.markdown("### Eligibility Commentary")
        st.markdown(f"> {commentary}")


# ---------------------------------------------------------------------------
# Tab 4: Raw data viewer
# ---------------------------------------------------------------------------
def render_raw_data(
    data: dict,
    insights: dict,
    prescription: Optional[dict] = None,
):
    """4 collapsed expanders: extracted fields, calculated values, skipped, JSON export."""
    # 1. Extracted fields with confidence
    with st.expander("Extracted Fields", expanded=False):
        confidence = data.get("_confidence", {})
        _render_fields_with_confidence(data, confidence)

    # 2. Calculated values with formulas
    with st.expander("Calculated Values", expanded=False):
        for key, val in insights.items():
            if val is None:
                continue
            if isinstance(val, dict) and "error" in val:
                st.error(f"**{key}**: {val['error']}")
            elif isinstance(val, dict) and "skipped" in val:
                continue  # shown in skipped section
            elif val is not None:
                st.markdown(f"**{key.replace('_', ' ').title()}**")
                st.json(val)

    # 3. Skipped insights
    with st.expander("Skipped Insights", expanded=False):
        if prescription:
            skip_reasons = prescription.get("skip_reasons", {})
            run_hardcoded = prescription.get("run_hardcoded", {})
            skipped = {k: v for k, v in run_hardcoded.items() if not v}
            if skipped:
                for k in skipped:
                    reason = skip_reasons.get(k, "No reason provided")
                    st.text(f"  {k} — skipped: {reason}")
            else:
                st.text("  No insights were skipped.")
        else:
            st.text("  Prescription data not available (Version A mode).")

    # 4. JSON export
    with st.expander("JSON Export", expanded=False):
        st.caption("Internal data format — for pipeline integration use only.")
        export = {
            "extracted": data,
            "insights": insights,
        }
        if prescription:
            export["prescription"] = prescription
        json_str = json.dumps(export, indent=2, default=str)
        st.code(json_str, language="json")
        st.download_button(
            "Download JSON",
            json_str,
            file_name="payslip_analysis.json",
            mime="application/json",
        )


def _render_fields_with_confidence(data: dict, confidence: dict, prefix: str = ""):
    """Render extracted fields with confidence badges."""
    for key, val in data.items():
        if key.startswith("_"):
            continue
        path = f"{prefix}.{key}" if prefix else key
        conf = _get_nested(confidence, path)

        if isinstance(val, dict) and key not in ("other_earnings", "other_deductions", "raw_extras"):
            st.markdown(f"**{key.replace('_', ' ').title()}**")
            _render_fields_with_confidence(val, confidence, path)
        else:
            badge = ""
            if conf == "high":
                badge = "🟢"
            elif conf == "medium":
                badge = "🟡"
            elif conf == "low":
                badge = "🔴"
            display_val = json.dumps(val, default=str) if isinstance(val, (dict, list)) else str(val)
            st.text(f"  {badge} {key}: {display_val}")


def _get_nested(d: dict, path: str):
    """Get a value from a nested dict using dot-separated path."""
    keys = path.split(".")
    current = d
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k)
        else:
            return None
    return current


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------
def render_version_comparison(
    results_a: dict,
    results_b: dict,
    time_a: float,
    time_b: float,
):
    """Side-by-side comparison of Version A vs Version B results."""
    st.markdown('<div class="comparison-banner"><strong>Both versions produced results. Comparing outputs below.</strong></div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Version A (Single Call)")
        st.metric("Processing Time", f"{time_a:.1f}s")
        if results_a:
            st.metric("Gross", _fmt_currency(results_a.get("earnings", {}).get("gross_salary")))
            st.metric("Net", _fmt_currency(results_a.get("net_pay", {}).get("net_salary")))

    with col2:
        st.subheader("Version B (Two Calls)")
        st.metric("Processing Time", f"{time_b:.1f}s")
        if results_b:
            st.metric("Gross", _fmt_currency(results_b.get("earnings", {}).get("gross_salary")))
            st.metric("Net", _fmt_currency(results_b.get("net_pay", {}).get("net_salary")))

    # Agreement check
    if results_a and results_b:
        gross_a = results_a.get("earnings", {}).get("gross_salary")
        gross_b = results_b.get("earnings", {}).get("gross_salary")
        net_a = results_a.get("net_pay", {}).get("net_salary")
        net_b = results_b.get("net_pay", {}).get("net_salary")

        if gross_a == gross_b and net_a == net_b:
            st.success("Both versions agreed on all key figures.")
        else:
            diffs = []
            if gross_a != gross_b:
                diffs.append(f"Gross: A={_fmt_currency(gross_a)} vs B={_fmt_currency(gross_b)}")
            if net_a != net_b:
                diffs.append(f"Net: A={_fmt_currency(net_a)} vs B={_fmt_currency(net_b)}")
            st.warning(f"Differences detected: {'; '.join(diffs)}")
