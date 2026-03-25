"""
Gemini Call 1 — Extraction (used by both Version A and Version B).

Sends raw file bytes (PDF/image) directly to Gemini with MIME type.
No PDF-to-image conversion. Returns free-form JSON (no Pydantic schema
constraint) so that other_earnings, other_deductions, and raw_extras
are never rejected by strict validation.
"""

import json
import os
from typing import Optional

from google import genai
from google.genai import types


# ---------------------------------------------------------------------------
# Supported MIME types
# ---------------------------------------------------------------------------
SUPPORTED_MIMES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
}

_EXT_TO_MIME = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


# ---------------------------------------------------------------------------
# Extraction system prompt — 4 sections
# ---------------------------------------------------------------------------
EXTRACTION_SYSTEM_PROMPT = """You are a financial document extraction specialist for an Indian NBFC.
Extract all structured information from this payslip or salary document.

SECTION 1 — ROLE
You are an expert at reading Indian payslips across diverse formats:
corporate MNC slips, government pay stubs, small-business salary letters,
scanned images, and informal formats. You must extract every single field
visible in the document.

SECTION 2 — INSTRUCTIONS
- Extract every field present in the document. Do not skip any field even
  if it seems minor or unusual.
- For monetary values, extract the raw number only — no currency symbols,
  no commas.
- For the "currency" field in document_meta: detect the actual currency from
  the document. Look for: $ or "USD" → "USD"; £ or "GBP" → "GBP"; € or
  "EUR" → "EUR"; ¥ or "JPY" → "JPY". Only use "INR" if the document is
  clearly Indian (₹ symbol, "Rs", "INR", Indian employer/address, or no
  other currency indicator is present).
- For dates, extract exactly as written — normalisation happens downstream.
- IMPORTANT: "Pay Date" or "date of issue" is NOT the same as pay_period_end.
  Only populate pay_period_end if the document explicitly states a period end
  date that is separate from the pay/issue date. If only a pay date is shown,
  set pay_period_end to null and put the pay date in date_of_issue only.
- For percentage values, extract as a decimal (10% → 0.10).
- If a field is present but illegible, set its value to null and set
  confidence to "low".
- If this document is not a payslip or salary document, return
  {"error": "not_a_payslip"} and nothing else.
- Return ONLY valid JSON. No prose, no markdown fences.

SECTION 3 — OUTPUT STRUCTURE
Organise extracted fields into these categories. Include any field you
find even if it does not fit neatly into a category — put it in
other_fields with its original label as the key:

{
  "document_meta": {
    "date_of_issue": "date as written",
    "pay_period_label": "e.g. March 2025",
    "pay_period_start": "date as written or null",
    "pay_period_end": "date as written or null",
    "salary_frequency": "monthly or weekly or biweekly or daily or null",
    "currency": "INR"
  },
  "employer_details": {
    "name": "",
    "address": "",
    "department": ""
  },
  "employee_details": {
    "name": "",
    "employee_id": "",
    "date_of_birth": "",
    "address": "",
    "job_title": "",
    "employment_date": "",
    "bank_account": ""
  },
  "pay_period": {
    "days_worked": null,
    "hours_worked": null,
    "hourly_rate": null,
    "days_in_period": null
  },
  "earnings": {
    "basic_salary": null,
    "hra": null,
    "lta": null,
    "special_allowance": null,
    "overtime": null,
    "bonus": null,
    "other_earnings": {},
    "gross_salary": null
  },
  "deductions": {
    "tds_income_tax": null,
    "pf_epf": null,
    "professional_tax": null,
    "gratuity": null,
    "esic": null,
    "loan_deduction": null,
    "other_deductions": {},
    "total_deductions": null
  },
  "net_pay": {
    "net_salary": null,
    "ctc_mentioned": null
  },
  "other_fields": {}
}

Put any field that does not fit into the above categories into other_fields
with its original label as the key and its value.

other_earnings and other_deductions are open dicts — any non-standard
earning or deduction found goes here with its original label as the key.
No data should ever be discarded.

SECTION 4 — CONFIDENCE
Include a "_confidence" key INSIDE the same JSON object, at the top level,
alongside the other sections. Its value is an object with values "high",
"medium", or "low" for every extracted field, mirroring the structure above.

CRITICAL: Return everything as ONE single JSON object. The _confidence key
must be inside the same { } braces as document_meta, employer_details, etc.
Do NOT return two separate JSON objects. Example top-level structure:

{
  "document_meta": {...},
  "employer_details": {...},
  "employee_details": {...},
  "pay_period": {...},
  "earnings": {...},
  "deductions": {...},
  "net_pay": {...},
  "other_fields": {...},
  "_confidence": {...}
}"""


# ---------------------------------------------------------------------------
# Pre-processor
# ---------------------------------------------------------------------------
def _detect_mime(filename: str) -> Optional[str]:
    """Detect MIME type from file extension."""
    ext = os.path.splitext(filename)[1].lower()
    return _EXT_TO_MIME.get(ext)


def preprocess_files(uploaded_files: list) -> list[dict]:
    """
    Validate uploaded files and return a list of dicts with:
      - bytes: raw file bytes
      - mime_type: detected MIME type
      - name: original filename
    """
    processed = []
    for f in uploaded_files:
        file_bytes = f.getvalue()

        # Detect MIME
        mime = None
        if hasattr(f, "type") and f.type in SUPPORTED_MIMES:
            mime = f.type
        if mime is None:
            mime = _detect_mime(f.name)
        if mime is None:
            raise ValueError(
                f"Unsupported file type: {f.name}. "
                f"Supported: PDF, JPG, PNG."
            )

        # Size check
        if len(file_bytes) > MAX_FILE_SIZE:
            raise ValueError(
                f"File too large: {f.name} "
                f"({len(file_bytes) / (1024*1024):.1f} MB, max 50 MB)."
            )

        processed.append({
            "bytes": file_bytes,
            "mime_type": mime,
            "name": f.name,
        })

    return processed


# ---------------------------------------------------------------------------
# Robust JSON parser — handles concatenated JSON objects from Gemini
# ---------------------------------------------------------------------------
def _deep_merge(base: dict, overlay: dict) -> dict:
    """Deep merge overlay into base without overwriting nested dicts."""
    for k, v in overlay.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _parse_gemini_json(text: str) -> dict:
    """Parse Gemini's JSON response, handling edge cases.

    Gemini sometimes returns two concatenated JSON objects instead of one:
      { ...fields... }
      { "_confidence": {...} }

    This parser:
    1. Tries json.loads() on the full text (happy path)
    2. If that fails, attempts to split on }{ boundaries and merge
    3. If all else fails, returns the raw text with an error flag
    """
    text = text.strip()

    # Happy path: single valid JSON object
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: try to split concatenated JSON objects
    # Look for }{ or }\n{ or }\n\n{ boundaries at brace depth 0
    objects = _split_concatenated_json(text)
    if objects and len(objects) >= 1:
        # Deep merge all objects so nested dicts (e.g. document_meta)
        # are not overwritten by a second object's confidence values
        merged = {}
        for obj in objects:
            _deep_merge(merged, obj)
        return merged

    # Last resort: return raw text with error flag
    return {
        "error": "json_parse_failed",
        "raw_response": text,
    }


def _split_concatenated_json(text: str) -> list[dict]:
    """Split a string containing multiple concatenated JSON objects.

    Tracks brace depth to find boundaries between top-level objects.
    """
    objects = []
    depth = 0
    start = None
    in_string = False
    escape_next = False

    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue

        if ch == '\\' and in_string:
            escape_next = True
            continue

        if ch == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                chunk = text[start:i + 1]
                try:
                    objects.append(json.loads(chunk))
                except json.JSONDecodeError:
                    pass
                start = None

    return objects


# ---------------------------------------------------------------------------
# Extraction function (Version B Call 1 / shared by both versions)
# ---------------------------------------------------------------------------
def extract_payslip_fields(
    files: list[dict],
    client: genai.Client,
    model: str = "gemini-2.5-flash",
) -> list[dict]:
    """
    Extract fields from one or more payslip files.

    Each file is processed in its own Gemini call for reliability.
    Returns a list of raw extraction dicts (free-form JSON from Gemini).
    """
    results = []

    for file_info in files:
        contents = [
            types.Part.from_bytes(
                data=file_info["bytes"],
                mime_type=file_info["mime_type"],
            ),
            "Extract all payslip fields from this document according to your instructions.",
        ]

        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=EXTRACTION_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )

        extraction = _parse_gemini_json(response.text)
        extraction["_source_file"] = file_info["name"]
        results.append(extraction)

    return results
