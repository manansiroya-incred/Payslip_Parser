# Payslip Parser & Document Analyser Agent

A Streamlit-based payslip analysis tool built for **InCred Finance** that extracts structured data from Indian and international payslips using Gemini Vision, computes financial insights via Python, and presents results in an interactive 4-tab UI. Supports two processing versions (A and B) for comparison, batch analysis of up to 3 months, loan pre-screening with EMI calculation, and per-session Markdown report generation.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Setup & Installation](#setup--installation)
- [Usage](#usage)
- [Processing Versions](#processing-versions)
- [Data Pipeline](#data-pipeline)
- [Extraction Prompt Design](#extraction-prompt-design)
- [Normalisation](#normalisation)
- [Insight Calculation Engine](#insight-calculation-engine)
- [Prescriber (Version B Call 2)](#prescriber-version-b-call-2)
- [UI Tabs](#ui-tabs)
- [Charts](#charts)
- [Report Generation](#report-generation)
- [Indian Number Formatting](#indian-number-formatting)
- [Design Decisions](#design-decisions)
- [Configuration](#configuration)
- [Future Enhancements](#future-enhancements)

---

## Features

- **Multi-format support** — PDF, JPG, PNG payslips sent as raw bytes to Gemini Vision (no PDF-to-image conversion)
- **Two processing versions** — Version A (single Gemini call) vs Version B (two calls + Python calculation) for accuracy comparison
- **12 hardcoded insight functions** — Pure Python calculations for annualisation, take-home ratio, TDS rate, PF ratio, deduction breakdown, salary consistency, hourly normalisation, overtime analysis, HRA/LTA ratios, professional tax, and gratuity accrual
- **Batch mode** — Upload 2-3 payslips for month-on-month trend analysis with salary consistency scoring
- **Loan pre-screening** — EMI calculation, FOIR affordability check, and AI-generated eligibility commentary
- **Session reports** — Markdown reports saved to `data/sessions/` after each analysis run for version comparison
- **Indian number formatting** — Correct comma placement for INR amounts (e.g. 11,16,000 instead of 1,116,000)
- **Currency-aware** — Auto-detects USD, GBP, EUR, JPY from document context; defaults to INR for Indian payslips

---

## Architecture

```
                          +-------------------+
                          |   Streamlit UI    |
                          |    (app.py)       |
                          +--------+----------+
                                   |
                    +--------------+--------------+
                    |                             |
             Version A                     Version B
          (1 Gemini call)              (2 Gemini calls)
                    |                             |
     +--------------+              +--------------+--------------+
     |                             |                             |
  Combined               Call 1: Extract              Call 2: Prescribe
  Extract +              (gemini_extractor)           (gemini_prescriber)
  Insights                     |                             |
  (gemini_version_a)           |                    +--------+--------+
     |                         |                    | run_hardcoded   |
     |                         |                    | skip_reasons    |
     |                         |                    | gemini_computed |
     +----------+--------------+                    +--------+--------+
                |                                            |
         +------+------+                          +----------+----------+
         |  Normaliser |                          | Python Calculator   |
         | (normaliser)|                          | (12 insight funcs)  |
         +------+------+                          +----------+----------+
                |                                            |
                +--------------------+----------------------+
                                     |
                          +----------+----------+
                          |   4-Tab UI Render   |
                          |  + Report Logger    |
                          +---------------------+
```

---

## Project Structure

```
Payslip_Parser/
+-- app.py                          # Main Streamlit orchestrator
+-- reporter.py                     # Markdown report generator
+-- requirements.txt                # Python dependencies
+-- .env                            # GEMINI_API_KEY (not committed)
+-- .gitignore                      # Excludes .env, data/sessions/, __pycache__/
|
+-- extractor/
|   +-- __init__.py
|   +-- gemini_extractor.py         # Call 1: Extraction via Gemini Vision
|   +-- gemini_version_a.py         # Version A: Combined extraction + insights
|   +-- gemini_prescriber.py        # Call 2: Prescription (Version B only)
|   +-- normaliser.py               # Maps free-form JSON to canonical schema
|
+-- calculator/
|   +-- __init__.py
|   +-- insights.py                 # 12 pure functions + HARDCODED_INSIGHTS map
|
+-- ui/
|   +-- __init__.py
|   +-- components.py               # Streamlit rendering functions
|   +-- charts.py                   # 3 Plotly chart functions
|   +-- styles.css                  # Custom CSS (metric cards, verdict badges, etc.)
|
+-- config/
|   +-- field_schema.json           # Canonical internal schema definition
|
+-- data/
|   +-- sessions/                   # Generated reports (gitignored)
|
+-- test_set/
    +-- ground_truth.json           # Test validation data (placeholder)
```

---

## Setup & Installation

### Prerequisites

- Python 3.11+
- A [Google AI Studio](https://aistudio.google.com/) API key for Gemini

### Steps

```bash
# Clone the repository
git clone <repo-url>
cd Payslip_Parser

# Install dependencies
pip install -r requirements.txt

# Configure API key
echo "GEMINI_API_KEY=your_key_here" > .env

# Run the application
streamlit run app.py
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `streamlit>=1.35.0` | Web UI framework |
| `google-genai>=1.0.0` | Gemini API client (NOT the deprecated `google-generativeai`) |
| `python-dotenv>=1.0.0` | Environment variable loading |
| `plotly>=5.18.0` | Interactive charts |
| `Pillow>=10.0.0` | Image handling |
| `numpy>=1.26.0` | Statistical calculations (consistency CV) |
| `python-dateutil>=2.9.0` | Robust date parsing |
| `pydantic>=2.0.0` | Available for structured validation |

> **Important SDK note:** This project uses `google-genai` (`from google import genai`), not the deprecated `google-generativeai` package. The import patterns and API surface are different.

---

## Usage

1. **Launch** the app with `streamlit run app.py`
2. **Upload** one or more payslips (PDF, JPG, or PNG) via the sidebar file uploader
3. **Select** processing version (A or B) — version locks after first analysis
4. **Click Analyse** — results populate across 4 tabs
5. **Download report** from the sidebar button after analysis completes
6. To compare versions, **Clear** results, switch version, and re-upload

### Sidebar Controls

- **File uploader** — accepts multiple files (up to 3 for batch mode)
- **Version toggle** — Version A (Gemini end-to-end) or Version B (Gemini + Python, recommended)
- **Analyse button** — triggers the processing pipeline
- **Clear button** — resets all results and unlocks version toggle
- **Download Report** — appears after analysis; saves `.md` file

---

## Processing Versions

### Version A — Gemini End-to-End

**1 API call per payslip.** A single combined prompt instructs Gemini to both extract fields and compute insights in one response.

- **Prompt:** `COMBINED_SYSTEM_PROMPT` (extraction Sections 1-4 + insight generation Section 5)
- **Returns:** `{raw_fields: {...}, gemini_insights: {...}}`
- **Post-processing:** Python always computes `monthly_to_annual_conversion` and `take_home_ratio` to ensure these standard metrics are present with correct keys
- **Pros:** Faster (one API call)
- **Cons:** Gemini may use unpredictable key names for insights, compute incorrect values, or skip fields

### Version B — Gemini + Python (Recommended)

**2 API calls per payslip.** Call 1 extracts fields. Call 2 decides which Python insight functions to run.

- **Call 1 (Extraction):** Same `EXTRACTION_SYSTEM_PROMPT` as Version A, file bytes sent directly
- **Normalisation:** Free-form JSON mapped to canonical schema
- **Call 2 (Prescription):** Receives extracted JSON (not the file), returns `{run_hardcoded, skip_reasons, gemini_computed_insights}`
- **Python execution:** Approved functions run with deterministic math
- **Forced insights:** `monthly_to_annual_conversion` and `take_home_ratio` always run regardless of prescription
- **Pros:** Deterministic calculations, explicit skip reasons, structured non-standard component handling
- **Cons:** Slower (two API calls)

### Comparison Summary

| Aspect | Version A | Version B |
|--------|-----------|-----------|
| API calls per file | 1 | 2 |
| Insight computation | Gemini (may be approximate) | Python (exact arithmetic) |
| Non-standard components | Mixed into insights dict | Separated in `gemini_computed` |
| Skip reasons | Not available | Explicitly listed |
| Latency | Lower | Higher |
| Recommended for | Quick exploration | Production / lending decisions |

---

## Data Pipeline

### End-to-End Flow

```
File upload (PDF/JPG/PNG)
    |
    v
[preprocess_files] -- validates MIME type, checks size (<50MB)
    |
    v
[Gemini extraction] -- raw bytes + MIME type sent directly (no conversion)
    |
    v
[_parse_gemini_json] -- handles concatenated JSON objects via deep merge
    |
    v
[normalise_extraction] -- monetary cleanup, date standardisation, frequency detection
    |
    v
[prescribe_insights] -- (Version B only) Gemini decides which Python functions to run
    |
    v
[run_insights] -- Python executes approved calculation functions
    |
    v
[_sort_payslips] -- chronological ordering by pay_period_start
    |
    v
[run_batch_insights] -- consistency analysis if >=2 payslips
    |
    v
[generate_report] -- Markdown report saved to data/sessions/
    |
    v
[Streamlit UI] -- 4-tab interactive display
```

### Concatenated JSON Handling

Gemini occasionally returns two separate JSON objects instead of one (e.g. fields + confidence as separate objects). The parser uses brace-depth tracking to identify boundaries and **deep merges** all objects so that nested dicts like `document_meta` are recursively combined rather than overwritten.

---

## Extraction Prompt Design

The extraction system prompt (`EXTRACTION_SYSTEM_PROMPT` in `extractor/gemini_extractor.py`) has 4 sections:

### Section 1 — Role
Positions Gemini as a financial document extraction specialist for an Indian NBFC, capable of reading diverse payslip formats (corporate, government, small-business, scanned, informal).

### Section 2 — Instructions
- Extract every field, no skipping
- Monetary values as raw numbers only (no symbols, no commas)
- **Currency detection**: auto-detect from document symbols (`$` -> USD, `₹`/Rs -> INR, etc.)
- **Date disambiguation**: "Pay Date" is NOT `pay_period_end` — only populate period end if explicitly stated
- Illegible fields set to null with confidence "low"
- Non-payslip documents return `{"error": "not_a_payslip"}`

### Section 3 — Output Structure
Defines the target JSON schema with categories: `document_meta`, `employer_details`, `employee_details`, `pay_period`, `earnings`, `deductions`, `net_pay`, `other_fields`. Open dicts (`other_earnings`, `other_deductions`) capture non-standard components without data loss.

### Section 4 — Confidence
A `_confidence` key inside the same JSON object with high/medium/low ratings for every extracted field. Must be a single JSON object, not a separate response.

**Key design choice:** No Pydantic `response_json_schema` is used for extraction — free-form JSON ensures non-standard fields (`other_earnings`, `other_deductions`, `raw_extras`) are never rejected by strict validation.

---

## Normalisation

The normaliser (`extractor/normaliser.py`) transforms Gemini's free-form extraction into a canonical internal schema.

### Transformations

| Transform | Input Examples | Output |
|-----------|---------------|--------|
| **Monetary cleanup** | "₹12,500.00", "Rs. 12500", "12,500" | `12500.0` (float) |
| **Date standardisation** | "26/03/2026", "March 2026", "2026-03-26" | `"2026-03-26"` (ISO) or `"2026-03"` |
| **Frequency detection** | "monthly", "weekly", heuristic from days_in_period | `"monthly"` / `"weekly"` / `"biweekly"` / `"daily"` |
| **Section renames** | `employer_details` -> `employer`, `pay_period` -> `attendance` | Canonical keys |

### Canonical Schema

```python
{
    "document_meta": {
        "date_of_issue", "pay_period_label", "pay_period_start",
        "pay_period_end", "salary_frequency", "currency"
    },
    "employer": {"name", "address", "department"},
    "employee": {
        "name", "employee_id", "date_of_birth", "address",
        "job_title", "employment_date", "bank_account"
    },
    "attendance": {"days_worked", "hours_worked", "hourly_rate", "days_in_period"},
    "earnings": {
        "basic_salary", "hra", "lta", "special_allowance", "overtime",
        "bonus", "other_earnings": {}, "gross_salary"
    },
    "deductions": {
        "tds_income_tax", "pf_epf", "professional_tax", "gratuity",
        "esic", "loan_deduction", "other_deductions": {}, "total_deductions"
    },
    "net_pay": {"net_salary", "ctc_mentioned"},
    "raw_extras": {},       # Non-standard fields from other_fields
    "_confidence": {},      # Field-level confidence ratings
    "_source_file": ""      # Original filename
}
```

All non-standard earnings/deductions are preserved in open dicts — no data is discarded.

---

## Insight Calculation Engine

The calculator (`calculator/insights.py`) contains 12 pure functions registered in the `HARDCODED_INSIGHTS` map — the single source of truth for what Python can compute.

### Functions

| # | Key | Function | Required Fields | Output |
|---|-----|----------|-----------------|--------|
| 1 | `monthly_to_annual_conversion` | `compute_annual_figures` | gross_salary, net_salary, salary_frequency | monthly_gross, annual_gross, monthly_net, annual_net, is_estimated, assumption |
| 2 | `take_home_ratio` | `compute_take_home_ratio` | gross_salary, net_salary | take_home_ratio (0-1), take_home_pct |
| 3 | `effective_tds_rate` | `compute_tds_rate` | tds_income_tax, gross_salary | tds_amount, effective_tds_rate, tds_pct |
| 4 | `pf_as_pct_of_basic` | `compute_pf_ratio` | pf_epf, basic_salary | pf_amount, pf_basic_ratio, pf_basic_pct |
| 5 | `deduction_breakdown` | `compute_deduction_breakdown` | gross_salary, all deductions | {deduction: {amount, pct_of_gross}} |
| 6 | `salary_consistency` | `compute_consistency` | List of payslips (batch only) | avg_monthly_net, std_dev, consistency_coefficient, consistency_label |
| 7 | `hourly_normalisation` | `compute_hourly` | hours_worked + hourly_rate, OR net + days_worked | hourly_rate, computed_gross |
| 8 | `overtime_analysis` | `compute_overtime` | overtime, gross_salary | overtime_amount, overtime_pct_of_gross |
| 9 | `hra_as_pct_of_gross` | `compute_hra_ratio` | hra, gross_salary | hra_amount, hra_pct_of_gross |
| 10 | `lta_as_pct_of_gross` | `compute_lta_ratio` | lta, gross_salary | lta_amount, lta_pct_of_gross |
| 11 | `professional_tax_check` | `compute_prof_tax` | professional_tax | professional_tax_monthly, professional_tax_annual |
| 12 | `gratuity_accrual_estimate` | `compute_gratuity` | basic_salary, employment_date (optional) | gratuity_per_year, gratuity_monthly_accrual, tenure_years, disclaimer |

### Annualisation Multipliers (Conservative for Lending)

| Frequency | Annual Multiplier | Reasoning |
|-----------|-------------------|-----------|
| Monthly | x 12 | Standard |
| Weekly | x 45 | 52 weeks minus 7 weeks standard leave |
| Biweekly | x 24 x 0.9 | 24 pay periods, leave-adjusted |
| Daily | x 5 x 45 | 5 days/week x 45 working weeks |

### Consistency Scoring

| Coefficient of Variation | Label | Meaning |
|--------------------------|-------|---------|
| < 5% | `consistent` | Stable salary |
| 5% - 20% | `minor_variation` | Some fluctuation |
| >= 20% | `high_variation` | Significant swings |

### Gratuity Disclaimer

For employees with less than 5 years of tenure, the gratuity insight includes a disclaimer noting that gratuity is payable only after 5 years of continuous service under the Payment of Gratuity Act, 1972. This prevents loan officers from counting theoretical gratuity accrual as a realisable asset.

---

## Prescriber (Version B Call 2)

The prescriber (`extractor/gemini_prescriber.py`) is the decision layer unique to Version B.

### How It Works

1. **Dynamic prompt generation** — iterates `HARDCODED_INSIGHTS.keys()` at runtime to build the prescription prompt. Adding a new insight function automatically includes it.

2. **Explicit field requirements** — each insight is listed with its required fields so Gemini makes informed run/skip decisions:
   ```
   - overtime_analysis: requires earnings.overtime AND earnings.gross_salary
     (does NOT need hours or hourly rate)
   ```

3. **Gemini responds** with:
   ```json
   {
     "run_hardcoded": {"monthly_to_annual_conversion": true, "hra_as_pct_of_gross": false, ...},
     "skip_reasons": {"hra_as_pct_of_gross": "HRA not present in this payslip", ...},
     "gemini_computed_insights": {
       "allowance_pct": {"value": 3.2, "unit": "% of gross", "label": "...", "description": "..."}
     }
   }
   ```

4. **Safety nets** — `salary_consistency` always forced to `false` (batch-only); `monthly_to_annual_conversion` and `take_home_ratio` always force-run in `app.py` regardless of prescription.

---

## UI Tabs

### Tab 1: Insights Report

| Section | Component | Data Source |
|---------|-----------|-------------|
| Employee Header | Name, title, employer, pay period, frequency | Extracted data |
| Salary Summary | 4 metric cards + narrative sentence | `monthly_to_annual_conversion`, `take_home_ratio` |
| Earnings Breakdown | Stacked horizontal bar + table | Extracted earnings |
| Deductions Analysis | Donut chart + table + TDS/PF commentary | Extracted deductions + `effective_tds_rate`, `pf_as_pct_of_basic` |
| Employment Profile | Two-column fact sheet | Extracted + `gratuity_accrual_estimate` |
| Non-Standard Components | Gemini-computed extras (Version B) | `gemini_computed_insights` |
| Data Quality Notice | Missing/low-confidence warnings | `_confidence` (filtered to non-null fields only) |

### Tab 2: Month-on-Month (requires 2+ payslips)

| Section | Component |
|---------|-----------|
| Salary Trend | 3-line chart (Gross dashed, Net solid, Deductions thin) + consistency band |
| Consistency Verdict | Green/amber/red card with CV % |
| Comparison Table | Gross/Net/TDS/PF/Total/Take-home% per month + average row |

### Tab 3: Loan Signals

| Section | Component |
|---------|-----------|
| Signals Table | 9 lending signals (net, gross, CTC, employer, tenure, consistency, frequency, PF, YTD) |
| Loan Parameters | Inputs for amount, tenure, interest rate |
| EMI Calculation | Monthly EMI, total interest, total payable |
| Affordability Check | FOIR assessment (40% threshold: green/amber/red) |
| Eligibility Commentary | AI-generated 3-5 sentence assessment (Gemini, temp=0.3) |

### Tab 4: Raw Data

| Section | Content |
|---------|---------|
| Extracted Fields | Nested dict with confidence badges |
| Calculated Values | All insight function outputs |
| Skipped Insights | Skip reasons from prescription (Version B only) |
| JSON Export | Download button for full data dump |

---

## Charts

Three Plotly chart functions in `ui/charts.py`:

### 1. Earnings Stacked Bar (`earnings_stacked_bar`)
- Horizontal stacked bar showing gross salary composition
- Colour palette: basic (#4e79a7), HRA (#f28e2b), LTA (#e15759), special allowance (#76b7b2), overtime (#59a14f), bonus (#edc948), other (#b07aa1)
- Fallback: if no component breakdown but gross > 0, shows single "Total Gross" bar

### 2. Deductions Donut (`deductions_donut`)
- Pie chart with 55% hole showing deduction proportions
- Centre annotation: total deductions amount
- Each `other_deductions` item gets a unique colour from a 10-colour rotating pool

### 3. Salary Trend Line (`salary_trend_line`)
- Three series: Gross (dashed), Net (solid, prominent), Deductions (thin)
- Consistency band: shaded +-5% around average net
- Reference line: dotted gray at average net

---

## Report Generation

After each analysis run, `reporter.py` generates a Markdown file in `data/sessions/`:

**Filename format:** `report_v{A|B}_{YYYY-MM-DD_HH-MM-SS}.md`

### Report Contents

1. **Session header** — version, timestamp, files processed, processing time
2. **Version note** — explains the computation method used
3. **Per-payslip sections:**
   - Document metadata (pay period, frequency, currency)
   - Employee & employer details
   - Attendance data (if present)
   - Earnings table with % of gross
   - Deductions table with % of gross
   - Net pay
   - Computed insights (annualised figures, ratios, breakdowns)
   - Prescription details (Version B: approved/skipped with reasons)
   - Low-confidence fields (only non-null values)
4. **Batch analysis** (if multiple payslips) — comparison table + consistency verdict
5. **Loan signals** — pre-screening values table

Reports use Indian comma formatting for INR amounts and are designed for side-by-side Version A vs B comparison via file diff.

---

## Indian Number Formatting

For INR (₹) amounts, the app uses the Indian numbering system where digits are grouped as 2-2-3 from the right (after the decimal), not the Western 3-3-3:

| Amount | Western | Indian (this app) |
|--------|---------|-------------------|
| 1116000 | 1,116,000.00 | 11,16,000.00 |
| 667333 | 667,333.00 | 6,67,333.00 |
| 93000 | 93,000.00 | 93,000.00 |

The `_fmt_indian()` function handles this. Non-INR currencies (USD, GBP, EUR) use standard Western formatting.

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Raw bytes to Gemini** (no PDF conversion) | Gemini 2.5 Flash natively supports PDF. Avoids quality loss and complexity. |
| **Free-form JSON on extraction** (no Pydantic) | Open dicts (`other_earnings`, `other_deductions`) would be rejected by strict schema validation. Normaliser handles mapping. |
| **temperature=0.0** on all extraction/prescription calls | Deterministic output for consistent extraction. Only exception: loan commentary (0.3) for natural phrasing. |
| **HARDCODED_INSIGHTS as single source of truth** | Prescriber prompt auto-generated from `.keys()`. Adding a new function = automatic prompt inclusion. |
| **Deep merge for concatenated JSON** | Gemini sometimes returns two objects. Shallow `dict.update()` overwrites nested dicts; deep merge preserves them. |
| **Force fundamental insights** | `monthly_to_annual_conversion` and `take_home_ratio` always run in both versions regardless of prescription. |
| **Confidence filtering** | Low-confidence warnings only shown for fields with non-null values. Null + "low" = confident the field wasn't there, not hard to read. |
| **Gratuity disclaimer** | Gratuity shown as theoretical accrual with explicit note when tenure < 5 years (Payment of Gratuity Act, 1972 requirement). |

---

## Configuration

### Environment Variables (`.env`)

```
GEMINI_API_KEY=your_gemini_api_key_here
```

### Gemini Model

All calls use `gemini-2.5-flash` by default. The model can be changed via the `model` parameter in each extraction/prescription function.

### API Call Temperature

| Call | Temperature | Reason |
|------|-------------|--------|
| Extraction (Call 1) | 0.0 | Deterministic field extraction |
| Prescription (Call 2) | 0.0 | Consistent run/skip decisions |
| Loan commentary | 0.3 | Natural language variation |

---

## Future Enhancements

- [ ] Test set evaluator framework with ground truth comparison
- [ ] Multi-page payslip support (payslips spanning multiple pages)
- [ ] Historical trend storage across sessions
- [ ] PDF report export (in addition to Markdown)
- [ ] Employer database for cross-referencing company details
- [ ] Enhanced batch mode with YTD reconciliation
- [ ] Automated version comparison dashboard
