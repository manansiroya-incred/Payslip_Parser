"""
Verification Engine — Payslip authenticity, tax compliance, and employer signals.

All functions are pure (no API calls, no Streamlit dependency, no side effects).
Each takes the normalised schema dict and returns a result dict.

Serves Enhancement 1 (Authenticity), Enhancement 4 (Tax Compliance),
and Enhancement 5 (Employer Compliance).
"""

from datetime import date
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Indian New Tax Regime FY 2025-26 slabs (Union Budget 2025):
# (lower_bound, upper_bound, marginal_rate)
NEW_REGIME_SLABS = [
    (0,           400_000,    0.00),
    (400_000,     800_000,    0.05),
    (800_000,   1_200_000,    0.10),
    (1_200_000, 1_600_000,    0.15),
    (1_600_000, 2_000_000,    0.20),
    (2_000_000, 2_400_000,    0.25),
    (2_400_000, float("inf"), 0.30),
]

STANDARD_DEDUCTION = 75_000   # increased from ₹50,000 in Budget 2025
# Rebate u/s 87A: no tax if taxable income ≤ ₹12,00,000 under new regime
REBATE_THRESHOLD = 1_200_000
TOLERANCE_ARITHMETIC = 5.0       # ±₹5 for arithmetic checks
PF_STATUTORY_RATE = 0.12         # 12% of basic
PF_TOLERANCE = 0.15              # 15% deviation tolerance
PF_WAGE_CEILING = 15_000         # monthly basic ceiling for PF cap
PF_CAP_MONTHLY = 1_800           # PF cap when basic > ceiling
PF_NON_STANDARD_LOW = 500        # lower bound for "non-standard" tier
PF_NON_STANDARD_HIGH = 1_800     # upper bound for "non-standard" tier
PT_MONTHLY_CAP = 300.0           # professional tax cap
TDS_TOLERANCE_LOW = 0.60         # flag if actual < 60% of expected
TDS_TOLERANCE_HIGH = 2.00        # flag if actual > 200% of expected
# Wide high tolerance (200%) because we compute using new regime only;
# old regime taxes can be 1.5-2x higher for the same income. Without
# knowing the employee's elected regime, 200% avoids false positives.

# Authenticity score penalties
PENALTY_ARITHMETIC = 40          # any arithmetic failure (category, not per-check)
PENALTY_PF = 20                  # PF anomalous
PENALTY_TDS = 15                 # TDS outside expected range
PENALTY_ROUND = 10               # suspicious round numbers
PENALTY_PT = 15                  # PT exceeds cap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_get(data: dict, *keys):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _sum_earnings(data: dict) -> Optional[float]:
    """Sum all individual earning components (excluding gross_salary itself)."""
    earnings = data.get("earnings", {})
    total = 0.0
    found_any = False

    for key in ("basic_salary", "hra", "lta", "special_allowance", "overtime", "bonus"):
        val = earnings.get(key)
        if val is not None and isinstance(val, (int, float)):
            total += val
            found_any = True

    other = earnings.get("other_earnings", {})
    if isinstance(other, dict):
        for val in other.values():
            if val is not None and isinstance(val, (int, float)):
                total += val
                found_any = True

    return total if found_any else None


def _sum_deductions(data: dict) -> Optional[float]:
    """Sum all individual deduction components (excluding total_deductions itself)."""
    deductions = data.get("deductions", {})
    total = 0.0
    found_any = False

    for key in ("tds_income_tax", "pf_epf", "professional_tax", "gratuity", "esic", "loan_deduction"):
        val = deductions.get(key)
        if val is not None and isinstance(val, (int, float)):
            total += val
            found_any = True

    other = deductions.get("other_deductions", {})
    if isinstance(other, dict):
        for val in other.values():
            if val is not None and isinstance(val, (int, float)):
                total += val
                found_any = True

    return total if found_any else None


def _is_round(val: float, divisor: int = 5000) -> bool:
    """Check if a value is exactly divisible by divisor."""
    if val is None or val == 0:
        return False
    return val % divisor == 0


# ---------------------------------------------------------------------------
# Tax Slab Computation (shared by E1 and E4)
# ---------------------------------------------------------------------------
def _compute_tax_on_income(taxable_income: float, *, apply_rebate: bool = True) -> dict:
    """Apply Indian new regime FY 2025-26 tax slabs.

    Includes:
    - 7 slab rates (Budget 2025)
    - Section 87A rebate: no tax if taxable income ≤ ₹12,00,000 (when apply_rebate=True)
    - 4% Health & Education Cess on tax

    Set apply_rebate=False when computing the upper bound of the expected range,
    since the employer may use old regime or the employee may not claim the rebate.
    """
    if taxable_income <= 0:
        return {
            "tax_before_cess": 0, "cess": 0, "total_tax": 0,
            "effective_rate": 0, "slab_breakdown": [], "rebate_applied": False,
        }

    tax = 0.0
    breakdown = []

    for lower, upper, rate in NEW_REGIME_SLABS:
        if taxable_income <= lower:
            break
        slab_income = min(taxable_income, upper) - lower
        slab_tax = slab_income * rate
        tax += slab_tax
        if slab_income > 0:
            breakdown.append({
                "slab": f"₹{lower:,.0f} – ₹{upper:,.0f}" if upper != float("inf") else f"Above ₹{lower:,.0f}",
                "rate": f"{rate * 100:.0f}%",
                "taxable_in_slab": round(slab_income, 2),
                "tax_on_slab": round(slab_tax, 2),
            })

    # Section 87A rebate — no tax if taxable income ≤ ₹12L
    rebate_applied = False
    if apply_rebate and taxable_income <= REBATE_THRESHOLD:
        rebate_applied = True
        tax = 0.0

    cess = round(tax * 0.04, 2)
    total = round(tax + cess, 2)
    effective = round(total / taxable_income, 4) if taxable_income > 0 else 0

    return {
        "tax_before_cess": round(tax, 2),
        "cess": cess,
        "total_tax": total,
        "effective_rate": effective,
        "slab_breakdown": breakdown,
        "rebate_applied": rebate_applied,
    }


def compute_expected_tax(
    annual_gross: float,
    annual_basic: float,
    annual_hra: float,
    *,
    metro: bool = False,
) -> dict:
    """Estimate annual tax under new regime FY 2024-25.

    Returns a RANGE (with and without HRA exemption) because individual
    situations vary and we don't have rent receipts.

    Conservative HRA estimate: min(actual HRA, 40% of basic for non-metro /
    50% for metro). Real exemption could be higher → less tax.
    """
    hra_pct = 0.50 if metro else 0.40
    hra_exempt = min(annual_hra, hra_pct * annual_basic) if annual_hra > 0 else 0

    # Taxable income scenarios
    taxable_with_hra = max(0, annual_gross - STANDARD_DEDUCTION - hra_exempt)
    taxable_without_hra = max(0, annual_gross - STANDARD_DEDUCTION)

    # Low end: with HRA exemption + rebate (best case for employee)
    tax_with_hra = _compute_tax_on_income(taxable_with_hra, apply_rebate=True)
    # High end: without HRA exemption AND without rebate (worst case —
    # employer may use old regime or employee may not claim rebate)
    tax_without_hra = _compute_tax_on_income(taxable_without_hra, apply_rebate=False)

    return {
        "annual_gross": round(annual_gross, 2),
        "annual_basic": round(annual_basic, 2),
        "annual_hra": round(annual_hra, 2),
        "standard_deduction": STANDARD_DEDUCTION,
        "hra_exemption_estimate": round(hra_exempt, 2),
        "taxable_income_with_hra": round(taxable_with_hra, 2),
        "taxable_income_without_hra": round(taxable_without_hra, 2),
        "expected_tax_low": tax_with_hra["total_tax"],      # lower tax (exemptions + rebate)
        "expected_tax_high": tax_without_hra["total_tax"],   # higher tax (no exemptions, no rebate)
        "slab_breakdown": tax_without_hra["slab_breakdown"],  # show the worst-case breakdown
    }


# ---------------------------------------------------------------------------
# Enhancement 4 — Tax Compliance Verification
# ---------------------------------------------------------------------------
def compute_tax_compliance(data: dict) -> Optional[dict]:
    """Full tax compliance verification.

    Annualises the payslip figures, estimates expected TDS range,
    and compares against actual TDS deducted.
    """
    gross = _safe_get(data, "earnings", "gross_salary")
    basic = _safe_get(data, "earnings", "basic_salary")
    hra = _safe_get(data, "earnings", "hra") or 0
    tds = _safe_get(data, "deductions", "tds_income_tax")
    freq = _safe_get(data, "document_meta", "salary_frequency") or "monthly"

    if gross is None or tds is None:
        return None

    # Annualise based on frequency
    multiplier = {"monthly": 12, "weekly": 52, "biweekly": 26, "daily": 260}.get(freq, 12)

    annual_gross = gross * multiplier
    annual_basic = (basic or 0) * multiplier
    annual_hra = hra * multiplier
    actual_annual_tds = tds * multiplier

    tax_estimate = compute_expected_tax(annual_gross, annual_basic, annual_hra)

    expected_low = tax_estimate["expected_tax_low"]
    expected_high = tax_estimate["expected_tax_high"]

    # Determine verdict
    if expected_high == 0 and actual_annual_tds == 0:
        verdict = "consistent"
        verdict_detail = "No TDS expected or deducted — income below taxable threshold."
    elif expected_high == 0 and actual_annual_tds > 0:
        verdict = "above_expected"
        verdict_detail = (
            f"TDS of ₹{actual_annual_tds:,.0f} deducted but income appears below taxable "
            f"threshold. May indicate additional income sources or employer using old regime."
        )
    elif actual_annual_tds < expected_low * TDS_TOLERANCE_LOW:
        verdict = "below_expected"
        verdict_detail = (
            f"Actual TDS (₹{actual_annual_tds:,.0f}) is significantly below the expected "
            f"range (₹{expected_low:,.0f}–₹{expected_high:,.0f}). May indicate salary "
            f"inflation or under-deduction. Recommend verifying with Form 16."
        )
    elif actual_annual_tds > expected_high * TDS_TOLERANCE_HIGH:
        verdict = "above_expected"
        verdict_detail = (
            f"Actual TDS (₹{actual_annual_tds:,.0f}) exceeds the expected range "
            f"(₹{expected_low:,.0f}–₹{expected_high:,.0f}). May indicate additional "
            f"income sources, fewer exemptions claimed, or employer using old regime."
        )
    else:
        verdict = "consistent"
        verdict_detail = (
            f"TDS of ₹{actual_annual_tds:,.0f} is within the expected range "
            f"(₹{expected_low:,.0f}–₹{expected_high:,.0f})."
        )

    return {
        "annual_gross": round(annual_gross, 2),
        "annual_basic": round(annual_basic, 2),
        "annual_hra": round(annual_hra, 2),
        "standard_deduction": STANDARD_DEDUCTION,
        "hra_exemption_estimate": tax_estimate["hra_exemption_estimate"],
        "taxable_income_with_hra": tax_estimate["taxable_income_with_hra"],
        "taxable_income_without_hra": tax_estimate["taxable_income_without_hra"],
        "expected_tds_range": {
            "low": round(expected_low, 2),
            "high": round(expected_high, 2),
        },
        "actual_monthly_tds": tds,
        "actual_annual_tds": round(actual_annual_tds, 2),
        "slab_breakdown": tax_estimate["slab_breakdown"],
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "frequency": freq,
        "multiplier": multiplier,
    }


# ---------------------------------------------------------------------------
# Enhancement 1 — Authenticity Checks
# ---------------------------------------------------------------------------
def check_arithmetic_net(data: dict) -> dict:
    """Check: net_salary == gross_salary - total_deductions (±₹5)."""
    gross = _safe_get(data, "earnings", "gross_salary")
    total_ded = _safe_get(data, "deductions", "total_deductions")
    net = _safe_get(data, "net_pay", "net_salary")

    if gross is None or total_ded is None or net is None:
        return {"check": "net_arithmetic", "pass": None, "severity": "skip",
                "message": "Insufficient data — gross, deductions, or net missing.",
                "penalty": 0}

    expected = round(gross - total_ded, 2)
    delta = round(abs(net - expected), 2)
    passed = delta <= TOLERANCE_ARITHMETIC

    return {
        "check": "net_arithmetic",
        "pass": passed,
        "expected": expected,
        "actual": net,
        "delta": delta,
        "severity": "ok" if passed else "critical",
        "message": (
            f"Net salary ₹{net:,.0f} = Gross ₹{gross:,.0f} − Deductions ₹{total_ded:,.0f}"
            if passed else
            f"Net salary ₹{net:,.0f} ≠ Gross ₹{gross:,.0f} − Deductions ₹{total_ded:,.0f} "
            f"(expected ₹{expected:,.0f}, off by ₹{delta:,.0f})"
        ),
        "penalty": 0 if passed else PENALTY_ARITHMETIC,
    }


def check_arithmetic_deductions(data: dict) -> dict:
    """Check: total_deductions == sum of individual deductions (±₹5)."""
    total_ded = _safe_get(data, "deductions", "total_deductions")
    computed_sum = _sum_deductions(data)

    if total_ded is None or computed_sum is None:
        return {"check": "deductions_sum", "pass": None, "severity": "skip",
                "message": "Insufficient data — total deductions or components missing.",
                "penalty": 0}

    delta = round(abs(total_ded - computed_sum), 2)
    passed = delta <= TOLERANCE_ARITHMETIC

    return {
        "check": "deductions_sum",
        "pass": passed,
        "expected": round(computed_sum, 2),
        "actual": total_ded,
        "delta": delta,
        "severity": "ok" if passed else "critical",
        "message": (
            f"Deductions total ₹{total_ded:,.0f} matches sum of components"
            if passed else
            f"Deductions total ₹{total_ded:,.0f} ≠ sum of components ₹{computed_sum:,.0f} "
            f"(off by ₹{delta:,.0f})"
        ),
        "penalty": 0 if passed else PENALTY_ARITHMETIC,
    }


def check_arithmetic_gross(data: dict) -> dict:
    """Check: gross_salary == sum of individual earning components (±₹5)."""
    gross = _safe_get(data, "earnings", "gross_salary")
    computed_sum = _sum_earnings(data)

    if gross is None or computed_sum is None:
        return {"check": "earnings_sum", "pass": None, "severity": "skip",
                "message": "Insufficient data — gross salary or components missing.",
                "penalty": 0}

    delta = round(abs(gross - computed_sum), 2)
    passed = delta <= TOLERANCE_ARITHMETIC

    return {
        "check": "earnings_sum",
        "pass": passed,
        "expected": round(computed_sum, 2),
        "actual": gross,
        "delta": delta,
        "severity": "ok" if passed else "critical",
        "message": (
            f"Gross salary ₹{gross:,.0f} matches sum of earnings components"
            if passed else
            f"Gross salary ₹{gross:,.0f} ≠ sum of components ₹{computed_sum:,.0f} "
            f"(off by ₹{delta:,.0f})"
        ),
        "penalty": 0 if passed else PENALTY_ARITHMETIC,
    }


def check_pf_compliance(data: dict) -> dict:
    """Three-tier PF compliance check.

    Standard: PF ≈ 12% of basic ± 15% → pass
    Non-standard: PF ₹500–₹1,800 AND basic > ₹15,000 → informational (0 penalty)
    Anomalous: PF inconsistent with any known rule → -20 penalty
    """
    pf = _safe_get(data, "deductions", "pf_epf")
    basic = _safe_get(data, "earnings", "basic_salary")

    if pf is None or basic is None:
        return {"check": "pf_compliance", "pass": None, "severity": "skip",
                "message": "PF or basic salary not present — cannot verify.",
                "penalty": 0}

    if basic == 0:
        return {"check": "pf_compliance", "pass": None, "severity": "skip",
                "message": "Basic salary is zero — cannot compute PF ratio.",
                "penalty": 0}

    actual_rate = pf / basic
    expected_pf = basic * PF_STATUTORY_RATE
    deviation = abs(actual_rate - PF_STATUTORY_RATE) / PF_STATUTORY_RATE if PF_STATUTORY_RATE > 0 else 0

    # Tier 1: Standard — within 15% of 12%
    if deviation <= PF_TOLERANCE:
        return {
            "check": "pf_compliance", "pass": True, "severity": "ok",
            "actual_rate": round(actual_rate, 4),
            "expected_rate": PF_STATUTORY_RATE,
            "pf_amount": pf,
            "basic": basic,
            "tier": "standard",
            "message": f"PF ₹{pf:,.0f} is {actual_rate * 100:.1f}% of basic — consistent with 12% statutory rate.",
            "penalty": 0,
        }

    # Tier 2: Non-standard — PF between ₹500 and ₹1,800 with basic > ₹15,000
    # This is a legitimate Indian PF rule: contributions capped at ₹15,000 basic ceiling
    if (PF_NON_STANDARD_LOW <= pf <= PF_NON_STANDARD_HIGH) and basic > PF_WAGE_CEILING:
        return {
            "check": "pf_compliance", "pass": True, "severity": "info",
            "actual_rate": round(actual_rate, 4),
            "expected_rate": PF_STATUTORY_RATE,
            "pf_amount": pf,
            "basic": basic,
            "tier": "non_standard",
            "message": (
                f"PF ₹{pf:,.0f} ({actual_rate * 100:.1f}% of basic) — non-standard but consistent "
                f"with PF wage ceiling of ₹{PF_WAGE_CEILING:,} (12% of ₹{PF_WAGE_CEILING:,} = ₹{PF_WAGE_CEILING * 0.12:,.0f})."
            ),
            "penalty": 0,
        }

    # Tier 3: Anomalous — doesn't match any known pattern
    return {
        "check": "pf_compliance", "pass": False, "severity": "flag",
        "actual_rate": round(actual_rate, 4),
        "expected_rate": PF_STATUTORY_RATE,
        "pf_amount": pf,
        "basic": basic,
        "tier": "anomalous",
        "message": (
            f"PF ₹{pf:,.0f} ({actual_rate * 100:.1f}% of basic) deviates from 12% statutory rate "
            f"and does not match PF wage ceiling pattern. Expected ₹{expected_pf:,.0f} (±15%)."
        ),
        "penalty": PENALTY_PF,
    }


def check_tds_consistency(data: dict) -> dict:
    """Quick TDS check using the tax slab engine.

    Flags if actual TDS < 60% or > 140% of expected range.
    """
    compliance = compute_tax_compliance(data)
    if compliance is None:
        return {"check": "tds_consistency", "pass": None, "severity": "skip",
                "message": "Cannot verify TDS — gross salary or TDS not present.",
                "penalty": 0}

    verdict = compliance["verdict"]
    passed = verdict == "consistent"

    return {
        "check": "tds_consistency",
        "pass": passed,
        "actual_annual_tds": compliance["actual_annual_tds"],
        "expected_range": compliance["expected_tds_range"],
        "severity": "ok" if passed else "flag",
        "message": compliance["verdict_detail"],
        "penalty": 0 if passed else PENALTY_TDS,
    }


def check_round_numbers(data: dict) -> dict:
    """Flag if totals are suspiciously round when components are not.

    Round components (e.g. basic=₹30,000) are normal.
    Round totals with non-round components are suspicious.
    """
    gross = _safe_get(data, "earnings", "gross_salary")
    net = _safe_get(data, "net_pay", "net_salary")
    total_ded = _safe_get(data, "deductions", "total_deductions")
    tds = _safe_get(data, "deductions", "tds_income_tax")

    # Collect individual components to check if they're round
    components = []
    for key in ("basic_salary", "hra", "lta", "special_allowance", "overtime", "bonus"):
        val = _safe_get(data, "earnings", key)
        if val is not None and isinstance(val, (int, float)) and val > 0:
            components.append(val)
    for key in ("tds_income_tax", "pf_epf", "professional_tax"):
        val = _safe_get(data, "deductions", key)
        if val is not None and isinstance(val, (int, float)) and val > 0:
            components.append(val)

    if not components:
        return {"check": "round_numbers", "pass": None, "severity": "skip",
                "message": "Insufficient component data for round number check.",
                "penalty": 0}

    # Are most components NOT round?
    non_round_count = sum(1 for c in components if not _is_round(c, 5000))
    has_non_round_components = non_round_count > len(components) * 0.5

    # Check totals for suspicious roundness
    flagged = []
    for label, val in [("Gross salary", gross), ("Net salary", net),
                       ("Total deductions", total_ded), ("TDS", tds)]:
        if val is not None and _is_round(val, 5000) and has_non_round_components:
            flagged.append(f"{label} (₹{val:,.0f})")

    if not flagged:
        return {
            "check": "round_numbers", "pass": True, "severity": "ok",
            "flagged_fields": [],
            "message": "No suspicious rounding patterns detected.",
            "penalty": 0,
        }

    return {
        "check": "round_numbers", "pass": False, "severity": "flag",
        "flagged_fields": flagged,
        "message": f"Suspiciously round values with non-round components: {', '.join(flagged)}.",
        "penalty": PENALTY_ROUND,
    }


def check_professional_tax(data: dict) -> dict:
    """Flag if professional tax exceeds ₹300/month."""
    pt = _safe_get(data, "deductions", "professional_tax")

    if pt is None:
        return {"check": "professional_tax", "pass": None, "severity": "skip",
                "message": "Professional tax not present — no check needed.",
                "penalty": 0}

    passed = pt <= PT_MONTHLY_CAP

    return {
        "check": "professional_tax",
        "pass": passed,
        "pt_monthly": pt,
        "cap": PT_MONTHLY_CAP,
        "severity": "ok" if passed else "flag",
        "message": (
            f"Professional tax ₹{pt:,.0f}/month is within standard limits."
            if passed else
            f"Professional tax ₹{pt:,.0f}/month exceeds ₹{PT_MONTHLY_CAP:,.0f} cap — "
            f"possible data entry error or fabrication."
        ),
        "penalty": 0 if passed else PENALTY_PT,
    }


# ---------------------------------------------------------------------------
# Enhancement 1 — Authenticity Score Aggregator
# ---------------------------------------------------------------------------
def compute_authenticity_score(data: dict) -> dict:
    """Run all checks and produce a 0-100 authenticity score.

    Scoring: start at 100.
    - Arithmetic failures (category): -40 if ANY of the 3 arithmetic checks fail
    - PF non-compliance: -20
    - TDS inconsistency: -15
    - Round number suspicion: -10
    - PT exceeds cap: -15
    """
    checks = [
        check_arithmetic_net(data),
        check_arithmetic_deductions(data),
        check_arithmetic_gross(data),
        check_pf_compliance(data),
        check_tds_consistency(data),
        check_round_numbers(data),
        check_professional_tax(data),
    ]

    score = 100

    # Arithmetic is a CATEGORY — deduct -40 once if any of the 3 fail
    arithmetic_checks = [c for c in checks if c["check"] in ("net_arithmetic", "deductions_sum", "earnings_sum")]
    arithmetic_failed = any(c.get("pass") is False for c in arithmetic_checks)
    if arithmetic_failed:
        score -= PENALTY_ARITHMETIC

    # Other checks — deduct individually
    for check in checks:
        if check["check"] in ("net_arithmetic", "deductions_sum", "earnings_sum"):
            continue  # already handled above
        if check.get("pass") is False:
            score -= check.get("penalty", 0)

    score = max(0, score)

    # Label
    if score >= 80:
        label = "Strong"
    elif score >= 50:
        label = "Moderate"
    elif score >= 25:
        label = "Weak"
    else:
        label = "Suspicious"

    return {
        "score": score,
        "label": label,
        "flags": checks,
    }


# ---------------------------------------------------------------------------
# Enhancement 5 — Employer Compliance Signals
# ---------------------------------------------------------------------------
def compute_employer_signals(data: dict, payslips_list: list = None) -> dict:
    """Derive employer compliance signals from payslip data.

    Args:
        data: single normalised payslip
        payslips_list: optional list of all payslips for batch signals
    """
    signals = []

    # 1. EPFO registered — PF deduction present
    pf = _safe_get(data, "deductions", "pf_epf")
    signals.append({
        "name": "epfo_registered",
        "present": pf is not None and pf > 0,
        "label": "EPFO Registered",
        "detail": (
            "PF deduction confirms formal EPFO registration."
            if pf is not None and pf > 0 else
            "No PF deduction — employer may not be EPFO registered."
        ),
        "category": "positive" if (pf is not None and pf > 0) else "missing",
    })

    # 2. State tax compliant — Professional tax present
    pt = _safe_get(data, "deductions", "professional_tax")
    signals.append({
        "name": "state_tax_compliant",
        "present": pt is not None and pt > 0,
        "label": "State Tax Compliant",
        "detail": (
            "Professional tax deducted — employer files state returns."
            if pt is not None and pt > 0 else
            "No professional tax — employer may be in a non-PT state or non-compliant."
        ),
        "category": "positive" if (pt is not None and pt > 0) else "missing",
    })

    # 3. Small-medium employer — ESIC present
    esic = _safe_get(data, "deductions", "esic")
    if esic is not None and esic > 0:
        signals.append({
            "name": "small_medium_employer",
            "present": True,
            "label": "Small-Medium Employer",
            "detail": "ESIC deduction suggests employer has <500 employees (ESIC threshold).",
            "category": "neutral",
        })
    else:
        signals.append({
            "name": "small_medium_employer",
            "present": False,
            "label": "ESIC Not Deducted",
            "detail": "Employer likely has 500+ employees or is exempt (IT/finance sector common exemption).",
            "category": "neutral",
        })

    # 4. Established employer — inferred from employment tenure (> 5 years)
    # Gratuity is an employer liability, not a standard deduction line item,
    # so checking for it in deductions is unreliable. Instead, if the employee
    # has been working there 5+ years, the employer is established by definition.
    emp_date_str = _safe_get(data, "employee", "employment_date")
    tenure_years = None
    if emp_date_str:
        try:
            emp_dt = date.fromisoformat(emp_date_str)
            tenure_years = (date.today() - emp_dt).days / 365.25
        except (ValueError, TypeError):
            pass

    if tenure_years is not None and tenure_years >= 5:
        signals.append({
            "name": "established_employer",
            "present": True,
            "label": "Established Employer",
            "detail": f"Employee tenure of {tenure_years:.1f} years confirms employer operating 5+ years.",
            "category": "positive",
        })
    elif tenure_years is not None:
        signals.append({
            "name": "established_employer",
            "present": None,
            "label": "Established Employer",
            "detail": f"Employee tenure is {tenure_years:.1f} years — cannot confirm employer operating 5+ years from this data alone.",
            "category": "neutral",
        })
    else:
        signals.append({
            "name": "established_employer",
            "present": None,
            "label": "Established Employer",
            "detail": "Employment date not available — cannot assess employer tenure.",
            "category": "neutral",
        })

    # 5. Correct PF computation — PF ≈ 12% of basic ± 5%
    basic = _safe_get(data, "earnings", "basic_salary")
    if pf is not None and basic is not None and basic > 0:
        pf_rate = pf / basic
        within_range = abs(pf_rate - PF_STATUTORY_RATE) / PF_STATUTORY_RATE <= 0.05
        signals.append({
            "name": "correct_pf_computation",
            "present": within_range,
            "label": "Correct PF Computation",
            "detail": (
                f"PF is {pf_rate * 100:.1f}% of basic — compliant payroll."
                if within_range else
                f"PF is {pf_rate * 100:.1f}% of basic (expected ~12%) — may use PF wage ceiling or non-standard rate."
            ),
            "category": "positive" if within_range else "missing",
        })
    else:
        signals.append({
            "name": "correct_pf_computation",
            "present": None,
            "label": "PF Computation",
            "detail": "Cannot verify — PF or basic salary not present.",
            "category": "neutral",
        })

    # 6. Payroll software used — batch signal: consistent decimal formatting
    if payslips_list and len(payslips_list) >= 2:
        # Check if all payslips use consistent decimal formatting on monetary values
        formatting_patterns = set()
        for p in payslips_list:
            net = _safe_get(p, "net_pay", "net_salary")
            if net is not None:
                # Check if values are whole numbers or have decimals
                formatting_patterns.add(net == int(net))
        consistent = len(formatting_patterns) <= 1
        signals.append({
            "name": "payroll_software_used",
            "present": consistent,
            "label": "Payroll Software Used",
            "detail": (
                "Consistent salary formatting across payslips suggests formal payroll software."
                if consistent else
                "Inconsistent decimal formatting across payslips — may indicate manual processing."
            ),
            "category": "positive" if consistent else "missing",
        })
    else:
        signals.append({
            "name": "payroll_software_used",
            "present": None,
            "label": "Payroll Software Used",
            "detail": "Requires multiple payslips to assess.",
            "category": "batch_required",
        })

    # 7. Salary paid on time — batch signal: consistent issue dates
    if payslips_list and len(payslips_list) >= 2:
        issue_days = []
        for p in payslips_list:
            doi = _safe_get(p, "document_meta", "date_of_issue")
            if doi:
                try:
                    dt = date.fromisoformat(doi)
                    issue_days.append(dt.day)
                except (ValueError, TypeError):
                    pass

        if len(issue_days) >= 2:
            day_range = max(issue_days) - min(issue_days)
            consistent = day_range <= 5  # within 5-day window
            signals.append({
                "name": "salary_paid_on_time",
                "present": consistent,
                "label": "Salary Paid On Time",
                "detail": (
                    f"Pay dates consistent (day {min(issue_days)}–{max(issue_days)} of month) — employer is financially stable."
                    if consistent else
                    f"Pay dates vary (day {min(issue_days)}–{max(issue_days)}) — may indicate irregular payroll."
                ),
                "category": "positive" if consistent else "missing",
            })
        else:
            signals.append({
                "name": "salary_paid_on_time",
                "present": None,
                "label": "Salary Paid On Time",
                "detail": "Insufficient date data to assess payment timing.",
                "category": "batch_required",
            })
    else:
        signals.append({
            "name": "salary_paid_on_time",
            "present": None,
            "label": "Salary Paid On Time",
            "detail": "Requires multiple payslips to assess.",
            "category": "batch_required",
        })

    # Summary counts
    assessable = [s for s in signals if s["category"] not in ("batch_required", "neutral")]
    positive = [s for s in assessable if s["present"] is True]

    return {
        "signals": signals,
        "positive_count": len(positive),
        "total_assessable": len(assessable),
    }
