"""Unified pipeline: auto-detect all return types → CSV ledgers."""

import os
import glob
import re
import pandas as pd
import pdfplumber
from typing import Callable

from .utils import to_float
from .gstr1.parser import parse_gstr1
from .gstr1.checks import run_sanity_checks_gstr1
from .gstr3b.parser import parse_complete_gstr3b
from .gstr3b.checks import run_sanity_checks_gstr3b
from .compliance_parsers import parse_esic, parse_pf, parse_ptrc, parse_tds


# ── Return-type detection ─────────────────────────────────────────────────────

def detect_return_type(text: str) -> str:
    t = text.upper()

    # GSTR forms — very specific markers
    if "GSTR-3B" in t or "GSTR3B" in t:
        return "GSTR3B"
    if "GSTR-1" in t or "GSTR1" in t:
        return "GSTR1"

    # ESIC — unique label
    if "CHALLAN PERIOD:" in t and ("EMPLOYEE'S STATE INSURANCE" in t or "ESIC" in t):
        return "ESIC"

    # PF — EPFO header + establishment code
    if "EMPLOYEES' PROVIDENT FUND" in t or ("ESTABLISHMENT CODE" in t and "A/C" in t):
        return "PF"

    # PTRC — Maharashtra FORM_IIIB / Profession Tax
    if "FORM_IIIB" in t or "PROFESSION TAX" in t or "PTRC" in t:
        return "PTRC"

    # TDS — Income Tax challan (ITNS 280/281/282 etc.)
    if ("INCOME TAX DEPARTMENT" in t or "CHALLAN RECEIPT" in t) and (
        "TAN" in t or "DATE OF DEPOSIT" in t or "NATURE OF PAYMENT" in t
    ):
        return "TDS"

    return "Unknown"


# ── Helper ────────────────────────────────────────────────────────────────────

def _fmt_date(ts) -> str | None:
    if ts is None or (isinstance(ts, float) and pd.isna(ts)):
        return None
    try:
        if pd.isna(ts):
            return None
    except Exception:
        pass
    try:
        return pd.Timestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return None


def _month_idx(ts) -> int:
    if ts is None:
        return 0
    try:
        if pd.isna(ts):
            return 0
    except Exception:
        pass
    try:
        cal_m = pd.Timestamp(ts).month
        return cal_m - 3 if cal_m >= 4 else cal_m + 9
    except Exception:
        return 0


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_unified_pipeline(
    input_folder: str,
    output_dir: str,
    progress_cb: Callable | None = None,
) -> list[dict]:

    os.makedirs(output_dir, exist_ok=True)
    pdf_files = sorted(glob.glob(os.path.join(input_folder, "*.pdf")))
    if not pdf_files:
        raise FileNotFoundError("No PDF files found in the input folder.")

    def log(step, msg=""):
        if progress_cb:
            progress_cb(step, msg)

    log("1", f"Found {len(pdf_files)} PDF(s). Analyzing...")

    records = []          # unified contract rows
    errors  = []          # failed files
    raw_details = {k: [] for k in ("GSTR1", "GSTR3B", "ESIC", "PF", "PTRC", "TDS")}

    for idx, fpath in enumerate(pdf_files, 1):
        fname = os.path.basename(fpath)
        log("2", f"Parsing {idx}/{len(pdf_files)}: {fname}")

        try:
            with pdfplumber.open(fpath) as pdf:
                if not pdf.pages:
                    raise ValueError("PDF has no pages")

                first_text = pdf.pages[0].extract_text() or ""
                return_type = detect_return_type(first_text)

                # If first page gave nothing, try full text
                if return_type == "Unknown":
                    full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
                    return_type = detect_return_type(full_text)

                # ── GSTR-1 ────────────────────────────────────────────────
                if return_type == "GSTR1":
                    res = parse_gstr1(fpath, errors)
                    if not res:
                        continue
                    meta = res["Metadata"]
                    sec_totals = res["Section_Totals"]

                    chk_errs = run_sanity_checks_gstr1(sec_totals, meta, [])
                    flags  = "; ".join(e["Check"] for e in chk_errs)
                    status = "Error" if any(e.get("Status") == "FAIL" for e in chk_errs) else ("Review" if flags else "OK")

                    tot_row = sec_totals[sec_totals["Section_Code"] == "TOTAL_LIABILITY"]
                    primary_amt = 0.0
                    if not tot_row.empty:
                        r = tot_row.iloc[0]
                        primary_amt = sum(to_float(r.get(c, 0)) for c in ("IGST", "CGST", "SGST", "Cess"))

                    pd_date = None
                    for fmt in ("%b-%y", "%b %Y"):
                        try:
                            pd_date = pd.to_datetime(meta["Period_Year"], format=fmt)
                            break
                        except Exception:
                            pass

                    records.append({
                        "ReturnType":    "GSTR1",
                        "EntityID":      meta.get("GSTIN", "Unknown"),
                        "EntityName":    meta.get("Legal_Name", "Unknown"),
                        "FY":            meta.get("FY", "Unknown"),
                        "PeriodDate":    _fmt_date(pd_date),
                        "MonthName":     pd_date.strftime("%B") if pd_date else "Unknown",
                        "MonthIndex":    _month_idx(pd_date),
                        "Status":        status,
                        "Flags":         flags,
                        "PrimaryAmount": primary_amt,
                        "SourceFile":    fname,
                    })
                    for _, row in sec_totals.iterrows():
                        dr = {"SourceFile": fname}
                        dr.update(meta)
                        dr.update(row.to_dict())
                        raw_details["GSTR1"].append(dr)

                # ── GSTR-3B ───────────────────────────────────────────────
                elif return_type == "GSTR3B":
                    res = parse_complete_gstr3b(fpath, errors)
                    if not res:
                        continue
                    meta = res["Metadata"]
                    file_tables = {
                        k: v for k, v in res.items()
                        if k != "Metadata" and isinstance(v, pd.DataFrame) and not v.empty
                    }
                    gstin  = meta.get("GSTIN", "Unknown")
                    period = meta.get("Period_Year", "Unknown")

                    _, chk_errs = run_sanity_checks_gstr3b(file_tables, gstin, period)
                    flags  = "; ".join(e["Check"] for e in chk_errs)
                    status = "Error" if any(e.get("Audit_Status") == "FAIL" for e in chk_errs) else ("Review" if flags else "OK")

                    primary_amt = 0.0
                    t61 = file_tables.get("Table_6_1")
                    if t61 is not None:
                        for col in ("Net_Tax_Payable", "Tax_Payable"):
                            if col in t61.columns:
                                primary_amt = float(t61[col].sum())
                                break

                    pd_date = None
                    for fmt in ("%b-%y", "%b %Y"):
                        try:
                            pd_date = pd.to_datetime(meta["Period_Year"], format=fmt)
                            break
                        except Exception:
                            pass

                    records.append({
                        "ReturnType":    "GSTR3B",
                        "EntityID":      gstin,
                        "EntityName":    meta.get("Legal_Name", "Unknown"),
                        "FY":            meta.get("Year", "Unknown"),
                        "PeriodDate":    _fmt_date(pd_date),
                        "MonthName":     pd_date.strftime("%B") if pd_date else "Unknown",
                        "MonthIndex":    _month_idx(pd_date),
                        "Status":        status,
                        "Flags":         flags,
                        "PrimaryAmount": primary_amt,
                        "SourceFile":    fname,
                    })
                    flat = {"SourceFile": fname}
                    flat.update(meta)
                    t31 = file_tables.get("Table_3_1")
                    if t31 is not None:
                        flat["Output_IGST"] = to_float(t31.get("Integrated tax", pd.Series([0])).sum())
                        flat["Output_CGST"] = to_float(t31.get("Central tax",    pd.Series([0])).sum())
                        flat["Output_SGST"] = to_float(t31.get("State/UT tax",   pd.Series([0])).sum())
                    t4 = file_tables.get("Table_4_ITC")
                    if t4 is not None:
                        flat["Net_ITC_IGST"] = to_float(t4.get("Integrated tax", pd.Series([0])).sum())
                        flat["Net_ITC_CGST"] = to_float(t4.get("Central tax",    pd.Series([0])).sum())
                        flat["Net_ITC_SGST"] = to_float(t4.get("State/UT tax",   pd.Series([0])).sum())
                    raw_details["GSTR3B"].append(flat)

                # ── ESIC ──────────────────────────────────────────────────
                elif return_type == "ESIC":
                    res = parse_esic(pdf, fname)
                    res["SourceFile"] = fname
                    raw_details["ESIC"].append(res)

                # ── PF ────────────────────────────────────────────────────
                elif return_type == "PF":
                    res = parse_pf(pdf, fname)
                    res["SourceFile"] = fname

                    flags_list = []
                    if res["EntityID"] in ("Unknown", ""):
                        flags_list.append("ENTITY?")
                    if res["PeriodDate"] is None:
                        flags_list.append("PERIOD?")
                    if res.get("PF_Admin_AC02", 0) == 0 and res.get("EDLI_Admin_AC22", 0) == 0:
                        flags_list.append("NO ADMIN")
                    ee = res.get("Employee_EPF_AC01", 0)
                    er = res.get("Employer_EPF_AC01", 0) + res.get("Employer_EPS_AC10", 0)
                    if er > 0 and abs(ee - er) / max(er, 1) > 0.05:
                        flags_list.append("EE<>ER?")

                    flags  = "; ".join(flags_list)
                    status = "Review" if flags_list else "OK"
                    primary_amt = sum(res.get(k, 0) for k in (
                        "Employer_EPF_AC01", "Employer_EPS_AC10", "Employer_EDLI_AC21",
                        "PF_Admin_AC02", "EDLI_Admin_AC22", "Employee_EPF_AC01"
                    ))
                    pd_date = res["PeriodDate"]

                    records.append({
                        "ReturnType":    "PF",
                        "EntityID":      res["EntityID"],
                        "EntityName":    res["EntityName"],
                        "FY":            res["FY"],
                        "PeriodDate":    _fmt_date(pd_date),
                        "MonthName":     pd.Timestamp(pd_date).strftime("%B") if pd_date else "Unknown",
                        "MonthIndex":    _month_idx(pd_date),
                        "Status":        status,
                        "Flags":         flags,
                        "PrimaryAmount": primary_amt,
                        "SourceFile":    fname,
                    })
                    raw_details["PF"].append(res)

                # ── PTRC ──────────────────────────────────────────────────
                elif return_type == "PTRC":
                    res = parse_ptrc(pdf, fname)
                    res["SourceFile"] = fname

                    flags_list = []
                    if res["EntityID"] in ("Unknown", ""):
                        flags_list.append("TIN?")
                    if res["PeriodDate"] is None:
                        flags_list.append("PERIOD?")
                    if res.get("PT Paid", 0) <= 0:
                        flags_list.append("AMT?")

                    flags  = "; ".join(flags_list)
                    status = "Review" if flags_list else "OK"
                    pd_date = res["PeriodDate"]

                    records.append({
                        "ReturnType":    "PTRC",
                        "EntityID":      res["EntityID"],
                        "EntityName":    res["EntityName"],
                        "FY":            res["FY"],
                        "PeriodDate":    _fmt_date(pd_date),
                        "MonthName":     pd.Timestamp(pd_date).strftime("%B") if pd_date else "Unknown",
                        "MonthIndex":    _month_idx(pd_date),
                        "Status":        status,
                        "Flags":         flags,
                        "PrimaryAmount": res.get("PT Paid", 0),
                        "SourceFile":    fname,
                    })
                    raw_details["PTRC"].append(res)

                # ── TDS ───────────────────────────────────────────────────
                elif return_type == "TDS":
                    res = parse_tds(pdf, fname)
                    res["SourceFile"] = fname

                    flags_list = []
                    if res["EntityID"] in ("Unknown", ""):
                        flags_list.append("TAN?")
                    if res["PeriodDate"] is None:
                        flags_list.append("MONTH?")
                    if abs(res.get("Crosscheck Diff", 0)) > 1.0:
                        flags_list.append("CROSSCHECK")
                    if res.get("Section", "Unknown") == "Unknown":
                        flags_list.append("SECTION?")
                    if res.get("Total Amount Paid", 0) <= 0:
                        flags_list.append("AMT?")

                    flags  = "; ".join(flags_list)
                    status = "Review" if flags_list else "OK"
                    pd_date = res["PeriodDate"]

                    records.append({
                        "ReturnType":    "TDS",
                        "EntityID":      res["EntityID"],
                        "EntityName":    res["EntityName"],
                        "FY":            res["FY"],
                        "PeriodDate":    _fmt_date(pd_date),
                        "MonthName":     pd.Timestamp(pd_date).strftime("%B") if pd_date else "Unknown",
                        "MonthIndex":    _month_idx(pd_date),
                        "Status":        status,
                        "Flags":         flags,
                        "PrimaryAmount": res.get("Total Amount Paid", 0),
                        "SourceFile":    fname,
                    })
                    raw_details["TDS"].append(res)

                else:
                    errors.append({
                        "File":       fname,
                        "Error_Type": "UnknownType",
                        "Message":    "Could not identify return type from PDF text.",
                        "Action":     "Skipped.",
                    })

        except Exception as exc:
            errors.append({
                "File":       fname,
                "Error_Type": type(exc).__name__,
                "Message":    str(exc)[:300],
                "Action":     "Parse failed — check if file is damaged or password-protected.",
            })

    # ── ESIC post-process: rank employer/employee challan per period ──────────
    if raw_details["ESIC"]:
        df_esic = pd.DataFrame(raw_details["ESIC"])
        df_esic = df_esic.sort_values(["FY", "Month", "Amount"], ascending=[True, True, False])
        df_esic["rank"]  = df_esic.groupby(["FY", "Month"]).cumcount()
        df_esic["Party"] = df_esic["rank"].map(lambda r: "Employer" if r == 0 else ("Employee" if r == 1 else "Other"))
        df_esic.drop(columns=["rank"], inplace=True)

        for _, row in df_esic.iterrows():
            flags_list = []
            pd_date = row.get("PeriodDate")
            is_nat  = pd_date is None or (isinstance(pd_date, float) and pd.isna(pd_date))
            try:
                is_nat = is_nat or pd.isna(pd_date)
            except Exception:
                pass
            if is_nat:
                flags_list.append("PERIOD?")
            if row.get("Party") == "Other":
                flags_list.append("EXTRA CHALLAN")
            if not row.get("Amount") or row["Amount"] <= 0:
                flags_list.append("AMT?")

            flags  = "; ".join(flags_list)
            status = "Review" if flags_list else "OK"

            records.append({
                "ReturnType":    "ESIC",
                "EntityID":      row.get("EntityID", ""),
                "EntityName":    row.get("EntityName", ""),
                "FY":            row["FY"],
                "PeriodDate":    _fmt_date(pd_date),
                "MonthName":     pd.Timestamp(pd_date).strftime("%B") if not is_nat else "Unknown",
                "MonthIndex":    _month_idx(pd_date) if not is_nat else 0,
                "Status":        status,
                "Flags":         flags,
                "PrimaryAmount": row.get("Amount", 0),
                "SourceFile":    row["SourceFile"],
            })
        raw_details["ESIC"] = df_esic.to_dict("records")

    # ── Write CSVs ────────────────────────────────────────────────────────────
    output_files = []

    if records:
        df_all = pd.DataFrame(records)
        df_all = df_all.sort_values(["ReturnType", "FY", "MonthIndex", "EntityID"])
        path_all = os.path.join(output_dir, "All_Returns_Consolidated.csv")
        df_all.to_csv(path_all, index=False)
        output_files.append({
            "label": "Consolidated Ledger",
            "desc":  "All parsed returns — unified contract schema.",
            "filename": "All_Returns_Consolidated.csv",
            "path": path_all,
        })

        df_dash = df_all.groupby(["ReturnType", "FY"]).agg(
            Records          = ("Status", "count"),
            OK               = ("Status", lambda s: (s == "OK").sum()),
            Review           = ("Status", lambda s: (s == "Review").sum()),
            Errors           = ("Status", lambda s: (s == "Error").sum()),
            Periods          = ("PeriodDate", "nunique"),
            TotalPrimaryAmt  = ("PrimaryAmount", "sum"),
        ).reset_index()
        df_dash["FlagRate"] = ((df_dash["Review"] + df_dash["Errors"]) / df_dash["Records"]).round(3)
        path_dash = os.path.join(output_dir, "Dashboard_Summary.csv")
        df_dash.to_csv(path_dash, index=False)
        output_files.append({
            "label": "Dashboard Summary",
            "desc":  "Filing counts, pass rates, totals grouped by return type and FY.",
            "filename": "Dashboard_Summary.csv",
            "path": path_dash,
        })

    for rtype, rlist in raw_details.items():
        if not rlist:
            continue
        df_det = pd.DataFrame(rlist)
        # Safely format any Timestamp columns
        for col in df_det.columns:
            if pd.api.types.is_datetime64_any_dtype(df_det[col]):
                df_det[col] = df_det[col].dt.strftime("%Y-%m-%d")
            elif df_det[col].dtype == object:
                df_det[col] = df_det[col].apply(
                    lambda v: v.strftime("%Y-%m-%d") if isinstance(v, pd.Timestamp) else v
                )
        path_det = os.path.join(output_dir, f"{rtype}_Details.csv")
        df_det.to_csv(path_det, index=False)
        output_files.append({
            "label": f"{rtype} Details",
            "desc":  f"Raw parsed fields for {rtype} returns.",
            "filename": f"{rtype}_Details.csv",
            "path": path_det,
        })

    if errors:
        df_err = pd.DataFrame(errors)
        path_err = os.path.join(output_dir, "Parsing_Errors.csv")
        df_err.to_csv(path_err, index=False)
        output_files.append({
            "label": "Parsing Errors",
            "desc":  "Files that failed parsing.",
            "filename": "Parsing_Errors.csv",
            "path": path_err,
        })

    log("3", f"Pipeline complete. {len(records)} records, {len(errors)} errors.")
    return output_files
