"""GSTR-3B sanity checks."""

import pandas as pd

TAX_HEADS = ("Integrated tax", "Central tax", "State/UT tax", "Cess")
PAYMENT_ITC_COLS = ("ITC_Integrated", "ITC_Central", "ITC_State_UT", "ITC_Cess")


def _coerce_numeric(df: pd.DataFrame, columns) -> pd.DataFrame:
    result = df.copy()
    present = [col for col in columns if col in result.columns]
    if present:
        result[present] = result[present].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    return result


def _sum_columns(df: pd.DataFrame, columns) -> float:
    present = [col for col in columns if col in df.columns]
    if not present:
        return 0.0
    return float(df[present].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum().sum())


def _check_tax_name(tax_col: str) -> str:
    return tax_col.replace("/", "_").replace(" ", "_")


def run_sanity_checks_gstr3b(
    tables: dict,
    gstin: str,
    period: str,
) -> tuple[dict, list]:
    """Run sanity checks on one parsed GSTR-3B return."""
    exceptions_list = []
    audited_tables = dict(tables)

    df6 = tables.get("Table_6_1")
    if isinstance(df6, pd.DataFrame) and not df6.empty:
        itc_cols = [col for col in PAYMENT_ITC_COLS if col in df6.columns]
        cash_col = "Tax_paid_cash" if "Tax_paid_cash" in df6.columns else None
        net_col = "Net_Tax_Payable" if "Net_Tax_Payable" in df6.columns else None

        if itc_cols and cash_col and net_col:
            df6 = _coerce_numeric(df6, [*itc_cols, cash_col, net_col])
            df6["Total_Paid"] = df6[itc_cols].sum(axis=1) + df6[cash_col]
            df6["Payment_Variance"] = (df6[net_col] - df6["Total_Paid"]).round(2)
            df6["Sanity_Status"] = df6["Payment_Variance"].abs().gt(1.0).map(
                {True: "FAIL", False: "PASS"}
            )

            for _, row in df6[df6["Sanity_Status"] == "FAIL"].iterrows():
                exceptions_list.append({
                    "GSTIN": gstin,
                    "Period_Year": period,
                    "Check": "Payment_Recon_6_1",
                    "Sanity_Status": "FAIL",
                    "Variance_Reason": (
                        f"Net Payable {row[net_col]:.2f} differs from "
                        f"ITC+Cash {row['Total_Paid']:.2f}"
                    ),
                })

            audited_tables["Table_6_1"] = df6.drop(
                columns=["Total_Paid", "Payment_Variance"],
                errors="ignore",
            )

    df4 = tables.get("Table_4_ITC")
    if isinstance(df4, pd.DataFrame) and not df4.empty and "Section" in df4.columns:
        df4 = _coerce_numeric(df4, TAX_HEADS)
        section = df4["Section"].astype(str)
        a_rows = df4[section.str.startswith("A.", na=False)]
        b_rows = df4[section.str.startswith("B.", na=False)]
        c_rows = df4[section.str.startswith("C.", na=False)]

        for tax_col in TAX_HEADS:
            if tax_col not in df4.columns:
                continue
            a_total = float(a_rows[tax_col].sum())
            b_total = float(b_rows[tax_col].sum())
            c_net = float(c_rows[tax_col].sum())
            variance = round((a_total - b_total) - c_net, 2)
            if abs(variance) > 1.0:
                exceptions_list.append({
                    "GSTIN": gstin,
                    "Period_Year": period,
                    "Check": f"ITC_Math_{_check_tax_name(tax_col)}",
                    "Sanity_Status": "FAIL",
                    "Variance_Reason": (
                        f"ITC A ({a_total:.2f}) - B ({b_total:.2f}) = "
                        f"{a_total - b_total:.2f}, but Net C is {c_net:.2f}. "
                        f"Variance: {variance:.2f}"
                    ),
                })

    t31 = tables.get("Table_3_1")
    t4 = tables.get("Table_4_ITC")
    if isinstance(t31, pd.DataFrame) and isinstance(t4, pd.DataFrame):
        nat_col = next((col for col in t31.columns if "nature" in str(col).lower()), None)
        if nat_col:
            rcm_mask = t31[nat_col].astype(str).str.contains(r"\(d\)", case=False, na=False)
            rcm_tax = _sum_columns(t31[rcm_mask], TAX_HEADS[:3])

            if "Details" in t4.columns:
                itc_rcm_mask = t4["Details"].astype(str).str.contains(r"\(3\)", case=False, na=False)
                itc_rcm = _sum_columns(t4[itc_rcm_mask], TAX_HEADS[:3])
            else:
                itc_rcm = 0.0

            if rcm_tax > 0:
                gap_pct = abs(rcm_tax - itc_rcm) / rcm_tax * 100
                if gap_pct > 10:
                    exceptions_list.append({
                        "GSTIN": gstin,
                        "Period_Year": period,
                        "Check": "RCM_CrossCheck",
                        "Sanity_Status": "WARN",
                        "Variance_Reason": (
                            f"RCM declared (3.1d) {rcm_tax:,.0f} vs ITC claimed "
                            f"(4.3) {itc_rcm:,.0f}, gap {gap_pct:.1f}%"
                        ),
                    })

    return audited_tables, exceptions_list
