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
from .compliance_parsers import (
    parse_esic, parse_pf, parse_pf_ecr, parse_pf_arrears, parse_pf_payment,
    parse_ptrc, parse_ptrc_challan, parse_tds, parse_ebrc, parse_ewb,
)
from .ui import write_sheet
from .shipping_bill import parse_shipping_bill, sb_flat_row, sb_item_rows


# ── Return-type detection ─────────────────────────────────────────────────────

def detect_document(text: str):
    """Classify a PDF as (head, kind).

    head ∈ {SB, GSTR1, GSTR3B, PF, ESIC, PTRC, TDS, Unknown}
    kind ∈ {Return, Challan, Payment, Arrears, Unknown}

    A statutory head carries several document kinds that serve different
    purposes: the Return (the filing), the Challan (the payment demand), the
    Payment receipt (proof of payment), and Arrears (supplementary). Detection
    must survive layout quirks — notably EPFO prints "EMPLOYEE'S PROVIDENT FUND"
    (singular) on returns/receipts but "EMPLOYEES' PROVIDENT FUND" (plural) on
    challans, so we match the apostrophe-agnostic "PROVIDENT FUND ORGANISATION".
    """
    t = text.upper()

    # Customs export documents — ICEGATE shipping bill
    if "INDIAN CUSTOMS EDI SYSTEM" in t or "SHIPPING BILL SUMMARY" in t:
        return "SB", "Return"

    # eBRC — DGFT bank-realisation certificate (export payment proof)
    if "STATEMENT OF BANK REALISATION" in t or ("DIRECTORATE GENERAL OF FOREIGN TRADE" in t and "REALISATION" in t):
        return "EBRC", "Return"

    # e-Way Bill — NIC GST movement-of-goods
    if "E-WAY BILL SYSTEM" in t or "E-WAY BILL NO" in t:
        return "EWB", "Return"

    # GSTR forms — very specific markers
    if "GSTR-3B" in t or "GSTR3B" in t:
        return "GSTR3B", "Return"
    if "GSTR-1" in t or "GSTR1" in t:
        return "GSTR1", "Return"

    # PF / EPFO — apostrophe-agnostic; resolve the kind from the doc's own header
    is_pf = (
        "PROVIDENT FUND ORGANISATION" in t
        or "COMBINED CHALLAN OF A/C" in t
        or ("PAYMENT CONFIRMATION RECEIPT" in t and "ESTABLISHMENT ID" in t)
    )
    if is_pf:
        if "COMBINED CHALLAN OF A/C" in t:
            return "PF", "Challan"
        if "PAYMENT CONFIRMATION RECEIPT" in t:
            return "PF", "Payment"
        if "ARREAR" in t and "ELECTRONIC CHALLAN CUM RETURN" not in t:
            return "PF", "Arrears"
        if "ELECTRONIC CHALLAN CUM RETURN" in t or "(ECR)" in t:
            return "PF", "Return"
        return "PF", "Challan"

    # ESIC — unique label (the ESIC doc is itself a challan/payment)
    if "CHALLAN PERIOD:" in t and ("EMPLOYEE'S STATE INSURANCE" in t or "ESIC" in t):
        return "ESIC", "Challan"

    # PTRC — Maharashtra profession tax: FORM_IIIB return vs MTR-6 challan
    is_ptrc = (
        "FORM_IIIB" in t or "PROFESSION TAX" in t or "PTRC" in t
        or ("MTR FORM" in t and "00280012" in t)
    )
    if is_ptrc:
        if "FORM_IIIB" in t or "ELECTRONIC RETURN UNDER" in t:
            return "PTRC", "Return"
        if "MTR FORM" in t or "00280012" in t:
            return "PTRC", "Challan"
        return "PTRC", "Return"

    # TDS — Income Tax challan (ITNS 280/281/282 etc.); the doc is a challan
    if ("INCOME TAX DEPARTMENT" in t or "CHALLAN RECEIPT" in t) and (
        "TAN" in t or "DATE OF DEPOSIT" in t or "NATURE OF PAYMENT" in t
    ):
        return "TDS", "Challan"

    return "Unknown", "Unknown"


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


def _consolidated_row(res: dict, fname: str, flags_list: list, status: str | None = None) -> dict:
    """Build one unified ledger row from a parser result dict.

    All compliance parsers return the same core keys (ReturnType, DocKind,
    EntityID, EntityName, FY, PeriodDate, PrimaryAmount, DocRef, FilingDate);
    this collapses them onto the consolidated contract so every head/kind lands
    on one schema.
    """
    pd_date = res.get("PeriodDate")
    is_nat = pd_date is None
    try:
        is_nat = is_nat or pd.isna(pd_date)
    except Exception:
        pass
    if status is None:
        status = "Review" if flags_list else "OK"
    return {
        "ReturnType":    res.get("ReturnType"),
        "DocKind":       res.get("DocKind", "Return"),
        "EntityID":      res.get("EntityID", ""),
        "EntityName":    res.get("EntityName", ""),
        "FY":            res.get("FY", "Unknown"),
        "PeriodDate":    _fmt_date(pd_date) if not is_nat else None,
        "MonthName":     pd.Timestamp(pd_date).strftime("%B") if not is_nat else "Unknown",
        "MonthIndex":    _month_idx(pd_date) if not is_nat else 0,
        "Status":        status,
        "Flags":         "; ".join(flags_list),
        "PrimaryAmount": res.get("PrimaryAmount", 0) or 0,
        "DocRef":        res.get("DocRef", ""),
        "FilingDate":    res.get("FilingDate", None),
        "SourceFile":    fname,
    }


# ── Reconciliation ────────────────────────────────────────────────────────────
# Per statutory head, which DocKind is the "demand" (obligation) and which is the
# "settlement" (payment). PF: the Combined Challan is the demand, the Payment
# receipt settles it (the ECR is a sub-component, not the full remittance).
# PTRC: the FORM_IIIB Return is the demand, the MTR-6 Challan settles it.
RECON_ROLES = {
    "PF":   ("Challan", "Payment"),
    "PTRC": ("Return",  "Challan"),
}


def _reconcile(records: list) -> list:
    """Tie out each period's declared liability against what settled it.

    Groups by (head, entity, period) for heads that carry more than one DocKind,
    compares demand vs settlement, and folds a flag back onto the member records
    so a mismatch is visible in the ledger too. Returns the reconciliation rows.
    """
    df = pd.DataFrame(records)
    if df.empty or "DocKind" not in df.columns:
        return []
    nkinds = df.groupby("ReturnType")["DocKind"].nunique()
    multi = set(nkinds[nkinds > 1].index)
    if not multi:
        return []

    sub = df[df["ReturnType"].isin(multi)].copy()
    # A document whose period could not be parsed must get its own bucket — never
    # pool it with other undated docs, or we'd fabricate a cross-period mismatch.
    sub["_gkey"] = sub["PeriodDate"].where(
        sub["PeriodDate"].notna(), "~undated~" + sub["SourceFile"].astype(str))

    recon = []
    for (head, ent, gkey), g in sub.groupby(["ReturnType", "EntityID", "_gkey"], dropna=False):
        def amt(kind):
            return float(g.loc[g["DocKind"] == kind, "PrimaryAmount"].fillna(0).sum())
        ret, chal, pay, arr = amt("Return"), amt("Challan"), amt("Payment"), amt("Arrears")
        demand_kind, settle_kind = RECON_ROLES.get(head, ("Return", "Challan"))
        demand     = {"Return": ret, "Challan": chal, "Payment": pay}[demand_kind]
        settlement = {"Return": ret, "Challan": chal, "Payment": pay}[settle_kind]
        if demand <= 0 and settlement <= 0:
            continue
        delta = round(settlement - demand, 2)
        tol   = max(1.0, 0.01 * demand)
        if demand > 0 and settlement > 0:
            status = "Matched" if abs(delta) <= tol else "Mismatch"
        elif demand > 0:
            status = "Unpaid?"
        else:
            status = "No demand doc"
        # Ledger tag is a period-level marker, NOT a per-row delta: when a period
        # has (say) two challans against one return, each challan may be fine on
        # its own — the discrepancy is the period's, so don't stamp Δ on each row.
        # The exact Δ and doc count live in the Reconciliation sheet.
        tag = {"Matched": None, "Mismatch": "UNRECONCILED",
               "Unpaid?": "UNPAID?", "No demand doc": "NO DEMAND"}[status]

        period_out = None if str(gkey).startswith("~undated~") else gkey
        recon.append({
            "ReturnType": head, "EntityID": ent, "PeriodDate": period_out,
            "Docs": int(len(g)),
            "Declared": round(demand, 2), "Return": round(ret, 2), "Challan": round(chal, 2),
            "Payment": round(pay, 2), "Arrears": round(arr, 2),
            "Delta": delta, "Status": status,
        })
        if tag:  # write the flag onto exactly this group's documents (SourceFile is unique per row)
            files = set(g["SourceFile"])
            for rec in records:
                if rec.get("SourceFile") in files:
                    rec["Flags"] = f'{rec["Flags"]}; {tag}'.strip("; ") if rec.get("Flags") else tag
                    if rec.get("Status") == "OK":
                        rec["Status"] = "Review"
    return recon


def _json_records(df) -> list:
    """DataFrame → JSON-clean list of dicts (Timestamps→ISO strings, NaN→None)."""
    if df is None or df.empty:
        return []
    clean = df.copy()
    for c in clean.columns:
        if pd.api.types.is_datetime64_any_dtype(clean[c]):
            clean[c] = clean[c].dt.strftime("%Y-%m-%d")
    clean = clean.astype(object).where(pd.notna(clean), None)
    return clean.to_dict("records")


def _detail_df(rlist: list):
    """Build a per-head detail DataFrame with any Timestamp columns stringified."""
    df = pd.DataFrame(rlist)
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
        elif df[col].dtype == object:
            df[col] = df[col].apply(lambda v: v.strftime("%Y-%m-%d") if isinstance(v, pd.Timestamp) else v)
    return df


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
    raw_details = {k: [] for k in ("GSTR1", "GSTR3B", "ESIC", "PF", "PTRC", "TDS", "SB", "EBRC", "EWB")}
    sb_items = []         # shipping-bill line items (separate ledger)

    for idx, fpath in enumerate(pdf_files, 1):
        fname = os.path.basename(fpath)
        log("2", f"Parsing {idx}/{len(pdf_files)}: {fname}")

        try:
            with pdfplumber.open(fpath) as pdf:
                if not pdf.pages:
                    raise ValueError("PDF has no pages")

                first_text = pdf.pages[0].extract_text() or ""
                return_type, doc_kind = detect_document(first_text)

                # If first page gave nothing, try full text
                if return_type == "Unknown":
                    full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
                    return_type, doc_kind = detect_document(full_text)

                # ── GSTR-1 ────────────────────────────────────────────────
                if return_type == "GSTR1":
                    res = parse_gstr1(fpath, errors, pdf=pdf)
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
                        "DocKind":       "Return",
                        "EntityID":      meta.get("GSTIN", "Unknown"),
                        "EntityName":    meta.get("Legal_Name", "Unknown"),
                        "FY":            meta.get("FY", "Unknown"),
                        "PeriodDate":    _fmt_date(pd_date),
                        "MonthName":     pd_date.strftime("%B") if pd_date else "Unknown",
                        "MonthIndex":    _month_idx(pd_date),
                        "Status":        status,
                        "Flags":         flags,
                        "PrimaryAmount": primary_amt,
                        "DocRef":        meta.get("ARN", ""),
                        "FilingDate":    meta.get("Date_of_ARN", None),
                        "SourceFile":    fname,
                    })
                    for _, row in sec_totals.iterrows():
                        dr = {"SourceFile": fname}
                        dr.update(meta)
                        dr.update(row.to_dict())
                        raw_details["GSTR1"].append(dr)

                # ── GSTR-3B ───────────────────────────────────────────────
                elif return_type == "GSTR3B":
                    res = parse_complete_gstr3b(fpath, errors, pdf=pdf)
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
                        "DocKind":       "Return",
                        "EntityID":      gstin,
                        "EntityName":    meta.get("Legal_Name", "Unknown"),
                        "FY":            meta.get("Year", "Unknown"),
                        "PeriodDate":    _fmt_date(pd_date),
                        "MonthName":     pd_date.strftime("%B") if pd_date else "Unknown",
                        "MonthIndex":    _month_idx(pd_date),
                        "Status":        status,
                        "Flags":         flags,
                        "PrimaryAmount": primary_amt,
                        "DocRef":        meta.get("ARN", ""),
                        "FilingDate":    meta.get("Date_of_ARN", None),
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

                # ── PF (Challan / ECR-Return / Arrears / Payment) ─────────
                elif return_type == "PF":
                    if doc_kind == "Return":
                        res = parse_pf_ecr(pdf, fname)
                    elif doc_kind == "Arrears":
                        res = parse_pf_arrears(pdf, fname)
                    elif doc_kind == "Payment":
                        res = parse_pf_payment(pdf, fname)
                    else:
                        res = parse_pf(pdf, fname)      # Combined Challan
                    res["SourceFile"] = fname

                    flags_list = []
                    if res["EntityID"] in ("Unknown", ""):
                        flags_list.append("ENTITY?")
                    if res.get("PeriodDate") is None:
                        flags_list.append("PERIOD?")
                    if not res.get("PrimaryAmount"):
                        flags_list.append("AMT?")
                    # challan-only internal check: employee vs employer EPF symmetry
                    if res.get("DocKind") == "Challan":
                        ee = res.get("Employee_EPF_AC01", 0)
                        er = res.get("Employer_EPF_AC01", 0) + res.get("Employer_EPS_AC10", 0)
                        if er > 0 and abs(ee - er) / max(er, 1) > 0.05:
                            flags_list.append("EE<>ER?")

                    records.append(_consolidated_row(res, fname, flags_list))
                    raw_details["PF"].append(res)

                # ── PTRC (FORM_IIIB Return / MTR-6 Challan) ────────────────
                elif return_type == "PTRC":
                    res = parse_ptrc_challan(pdf, fname) if doc_kind == "Challan" else parse_ptrc(pdf, fname)
                    res["SourceFile"] = fname

                    flags_list = []
                    if res["EntityID"] in ("Unknown", ""):
                        flags_list.append("TIN?")
                    if res.get("PeriodDate") is None:
                        flags_list.append("PERIOD?")
                    if not res.get("PrimaryAmount"):
                        flags_list.append("AMT?")

                    records.append(_consolidated_row(res, fname, flags_list))
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
                    if res.get("PeriodEstimated"):
                        flags_list.append("PERIOD_EST")

                    flags  = "; ".join(flags_list)
                    status = "Review" if flags_list else "OK"
                    pd_date = res["PeriodDate"]

                    records.append({
                        "ReturnType":    "TDS",
                        "DocKind":       "Challan",
                        "EntityID":      res["EntityID"],
                        "EntityName":    res["EntityName"],
                        "FY":            res["FY"],
                        "PeriodDate":    _fmt_date(pd_date),
                        "MonthName":     pd.Timestamp(pd_date).strftime("%B") if pd_date else "Unknown",
                        "MonthIndex":    _month_idx(pd_date),
                        "Status":        status,
                        "Flags":         flags,
                        "PrimaryAmount": res.get("Total Amount Paid", 0),
                        "DocRef":        res.get("DocRef", ""),
                        "FilingDate":    res.get("FilingDate", None),
                        "SourceFile":    fname,
                    })
                    raw_details["TDS"].append(res)

                # ── Shipping Bill (ICEGATE) ───────────────────────────────
                elif return_type == "SB":
                    doc = parse_shipping_bill(pdf, fname)

                    checks = doc.get("validation", {}).get("checks", [])
                    failed = [c["check"] for c in checks if c["ok"] is False]
                    flags_list = list(failed)
                    if any(w.startswith("missing core fields")
                           for w in doc.get("warnings", [])):
                        flags_list.append("FIELDS?")
                    flags  = "; ".join(flags_list)
                    status = "Review" if flags_list else "OK"

                    pd_date = None
                    try:
                        pd_date = pd.to_datetime(doc.get("sb_date"),
                                                 format="%d-%b-%y")
                    except Exception:
                        pass
                    fy = "Unknown"
                    if pd_date is not None:
                        y = pd_date.year if pd_date.month >= 4 else pd_date.year - 1
                        fy = f"{y}-{str(y + 1)[-2:]}"

                    leo = ((doc.get("process") or {}).get("leo") or {})
                    records.append({
                        "ReturnType":    "SB",
                        "DocKind":       "Return",
                        "EntityID":      doc.get("iec", "Unknown"),
                        "EntityName":    (doc.get("exporter") or {}).get("name", "Unknown"),
                        "FY":            fy,
                        "PeriodDate":    _fmt_date(pd_date),
                        "MonthName":     pd_date.strftime("%B") if pd_date is not None else "Unknown",
                        "MonthIndex":    _month_idx(pd_date),
                        "Status":        status,
                        "Flags":         flags,
                        "PrimaryAmount": doc.get("fob_value_inr") or 0.0,
                        "DocRef":        doc.get("sb_no", ""),
                        "FilingDate":    leo.get("date"),
                        "SourceFile":    fname,
                    })
                    flat = sb_flat_row(doc)
                    flat["SourceFile"] = fname
                    raw_details["SB"].append(flat)
                    for row in sb_item_rows(doc):
                        row["SourceFile"] = fname
                        sb_items.append(row)

                # ── eBRC (DGFT bank-realisation certificate) ──────────────
                elif return_type == "EBRC":
                    res = parse_ebrc(pdf, fname)
                    res["SourceFile"] = fname
                    flags_list = []
                    if res["EntityID"] in ("Unknown", ""):
                        flags_list.append("ENTITY?")
                    if res.get("PeriodDate") is None:
                        flags_list.append("PERIOD?")
                    if not res.get("PrimaryAmount"):
                        flags_list.append("AMT?")
                    records.append(_consolidated_row(res, fname, flags_list))
                    raw_details["EBRC"].append(res)

                # ── e-Way Bill (GST movement of goods) ─────────────────────
                elif return_type == "EWB":
                    res = parse_ewb(pdf, fname)
                    res["SourceFile"] = fname
                    flags_list = []
                    if res["EntityID"] in ("Unknown", ""):
                        flags_list.append("ENTITY?")
                    if res.get("PeriodDate") is None:
                        flags_list.append("PERIOD?")
                    if not res.get("PrimaryAmount"):
                        flags_list.append("AMT?")
                    records.append(_consolidated_row(res, fname, flags_list))
                    raw_details["EWB"].append(res)

                else:
                    scanned = not first_text.strip()
                    errors.append({
                        "File":       fname,
                        "Error_Type": "NoTextLayer" if scanned else "UnknownType",
                        "Message":    ("No text layer — this looks like a scanned "
                                       "document; OCR it first (e.g. Adobe / "
                                       "ilovepdf OCR) and re-drop.") if scanned
                                      else "Could not identify return type from PDF text.",
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
                "DocKind":       "Challan",
                "EntityID":      row.get("EntityID", ""),
                "EntityName":    row.get("EntityName", ""),
                "FY":            row["FY"],
                "PeriodDate":    _fmt_date(pd_date),
                "MonthName":     pd.Timestamp(pd_date).strftime("%B") if not is_nat else "Unknown",
                "MonthIndex":    _month_idx(pd_date) if not is_nat else 0,
                "Status":        status,
                "Flags":         flags,
                "PrimaryAmount": row.get("Amount", 0),
                "DocRef":        row.get("DocRef", ""),
                "FilingDate":    row.get("FilingDate", None),
                "SourceFile":    row["SourceFile"],
            })
        raw_details["ESIC"] = df_esic.to_dict("records")

    # ── Reconcile declared vs paid (mutates records' Flags/Status on mismatch) ──
    reconciliation = _reconcile(records)

    # ── Build the consolidated ledger ──
    df_all = pd.DataFrame(records)
    if not df_all.empty:
        # Normalise FilingDate to ISO across all heads (GSTR uses DD/MM/YYYY)
        if "FilingDate" in df_all.columns:
            df_all["FilingDate"] = pd.to_datetime(
                df_all["FilingDate"], format="mixed", dayfirst=True, errors="coerce"
            ).dt.strftime("%Y-%m-%d")
        # Column order: identity first, then status/amounts
        lead = ["ReturnType", "DocKind", "EntityID", "EntityName", "FY",
                "PeriodDate", "MonthName", "Status", "Flags", "PrimaryAmount",
                "DocRef", "FilingDate", "SourceFile"]
        df_all = df_all[[c for c in lead if c in df_all.columns]
                        + [c for c in df_all.columns if c not in lead]]
        df_all = df_all.sort_values(["ReturnType", "DocKind", "FY", "MonthIndex", "EntityID"])

    # ── Dashboard: grouped by head × DocKind × FY (kinds counted separately) ──
    df_dash = pd.DataFrame()
    if not df_all.empty:
        df_dash = df_all.groupby(["ReturnType", "DocKind", "FY"]).agg(
            Records          = ("Status", "count"),
            OK               = ("Status", lambda s: (s == "OK").sum()),
            Review           = ("Status", lambda s: (s == "Review").sum()),
            Errors           = ("Status", lambda s: (s == "Error").sum()),
            Periods          = ("PeriodDate", "nunique"),
            TotalAmount      = ("PrimaryAmount", "sum"),
        ).reset_index()

    # ── Write ONE Excel workbook (all sheets) — the sole deliverable ──
    workbook_name = "Statutory_Returns.xlsx"
    path_xlsx = os.path.join(output_dir, workbook_name)
    with pd.ExcelWriter(path_xlsx, engine="xlsxwriter") as xw:
        if not df_all.empty:
            write_sheet(xw, df_all, "Consolidated", sort=False)
        if not df_dash.empty:
            write_sheet(xw, df_dash, "Dashboard", sort=False)
        if reconciliation:
            write_sheet(xw, pd.DataFrame(reconciliation), "Reconciliation", sort=False)
        for rtype, rlist in raw_details.items():
            if rlist:
                write_sheet(xw, _detail_df(rlist), rtype, sort=False)
        if sb_items:
            write_sheet(xw, pd.DataFrame(sb_items), "SB_Items", sort=False)
        if errors:
            write_sheet(xw, pd.DataFrame(errors), "Parsing_Errors", sort=False)
        # xlsxwriter needs at least one visible sheet
        if df_all.empty and not errors and not sb_items:
            xw.book.add_worksheet("Empty")

    log("3", f"Pipeline complete. {len(records)} records, {len(errors)} errors.")
    return {
        "workbook":       path_xlsx,
        "workbook_name":  workbook_name,
        "consolidated":   _json_records(df_all),
        "dashboard":      _json_records(df_dash),
        "reconciliation": reconciliation,
        "errors":         errors,
    }
