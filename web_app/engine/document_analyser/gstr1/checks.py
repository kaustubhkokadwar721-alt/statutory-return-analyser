"""GSTR-1 sanity checks."""

import pandas as pd

from ..constants import LIABILITY_SECTIONS

TAX_HEADS = ("Value", "IGST", "CGST", "SGST", "Cess")
RECORD_CHECK_SECTIONS = ("4A", "4B", "5", "6A", "9B_CDNR", "9C_CDNUR")
INTERSTATE_ONLY_SECTIONS = (("5", "B2CL"), ("6A", "Export"), ("6B", "SEZ"))


def _section_lookup(section_totals: pd.DataFrame) -> pd.DataFrame:
    if section_totals.empty or "Section_Code" not in section_totals.columns:
        return pd.DataFrame()

    totals = section_totals.copy()
    numeric_cols = [c for c in (*TAX_HEADS, "Num_Records") if c in totals.columns]
    totals[numeric_cols] = totals[numeric_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    return totals.groupby("Section_Code", dropna=False)[numeric_cols].sum()


def run_sanity_checks_gstr1(section_totals: pd.DataFrame, meta: dict) -> list:
    """Return exception rows for a parsed GSTR-1 return."""
    exceptions = []
    period = meta.get("Period_Year", "")
    gstin = meta.get("GSTIN", "")
    st = _section_lookup(section_totals)

    def g(code: str, col: str) -> float:
        if st.empty or code not in st.index or col not in st.columns:
            return 0.0
        return float(st.at[code, col])

    # Check 1: Computed Total Liability == reported footer per tax head.
    for col in TAX_HEADS:
        computed = sum(g(s, col) for s in LIABILITY_SECTIONS)
        reported = g("TOTAL_LIABILITY", col)
        variance = round(computed - reported, 2)
        if abs(variance) > 1.0:
            exceptions.append({
                "GSTIN": gstin, "Period_Year": period,
                "Check": f"Total_Liability_{col}",
                "Computed": round(computed, 2), "Reported": round(reported, 2),
                "Variance": variance, "Status": "FAIL",
                "Reason": f"Sum of liability sections differs from reported Total Liability for {col}",
            })

    # Check 2: HSN Grand Total vs sum of primary supply tables, percentage based.
    hsn_val = g("12_HSN", "Value")
    supply_val = sum(g(s, "Value") for s in ("4A", "4B", "5", "6A", "6B", "6C", "7"))
    if supply_val != 0:
        pct = abs(hsn_val - supply_val) / abs(supply_val) * 100
        if pct > 10.0:
            exceptions.append({
                "GSTIN": gstin, "Period_Year": period,
                "Check": "HSN_vs_Supply_Tables",
                "Computed": round(supply_val, 2), "Reported": round(hsn_val, 2),
                "Variance": round(hsn_val - supply_val, 2), "Status": "WARN",
                "Reason": f"HSN Total Value differs from supply table sum by {pct:.1f}%",
            })

    # Check 3: records > 0 should agree with non-zero value for major sections.
    for sec in RECORD_CHECK_SECTIONS:
        recs = g(sec, "Num_Records")
        val = g(sec, "Value")
        if (recs == 0 and val != 0) or (recs > 0 and val == 0):
            exceptions.append({
                "GSTIN": gstin, "Period_Year": period,
                "Check": f"Record_Count_{sec}",
                "Computed": recs, "Reported": val, "Variance": 0,
                "Status": "WARN",
                "Reason": f"{sec}: Num_Records={recs:g} but Value={val:.2f}; mismatch",
            })

    # Check 4: B2CL average invoice should exceed INR 2.5L.
    b2cl_val = g("5", "Value")
    b2cl_rec = g("5", "Num_Records")
    if b2cl_rec > 0 and (b2cl_val / b2cl_rec) <= 250000:
        avg_invoice = b2cl_val / b2cl_rec
        exceptions.append({
            "GSTIN": gstin, "Period_Year": period,
            "Check": "B2CL_Threshold",
            "Computed": round(avg_invoice, 2), "Reported": 250000, "Variance": 0,
            "Status": "FAIL",
            "Reason": f"B2CL average invoice {avg_invoice:,.0f} is at or below 2.5L threshold.",
        })

    # Check 5: interstate supplies should carry IGST only.
    for sec, name in INTERSTATE_ONLY_SECTIONS:
        cgst = g(sec, "CGST")
        sgst = g(sec, "SGST")
        if cgst > 0 or sgst > 0:
            exceptions.append({
                "GSTIN": gstin, "Period_Year": period,
                "Check": f"Interstate_Tax_{sec}",
                "Computed": round(cgst + sgst, 2), "Reported": 0,
                "Variance": round(cgst + sgst, 2), "Status": "FAIL",
                "Reason": f"{name} ({sec}) has CGST/SGST. Inter-state supplies should carry IGST only.",
            })

    # Check 6: net credit/debit notes are expected to be non-positive.
    cdnr_val = g("9B_CDNR", "Value") + g("9C_CDNUR", "Value")
    if cdnr_val > 0:
        exceptions.append({
            "GSTIN": gstin, "Period_Year": period,
            "Check": "CDNR_Sign_Check",
            "Computed": round(cdnr_val, 2), "Reported": 0,
            "Variance": round(cdnr_val, 2), "Status": "WARN",
            "Reason": f"Net CDNR/CDNUR value is positive ({cdnr_val:,.2f}). Debit notes exceed credit notes.",
        })

    return exceptions
