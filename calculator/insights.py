"""
HARDCODED_INSIGHTS map + 12 pure calculation functions.

This module is the single source of truth for what Python can compute.
The prescription prompt in gemini_prescriber.py is generated
programmatically from HARDCODED_INSIGHTS.keys().

All functions are pure — no API calls, no side effects.
Each takes the normalised schema dict as input and returns
Optional[dict]. Every function guards against None inputs.
"""

from datetime import date
from typing import Callable, Optional

from dateutil.relativedelta import relativedelta


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _safe_get(data: dict, *keys):
    """Safely navigate nested dicts. Returns None on any missing key."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


# ---------------------------------------------------------------------------
# 1. Monthly → Annual conversion
# ---------------------------------------------------------------------------
def compute_annual_figures(data: dict) -> Optional[dict]:
    """Annualise gross and net salary based on detected frequency.

    Uses conservative assumptions appropriate for lending:
    - monthly: gross x 12
    - weekly: gross x 45 weeks (52 minus 7 weeks standard leave)
    - biweekly: gross x 24 pay periods x 0.9 (same leave adjustment)
    - daily: gross x 5 days x 45 weeks
    """
    freq = _safe_get(data, "document_meta", "salary_frequency") or "monthly"
    gross = _safe_get(data, "earnings", "gross_salary")
    net = _safe_get(data, "net_pay", "net_salary")

    if gross is None or net is None:
        return None

    # Annual multiplier (periods per year, conservative for lending)
    annual_multiplier = {
        "daily": 5 * 45,        # 5 days x 45 weeks
        "weekly": 45,            # 52 minus 7 weeks leave
        "biweekly": 24 * 0.9,   # 24 pay periods, leave-adjusted
        "monthly": 12,
    }

    # Period-to-monthly multiplier (for normalised monthly figures)
    monthly_multiplier = {
        "daily": 26,
        "weekly": 4.33,
        "biweekly": 2.17,
        "monthly": 1,
    }

    ann_m = annual_multiplier.get(freq, 12)
    mon_m = monthly_multiplier.get(freq, 1)
    is_estimated = freq != "monthly"

    # Assumptions text for non-monthly frequencies
    assumptions = {
        "daily": f"daily gross {_fmt_inr(gross)} x 5 days x 45 working weeks",
        "weekly": f"weekly gross {_fmt_inr(gross)} x 45 working weeks (52 minus 7 weeks standard leave)",
        "biweekly": f"biweekly gross {_fmt_inr(gross)} x 24 pay periods x 0.9 (leave adjustment)",
    }

    return {
        "monthly_gross": round(gross * mon_m, 2),
        "annual_gross": round(gross * ann_m, 2),
        "monthly_net": round(net * mon_m, 2),
        "annual_net": round(net * ann_m, 2),
        "is_estimated": is_estimated,
        "frequency": freq,
        "assumption": assumptions.get(freq),
    }


def _fmt_inr(val) -> str:
    """Format as INR for assumption text."""
    if val is None:
        return "N/A"
    return f"\u20b9{val:,.2f}"


# ---------------------------------------------------------------------------
# 2. Take-home ratio
# ---------------------------------------------------------------------------
def compute_take_home_ratio(data: dict) -> Optional[dict]:
    """Net pay as a fraction of gross."""
    gross = _safe_get(data, "earnings", "gross_salary")
    net = _safe_get(data, "net_pay", "net_salary")

    if not gross or not net or gross == 0:
        return None

    ratio = round(net / gross, 4)
    return {
        "take_home_ratio": ratio,
        "take_home_pct": f"{ratio * 100:.1f}%",
    }


# ---------------------------------------------------------------------------
# 3. Effective TDS rate
# ---------------------------------------------------------------------------
def compute_tds_rate(data: dict) -> Optional[dict]:
    """TDS / income tax as fraction of gross."""
    tds = _safe_get(data, "deductions", "tds_income_tax")
    gross = _safe_get(data, "earnings", "gross_salary")

    if tds is None or not gross or gross == 0:
        return None

    rate = round(tds / gross, 4)
    return {
        "tds_amount": tds,
        "effective_tds_rate": rate,
        "tds_pct": f"{rate * 100:.1f}%",
    }


# ---------------------------------------------------------------------------
# 4. PF as % of basic
# ---------------------------------------------------------------------------
def compute_pf_ratio(data: dict) -> Optional[dict]:
    """PF/EPF contribution as fraction of basic salary."""
    pf = _safe_get(data, "deductions", "pf_epf")
    basic = _safe_get(data, "earnings", "basic_salary")

    if pf is None or not basic or basic == 0:
        return None

    ratio = round(pf / basic, 4)
    return {
        "pf_amount": pf,
        "basic_salary": basic,
        "pf_basic_ratio": ratio,
        "pf_basic_pct": f"{ratio * 100:.1f}%",
    }


# ---------------------------------------------------------------------------
# 5. Deduction breakdown
# ---------------------------------------------------------------------------
def compute_deduction_breakdown(data: dict) -> Optional[dict]:
    """Each deduction as amount and % of gross."""
    gross = _safe_get(data, "earnings", "gross_salary")
    deductions = data.get("deductions", {})

    if not gross or gross == 0:
        return None

    breakdown = {}
    for k, v in deductions.items():
        if v is not None and k not in ("total_deductions", "other_deductions"):
            if isinstance(v, (int, float)):
                breakdown[k] = {
                    "amount": v,
                    "pct_of_gross": round(v / gross, 4),
                }

    # Include other_deductions
    other_ded = deductions.get("other_deductions", {})
    if isinstance(other_ded, dict):
        for k, v in other_ded.items():
            if v is not None and isinstance(v, (int, float)):
                breakdown[k] = {
                    "amount": v,
                    "pct_of_gross": round(v / gross, 4),
                }

    return breakdown if breakdown else None


# ---------------------------------------------------------------------------
# 6. Salary consistency (BATCH MODE ONLY)
# ---------------------------------------------------------------------------
def compute_consistency(payslips_list: list) -> Optional[dict]:
    """
    Compare net salary across multiple payslips.
    Receives a list of normalised schema dicts.
    """
    if not payslips_list or len(payslips_list) < 2:
        return None

    nets = []
    for p in payslips_list:
        net = _safe_get(p, "net_pay", "net_salary")
        if net is not None:
            nets.append(net)

    if len(nets) < 2:
        return None

    avg = sum(nets) / len(nets)
    if avg == 0:
        return None

    std = (sum((x - avg) ** 2 for x in nets) / len(nets)) ** 0.5
    cv = std / avg

    return {
        "avg_monthly_net": round(avg, 2),
        "std_dev": round(std, 2),
        "consistency_coefficient": round(cv, 4),
        "consistency_label": (
            "consistent" if cv < 0.05
            else "minor_variation" if cv < 0.20
            else "high_variation"
        ),
        "num_payslips": len(nets),
        "net_values": nets,
    }


# ---------------------------------------------------------------------------
# 7. Hourly normalisation
# ---------------------------------------------------------------------------
def compute_hourly(data: dict) -> Optional[dict]:
    """Compute effective hourly/daily rate from attendance data."""
    hourly_rate = _safe_get(data, "attendance", "hourly_rate")
    hours_worked = _safe_get(data, "attendance", "hours_worked")

    if hourly_rate is not None and hours_worked is not None:
        return {
            "hourly_rate": hourly_rate,
            "hours_worked": hours_worked,
            "computed_gross": round(hourly_rate * hours_worked, 2),
        }

    # Fallback: derive from net pay and days worked
    net = _safe_get(data, "net_pay", "net_salary")
    days = _safe_get(data, "attendance", "days_worked")
    if net is not None and days is not None and days > 0:
        daily = round(net / days, 2)
        hourly = round(daily / 8, 2)
        return {
            "daily_rate": daily,
            "hourly_rate": hourly,
            "days_worked": days,
        }

    return None


# ---------------------------------------------------------------------------
# 8. Overtime analysis
# ---------------------------------------------------------------------------
def compute_overtime(data: dict) -> Optional[dict]:
    """Overtime amount and its share of gross."""
    gross = _safe_get(data, "earnings", "gross_salary")
    ot = _safe_get(data, "earnings", "overtime")

    if ot is None or not gross or gross == 0:
        return None

    return {
        "overtime_amount": ot,
        "overtime_pct_of_gross": round(ot / gross, 4),
    }


# ---------------------------------------------------------------------------
# 9. HRA as % of gross
# ---------------------------------------------------------------------------
def compute_hra_ratio(data: dict) -> Optional[dict]:
    """HRA as fraction of gross salary."""
    hra = _safe_get(data, "earnings", "hra")
    gross = _safe_get(data, "earnings", "gross_salary")

    if hra is None or not gross or gross == 0:
        return None

    return {
        "hra_amount": hra,
        "hra_pct_of_gross": round(hra / gross, 4),
    }


# ---------------------------------------------------------------------------
# 10. LTA as % of gross
# ---------------------------------------------------------------------------
def compute_lta_ratio(data: dict) -> Optional[dict]:
    """LTA as fraction of gross salary."""
    lta = _safe_get(data, "earnings", "lta")
    gross = _safe_get(data, "earnings", "gross_salary")

    if lta is None or not gross or gross == 0:
        return None

    return {
        "lta_amount": lta,
        "lta_pct_of_gross": round(lta / gross, 4),
    }


# ---------------------------------------------------------------------------
# 11. Professional tax check
# ---------------------------------------------------------------------------
def compute_prof_tax(data: dict) -> Optional[dict]:
    """Professional tax monthly and annualised."""
    pt = _safe_get(data, "deductions", "professional_tax")
    if pt is None:
        return None

    return {
        "professional_tax_monthly": pt,
        "professional_tax_annual": pt * 12,
    }


# ---------------------------------------------------------------------------
# 12. Gratuity accrual estimate
# ---------------------------------------------------------------------------
def compute_gratuity(data: dict) -> Optional[dict]:
    """
    Gratuity estimate = (Basic x 15 / 26) x years of service.
    If employment_date is missing, returns per-year accrual only.
    """
    basic = _safe_get(data, "earnings", "basic_salary")
    if basic is None:
        return None

    per_year = round(basic * 15 / 26, 2)
    monthly_accrual = round(per_year / 12, 2)

    result = {
        "gratuity_per_year": per_year,
        "gratuity_monthly_accrual": monthly_accrual,
    }

    emp_dt_str = _safe_get(data, "employee", "employment_date")
    if emp_dt_str:
        try:
            emp_dt = date.fromisoformat(emp_dt_str)
            tenure = relativedelta(date.today(), emp_dt)
            years = tenure.years + tenure.months / 12
            result["gratuity_accrued_to_date"] = round(per_year * years, 2)
            result["tenure_years"] = round(years, 2)
            if years < 5:
                result["disclaimer"] = (
                    "Gratuity is payable only after 5 years of continuous service "
                    "under the Payment of Gratuity Act, 1972. Current tenure of "
                    f"{years:.1f} years does not meet this threshold. Figures shown "
                    "are theoretical accrual rates only and should not be counted "
                    "as an asset for lending purposes."
                )
        except (ValueError, TypeError):
            pass

    return result


# ===========================================================================
# HARDCODED_INSIGHTS — THE SINGLE SOURCE OF TRUTH
# ===========================================================================
HARDCODED_INSIGHTS: dict[str, Callable] = {
    "monthly_to_annual_conversion": compute_annual_figures,
    "take_home_ratio": compute_take_home_ratio,
    "effective_tds_rate": compute_tds_rate,
    "pf_as_pct_of_basic": compute_pf_ratio,
    "deduction_breakdown": compute_deduction_breakdown,
    "salary_consistency": compute_consistency,  # batch-mode only
    "hourly_normalisation": compute_hourly,
    "overtime_analysis": compute_overtime,
    "hra_as_pct_of_gross": compute_hra_ratio,
    "lta_as_pct_of_gross": compute_lta_ratio,
    "professional_tax_check": compute_prof_tax,
    "gratuity_accrual_estimate": compute_gratuity,
}


# ---------------------------------------------------------------------------
# Runner functions
# ---------------------------------------------------------------------------
def run_insights(data: dict, keys_to_run: list[str]) -> dict:
    """Run only the specified insight functions. Returns {name: result_or_none}."""
    results = {}
    for key in keys_to_run:
        fn = HARDCODED_INSIGHTS.get(key)
        if fn is None:
            results[key] = {"error": f"Unknown insight: {key}"}
            continue
        if key == "salary_consistency":
            # Skip — this needs a list, not a single dict
            results[key] = {"skipped": "batch-mode only"}
            continue
        try:
            results[key] = fn(data)
        except Exception as e:
            results[key] = {"error": str(e)}
    return results


def run_all_insights(data: dict) -> dict:
    """Run all non-batch insight functions."""
    keys = [k for k in HARDCODED_INSIGHTS if k != "salary_consistency"]
    return run_insights(data, keys)


def run_batch_insights(payslips_list: list[dict]) -> Optional[dict]:
    """Run batch-only insights (consistency analysis)."""
    return compute_consistency(payslips_list)
