# Payslip Parser & Document Analyser Agent

An AI-powered payslip analysis tool built for **InCred Finance** that extracts salary data from payslip documents using Google Gemini Vision, computes financial insights through a Python calculation engine, and presents results in an interactive Streamlit dashboard with fraud detection, tax compliance verification, employer compliance profiling, and loan pre-screening capabilities.

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
- [Enhancements](#enhancements)
- [Design Decisions](#design-decisions)
- [Configuration](#configuration)
- [Future Enhancements](#future-enhancements)

---

## Features

- **Multi-format extraction** — PDF, JPG, PNG payslips sent as raw bytes to Gemini Vision (no OCR or PDF conversion)
- **Two processing versions** — Version A (single Gemini call) vs Version B (two calls + Python calculation) with side-by-side comparison
- **13 insight functions** — Pure Python calculations covering annualisation, take-home ratio, TDS rate, PF ratio, deduction breakdown, salary consistency, hourly normalisation, overtime, HRA/LTA ratios, professional tax, gratuity accrual, and income projection
- **Payslip authenticity scoring** — 7 automated checks (arithmetic consistency, PF compliance, TDS verification, round number detection, professional tax) producing a 0-100 fraud risk score
- **Tax compliance verification** — Indian FY 2025-26 new regime slab computation with section 87A rebate, expected vs actual TDS comparison as a range
- **Employer compliance signals** — 7 signals derived from payslip data (EPFO registration, state tax compliance, PF computation accuracy, employment tenure, payroll consistency)
- **Batch mode** — Upload 2-3 payslips for trend analysis, consistency scoring, and income projection with trajectory classification
- **Loan pre-screening** — Loan type selector (Personal 14% / Education 11%), EMI calculation, 4-tier FOIR assessment, AI-generated eligibility commentary
- **Professional PDF export** — One-page credit document for loan files generated via ReportLab
- **Session reports** — Auto-generated Markdown reports with full extraction, insights, verification results, and batch analysis
- **Indian number formatting** — Correct lakh/crore comma placement (11,16,000 not 1,116,000)
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
         | (normaliser)|                          | (13 insight funcs)  |
         +------+------+                          +----------+----------+
                |                                            |
                +--------------------+----------------------+
                                     |
                          +----------+----------+
                          | Verification Engine |
                          | (authenticity, tax, |
                          |  employer signals)  |
                          +----------+----------+
                                     |
                          +----------+----------+
                          |   4-Tab UI Render   |
                          |  + Report + PDF     |
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
|   +-- insights.py                 # 13 pure functions + HARDCODED_INSIGHTS map
|   +-- verification.py             # Authenticity scoring, tax compliance, employer signals
|
+-- ui/
|   +-- __init__.py
|   +-- components.py               # Streamlit rendering functions (15+ components)
|   +-- charts.py                   # 3 Plotly charts (stacked bar, donut, trend+projection)
|   +-- pdf_export.py               # ReportLab PDF generation for loan files
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
| `numpy>=1.26.0` | Statistical calculations (consistency CV, income projection regression) |
| `python-dateutil>=2.9.0` | Robust date parsing |
| `pydantic>=2.0.0` | Available for structured validation |
| `reportlab>=4.0.0` | PDF loan file generation |

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

The calculator (`calculator/insights.py`) contains 13 pure functions — 12 registered in the `HARDCODED_INSIGHTS` map (the single source of truth for what Python can compute) plus `compute_income_projection` for batch analysis.

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
| 13 | *(batch)* | `compute_income_projection` | 3+ payslips | trajectory, monthly_growth_rate, projected_net_12m, projected_values, r_squared |

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
| **Authenticity Score** | Expandable 0-100 score card with 7-check breakdown | `calculator/verification.py` |
| Earnings Breakdown | Stacked horizontal bar + table | Extracted earnings |
| Deductions Analysis | Donut chart + table + TDS/PF commentary | Extracted deductions + `effective_tds_rate`, `pf_as_pct_of_basic` |
| **Tax Compliance** | Expected TDS range vs actual, slab breakdown, verdict | `calculator/verification.py` (FY 2025-26 slabs) |
| Employment Profile | Two-column fact sheet | Extracted + `gratuity_accrual_estimate` |
| **Employer Signals** | 7-signal compliance checklist with positive/missing/neutral indicators | `calculator/verification.py` |
| Non-Standard Components | Gemini-computed extras (Version B) | `gemini_computed_insights` |
| Data Quality Notice | Missing/low-confidence warnings | `_confidence` (filtered to non-null fields only) |

### Tab 2: Month-on-Month (requires 2+ payslips)

| Section | Component |
|---------|-----------|
| Salary Trend | 3-line chart (Gross dashed, Net solid, Deductions thin) + consistency band + **dotted projection line** (3+ payslips) |
| Consistency Verdict | Green/amber/red card with CV % |
| **Income Projection** | Trajectory (Positive/Flat/Declining), growth rate, projected net at 12 months (3+ payslips only) |
| Comparison Table | Gross/Net/TDS/PF/Total/Take-home% per month + average row |

### Tab 3: Loan Signals

| Section | Component |
|---------|-----------|
| Signals Table | 9 lending signals (**batch average** for net/gross when multiple payslips uploaded) |
| **Loan Type Selector** | Personal Loan (14% default) / Education Loan (11%) / Custom |
| Loan Parameters | Inputs for amount, tenure (max 60 PL / 84 EL), interest rate |
| EMI Calculation | Monthly EMI, total interest, total payable, loan-to-salary ratio |
| **4-Tier Affordability** | Comfortable (<30%), Manageable (30-45%), Stretched (45-55%), Exceeds Limit (>55%) |
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
- **Income projection**: When 3+ payslips are provided, a dotted green extension line shows the projected net salary for 12 months forward based on linear regression

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
   - **Authenticity score** with 7-check breakdown
   - **Tax compliance verification** with slab details and expected TDS range
   - **Employer compliance signals** (7 signals)
   - Prescription details (Version B: approved/skipped with reasons)
   - Low-confidence fields (only non-null values)
4. **Batch analysis** (if multiple payslips) — comparison table + consistency verdict + **income projection**
5. **Loan signals** — pre-screening values table (uses **batch averages** when multiple payslips uploaded)

### PDF Loan File (on-demand)

A professional one-page credit document generated via ReportLab, downloadable from the sidebar. Contains employee snapshot, key metrics, earnings/deductions tables, authenticity score, tax compliance verdict, employer signals, affordability summary (if loan params set), and a disclaimer footer. Includes the processing version label.

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

## Enhancements

Six production-grade enhancements built on top of the core extraction and calculation architecture:

### Enhancement 1 — Payslip Authenticity Signals

Checks internal mathematical and compliance consistency. Produces a 0-100 score.

| Check | What it verifies | Penalty |
|-------|-----------------|---------|
| Net arithmetic | `net = gross - deductions` (+-5 tolerance) | -40 (category) |
| Deductions sum | `total_deductions = sum of components` (+-5) | -40 (category) |
| Earnings sum | `gross = sum of components` (+-5) | -40 (category) |
| PF compliance | 3-tier: standard (12%), non-standard (wage ceiling ₹1,800), anomalous | 0 / 0 / -20 |
| TDS consistency | Actual TDS within 60-200% of expected (FY 2025-26 slabs) | -15 |
| Round numbers | Round totals with non-round components | -10 |
| Professional tax | PT <= ₹300/month | -15 |

Arithmetic checks are a **category** — deduct -40 once if any of the 3 fail, not -40 per check. Labels: Strong (>=80), Moderate (50-79), Weak (25-49), Suspicious (<25).

The PF check uses three-tier logic to avoid false positives: ₹500-₹1,800 on basic > ₹15,000 is classified as "non-standard" (legitimate wage ceiling) with 0 penalty.

### Enhancement 2 — Salary-to-Loan Contextualisation

Extends the existing Tab 3 with:
- **Loan type selector**: Personal Loan (14% default rate), Education Loan (11%), or Custom
- **4-tier FOIR**: Comfortable (<30%), Manageable (30-45%), Stretched (45-55%), Exceeds Limit (>55%)
- **Loan-to-salary ratio**: Shows how many times annual salary the loan represents
- **Batch averaging**: When multiple payslips are uploaded, signals use average monthly net/gross

### Enhancement 3 — Income Trend Projection

When 3+ payslips are uploaded:
- Linear regression (`numpy.polyfit`) on monthly net salaries
- Classifies trajectory: **Positive** (>1%/month), **Flat** (+-1%), **Declining** (<-1%)
- Projects net salary 12 months forward
- Dotted projection line added to the salary trend chart
- R-squared value indicates fit confidence

### Enhancement 4 — Tax Compliance Verification

Verifies TDS against Indian FY 2025-26 new regime slabs (Union Budget 2025):

| Taxable Income | Rate |
|---------------|------|
| Up to ₹4L | 0% |
| ₹4L - ₹8L | 5% |
| ₹8L - ₹12L | 10% |
| ₹12L - ₹16L | 15% |
| ₹16L - ₹20L | 20% |
| ₹20L - ₹24L | 25% |
| Above ₹24L | 30% |

- Standard deduction: ₹75,000
- Section 87A rebate: No tax if taxable income <= ₹12,00,000 (applied to low end of range only)
- HRA exemption estimated conservatively: `min(actual HRA, 40% of basic)`
- Expected TDS always shown as a **range** (with/without HRA, with/without rebate)
- 4% Health & Education Cess applied

### Enhancement 5 — Employer Compliance Signals

7 signals derived entirely from payslip data (no external API calls):

| Signal | Derived From | Notes |
|--------|-------------|-------|
| EPFO Registered | PF deduction present | Confirms formal registration |
| State Tax Compliant | Professional tax present | Employer files state returns |
| Small-Medium Employer | ESIC present | <500 employees (ESIC threshold) |
| Established Employer | Employee tenure >= 5 years | Inferred from employment date, not gratuity deduction |
| Correct PF Computation | PF = 12% of basic +-5% | Compliant payroll |
| Payroll Software Used | Consistent formatting (batch) | Requires 2+ payslips |
| Salary Paid On Time | Consistent issue dates (batch) | Requires 2+ payslips |

### Enhancement 6 — Loan File PDF Export

One-page professional credit document via ReportLab, downloadable from the sidebar:
- Header with InCred Finance branding, date, and processing version
- Employee snapshot and key metrics
- Earnings and deductions summary table
- Authenticity score with flag breakdown
- Tax compliance verdict
- Employer compliance signals
- Loan affordability summary (if parameters set)
- Disclaimer footer

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
| **Single verification module** | `calculator/verification.py` serves authenticity (E1), tax compliance (E4), and employer signals (E5) with a shared tax slab engine. TDS computation is never duplicated. |
| **Tax range, never a point estimate** | Expected TDS always computed as a range (with/without HRA, with/without 87A rebate) because individual tax situations vary. |
| **PF 3-tier logic** | Standard (12%), non-standard (wage ceiling), anomalous. Prevents false positives on legitimate payslips where PF is capped at ₹1,800. |
| **Established employer via tenure** | Uses employment date (>= 5 years) instead of checking for gratuity deduction, which rarely appears as a line item on payslips. |
| **Batch averaging for loan signals** | Multiple payslips → average monthly net/gross used for lending signals. More reliable than any single month. |
| **Chronological sorting** | Payslips sorted by `pay_period_start`, with fallback to parsed `pay_period_label` ("February 2026" → "2026-02"), then `date_of_issue`. |

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

- [ ] Test set evaluator framework with ground truth comparison and 95% accuracy target
- [ ] Multi-page payslip support (payslips spanning multiple pages)
- [ ] Historical trend storage across sessions (persistent database)
- [ ] Employer database for cross-referencing company details
- [ ] Enhanced batch mode with YTD reconciliation
- [ ] Old vs new tax regime comparison in tax compliance section
- [ ] Multi-language payslip support (Hindi, regional languages)
