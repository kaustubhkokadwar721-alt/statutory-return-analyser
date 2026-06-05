"""GSTR-3B analytics functions."""

import pandas as pd

TAX_HEADS = ("Integrated tax", "Central tax", "State/UT tax", "Cess")
PAYMENT_ITC_COLS = ("ITC_Integrated", "ITC_Central", "ITC_State_UT", "ITC_Cess")
PAYMENT_CASH_COLS = ("Tax_paid_cash", "Interest_paid_cash", "Late_fee_paid_cash")

PAYMENT_ID_COLS = (
    "Source_File", "Year", "Period", "Period_Year", "GSTIN",
    "Section", "Description", "Sanity_Status",
)
OUTWARD_ID_COLS = (
    "Source_File", "Year", "Period", "Period_Year", "GSTIN",
    "Nature of Supplies",
)
ITC_ID_COLS = (
    "Source_File", "Year", "Period", "Period_Year", "GSTIN",
    "Details", "Section",
)


def _ensure_columns(df: pd.DataFrame, columns, default=None) -> pd.DataFrame:
    result = df.copy()
    for col in columns:
        if col not in result.columns:
            result[col] = default
    return result


def _coerce_numeric(df: pd.DataFrame, columns) -> pd.DataFrame:
    result = df.copy()
    present = [col for col in columns if col in result.columns]
    if present:
        result[present] = result[present].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    return result


def _standard_tax_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for col in df.columns:
        col_lower = str(col).lower()
        if "integrated" in col_lower:
            rename_map[col] = "Integrated tax"
        elif "central" in col_lower:
            rename_map[col] = "Central tax"
        elif "state" in col_lower or "ut" in col_lower:
            rename_map[col] = "State/UT tax"
        elif "cess" in col_lower:
            rename_map[col] = "Cess"
    return df.rename(columns=rename_map)


def _parse_period(period_str) -> "pd.Timestamp | None":
    """Parse 'Apr-25' or 'Apr 2025' → Timestamp; None on failure."""
    if not period_str or str(period_str) in ("Unknown", "nan", ""):
        return None
    p = pd.to_datetime(str(period_str), format="%b-%y", errors="coerce")
    if pd.isna(p):
        p = pd.to_datetime(str(period_str), format="%b %Y", errors="coerce")
    return None if pd.isna(p) else p


def create_analytics_schema_gstr3b(audited_tables: dict) -> dict:
    """Convert audited GSTR-3B tables into long-form analytics fact tables."""
    analytics_tables = {}

    df6 = audited_tables.get("Table_6_1")
    if isinstance(df6, pd.DataFrame) and not df6.empty:
        df6 = _ensure_columns(df6, PAYMENT_ID_COLS)
        df6 = _coerce_numeric(df6, (*PAYMENT_ITC_COLS, *PAYMENT_CASH_COLS))

        itc_vars = [col for col in PAYMENT_ITC_COLS if col in df6.columns]
        cash_vars = [col for col in PAYMENT_CASH_COLS if col in df6.columns]
        pieces = []

        if itc_vars:
            itc_melt = df6.melt(
                id_vars=list(PAYMENT_ID_COLS),
                value_vars=itc_vars,
                var_name="Payment_Type",
                value_name="Amount",
            )
            itc_melt["Payment_Category"] = "ITC"
            itc_melt["Payment_Type"] = itc_melt["Payment_Type"].str.replace(
                "ITC_", "", regex=False
            )
            pieces.append(itc_melt)

        if cash_vars:
            cash_melt = df6.melt(
                id_vars=list(PAYMENT_ID_COLS),
                value_vars=cash_vars,
                var_name="Payment_Type",
                value_name="Amount",
            )
            cash_melt["Payment_Category"] = "Cash"
            pieces.append(cash_melt)

        if pieces:
            fact_payments = pd.concat(pieces, ignore_index=True)
            fact_payments = fact_payments[fact_payments["Amount"].ne(0.0)].reset_index(drop=True)
            analytics_tables["Fact_Tax_Payments"] = fact_payments[
                [*PAYMENT_ID_COLS, "Payment_Type", "Amount", "Payment_Category"]
            ]

    df31 = audited_tables.get("Table_3_1")
    if isinstance(df31, pd.DataFrame) and not df31.empty:
        df31 = _standard_tax_columns(df31)
        df31 = _ensure_columns(df31, OUTWARD_ID_COLS)
        df31 = _coerce_numeric(df31, TAX_HEADS)
        melt_vars = [col for col in TAX_HEADS if col in df31.columns]

        if melt_vars:
            melt_31 = df31.melt(
                id_vars=list(OUTWARD_ID_COLS),
                value_vars=melt_vars,
                var_name="Tax_Head",
                value_name="Liability_Amount",
            )
            melt_31["RCM_Flag"] = melt_31["Nature of Supplies"].astype(str).str.contains(
                r"\(d\)", case=False, na=False
            ).map({True: "RCM", False: "Regular"})
            analytics_tables["Fact_Outward_Liability"] = melt_31[
                [*OUTWARD_ID_COLS, "Tax_Head", "Liability_Amount", "RCM_Flag"]
            ]

    df4 = audited_tables.get("Table_4_ITC")
    if isinstance(df4, pd.DataFrame) and not df4.empty:
        df4 = _standard_tax_columns(df4)
        df4 = _ensure_columns(df4, ITC_ID_COLS)
        df4 = _coerce_numeric(df4, TAX_HEADS)
        melt_vars = [col for col in TAX_HEADS if col in df4.columns]

        if melt_vars:
            melt_4 = df4.melt(
                id_vars=list(ITC_ID_COLS),
                value_vars=melt_vars,
                var_name="Tax_Head",
                value_name="Amount",
            )
            melt_4["RCM_Flag"] = melt_4["Details"].astype(str).str.contains(
                r"\(3\)", case=False, na=False
            ).map({True: "RCM", False: "Regular"})
            analytics_tables["Fact_Eligible_ITC"] = melt_4[
                [*ITC_ID_COLS, "Tax_Head", "Amount", "RCM_Flag"]
            ]

    return analytics_tables


def build_executive_summary_gstr3b(
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
    ws.set_column(0, 0, 20)    # GSTIN
    ws.set_column(1, 1, 10)    # Period
    ws.set_column(2, 8, 17)    # money cols
    ws.set_column(9, 9, 14)    # Sanity Status

    # ── row heights ───────────────────────────────────────────────────────────
    ws.set_row(0, 34)   # title
    ws.set_row(1, 18)   # subtitle
    ws.set_row(2, 6)    # spacer
    ws.set_row(3, 22)   # KPI labels
    ws.set_row(4, 30)   # KPI values
    ws.set_row(5, 6)    # spacer
    ws.set_row(6, 20)   # table header

    # ── title (row 0) ─────────────────────────────────────────────────────────
    ws.merge_range(0, 0, 0, 9, "GSTR-3B Analytics Summary", title_fmt)

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
        1, 0, 1, 9,
        f"{n_ret} return{'s' if n_ret != 1 else ''}  ·  {period_str}",
        subtitle_fmt,
    )

    # ── KPI band (rows 3–4) ───────────────────────────────────────────────────
    # 5 KPIs × 2 columns = 10 columns (A:J)
    kpi_defs = [
        ("Returns\nProcessed",     n_ret,                                                      False),
        ("Sanity\nIssues",         exception_count,                                            True),
        ("Gross Tax\nLiability",   "=SUM(Fact_Outward_Liability!H:H)",                         False),
        ("Eligible ITC\nClaimed",  "=SUM(Fact_Eligible_ITC!I:I)",                              False),
        ("Cash\nPaid",             '=SUMIFS(Fact_Tax_Payments!J:J,Fact_Tax_Payments!K:K,"Cash")', False),
    ]
    for i, (label, value, is_issues) in enumerate(kpi_defs):
        c1, c2 = i * 2, i * 2 + 1
        ws.merge_range(3, c1, 3, c2, label, kpi_lbl_fmt)
        if is_issues:
            fmt = kpi_alert_fmt if isinstance(value, int) and value > 0 else kpi_ok_fmt
            ws.merge_range(4, c1, 4, c2, value, fmt)
        else:
            # merge_range handles '=...' strings as formulas directly
            ws.merge_range(4, c1, 4, c2, value, kpi_val_fmt)

    # ── table header (row 6) ──────────────────────────────────────────────────
    headers = [
        "GSTIN", "Period", "Gross Outward Value", "Net Tax Paid",
        "ITC Utilized", "Cash Paid", "RCM Declared", "RCM ITC Claimed",
        "RCM Variance", "Sanity Status",
    ]
    for col_num, header in enumerate(headers):
        ws.write(6, col_num, header, hdr)

    # autofilter on table
    ws.autofilter(6, 0, 6, len(headers) - 1)

    # ── data rows (row 7+) — sorted by period ascending ───────────────────────
    unique_returns = []
    if not df_metadata.empty:
        seen = set()
        for rec in df_metadata.reindex(columns=["GSTIN", "Period_Year", "Source_File"]).to_dict("records"):
            key = (rec.get("GSTIN", ""), rec.get("Period_Year", ""))
            if key not in seen:
                seen.add(key)
                unique_returns.append(rec)

    # sort by parsed period date, then GSTIN
    unique_returns.sort(key=lambda r: (
        _parse_period(r.get("Period_Year", "")) or pd.Timestamp.min,
        r.get("GSTIN", ""),
    ))

    for row_idx, ret in enumerate(unique_returns, start=7):
        gstin = ret.get("GSTIN", "")
        period = ret.get("Period_Year", "")
        row_ref = row_idx + 1

        ws.write(row_idx, 0, gstin, bdr)

        p_ts = _parse_period(period)
        if p_ts is not None:
            ws.write_datetime(row_idx, 1, p_ts.to_pydatetime(), date_fmt)
        else:
            ws.write(row_idx, 1, period, bdr)

        ws.write_formula(
            row_idx, 2,
            f"=SUMIFS(Fact_Outward_Liability!H:H,"
            f"Fact_Outward_Liability!E:E,A{row_ref},"
            f"Fact_Outward_Liability!D:D,B{row_ref})",
            curr,
        )
        ws.write_formula(
            row_idx, 3,
            f"=SUMIFS(Fact_Tax_Payments!J:J,"
            f"Fact_Tax_Payments!E:E,A{row_ref},"
            f"Fact_Tax_Payments!D:D,B{row_ref})",
            curr,
        )
        ws.write_formula(
            row_idx, 4,
            f"=SUMIFS(Fact_Tax_Payments!J:J,"
            f"Fact_Tax_Payments!E:E,A{row_ref},"
            f"Fact_Tax_Payments!D:D,B{row_ref},"
            f'Fact_Tax_Payments!K:K,"ITC")',
            curr,
        )
        ws.write_formula(
            row_idx, 5,
            f"=SUMIFS(Fact_Tax_Payments!J:J,"
            f"Fact_Tax_Payments!E:E,A{row_ref},"
            f"Fact_Tax_Payments!D:D,B{row_ref},"
            f'Fact_Tax_Payments!K:K,"Cash")',
            curr,
        )
        ws.write_formula(
            row_idx, 6,
            f"=SUMIFS(Fact_Outward_Liability!H:H,"
            f"Fact_Outward_Liability!E:E,A{row_ref},"
            f"Fact_Outward_Liability!D:D,B{row_ref},"
            f'Fact_Outward_Liability!I:I,"RCM")',
            curr,
        )
        ws.write_formula(
            row_idx, 7,
            f"=SUMIFS(Fact_Eligible_ITC!I:I,"
            f"Fact_Eligible_ITC!E:E,A{row_ref},"
            f"Fact_Eligible_ITC!D:D,B{row_ref},"
            f'Fact_Eligible_ITC!J:J,"RCM")',
            curr,
        )
        ws.write_formula(row_idx, 8, f"=G{row_ref}-H{row_ref}", curr)
        ws.write_formula(row_idx, 9, f'=IF(ABS(I{row_ref})<=1,"PASS","REVIEW")', bdr)

    # ── conditional formatting — Sanity Status column (col J = index 9) ───────
    if unique_returns:
        last_row = 6 + len(unique_returns)   # 0-based last data row
        # PASS → green fill
        ws.conditional_format(7, 9, last_row, 9, {
            "type": "text", "criteria": "containing", "value": "PASS",
            "format": pass_fmt,
        })
        # REVIEW → amber
        ws.conditional_format(7, 9, last_row, 9, {
            "type": "text", "criteria": "containing", "value": "REVIEW",
            "format": warn_fmt,
        })
        # FAIL → red
        ws.conditional_format(7, 9, last_row, 9, {
            "type": "text", "criteria": "containing", "value": "FAIL",
            "format": fail_fmt,
        })

    ws.freeze_panes(7, 0)
