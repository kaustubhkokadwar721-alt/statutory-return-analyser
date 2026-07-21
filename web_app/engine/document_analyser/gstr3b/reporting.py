"""Map parsed GSTR-3B tables to one analysis-ready row per return."""

import re

import pandas as pd


ANALYSIS_COLUMNS = (
    "Year", "Return Period", "Month", "GSTIN", "Company Name", "Trade Name",
    "ARN", "Date of filing",
    "Outward taxable supplies (other than zero rated, nil rated and exempted)",
    "Outward taxable supplies (zero rated)",
    "Other outward supplies (nil rated, exempted)",
    "Output IGST", "Output CGST", "Output SGST",
    "RCM Taxable Value", "RCM IGST Payable", "RCM CGST Payable", "RCM SGST Payable",
    "Total Input IGST", "Total Input CGST", "Total Input SGST",
    "Ineligible IGST", "Ineligible CGST", "Ineligible SGST",
    "Net Input IGST", "Net Input CGST", "Net Input SGST",
    "IGST to IGST", "IGST to CGST", "IGST to SGST",
    "CGST to IGST", "CGST to CGST", "SGST to IGST", "SGST to SGST",
    "IGST Payable", "CGST Payable", "SGST Payable",
    "Interest paid", "Late Fees paid",
    "Status", "Validation Findings", "Missing Fields", "Source File",
)

def _normalise(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def _column(df: pd.DataFrame | None, *terms: str) -> str | None:
    if not isinstance(df, pd.DataFrame):
        return None
    wanted = tuple(_normalise(term) for term in terms)
    for col in df.columns:
        name = _normalise(col)
        if all(term in name for term in wanted):
            return col
    return None


def _numeric_sum(series: pd.Series) -> float:
    return round(float(pd.to_numeric(series, errors="coerce").fillna(0.0).sum()), 2)


def _matching_value(
    df: pd.DataFrame | None,
    label_col: str | None,
    pattern: str,
    value_col: str | None,
) -> float | None:
    if not isinstance(df, pd.DataFrame) or df.empty or not label_col or not value_col:
        return None
    rows = df[df[label_col].astype(str).str.contains(pattern, case=False, na=False, regex=True)]
    return None if rows.empty else _numeric_sum(rows[value_col])


def _required_rows_sum(
    df: pd.DataFrame | None,
    label_col: str | None,
    patterns: tuple[str, ...],
    value_col: str | None,
) -> float | None:
    values = [_matching_value(df, label_col, pattern, value_col) for pattern in patterns]
    return None if any(value is None for value in values) else round(sum(values), 2)


def _section_sum(
    df: pd.DataFrame | None,
    section_prefix: str,
    value_col: str | None,
) -> float | None:
    if not isinstance(df, pd.DataFrame) or df.empty or "Section" not in df.columns or not value_col:
        return None
    rows = df[df["Section"].astype(str).str.startswith(section_prefix, na=False)]
    return None if rows.empty else _numeric_sum(rows[value_col])


def _payment_value(
    df: pd.DataFrame | None,
    section_marker: str,
    tax_name: str,
    value_col: str,
) -> float | None:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    if not {"Section", "Description", value_col}.issubset(df.columns):
        return None
    section = df["Section"].astype(str).str.contains(
        re.escape(section_marker), case=False, na=False, regex=True
    )
    description = df["Description"].map(_normalise)
    rows = df[section & description.str.contains(_normalise(tax_name), regex=False)]
    return None if rows.empty else _numeric_sum(rows[value_col])


def _sum_known(values: list[float | None]) -> float | None:
    return None if any(value is None for value in values) else round(sum(values), 2)


def _balance(*values: float | None) -> float | None:
    if any(value is None for value in values):
        return None
    return round(values[0] + values[1] - sum(values[2:]), 2)


def _iso_period(period: str) -> str | None:
    for fmt in ("%b-%y", "%b %Y"):
        try:
            return pd.to_datetime(period, format=fmt).strftime("%Y-%m")
        except (TypeError, ValueError):
            continue
    return None


def _iso_date(value: str) -> str | None:
    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def build_analysis_row(parsed: dict, source_file: str) -> tuple[dict, list[str]]:
    """Return the wide analysis row and fields whose source could not be found."""
    meta = parsed.get("Metadata", {})
    t31 = parsed.get("Table_3_1")
    t4 = parsed.get("Table_4_ITC")
    t61 = parsed.get("Table_6_1")

    nature_col = _column(t31, "nature")
    taxable_col = _column(t31, "taxable", "value")
    t31_tax_cols = {
        "IGST": _column(t31, "integrated"),
        "CGST": _column(t31, "central"),
        "SGST": _column(t31, "state", "tax"),
    }
    itc_cols = {
        "IGST": _column(t4, "integrated"),
        "CGST": _column(t4, "central"),
        "SGST": _column(t4, "state", "tax"),
    }

    row_patterns = {
        "a": r"\(\s*a\s*\).*other than zero rated",
        "b": r"\(\s*b\s*\).*zero rated",
        "c": r"\(\s*c\s*\).*other outward supplies",
        "d": r"\(\s*d\s*\).*reverse charge",
    }
    outward_patterns = (row_patterns["a"], row_patterns["b"], row_patterns["c"])

    values = {
        "Outward taxable supplies (other than zero rated, nil rated and exempted)":
            _matching_value(t31, nature_col, row_patterns["a"], taxable_col),
        "Outward taxable supplies (zero rated)":
            _matching_value(t31, nature_col, row_patterns["b"], taxable_col),
        "Other outward supplies (nil rated, exempted)":
            _matching_value(t31, nature_col, row_patterns["c"], taxable_col),
        "RCM Taxable Value": _matching_value(t31, nature_col, row_patterns["d"], taxable_col),
    }
    for tax_name in ("IGST", "CGST", "SGST"):
        values[f"Output {tax_name}"] = _required_rows_sum(
            t31, nature_col, outward_patterns, t31_tax_cols[tax_name]
        )
        values[f"RCM {tax_name} Payable"] = _matching_value(
            t31, nature_col, row_patterns["d"], t31_tax_cols[tax_name]
        )
        total_input = _section_sum(t4, "A.", itc_cols[tax_name])
        ineligible = _section_sum(t4, "B.", itc_cols[tax_name])
        values[f"Total Input {tax_name}"] = total_input
        values[f"Ineligible {tax_name}"] = ineligible
        values[f"Net Input {tax_name}"] = (
            None if total_input is None or ineligible is None
            else round(total_input - ineligible, 2)
        )

    utilisation = {
        "IGST to IGST": _payment_value(t61, "(A)", "Integrated tax", "ITC_Integrated"),
        "IGST to CGST": _payment_value(t61, "(A)", "Central tax", "ITC_Integrated"),
        "IGST to SGST": _payment_value(t61, "(A)", "State/UT tax", "ITC_Integrated"),
        "CGST to IGST": _payment_value(t61, "(A)", "Integrated tax", "ITC_Central"),
        "CGST to CGST": _payment_value(t61, "(A)", "Central tax", "ITC_Central"),
        "SGST to IGST": _payment_value(t61, "(A)", "Integrated tax", "ITC_State_UT"),
        "SGST to SGST": _payment_value(t61, "(A)", "State/UT tax", "ITC_State_UT"),
    }
    values.update(utilisation)
    values["IGST Payable"] = _balance(
        values["Output IGST"], values["RCM IGST Payable"],
        utilisation["IGST to IGST"], utilisation["CGST to IGST"], utilisation["SGST to IGST"],
    )
    values["CGST Payable"] = _balance(
        values["Output CGST"], values["RCM CGST Payable"],
        utilisation["IGST to CGST"], utilisation["CGST to CGST"],
    )
    values["SGST Payable"] = _balance(
        values["Output SGST"], values["RCM SGST Payable"],
        utilisation["IGST to SGST"], utilisation["SGST to SGST"],
    )

    payment_rows = [
        _payment_value(t61, section, tax, column)
        for section in ("(A)", "(B)")
        for tax in ("Integrated tax", "Central tax", "State/UT tax")
        for column in ("Interest_paid_cash", "Late_fee_paid_cash")
    ]
    values["Interest paid"] = _sum_known(payment_rows[0::2])
    values["Late Fees paid"] = _sum_known(payment_rows[1::2])

    period = meta.get("Period_Year")
    row = {
        "Year": meta.get("Year"),
        "Return Period": _iso_period(period),
        "Month": meta.get("Period"),
        "GSTIN": meta.get("GSTIN"),
        "Company Name": meta.get("Legal_Name"),
        "Trade Name": meta.get("Trade_Name"),
        "ARN": meta.get("ARN"),
        "Date of filing": _iso_date(meta.get("Date_of_ARN")),
        **values,
        "Source File": source_file,
    }
    missing = [
        field for field in ANALYSIS_COLUMNS[:39]
        if row.get(field) is None or str(row.get(field)).strip() in ("", "Unknown")
    ]
    return row, missing
