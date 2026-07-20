# GSTR Return Analyser (Legacy Desktop Source)

This desktop package is retained for historical reference only. The maintained
product and sole parser engine are under `web_app/engine/`, where all future
changes must be made for the browser-only, local-processing application.

Batch-process GSTR-1 and GSTR-3B PDFs downloaded from the GST portal into
audit-ready Excel workbooks with sanity checks, reconciliation tables, and
an analytics star schema.

---

## Quick Start

```
# 1. Install dependencies (one time)
pip install -r requirements.txt

# 2. Run
python main.py
```

Select **[1]** for GSTR-1 or **[2]** for GSTR-3B, pick the folder containing
your PDFs, and the tool writes two Excel files inside a
`GSTR1_Verified_Reports/` (or `GSTR3B_Verified_Reports/`) sub-folder.

---

## Output Files

### GSTR-1

| Workbook | Sheets |
|----------|--------|
| `GSTR1_Auditor_Master.xlsx` | ERRORS_LOG, Metadata_Master, EXCEPTIONS_LOG, Table_Coverage, Liability_Recon, Raw_Summary_Table, Section_Totals |
| `GSTR1_Analytics_Master.xlsx` | Executive_Summary, Dim_Taxpayer_Calendar, Fact_Liability |

### GSTR-3B

| Workbook | Sheets |
|----------|--------|
| `GSTR3B_Auditor_Master.xlsx` | ERRORS_LOG, Metadata_Master, EXCEPTIONS_LOG, Checksum_Status, T_3_1 … T_Breakup |
| `GSTR3B_Analytics_Master.xlsx` | Executive_Summary, Dim_Taxpayer_Calendar, Fact_Tax_Payments, Fact_Outward_Liability, Fact_Eligible_ITC |

---

## Sanity Checks

### GSTR-1 (6 checks)

| # | Check | Threshold | Status |
|---|-------|-----------|--------|
| 1 | Computed total liability == reported footer (per tax head) | ₹1 tolerance | FAIL |
| 2 | HSN Grand Total vs sum of supply tables | >10% deviation | WARN |
| 3 | Num_Records > 0 iff Value != 0 (major sections) | mismatch | WARN |
| 4 | B2CL average invoice > ₹2.5L | at or below threshold | FAIL |
| 5 | B2CL / Export / SEZ must carry IGST only (no CGST/SGST) | any CGST/SGST > 0 | FAIL |
| 6 | Net CDNR/CDNUR value should be ≤ 0 | positive net | WARN |

### GSTR-3B (3 checks)

| # | Check | Threshold | Status |
|---|-------|-----------|--------|
| 1 | Table 6.1: Net_Tax_Payable == ITC + Cash paid | ₹1 tolerance | FAIL |
| 2 | Table 4: ITC A − B == Net C (per tax head) | ₹1 tolerance | FAIL |
| 3 | RCM cross-check: Table 3.1(d) vs Table 4 row(3) | >10% gap | WARN |

---

## Package Structure

```
gstr_analyser_src/
├── main.py                        # Entry point (UTF-8 fix + calls cli.main)
├── requirements.txt
├── README.md
└── gstr_analyser/
    ├── __init__.py                # Exposes VERSION, APP_NAME
    ├── constants.py               # All lookup tables, regex patterns, section lists
    ├── utils.py                   # clean_cell, to_float, make_period_year, check_file_locks
    ├── cache.py                   # Pickle-based parse cache (_cache_key, _load_cache, …)
    ├── ui.py                      # PipelineUI (Rich) + Excel helpers (write_sheet, …)
    ├── cli.py                     # Menu, folder picker, dependency_check, main()
    ├── gstr1/
    │   ├── __init__.py
    │   ├── parser.py              # extract_metadata_gstr1, extract_summary_table, …
    │   ├── checks.py              # run_sanity_checks_gstr1 (6 checks)
    │   ├── analytics.py           # build_liability_recon, create_fact_table_gstr1, …
    │   └── pipeline.py            # run_pipeline_gstr1 → (auditor_path, analytics_path)
    └── gstr3b/
        ├── __init__.py
        ├── parser.py              # clean_gstr3b_dataframe, parse_complete_gstr3b
        ├── checks.py              # run_sanity_checks_gstr3b (3 checks)
        ├── analytics.py           # create_analytics_schema_gstr3b, build_executive_summary_gstr3b
        └── pipeline.py            # run_pipeline_gstr3b → (auditor_path, analytics_path)
```

---

## Performance

- **Parallel parsing** — up to 4 PDFs parsed simultaneously via `ThreadPoolExecutor`.
- **Parse cache** — results stored in `.parse_cache.pkl` inside the output folder.
  Re-running on the same PDFs skips parsing entirely (~7× faster warm run).
  Cache is keyed by filename + file size + modification timestamp.
  Delete `.parse_cache.pkl` to force a full re-parse.

---

## Requirements

- Python 3.10+ (uses `X | Y` union type hints)
- Windows / macOS / Linux
- tkinter (standard library on full Python installs) — optional; falls back to console prompt

---

## Potential Improvements

The following enhancements are scoped but not yet implemented:

| Area | Idea |
|------|------|
| **Accuracy** | Regex pattern library versioned separately — allow overrides via `patterns.json` |
| **Accuracy** | Confidence score per extraction (number of fallback vs canonical matches) |
| **Output** | Pivot table / chart sheets in Analytics workbook (xlsxwriter supports charts) |
| **Output** | GSTR-2B vs GSTR-3B ITC reconciliation (requires GSTR-2B parser) |
| **Output** | Month-over-month trend sheet per GSTIN |
| **Robustness** | Async PDF I/O with `asyncio` + `aiofiles` for very large batches (50+ files) |
| **Robustness** | Retry logic for pdfplumber timeouts on large PDFs |
| **CLI** | `--headless` flag for CI/server use (skip menu, accept folder paths as args) |
| **CLI** | Progress bar with ETA (Rich `Progress` widget) instead of plain step counter |
| **Packaging** | `pyproject.toml` + `pip install -e .` for proper editable installs |
| **Testing** | `pytest` suite with synthetic PDF fixtures for each parser function |
| **Testing** | Golden-file regression tests: parse a known PDF, assert DataFrame shape + key values |
