"""
Payslip Parser and Document Analyser Agent — Main Streamlit Application.

Orchestrates:
- File upload and preprocessing
- Version A (single Gemini call) or Version B (two calls + Python)
- 4-tab UI: Insights Report, Month-on-Month, Loan Signals, Raw Data
- Version comparison when both versions have been run
"""

import json
import os
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

from extractor.gemini_extractor import extract_payslip_fields, preprocess_files
from extractor.gemini_prescriber import prescribe_insights
from extractor.gemini_version_a import extract_and_analyse_v1
from extractor.normaliser import normalise_extraction
from calculator.insights import run_insights, run_all_insights, run_batch_insights
from ui.components import (
    render_employee_header,
    render_salary_summary,
    render_earnings_breakdown,
    render_deductions_analysis,
    render_employment_profile,
    render_non_standard_components,
    render_data_quality_notice,
    render_consistency_verdict,
    render_month_comparison_table,
    render_loan_signals,
    render_raw_data,
    render_version_comparison,
)
from ui.charts import salary_trend_line
from reporter import generate_report

load_dotenv()


# ---------------------------------------------------------------------------
# Gemini client (cached)
# ---------------------------------------------------------------------------
@st.cache_resource
def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_key_here":
        return None
    return genai.Client(api_key=api_key)


# ---------------------------------------------------------------------------
# CSS loader
# ---------------------------------------------------------------------------
def _load_css():
    css_path = Path(__file__).parent / "ui" / "styles.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------
def _init_session_state():
    defaults = {
        "version": "B",
        "version_locked": False,
        "results": None,          # list of normalised payslip dicts
        "insights": None,         # list of insight dicts (one per payslip)
        "prescriptions": None,    # list of prescription dicts (Version B only)
        "consistency": None,      # batch consistency result
        "processing_time": None,
        "gemini_insights_va": None,  # Version A gemini_insights (for comparison)
        # Version comparison storage
        "results_a": None,
        "insights_a": None,
        "time_a": None,
        "results_b": None,
        "insights_b": None,
        "time_b": None,
        # Loan commentary
        "loan_commentary": None,
        "last_report_path": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ---------------------------------------------------------------------------
# Batch sorting
# ---------------------------------------------------------------------------
def _sort_payslips(normalised_list: list, insights_list: list, prescriptions_list: list = None):
    """Sort payslips chronologically by pay_period_start, with fallbacks."""
    def sort_key(item):
        data = item[0]
        # Primary: pay_period_start
        pp_start = data.get("document_meta", {}).get("pay_period_start")
        if pp_start:
            return pp_start
        # Secondary: pay_period_label (try to extract sortable string)
        pp_label = data.get("document_meta", {}).get("pay_period_label", "")
        if pp_label:
            return pp_label
        # Tertiary: source file name
        return data.get("_source_file", "zzz")

    if prescriptions_list:
        combined = list(zip(normalised_list, insights_list, prescriptions_list))
        combined.sort(key=sort_key)
        n, i, p = zip(*combined) if combined else ([], [], [])
        return list(n), list(i), list(p)
    else:
        combined = list(zip(normalised_list, insights_list))
        combined.sort(key=sort_key)
        n, i = zip(*combined) if combined else ([], [])
        return list(n), list(i), None


# ---------------------------------------------------------------------------
# Analysis runner
# ---------------------------------------------------------------------------
def _run_analysis(uploaded_files):
    """Run the full analysis pipeline."""
    client = get_gemini_client()
    if client is None:
        st.error("Please set a valid GEMINI_API_KEY in the .env file.")
        return

    try:
        files = preprocess_files(uploaded_files)
    except ValueError as e:
        st.error(str(e))
        return

    version = st.session_state["version"]
    start = time.time()

    with st.spinner(f"Analysing {len(files)} payslip(s) with Version {version}..."):
        if version == "A":
            # Version A: single combined call
            raw_results = extract_and_analyse_v1(files, client)
            normalised_list = []
            insights_list = []
            for r in raw_results:
                raw_fields = r.get("raw_fields", {})
                raw_fields["_source_file"] = r.get("_source_file", "")
                normalised = normalise_extraction(raw_fields)
                normalised_list.append(normalised)
                # Merge Gemini insights with Python-computed standard metrics
                # so that monthly_to_annual_conversion and take_home_ratio are
                # always present under the expected keys regardless of what keys
                # Gemini chose for its own insight objects.
                gemini_insights = r.get("gemini_insights", {})
                python_insights = run_insights(
                    normalised,
                    ["monthly_to_annual_conversion", "take_home_ratio"],
                )
                insights_list.append({**gemini_insights, **python_insights})

            prescriptions_list = None

        else:
            # Version B: extraction → prescription → Python calculation
            raw_extractions = extract_payslip_fields(files, client)
            normalised_list = [normalise_extraction(e) for e in raw_extractions]
            insights_list = []
            prescriptions_list = []

            for norm_data in normalised_list:
                # Call 2: prescription
                prescription = prescribe_insights(norm_data, client)
                prescriptions_list.append(prescription)

                # Run what Gemini prescribed
                keys_to_run = [
                    k for k, v in prescription.get("run_hardcoded", {}).items()
                    if v
                ]
                # Always force fundamental insights — prescriber sometimes
                # wrongly skips these for non-monthly frequencies
                for essential in ["monthly_to_annual_conversion", "take_home_ratio"]:
                    if essential not in keys_to_run:
                        keys_to_run.append(essential)
                computed = run_insights(norm_data, keys_to_run)

                # Merge Gemini-computed insights for non-standard components
                computed["gemini_computed"] = prescription.get("gemini_computed_insights", {})
                computed["_prescription"] = prescription
                insights_list.append(computed)

    elapsed = time.time() - start

    # Sort chronologically
    normalised_list, insights_list, prescriptions_list = _sort_payslips(
        normalised_list, insights_list, prescriptions_list
    )

    # Batch consistency
    consistency = None
    if len(normalised_list) > 1:
        consistency = run_batch_insights(normalised_list)

    # Store in session state
    st.session_state["results"] = normalised_list
    st.session_state["insights"] = insights_list
    st.session_state["prescriptions"] = prescriptions_list
    st.session_state["consistency"] = consistency
    st.session_state["processing_time"] = elapsed
    st.session_state["loan_commentary"] = None  # reset

    # Store for version comparison
    key_prefix = "a" if version == "A" else "b"
    st.session_state[f"results_{key_prefix}"] = normalised_list
    st.session_state[f"insights_{key_prefix}"] = insights_list
    st.session_state[f"time_{key_prefix}"] = elapsed

    # Generate session report
    try:
        report_path = generate_report(
            version=version,
            results=normalised_list,
            insights_list=insights_list,
            prescriptions_list=prescriptions_list,
            consistency=consistency,
            processing_time=elapsed,
        )
        st.session_state["last_report_path"] = str(report_path)
    except Exception as e:
        st.session_state["last_report_path"] = None
        st.warning(f"Report generation failed: {e}")


# ---------------------------------------------------------------------------
# Loan commentary generator (Tab 3)
# ---------------------------------------------------------------------------
def _generate_loan_commentary(data: dict, insights: dict, consistency: dict):
    """Generate eligibility commentary via Gemini — the ONLY narrative text call."""
    client = get_gemini_client()
    if client is None:
        return "API key not configured."

    # Build lending signals dict
    annual_data = insights.get("monthly_to_annual_conversion") or {}
    th_data = insights.get("take_home_ratio") or {}
    gratuity_data = insights.get("gratuity_accrual_estimate") or {}

    # Read PF directly from extracted data — don't depend on insight being run
    pf_amount = data.get("deductions", {}).get("pf_epf")

    # Use normalised monthly figures (handles weekly/biweekly conversion)
    monthly_net = annual_data.get("monthly_net") or data.get("net_pay", {}).get("net_salary")
    monthly_gross = annual_data.get("monthly_gross") or data.get("earnings", {}).get("gross_salary")
    currency = data.get("document_meta", {}).get("currency", "INR")

    # Compute tenure directly — don't rely on gratuity insight being run
    from datetime import date as _date
    today = _date.today()
    employment_date_str = data.get("employee", {}).get("employment_date")
    tenure_months_calculated = None
    if employment_date_str:
        try:
            emp_dt = _date.fromisoformat(employment_date_str)
            tenure_months_calculated = round((today - emp_dt).days / 30.44, 1)
        except (ValueError, TypeError):
            pass

    # Get loan parameters from session state if user entered them
    loan_amount = st.session_state.get("loan_amount")
    loan_tenure = st.session_state.get("loan_tenure")
    loan_rate = st.session_state.get("loan_rate")

    lending_signals = {
        "today": str(today),
        "monthly_net_normalised": monthly_net,
        "monthly_gross_normalised": monthly_gross,
        "raw_period_net": data.get("net_pay", {}).get("net_salary"),
        "salary_frequency": data.get("document_meta", {}).get("salary_frequency"),
        "annual_gross": annual_data.get("annual_gross"),
        "annual_net": annual_data.get("annual_net"),
        "is_estimated": annual_data.get("is_estimated", False),
        "take_home_ratio": th_data.get("take_home_ratio"),
        "employer_name": data.get("employer", {}).get("name"),
        "employment_date": employment_date_str,
        "tenure_months": tenure_months_calculated,
        "pf_confirmed": pf_amount is not None,
        "pf_monthly": pf_amount,
        "currency": currency,
        "consistency": consistency,
    }

    # Include loan parameters if specified
    if loan_amount and loan_amount > 0:
        lending_signals["loan_amount_sought"] = loan_amount
        lending_signals["loan_tenure_months"] = loan_tenure
        lending_signals["interest_rate_pct"] = loan_rate
        if loan_rate and loan_rate > 0 and loan_tenure and loan_tenure > 0:
            r = loan_rate / 100 / 12
            emi = loan_amount * r * (1 + r) ** loan_tenure / ((1 + r) ** loan_tenure - 1)
            lending_signals["calculated_emi"] = round(emi, 2)
            if monthly_net and monthly_net > 0:
                lending_signals["emi_to_income_ratio"] = round(emi / monthly_net, 4)

    prompt = f"""You are a senior credit analyst at InCred Finance. Based on the
following salary data extracted from an applicant's payslip, write 3-5 sentences
summarising whether this applicant meets InCred's lending criteria.

TODAY'S DATE: {today} — use this as the reference date for all tenure calculations.

LENDING SIGNALS:
{json.dumps(lending_signals, indent=2, default=str)}

REQUIREMENTS:
- TODAY IS {today}. Use this date when assessing tenure or employment stability.
  The field "tenure_months" in the signals is pre-calculated as of today — trust it.
- Reference specific numbers from the data (monthly net, take-home ratio,
  tenure in months, PF confirmation, consistency score if available).
- Do NOT speak in generalities — cite the actual figures.
- The currency is {currency}. Use the correct currency symbol.
- If loan_amount_sought and calculated_emi are present, assess whether the
  applicant can afford the EMI based on their monthly net income. Use a 40%
  FOIR (Fixed Obligations to Income Ratio) threshold as the standard.
- Comment on: income adequacy, employment stability (minimum 6 months tenure),
  salary consistency (if batch data available), and formal employment indicators.
- Keep it professional and factual — suitable for a loan file note."""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3),
        )
        return response.text
    except Exception as e:
        return f"Error generating commentary: {str(e)}"


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def _render_sidebar():
    with st.sidebar:
        st.title("Payslip Parser")
        st.caption("InCred Finance — Document Analyser Agent")

        uploaded_files = st.file_uploader(
            "Upload payslip(s) — single or up to 3 months",
            type=["pdf", "jpg", "jpeg", "png"],
            accept_multiple_files=True,
        )

        version = st.radio(
            "Processing Version",
            ["Version A — Gemini end-to-end", "Version B — Gemini + Python (Recommended)"],
            index=1,
            disabled=st.session_state.get("version_locked", False),
        )
        st.session_state["version"] = "A" if "Version A" in version else "B"

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("Analyse", type="primary", disabled=not uploaded_files, use_container_width=True):
                st.session_state["version_locked"] = True
                _run_analysis(uploaded_files)
                st.rerun()

        with col_btn2:
            if st.button("Clear", use_container_width=True):
                st.session_state["version_locked"] = False
                for key in [
                    "results", "insights", "prescriptions", "consistency",
                    "processing_time", "loan_commentary", "last_report_path",
                    "results_a", "insights_a", "time_a",
                    "results_b", "insights_b", "time_b",
                ]:
                    st.session_state[key] = None
                st.rerun()

        if st.session_state.get("version_locked"):
            st.caption("Clear results to change version.")

        if st.session_state.get("processing_time"):
            st.caption(f"Processed in {st.session_state['processing_time']:.1f}s")

        # Report download
        report_path = st.session_state.get("last_report_path")
        if report_path:
            try:
                report_text = open(report_path, encoding="utf-8").read()
                st.divider()
                st.download_button(
                    label="⬇ Download Report (.md)",
                    data=report_text,
                    file_name=Path(report_path).name,
                    mime="text/markdown",
                    use_container_width=True,
                )
                st.caption(f"Saved: `{Path(report_path).name}`")
            except Exception:
                pass

        # Version comparison check
        if st.session_state.get("results_a") and st.session_state.get("results_b"):
            st.divider()
            st.success("Both versions have results. See comparison in Insights tab.")

    return uploaded_files


# ---------------------------------------------------------------------------
# Tab renderers
# ---------------------------------------------------------------------------
def _render_tab1():
    """Insights Report tab."""
    results = st.session_state["results"]
    insights_list = st.session_state["insights"]

    if not results:
        return

    # For single payslip, show directly. For batch, show first with selector.
    if len(results) > 1:
        labels = [
            r.get("document_meta", {}).get("pay_period_label") or r.get("_source_file", f"Payslip {i+1}")
            for i, r in enumerate(results)
        ]
        selected_idx = st.selectbox("Select payslip", range(len(results)), format_func=lambda i: labels[i])
    else:
        selected_idx = 0

    data = results[selected_idx]
    insights = insights_list[selected_idx] if selected_idx < len(insights_list) else {}

    # Check for not-a-payslip error
    if data.get("error") == "not_a_payslip":
        st.error("This document does not appear to be a payslip. Please upload a valid payslip or salary document.")
        return

    # Section 1: Employee header
    render_employee_header(data)

    # Section 2: Salary summary
    st.markdown("### Salary Summary")
    render_salary_summary(data, insights)

    # Section 3: Earnings breakdown
    st.markdown("### Earnings Breakdown")
    render_earnings_breakdown(data)

    # Section 4: Deductions analysis
    st.markdown("### Deductions Analysis")
    render_deductions_analysis(data, insights)

    # Section 5: Employment profile
    st.markdown("### Employment Profile")
    render_employment_profile(data, insights)

    # Section 6: Non-standard components
    gemini_computed = insights.get("gemini_computed", {})
    render_non_standard_components(data, gemini_computed)

    # Section 7: Data quality notice
    render_data_quality_notice(data)

    # Version comparison banner
    if st.session_state.get("results_a") and st.session_state.get("results_b"):
        st.divider()
        render_version_comparison(
            st.session_state["results_a"][0] if st.session_state["results_a"] else {},
            st.session_state["results_b"][0] if st.session_state["results_b"] else {},
            st.session_state.get("time_a", 0),
            st.session_state.get("time_b", 0),
        )


def _render_tab2():
    """Month-on-Month Analysis tab."""
    results = st.session_state["results"]
    consistency = st.session_state.get("consistency")

    if not results or len(results) < 2:
        st.info("Upload 2 or more payslips to enable trend analysis.")
        return

    # Section 1: Salary trend chart
    st.markdown("### Salary Trend")
    fig = salary_trend_line(results)
    st.plotly_chart(fig, use_container_width=True)

    # Section 2: Consistency verdict
    if consistency:
        render_consistency_verdict(consistency)

    # Section 3: Comparison table
    st.markdown("### Month-by-Month Comparison")
    render_month_comparison_table(results)


def _render_tab3():
    """Loan Signals tab."""
    results = st.session_state["results"]
    insights_list = st.session_state["insights"]
    consistency = st.session_state.get("consistency")

    if not results:
        return

    # Use first payslip (or average for batch)
    data = results[0]
    insights = insights_list[0] if insights_list else {}

    # Render signals + loan params (this includes the number inputs)
    render_loan_signals(data, insights, consistency, st.session_state.get("loan_commentary", ""))

    # Commentary generation button (separate so it picks up loan params)
    if st.button("Generate Eligibility Commentary", type="primary", key="gen_commentary"):
        with st.spinner("Generating eligibility commentary..."):
            commentary = _generate_loan_commentary(data, insights, consistency)
            st.session_state["loan_commentary"] = commentary
            st.rerun()
    elif st.session_state.get("loan_commentary") is None:
        st.caption("Click the button above to generate an AI-powered eligibility assessment. "
                   "Set loan parameters first for a more specific analysis.")


def _render_tab4():
    """Raw Data tab."""
    results = st.session_state["results"]
    insights_list = st.session_state["insights"]
    prescriptions = st.session_state.get("prescriptions")

    if not results:
        return

    if len(results) > 1:
        labels = [
            r.get("document_meta", {}).get("pay_period_label") or r.get("_source_file", f"Payslip {i+1}")
            for i, r in enumerate(results)
        ]
        selected_idx = st.selectbox("Select payslip", range(len(results)), format_func=lambda i: labels[i], key="tab4_selector")
    else:
        selected_idx = 0

    data = results[selected_idx]
    insights = insights_list[selected_idx] if selected_idx < len(insights_list) else {}
    prescription = prescriptions[selected_idx] if prescriptions and selected_idx < len(prescriptions) else None

    render_raw_data(data, insights, prescription)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    st.set_page_config(
        page_title="Payslip Parser — InCred Finance",
        page_icon="📄",
        layout="wide",
    )

    _load_css()
    _init_session_state()
    _render_sidebar()

    if st.session_state.get("results"):
        tab1, tab2, tab3, tab4 = st.tabs([
            "📊 Insights Report",
            "📈 Month-on-Month",
            "🏦 Loan Signals",
            "🔧 Raw Data",
        ])

        with tab1:
            _render_tab1()
        with tab2:
            _render_tab2()
        with tab3:
            _render_tab3()
        with tab4:
            _render_tab4()
    else:
        st.markdown("## Payslip Parser & Document Analyser")
        st.markdown(
            "Upload one or more payslips (PDF, JPG, PNG) using the sidebar, "
            "select your processing version, and click **Analyse** to begin."
        )
        st.markdown("""
        **Features:**
        - Single payslip analysis with financial insights
        - Batch processing (up to 3 months) with trend analysis
        - Loan pre-screening signals
        - Version A vs B comparison
        """)


if __name__ == "__main__":
    main()
