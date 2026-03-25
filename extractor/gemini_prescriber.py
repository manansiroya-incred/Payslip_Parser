"""
Gemini Call 2 — Prescription + non-standard computation (Version B only).

Receives the extracted JSON from Call 1 (NOT the original file).
Tells Python which HARDCODED_INSIGHTS functions to run, and directly
computes insights for any components Python cannot handle.

The prompt is generated PROGRAMMATICALLY from HARDCODED_INSIGHTS.keys() —
never hardcoded as a static string. Adding a new function to
HARDCODED_INSIGHTS automatically includes it in the prompt.
"""

import json
from typing import Any

from google import genai
from google.genai import types

from calculator.insights import HARDCODED_INSIGHTS


# ---------------------------------------------------------------------------
# Build prescription prompt dynamically
# ---------------------------------------------------------------------------
def _build_prescription_prompt(extracted_json: dict) -> str:
    """Build the prescription prompt from HARDCODED_INSIGHTS keys."""
    # Exclude salary_consistency — it's batch-only
    insight_names = [
        k for k in HARDCODED_INSIGHTS.keys()
        if k != "salary_consistency"
    ]

    # Explicit field requirements — prevents Gemini from guessing wrong
    REQUIREMENTS = {
        "monthly_to_annual_conversion": "earnings.gross_salary AND net_pay.net_salary",
        "take_home_ratio": "earnings.gross_salary AND net_pay.net_salary",
        "effective_tds_rate": "deductions.tds_income_tax AND earnings.gross_salary",
        "pf_as_pct_of_basic": "deductions.pf_epf AND earnings.basic_salary",
        "deduction_breakdown": "earnings.gross_salary (and any deductions present)",
        "hourly_normalisation": "attendance.hours_worked AND attendance.hourly_rate, OR attendance.days_worked",
        "overtime_analysis": "earnings.overtime AND earnings.gross_salary (does NOT need hours or hourly rate)",
        "hra_as_pct_of_gross": "earnings.hra AND earnings.gross_salary",
        "lta_as_pct_of_gross": "earnings.lta AND earnings.gross_salary",
        "professional_tax_check": "deductions.professional_tax",
        "gratuity_accrual_estimate": "earnings.basic_salary (employment_date optional)",
    }
    insight_list = "\n".join(
        f"  - {name}: requires {REQUIREMENTS.get(name, 'see function')}"
        for name in insight_names
    )

    return f"""You have extracted the following data from a payslip:

{json.dumps(extracted_json, indent=2, default=str)}

The following insights can be computed by our calculation engine
automatically if the required fields are present. For each one,
respond true or false on whether to run it, and give a reason if false.
The required fields for each insight are listed — only set false if the
required fields are genuinely null/absent:

{insight_list}

IMPORTANT: Always set "salary_consistency" to false — this is a batch-only
insight that cannot run on a single document. It is not included in the
list above but must be present in your response as false.

For any fields or components present in this payslip that fall OUTSIDE
the above list — for example unusual allowances, employer-specific
deductions, or non-standard components — compute the insight directly
and include it in gemini_computed_insights.

For each gemini-computed insight include:
- value: the computed number
- unit: e.g. "% of gross", "INR", "ratio"
- label: a plain English label
- description: a one-sentence description suitable for a loan officer

Return ONLY valid JSON in this exact format:
{{
  "run_hardcoded": {{
    "monthly_to_annual_conversion": true,
    "take_home_ratio": true,
    ...one key per insight listed above plus salary_consistency...
  }},
  "skip_reasons": {{
    "pf_as_pct_of_basic": "PF not present in this payslip",
    ...only for entries where run_hardcoded is false...
  }},
  "gemini_computed_insights": {{
    "special_productivity_allowance_pct": {{
      "value": 8.6,
      "unit": "% of gross",
      "label": "Special Productivity Allowance",
      "description": "₹5,000 productivity allowance represents 8.6% of gross salary"
    }}
    ...one entry per non-standard component found, or empty if none...
  }}
}}"""


# ---------------------------------------------------------------------------
# Prescription function
# ---------------------------------------------------------------------------
def prescribe_insights(
    extracted_data: dict,
    client: genai.Client,
    model: str = "gemini-2.5-flash",
) -> dict:
    """
    Call 2: Prescribe which hardcoded insights to run and compute
    non-standard insights directly.

    Args:
        extracted_data: Normalised extraction dict from Call 1
        client: Gemini client
        model: Model ID

    Returns:
        Dict with keys: run_hardcoded, skip_reasons, gemini_computed_insights
    """
    prompt = _build_prescription_prompt(extracted_data)

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0,
        ),
    )

    try:
        result = json.loads(response.text)
    except json.JSONDecodeError:
        result = {
            "run_hardcoded": {},
            "skip_reasons": {"_error": "Failed to parse prescription response"},
            "gemini_computed_insights": {},
        }

    # Ensure required keys exist
    result.setdefault("run_hardcoded", {})
    result.setdefault("skip_reasons", {})
    result.setdefault("gemini_computed_insights", {})

    # Force salary_consistency to false (safety net)
    result["run_hardcoded"]["salary_consistency"] = False

    return result
