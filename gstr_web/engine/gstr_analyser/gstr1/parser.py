"""GSTR-1 PDF parser."""

import os
import re
import contextlib

import pandas as pd
import pdfplumber

from ..constants import (
    CANONICAL_PATTERNS,
    COL_NAMES,
    HSN_SUBSECTIONS,
    SECTION_DEFS,
    SECTION_LABELS,
)
from ..utils import clean_cell, make_period_year, to_float


def extract_metadata_gstr1(pdf) -> dict:
    """Extract taxpayer and period metadata from page 1."""
    page1_text = pdf.pages[0].extract_text() or ""

    def find(pattern: str) -> str:
        match = re.search(pattern, page1_text, re.IGNORECASE)
        return clean_cell(match.group(1)) if match else "Unknown"

    fy = find(r"Financial year\s+([\d\-]+)")
    period = find(r"Tax period\s+([A-Za-z]+)")

    return {
        "GSTIN": find(r"GSTIN\s+([A-Z0-9]{15})"),
        "Legal_Name": find(r"Legal name of the registered person\s+(.+)"),
        "Trade_Name": find(r"Trade name[,\s]+if any\s+(.+)"),
        "ARN": find(r"\bARN\b\s+([A-Z0-9]+)"),
        "ARN_Date": find(r"(?:ARN date|Date of ARN)\s+([\d/]+)"),
        "FY": fy,
        "Period": period,
        "Period_Year": make_period_year(period, fy),
    }


def _normalise_summary_row(row) -> list:
    values = list(row or [])
    values.extend([None] * max(0, len(COL_NAMES) - len(values)))
    return values[:len(COL_NAMES)]


def extract_summary_table(pdf) -> pd.DataFrame:
    """Concatenate the summary table that spans all pages."""
    all_rows = []
    for page_num, page in enumerate(pdf.pages):
        tables = page.extract_tables() or []
        if not tables:
            continue

        table = tables[2] if page_num == 0 and len(tables) >= 3 else tables[-1 if page_num == 0 else 0]
        for row in table[1:]:
            normalised = _normalise_summary_row(row)
            desc = clean_cell(normalised[0])
            if not desc or desc.lower() == "description":
                continue
            normalised[0] = desc
            all_rows.append(normalised)

    df = pd.DataFrame(all_rows, columns=COL_NAMES)
    if not df.empty:
        df["Description"] = df["Description"].apply(clean_cell)
    return df


def label_sections(df: pd.DataFrame) -> pd.DataFrame:
    """Assign Section_Code to each summary row using SECTION_DEFS in order."""
    result = df.copy()
    if result.empty:
        result["Section_Code"] = pd.Series(dtype="object")
        return result

    result["Section_Code"] = ""
    current = ""
    for idx, row in result.iterrows():
        desc = clean_cell(row.get("Description", ""))
        if desc:
            for code, pattern in SECTION_DEFS:
                if re.search(pattern, desc, re.IGNORECASE):
                    current = code
                    break
        result.at[idx, "Section_Code"] = current
    return result


def _empty_record(code: str) -> dict:
    return {
        "Section_Code": code,
        "Section_Label": SECTION_LABELS.get(code, code),
        "Found": False,
        "Num_Records": 0,
        "Doc_Type": "",
        "Value": 0.0,
        "IGST": 0.0,
        "CGST": 0.0,
        "SGST": 0.0,
        "Cess": 0.0,
    }


def extract_section_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Extract one canonical total row per section code."""
    if df.empty or "Section_Code" not in df.columns:
        return pd.DataFrame([_empty_record(code) for code in CANONICAL_PATTERNS])

    records = []
    for section_code, canonical_pattern in CANONICAL_PATTERNS.items():
        parent = HSN_SUBSECTIONS.get(section_code, section_code)
        section_rows = df[df["Section_Code"] == parent].copy()
        if section_rows.empty:
            records.append(_empty_record(section_code))
            continue

        descriptions = section_rows["Description"].fillna("").astype(str)
        canonical = section_rows[descriptions.str.contains(
            canonical_pattern,
            case=False,
            na=False,
            regex=True,
        )]
        if canonical.empty:
            records.append(_empty_record(section_code))
            continue

        row = canonical.iloc[0]
        records.append({
            "Section_Code": section_code,
            "Section_Label": SECTION_LABELS.get(section_code, section_code),
            "Found": True,
            "Num_Records": int(to_float(row.get("Num_Records"))),
            "Doc_Type": clean_cell(row.get("Doc_Type")),
            "Value": to_float(row.get("Value")),
            "IGST": to_float(row.get("IGST")),
            "CGST": to_float(row.get("CGST")),
            "SGST": to_float(row.get("SGST")),
            "Cess": to_float(row.get("Cess")),
        })
    return pd.DataFrame(records)


def build_table_coverage(section_totals: pd.DataFrame) -> pd.DataFrame:
    """Flag which sections have data for the Table_Coverage audit sheet."""
    cov = section_totals.copy()
    required_cols = [
        "Section_Code", "Section_Label", "Found", "Num_Records",
        "Value", "IGST", "CGST", "SGST", "Cess",
    ]
    for col in required_cols:
        if col not in cov.columns:
            if col == "Found":
                cov[col] = False
            elif col in ("Section_Code", "Section_Label"):
                cov[col] = ""
            else:
                cov[col] = 0.0
    numeric_cols = ["Value", "IGST", "CGST", "SGST", "Cess"]
    cov["Has_Data"] = cov[numeric_cols].ne(0).any(axis=1).map({True: "Yes", False: "No"})
    return cov[[
        "Section_Code", "Section_Label", "Has_Data", "Found",
        "Num_Records", "Value", "IGST", "CGST", "SGST", "Cess",
    ]]


def parse_gstr1(pdf_path: str, error_log: list, pdf=None) -> dict | None:
    """Open and parse a GSTR-1 PDF. Append a friendly error row on failure.

    Reuses an already-open pdfplumber ``pdf`` when the unified pipeline passes
    one (opened once for detection); the caller keeps ownership.
    """
    fname = os.path.basename(pdf_path)
    try:
        _own = pdf is None
        with (pdfplumber.open(pdf_path) if _own else contextlib.nullcontext(pdf)) as pdf:
            if not pdf.pages:
                raise ValueError("PDF has no pages.")

            first_text = pdf.pages[0].extract_text() or ""
            if "GSTR-1" not in first_text and "GSTR1" not in first_text.upper():
                error_log.append({
                    "File": fname,
                    "Error_Type": "WrongDocumentType",
                    "Message": "GSTR-1 identifier not found on page 1.",
                    "Action": "This file does not appear to be a GSTR-1. Skipped.",
                })
                return None

            meta = extract_metadata_gstr1(pdf)
            raw_df = extract_summary_table(pdf)
            labeled_df = label_sections(raw_df)
            section_tots = extract_section_totals(labeled_df)
            coverage = build_table_coverage(section_tots)

        return {
            "Metadata": meta,
            "Raw_Rows": labeled_df,
            "Section_Totals": section_tots,
            "Table_Coverage": coverage,
        }

    except Exception as exc:
        error_log.append({
            "File": fname,
            "Error_Type": type(exc).__name__,
            "Message": str(exc),
            "Action": "Could not read this file. It may be damaged or password-protected.",
        })
        return None
