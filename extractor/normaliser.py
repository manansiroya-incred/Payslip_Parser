"""
Normaliser — maps Gemini's free-form extraction JSON to the canonical
internal schema defined in config/field_schema.json.

Handles:
- Monetary value cleanup (commas, currency symbols → float)
- Date standardisation (various formats → ISO YYYY-MM-DD)
- Salary frequency detection
- Preserves all other_earnings, other_deductions, raw_extras as open dicts
"""

import re
from datetime import date
from typing import Any, Optional

from dateutil import parser as dateutil_parser


# ---------------------------------------------------------------------------
# Monetary value normalisation
# ---------------------------------------------------------------------------
def _normalise_monetary(value: Any) -> Optional[float]:
    """Convert string/int/float monetary values to float.

    Handles: "₹12,500.00", "Rs. 12500", "12,500", 12500, "12500.50"
    Returns None if value is None or cannot be parsed.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Remove currency symbols, commas, spaces, Rs, INR prefix
        cleaned = value.strip()
        cleaned = re.sub(r"[₹$€£]", "", cleaned)
        cleaned = re.sub(r"(?i)^(rs\.?|inr)\s*", "", cleaned)
        cleaned = cleaned.replace(",", "").replace(" ", "").strip()
        if not cleaned or cleaned == "-":
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Date normalisation
# ---------------------------------------------------------------------------
_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%Y/%m/%d",
]

_MONTH_YEAR_FORMATS = [
    "%B %Y",      # March 2025
    "%b %Y",      # Mar 2025
    "%m-%Y",      # 03-2025
    "%m/%Y",      # 03/2025
    "%Y-%m",      # 2025-03
]


def _normalise_date(value: Any) -> Optional[str]:
    """Parse various date formats to ISO YYYY-MM-DD.

    Returns None if value is None or cannot be parsed.
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    # Try explicit formats first
    from datetime import datetime

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue

    # Try month-year formats (no day component)
    for fmt in _MONTH_YEAR_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.strftime("%Y-%m")
        except ValueError:
            continue

    # Fall back to dateutil
    try:
        parsed = dateutil_parser.parse(cleaned, dayfirst=True)
        return parsed.date().isoformat()
    except (ValueError, TypeError):
        pass

    return None


# ---------------------------------------------------------------------------
# Frequency detection
# ---------------------------------------------------------------------------
_FREQUENCY_ALIASES = {
    "monthly": "monthly",
    "month": "monthly",
    "weekly": "weekly",
    "week": "weekly",
    "biweekly": "biweekly",
    "bi-weekly": "biweekly",
    "fortnightly": "biweekly",
    "daily": "daily",
    "day": "daily",
}


def _detect_frequency(raw_extraction: dict) -> str:
    """Detect salary frequency from extraction data."""
    # Check if Gemini already detected it
    doc_meta = raw_extraction.get("document_meta", {})
    freq = doc_meta.get("salary_frequency")
    if freq and isinstance(freq, str):
        normalised = _FREQUENCY_ALIASES.get(freq.lower().strip())
        if normalised:
            return normalised

    # Heuristic: if days_in_period is 7, it's weekly; ~14 biweekly; ~30 monthly
    pay_period = raw_extraction.get("pay_period", {})
    days = pay_period.get("days_in_period")
    if days is not None:
        try:
            days = float(days)
            if days <= 7:
                return "weekly"
            elif days <= 16:
                return "biweekly"
            elif days <= 1:
                return "daily"
        except (ValueError, TypeError):
            pass

    return "monthly"  # default assumption


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------
def _safe_get(data: dict, *keys, default=None) -> Any:
    """Safely navigate nested dicts."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


def _normalise_monetary_dict(d: dict) -> dict:
    """Normalise all values in a flat dict to floats where possible."""
    result = {}
    for k, v in d.items():
        normalised = _normalise_monetary(v)
        if normalised is not None:
            result[k] = normalised
        else:
            result[k] = v  # preserve non-monetary values as-is
    return result


# ---------------------------------------------------------------------------
# Main normaliser
# ---------------------------------------------------------------------------
def normalise_extraction(raw: dict) -> dict:
    """
    Map Gemini's free-form extraction JSON to the canonical internal schema.

    Returns a dict matching config/field_schema.json structure.
    No data is discarded — non-standard fields go to other_earnings,
    other_deductions, or raw_extras.
    """
    if raw.get("error"):
        return raw  # pass through error responses

    # --- document_meta ---
    doc_meta_raw = raw.get("document_meta", {})
    document_meta = {
        "date_of_issue": _normalise_date(doc_meta_raw.get("date_of_issue")),
        "pay_period_label": doc_meta_raw.get("pay_period_label"),
        "pay_period_start": _normalise_date(doc_meta_raw.get("pay_period_start")),
        "pay_period_end": _normalise_date(doc_meta_raw.get("pay_period_end")),
        "salary_frequency": _detect_frequency(raw),
        "currency": doc_meta_raw.get("currency", "INR"),
    }

    # --- employer ---
    emp_raw = raw.get("employer_details", {})
    employer = {
        "name": emp_raw.get("name") or "",
        "address": emp_raw.get("address") or "",
        "department": emp_raw.get("department") or "",
    }

    # --- employee ---
    ee_raw = raw.get("employee_details", {})
    employee = {
        "name": ee_raw.get("name") or "",
        "employee_id": ee_raw.get("employee_id") or "",
        "date_of_birth": _normalise_date(ee_raw.get("date_of_birth")),
        "address": ee_raw.get("address") or "",
        "job_title": ee_raw.get("job_title") or "",
        "employment_date": _normalise_date(ee_raw.get("employment_date")),
        "bank_account": ee_raw.get("bank_account") or "",
    }

    # --- attendance ---
    pay_period_raw = raw.get("pay_period", {})
    attendance = {
        "days_worked": _normalise_monetary(pay_period_raw.get("days_worked")),
        "hours_worked": _normalise_monetary(pay_period_raw.get("hours_worked")),
        "hourly_rate": _normalise_monetary(pay_period_raw.get("hourly_rate")),
        "days_in_period": _normalise_monetary(pay_period_raw.get("days_in_period")),
    }

    # --- earnings ---
    earn_raw = raw.get("earnings", {})
    other_earnings_raw = earn_raw.get("other_earnings", {})
    if isinstance(other_earnings_raw, dict):
        other_earnings = _normalise_monetary_dict(other_earnings_raw)
    elif isinstance(other_earnings_raw, list):
        # Some formats return list of {name, amount} dicts
        other_earnings = {}
        for item in other_earnings_raw:
            if isinstance(item, dict):
                name = item.get("name", item.get("label", "unknown"))
                amount = _normalise_monetary(item.get("amount", item.get("value")))
                other_earnings[str(name)] = amount
    else:
        other_earnings = {}

    earnings = {
        "basic_salary": _normalise_monetary(earn_raw.get("basic_salary")),
        "hra": _normalise_monetary(earn_raw.get("hra")),
        "lta": _normalise_monetary(earn_raw.get("lta")),
        "special_allowance": _normalise_monetary(earn_raw.get("special_allowance")),
        "overtime": _normalise_monetary(earn_raw.get("overtime")),
        "bonus": _normalise_monetary(earn_raw.get("bonus")),
        "other_earnings": other_earnings,
        "gross_salary": _normalise_monetary(earn_raw.get("gross_salary")),
    }

    # --- deductions ---
    ded_raw = raw.get("deductions", {})
    other_deductions_raw = ded_raw.get("other_deductions", {})
    if isinstance(other_deductions_raw, dict):
        other_deductions = _normalise_monetary_dict(other_deductions_raw)
    elif isinstance(other_deductions_raw, list):
        other_deductions = {}
        for item in other_deductions_raw:
            if isinstance(item, dict):
                name = item.get("name", item.get("label", "unknown"))
                amount = _normalise_monetary(item.get("amount", item.get("value")))
                other_deductions[str(name)] = amount
    else:
        other_deductions = {}

    deductions = {
        "tds_income_tax": _normalise_monetary(ded_raw.get("tds_income_tax")),
        "pf_epf": _normalise_monetary(ded_raw.get("pf_epf")),
        "professional_tax": _normalise_monetary(ded_raw.get("professional_tax")),
        "gratuity": _normalise_monetary(ded_raw.get("gratuity")),
        "esic": _normalise_monetary(ded_raw.get("esic")),
        "loan_deduction": _normalise_monetary(ded_raw.get("loan_deduction")),
        "other_deductions": other_deductions,
        "total_deductions": _normalise_monetary(ded_raw.get("total_deductions")),
    }

    # --- net_pay ---
    net_raw = raw.get("net_pay", {})
    net_pay = {
        "net_salary": _normalise_monetary(net_raw.get("net_salary")),
        "ctc_mentioned": _normalise_monetary(net_raw.get("ctc_mentioned")),
    }

    # --- raw_extras (anything not in standard categories) ---
    raw_extras = raw.get("other_fields", {})
    if not isinstance(raw_extras, dict):
        raw_extras = {}

    # --- confidence ---
    confidence = raw.get("_confidence", {})

    # --- source file ---
    source_file = raw.get("_source_file", "")

    return {
        "document_meta": document_meta,
        "employer": employer,
        "employee": employee,
        "attendance": attendance,
        "earnings": earnings,
        "deductions": deductions,
        "net_pay": net_pay,
        "raw_extras": raw_extras,
        "_confidence": confidence,
        "_source_file": source_file,
    }
