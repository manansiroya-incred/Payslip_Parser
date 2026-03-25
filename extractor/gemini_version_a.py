"""
Version A — Single combined Gemini prompt.

Merges extraction and insight generation into one call.
Gemini returns raw_fields + gemini_insights together in one response.
Uses free-form JSON (no Pydantic schema constraint).
"""

import json
from typing import Optional

from google import genai
from google.genai import types

from .gemini_extractor import EXTRACTION_SYSTEM_PROMPT, _parse_gemini_json


# ---------------------------------------------------------------------------
# Combined system prompt — extends extraction with Section 5
# ---------------------------------------------------------------------------
COMBINED_SYSTEM_PROMPT = EXTRACTION_SYSTEM_PROMPT + """

SECTION 5 — INSIGHT GENERATION (Version A)
After extracting all fields, also compute and return the following
under a top-level "gemini_insights" key:

- Annualised gross and net salary (multiply monthly by 12, or apply
  appropriate multiplier for weekly/biweekly/daily)
- Take-home ratio (net / gross as percentage)
- Effective TDS rate (TDS / gross as percentage, if TDS present)
- Total deduction rate (total deductions / gross as percentage)
- PF as percentage of basic (if both present)
- HRA and LTA as percentage of gross (if present)
- Salary frequency classification (monthly/weekly/biweekly/daily)
- For any non-standard components found (unusual allowances,
  employer-specific deductions): compute the same style of
  percentage-of-gross insight and include it

For each insight include:
- value: the computed number
- unit: e.g. "% of gross", "INR/year", "ratio"
- label: a plain English label
- description: a one-sentence description suitable for a loan officer

Return your response as a JSON object with two top-level keys:
1. "raw_fields" — containing all the extracted fields from Sections 1-4
2. "gemini_insights" — containing all computed insights from this section

Example structure:
{
  "raw_fields": {
    "document_meta": {...},
    "employer_details": {...},
    "employee_details": {...},
    "pay_period": {...},
    "earnings": {...},
    "deductions": {...},
    "net_pay": {...},
    "other_fields": {...},
    "_confidence": {...}
  },
  "gemini_insights": {
    "annual_gross": {
      "value": 696000,
      "unit": "INR/year",
      "label": "Annualised Gross Salary",
      "description": "Monthly gross of ₹58,000 annualised to ₹6,96,000"
    },
    "take_home_ratio": {
      "value": 77.6,
      "unit": "%",
      "label": "Take-Home Ratio",
      "description": "Employee takes home 77.6% of gross salary"
    }
    ...
  }
}"""


# ---------------------------------------------------------------------------
# Version A extraction + analysis function
# ---------------------------------------------------------------------------
def extract_and_analyse_v1(
    files: list[dict],
    client: genai.Client,
    model: str = "gemini-2.5-flash",
) -> list[dict]:
    """
    Version A: Single Gemini call for extraction + insights.

    Returns a list of dicts, each with:
      - raw_fields: extraction data (same structure as Call 1)
      - gemini_insights: computed insights
      - _source_file: original filename
    """
    results = []

    for file_info in files:
        contents = [
            types.Part.from_bytes(
                data=file_info["bytes"],
                mime_type=file_info["mime_type"],
            ),
            "Extract all payslip fields and compute insights according to your instructions.",
        ]

        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=COMBINED_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )

        result = _parse_gemini_json(response.text)

        # Version A returns {raw_fields, gemini_insights} at top level.
        # If Gemini returned a flat structure instead, wrap it.
        if "raw_fields" not in result and "gemini_insights" not in result:
            result = {
                "raw_fields": result,
                "gemini_insights": {},
            }

        # Ensure required keys
        result.setdefault("raw_fields", {})
        result.setdefault("gemini_insights", {})
        result["_source_file"] = file_info["name"]

        results.append(result)

    return results
