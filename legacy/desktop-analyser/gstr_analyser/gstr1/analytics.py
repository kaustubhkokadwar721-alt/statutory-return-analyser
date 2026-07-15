"""GSTR-1 analytics functions."""

import pandas as pd

from ..constants import LIABILITY_SECTIONS

TAX_HEADS = ("Value", "IGST", "CGST", "SGST", "Cess")
FACT_ID_COLS = (
    "GSTIN", "Period_Year", "FY", "Period", "Source_File",
    "Section_Code", "Section_Label",
)


def _ensure_columns(df: pd.DataFrame, columns, default=None) -> pd.DataFrame:
    """Return a copy with all requested columns present."""
    result = df.copy()
    for col in columns:
        if col not in result.columns:
            result[col] = default
    return result


def _parse_period(period_str) -> "pd.Timestamp | None":
    """Parse 'Apr-25' or 'Apr 2025' → Timestamp; None on failure."""
    if not period_str or str(period_str) in ("Unknown", "nan", ""):
        return None
    p = pd.to_datetime(str(period_str), format="%b-%y", errors="coerce")
    if pd.isna(p):
        p = pd.to_datetime(str(period_str), format="%b %Y", errors="coerce")
    return None if pd.isna(p) else p


def _parse_period_year(series: pd.Series) -> pd.Series:
    """Convert known Period_Year strings to Excel-friendly datetimes when possible."""
    parsed = pd.to_datetime(series, format="%b-%y", errors="coerce")
    fallback = pd.to_datetime(series, format="%b %Y", errors="coerce")
    parsed = parsed.fillna(fallback)
    return parsed.where(parsed.notna(), series)


def build_liability_recon(df_totals: pd.DataFrame, df_meta: pd.DataFrame) -> pd.DataFrame:
    if df_totals.empty or df_meta.empty:
        return pd.DataFrame()

    required_cols = ["GSTIN", "Period_Year", "Section_Code"]
    if any(col not in df_totals.columns for col in required_cols):
        return pd.DataFrame()

    totals = _ensure_columns(df_totals, TAX_HEADS, 0.0)
    totals[list(TAX_HEADS)] = totals[list(TAX_HEADS)].apply(
        pd.to_numeric, errors="coerce"
    ).fillna(0.0)

    totals = totals.groupby(
        required_cols,
        dropna=False,
        as_index=True,
    )[list(TAX_HEADS)].sum()

    rows = []
    meta = df_meta.reindex(columns=["GSTIN", "Period_Year"], fill_value="")

    for gstin, period in meta.itertuples(index=False, name=None):
        try:
            period_totals = totals.loc[(gstin, period)]
        except KeyError:
            period_totals = pd.DataFrame(columns=TAX_HEADS)

        liability = period_totals.reindex(LIABILITY_SECTIONS).fillna(0.0)
        reported = period_totals.reindex(["TOTAL_LIABILITY"]).fillna(0.0)

        for head in TAX_HEADS:
            computed = round(float(liability[head].sum()), 2)
            reported_amt = round(float(reported[head].sum()), 2)
            variance = round(computed - reported_amt, 2)

            rows.append({
                "GSTIN": gstin,
                "Period_Year": period,
                "Tax_Head": head,
                "Computed": computed,
                "Reported": reported_amt,
                "Variance": variance,
                "Status": "PASS" if abs(variance) <= 1.0 else "FAIL",
            })

    return pd.DataFrame(rows)


def create_fact_table_gstr1(section_totals: pd.DataFrame) -> pd.DataFrame:
    final_cols = [*FACT_ID_COLS, "Tax_Head", "Amount", "Sign"]
    if section_totals.empty:
        return pd.DataFrame(columns=final_cols)

    totals = _ensure_columns(section_totals, TAX_HEADS, 0.0)
    totals = _ensure_columns(totals, FACT_ID_COLS, None)
    totals[list(TAX_HEADS)] = totals[list(TAX_HEADS)].apply(
        pd.to_numeric, errors="coerce"
    ).fillna(0.0)
    totals["Period_Year"] = _parse_period_year(totals["Period_Year"])

    fact = totals.melt(
        id_vars=list(FACT_ID_COLS),
        value_vars=list(TAX_HEADS),
        var_name="Tax_Head",
        value_name="Amount",
    )

    fact = fact[fact["Amount"].ne(0.0)].reset_index(drop=True)
    fact["Sign"] = fact["Amount"].lt(0).map({True: "Credit", False: "Debit"})

    # Keep Amount in column I and Tax_Head in column H for Summary SUMIFS formulas.
    return fact[final_cols]


def build_executive_summary_gstr1(
    writer,
    df_metadata: pd.DataFrame,
    exception_count: int,
) -> None:
    """Write Summary sheet — professional layout with KPI band and per-return table."""
    wb = writer.book
    ws = wb.add_worksheet("Summary")
    ws.activate()

    # ── formats ──────────────────────────────────────────────────────────────
    title_fmt = wb.add_format({
        "bold": True, "font_size": 16, "font_color": "white",
        "bg_color": "#1F3864", "align": "center", "valign": "vcenter",
    })
    subtitle_fmt = wb.add_format({
        "font_size": 10, "font_color": "#595959",
        "bg_color": "#EBF3FB", "align": "center", "valign": "vcenter",
    })
    kpi_lbl_fmt = wb.add_format({
        "bold": True, "font_size": 9, "font_color": "#ffffff",
        "bg_color": "#2E75B6", "align": "center", "valign": "vcenter",
        "text_wrap": True,
    })
    kpi_val_fmt = wb.add_format({
        "bold": True, "font_size": 14, "font_color": "#1F3864",
        "bg_color": "#DEEAF1", "align": "center", "valign": "vcenter",
        "border": 1, "num_format": "##,##,##0",
    })
    kpi_alert_fmt = wb.add_format({
        "bold": True, "font_size": 14, "font_color": "#C00000",
        "bg_color": "#FFE7E7", "align": "center", "valign": "vcenter",
        "border": 1,
    })
    kpi_ok_fmt = wb.add_format({
        "bold": True, "font_size": 14, "font_color": "#375623",
        "bg_color": "#E2EFDA", "align": "center", "valign": "vcenter",
        "border": 1,
    })
    hdr = wb.add_format({
        "bold": True, "bg_color": "#1F4E78", "font_color": "white",
        "border": 1, "align": "center", "valign": "vcenter",
    })
    bdr = wb.add_format({"border": 1, "align": "left"})
    curr = wb.add_format({"num_format": "##,##,##0", "border": 1, "align": "right"})
    date_fmt = wb.add_format({"num_format": "mmm-yy", "border": 1, "align": "center"})
    pass_fmt = wb.add_format({
        "bold": True, "border": 1, "align": "center",
        "font_color": "#375623", "bg_color": "#E2EFDA",
    })
    warn_fmt = wb.add_format({
        "bold": True, "border": 1, "align": "center",
        "font_color": "#7F6000", "bg_color": "#FFF2CC",
    })
    fail_fmt = wb.add_format({
        "bold": True, "border": 1, "align": "center",
        "font_color": "#C00000", "bg_color": "#FFE7E7",
    })

    # ── column widths ─────────────────────────────────────────────────────────
    # 9 data columns: GSTIN(0), Period(1), B2B Value(2), B2B IGST(3),
    # B2CS Value(4), CDNR Net(5), Net IGST(6), Net CGST(7), Net SGST(8)
    ws.set_column(0, 0, 20)    # GSTIN
    ws.set_column(1, 1, 10)    # Period
    ws.set_column(2, 8, 15)    # metric cols

    # ── row heights ───────────────────────────────────────────────────────────
    ws.set_row(0, 34)   # title
    ws.set_row(1, 18)   # subtitle
    ws.set_row(2, 6)    # spacer
    ws.set_row(3, 22)   # KPI labels
    ws.set_row(4, 30)   # KPI values
    ws.set_row(5, 6)    # spacer
    ws.set_row(6, 20)   # table header

    # ── title (row 0) ─────────────────────────────────────────────────────────
    ws.merge_range(0, 0, 0, 8, "GSTR-1 Analytics Summary", title_fmt)

    # ── subtitle (row 1) ──────────────────────────────────────────────────────
    n_ret = len(df_metadata)
    period_str = "N/A"
    if not df_metadata.empty and "Period_Year" in df_metadata.columns:
        parsed = sorted(
            p for p in (
                _parse_period(v) for v in df_metadata["Period_Year"].dropna().unique()
            )
            if p is not None
        )
        if parsed:
            period_str = f"{parsed[0].strftime('%b-%y')} to {parsed[-1].strftime('%b-%y')}"
    ws.merge_range(
        1, 0, 1, 8,
        f"{n_ret} return{'s' if n_ret != 1 else ''}  ·  {period_str}",
        subtitle_fmt,
    )

    # ── KPI band (rows 3–4) — 3 KPIs × 3 cols = 9 cols ───────────────────────
    def _sumifs_total(head: str) -> str:
        return f'=SUMIFS(Fact_Liability!I:I,Fact_Liability!F:F,"TOTAL_LIABILITY",Fact_Liability!H:H,"{head}")'

    kpi_defs = [
        ("Returns\nProcessed",  n_ret,                    False),
        ("Sanity\nIssues",      exception_count,           True),
        ("Net Total\nIGST",     _sumifs_total("IGST"),     False),
    ]
    for i, (label, value, is_issues) in enumerate(kpi_defs):
        c1, c2 = i * 3, i * 3 + 2
        ws.merge_range(3, c1, 3, c2, label, kpi_lbl_fmt)
        if is_issues:
            fmt = kpi_alert_fmt if isinstance(value, int) and value > 0 else kpi_ok_fmt
            ws.merge_range(4, c1, 4, c2, value, fmt)
        else:
            ws.merge_range(4, c1, 4, c2, value, kpi_val_fmt)

    # ── table header (row 6) ──────────────────────────────────────────────────
    metrics = (
        ("B2B Value",      "4A", "Value"),
        ("B2B IGST",       "4A", "IGST"),
        ("B2CS Value",     "7",  "Value"),
        ("CDNR Net Value", "9B_CDNR", "Value"),
        ("Net Total IGST", "TOTAL_LIABILITY", "IGST"),
        ("Net Total CGST", "TOTAL_LIABILITY", "CGST"),
        ("Net Total SGST", "TOTAL_LIABILITY", "SGST"),
    )
    for col, header in enumerate(("GSTIN", "Period", *(m[0] for m in metrics))):
        ws.write(6, col, header, hdr)

    ws.autofilter(6, 0, 6, 8)

    # ── data rows (row 7+) — sorted by period ascending ───────────────────────
    meta_rows = []
    if not df_metadata.empty:
        seen = set()
        for rec in df_metadata.reindex(columns=["GSTIN", "Period_Year"]).to_dict("records"):
            key = (rec.get("GSTIN", ""), rec.get("Period_Year", ""))
            if key not in seen:
                seen.add(key)
                meta_rows.append(rec)

    meta_rows.sort(key=lambda r: (
        _parse_period(r.get("Period_Year", "")) or pd.Timestamp.min,
        r.get("GSTIN", ""),
    ))

    def _sumifs(section: str, head: str, gstin_cell: str, period_cell: str) -> str:
        return (
            f"=SUMIFS(Fact_Liability!I:I,"
            f"Fact_Liability!A:A,{gstin_cell},"
            f"Fact_Liability!B:B,{period_cell},"
            f'Fact_Liability!F:F,"{section}",'
            f'Fact_Liability!H:H,"{head}")'
        )

    for row_idx, rec in enumerate(meta_rows, start=7):
        gstin = rec.get("GSTIN", "")
        period = rec.get("Period_Year", "")
        row_ref = row_idx + 1

        ws.write(row_idx, 0, gstin, bdr)

        p_ts = _parse_period(period)
        if p_ts is not None:
            ws.write_datetime(row_idx, 1, p_ts.to_pydatetime(), date_fmt)
        else:
            ws.write(row_idx, 1, period, bdr)

        for col, (_, section, head) in enumerate(metrics, start=2):
            ws.write_formula(
                row_idx, col,
                _sumifs(section, head, f"A{row_ref}", f"B{row_ref}"),
                curr,
            )

    ws.freeze_panes(7, 0)
