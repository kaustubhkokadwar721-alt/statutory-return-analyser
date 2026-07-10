"""GSTR-3B PDF parser."""

import os
import re
import contextlib

import pandas as pd
import pdfplumber

from ..utils import calculate_period_year, clean_cell, to_float

TABLE_NAMES = (
    "Table_3_1", "Table_3_1_1", "Table_3_2", "Table_4_ITC",
    "Table_5", "Table_5_1", "Table_6_1", "Table_Breakup",
)


def clean_gstr3b_dataframe(df: pd.DataFrame, text_columns: list) -> pd.DataFrame:
    """Clean PDF artifacts and convert non-text columns to floats."""
    if df is None or df.empty:
        return df

    cleaned_df = df.copy()
    text_set = set(text_columns)
    for col in text_columns:
        if col in cleaned_df.columns:
            cleaned_df[col] = cleaned_df[col].map(clean_cell)

    for col in [col for col in cleaned_df.columns if col not in text_set]:
        cleaned_df[col] = cleaned_df[col].map(to_float)

    return cleaned_df


def _clean_col_header(raw) -> str:
    return clean_cell(raw)


def _dedupe_columns(columns) -> list[str]:
    seen = {}
    result = []
    for col in columns:
        name = _clean_col_header(col) or "Col"
        count = seen.get(name, 0)
        seen[name] = count + 1
        result.append(name if count == 0 else f"{name}_{count + 1}")
    return result


def _table_contains(df: pd.DataFrame, pattern: str) -> bool:
    if df.empty:
        return False
    return df.astype(str).apply(
        lambda col: col.str.contains(pattern, case=False, na=False, regex=True)
    ).any().any()


def _extract_metadata(first_page_text: str) -> dict:
    def find(pattern: str) -> str:
        match = re.search(pattern, first_page_text, re.IGNORECASE)
        return clean_cell(match.group(1)) if match else "Unknown"

    raw_period = find(r"Period\s*([A-Za-z]+)")
    raw_year = find(r"Year\s*([0-9\-]+)")

    return {
        "GSTIN": find(r"GSTIN of the supplier\s*([A-Z0-9]+)"),
        "Period": raw_period,
        "Year": raw_year,
        "Period_Year": calculate_period_year(raw_period, raw_year),
        "Legal_Name": find(r"Legal name of the registered person\s*([^\n]+)"),
        "Trade_Name": find(r"Trade name, if any\s*([^\n]+)"),
        "ARN": find(r"\bARN\b\s*([A-Z0-9]+)"),
        "Date_of_ARN": find(r"Date of ARN\s*([\d/]+)"),
    }


def _table_from_first_header(df: pd.DataFrame, text_columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    result = df.copy()
    result.columns = _dedupe_columns(result.iloc[0])
    return clean_gstr3b_dataframe(
        result.iloc[1:].dropna(how="all").reset_index(drop=True),
        text_columns,
    )


def _parse_payment_table(df: pd.DataFrame) -> pd.DataFrame | None:
    if len(df) < 3:
        return None

    col_header = []
    row1 = df.iloc[1] if len(df) > 1 else [None] * len(df.columns)
    for top, bottom in zip(df.iloc[0], row1):
        top_s = _clean_col_header(top)
        bottom_s = _clean_col_header(bottom)
        combined = f"{top_s} {bottom_s}".strip()
        col_header.append(combined or "Col")

    df_clean = df.iloc[2:].copy().reset_index(drop=True)
    df_clean.columns = _dedupe_columns(col_header)

    rename_map = {}
    for col in df_clean.columns:
        col_lower = str(col).lower()
        if "description" in col_lower or col_lower.startswith("descrip"):
            rename_map[col] = "Description"
        elif "net tax" in col_lower:
            rename_map[col] = "Net_Tax_Payable"
        elif "adjustment" in col_lower or "negative" in col_lower:
            rename_map[col] = "Adjustment"
        elif "payable" in col_lower and "net" not in col_lower:
            rename_map[col] = "Tax_Payable"
        elif "integrated" in col_lower:
            rename_map[col] = "ITC_Integrated"
        elif "central" in col_lower:
            rename_map[col] = "ITC_Central"
        elif "state" in col_lower or "ut" in col_lower:
            rename_map[col] = "ITC_State_UT"
        elif "cess" in col_lower:
            rename_map[col] = "ITC_Cess"
        elif "cash" in col_lower and "interest" not in col_lower and "late" not in col_lower:
            rename_map[col] = "Tax_paid_cash"
        elif "interest" in col_lower:
            rename_map[col] = "Interest_paid_cash"
        elif "late" in col_lower:
            rename_map[col] = "Late_fee_paid_cash"

    df_clean = df_clean.rename(columns=rename_map)
    if "Description" not in df_clean.columns:
        return None

    df_clean["Section"] = df_clean["Description"].map(
        lambda value: value if ("(A)" in str(value) or "(B)" in str(value)) else None
    )
    df_clean["Section"] = df_clean["Section"].ffill()
    df_clean = df_clean[["Section", *[col for col in df_clean.columns if col != "Section"]]]
    df_clean = df_clean[
        ~df_clean["Description"].astype(str).str.contains(r"\([A-B]\)", na=False)
    ]

    text_cols = [col for col in ("Section", "Description") if col in df_clean.columns]
    return clean_gstr3b_dataframe(df_clean.reset_index(drop=True), text_cols)


def _combine_itc_pieces(itc_table_pieces: list[pd.DataFrame]) -> pd.DataFrame | None:
    if not itc_table_pieces:
        return None

    normalised = []
    for piece in itc_table_pieces:
        if piece is None or piece.empty:
            continue
        current = piece.copy()
        while len(current.columns) < 5:
            current[len(current.columns)] = ""
        current = current.iloc[:, :5].copy()
        current.columns = range(5)
        normalised.append(current)

    if not normalised:
        return None

    combined_itc = pd.concat(normalised, ignore_index=True)
    combined_itc.columns = ["Details", "Integrated tax", "Central tax", "State/UT tax", "Cess"]
    combined_itc = combined_itc[
        ~combined_itc["Details"].astype(str).str.contains("Details", case=False, na=False)
    ]

    details = combined_itc["Details"].map(clean_cell)
    combined_itc["Section"] = details.where(details.str.match(r"^[A-D]\.", na=False)).ffill()
    combined_itc = combined_itc[
        ~details.str.match(r"^[ABD]\.", na=False)
    ].reset_index(drop=True)

    return clean_gstr3b_dataframe(combined_itc, ["Details", "Section"])


def parse_complete_gstr3b(pdf_path: str, error_log: list, pdf=None) -> dict | None:
    """Open and parse a GSTR-3B PDF. Append a friendly error row on failure.

    If an already-open pdfplumber ``pdf`` is passed (e.g. from the unified
    pipeline, which opens once for return-type detection), it is reused instead
    of re-opening the file — the caller retains ownership and closes it.
    """
    fname = os.path.basename(pdf_path)
    try:
        parsed = {"Metadata": {}, **{name: None for name in TABLE_NAMES}}
        itc_table_pieces = []

        _own = pdf is None
        with (pdfplumber.open(pdf_path) if _own else contextlib.nullcontext(pdf)) as pdf:
            if not pdf.pages:
                raise ValueError("PDF has no pages.")

            first_page_text = pdf.pages[0].extract_text() or ""
            if "GSTR-3B" not in first_page_text and "GSTR3B" not in first_page_text.upper():
                error_log.append({
                    "File": fname,
                    "Error_Type": "WrongDocumentType",
                    "Message": "GSTR-3B identifier not found on page 1.",
                    "Action": "This file does not appear to be a GSTR-3B. Skipped.",
                })
                return None

            parsed["Metadata"] = _extract_metadata(first_page_text)

            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    df = pd.DataFrame(table)
                    if df.empty:
                        continue

                    if _table_contains(df, r"\(a\)\s*Outward taxable supplies"):
                        parsed["Table_3_1"] = _table_from_first_header(
                            df, ["Nature of Supplies"]
                        )

                    elif _table_contains(df, r"electronic commerce operator pays tax"):
                        parsed["Table_3_1_1"] = _table_from_first_header(
                            df, ["Nature of Supplies"]
                        )

                    elif _table_contains(df, r"Supplies made to Unregistered Persons"):
                        parsed["Table_3_2"] = _table_from_first_header(
                            df, ["Nature of Supplies"]
                        )

                    elif _table_contains(df, r"A\.\s*ITC Available"):
                        current = df.copy()
                        current.columns = _dedupe_columns(current.iloc[0])
                        itc_table_pieces.append(current.iloc[1:].dropna(how="all"))

                    elif _table_contains(df, r"\(4\)\s*Inward supplies from ISD|B\.\s*ITC Reversed"):
                        df_clean = df.dropna(how="all")
                        if not df_clean.empty and "Details" in str(df_clean.iloc[0].values):
                            df_clean = df_clean.iloc[1:]
                        itc_table_pieces.append(df_clean)

                    elif _table_contains(df, r"From a supplier under composition scheme"):
                        parsed["Table_5"] = _table_from_first_header(
                            df, ["Nature of Supplies"]
                        )

                    elif _table_contains(df, r"System computed Interest|Interest Paid"):
                        parsed["Table_5_1"] = _table_from_first_header(df, ["Details"])

                    elif _table_contains(df, r"\(A\)\s*Other than reverse charge"):
                        payment_table = _parse_payment_table(df)
                        if payment_table is not None:
                            parsed["Table_6_1"] = payment_table

                    elif (
                        _table_contains(df, r"Breakup of tax liability")
                        or ("Period" in df.astype(str).values and "Integrated tax" in df.astype(str).values)
                    ):
                        header_idx = df.index[df.apply(
                            lambda row: row.astype(str).str.contains(
                                r"Period", case=False, na=False
                            ).any(),
                            axis=1,
                        )].tolist()
                        if header_idx:
                            idx = header_idx[0]
                            df_breakup = df.copy()
                            df_breakup.columns = _dedupe_columns(df_breakup.iloc[idx])
                            parsed["Table_Breakup"] = clean_gstr3b_dataframe(
                                df_breakup.iloc[idx + 1:].dropna(how="all").reset_index(drop=True),
                                ["Period"],
                            )

        parsed["Table_4_ITC"] = _combine_itc_pieces(itc_table_pieces)
        return parsed

    except Exception as exc:
        error_log.append({
            "File": fname,
            "Error_Type": type(exc).__name__,
            "Message": str(exc),
            "Action": "Could not read this file. It may be damaged or password-protected.",
        })
        return None
