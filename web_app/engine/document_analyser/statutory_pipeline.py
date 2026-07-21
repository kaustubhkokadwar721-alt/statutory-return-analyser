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
from .gstr3b.reporting import ANALYSIS_COLUMNS as GSTR3B_ANALYSIS_COLUMNS
from .gstr3b.reporting import build_analysis_row as build_gstr3b_analysis_row
from .compliance_parsers import (
    parse_esic,
)
from .ui import write_sheet
from .shipping_bill import (
    parse_shipping_bill, sb_flat_row, sb_item_rows, sb_invoice_summary_rows,
)
from .audit import audit_record, classify_document, preflight_pdf
from .handler_registry import REGISTERED_HANDLERS, run_registered
from .ocr import OCRTextPdf, read_ocr_sidecar


# ── Return-type detection ─────────────────────────────────────────────────────

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
    audit_contexts = {}   # source file -> (preflight, classification), current run only
    raw_details = {k: [] for k in ("GSTR1", "ESIC", "PF", "PTRC", "TDS", "SB", "EBRC", "EWB")}
    gstr3b_analysis = []
    sb_items = []         # shipping-bill line items (separate ledger)
    sb_invoice_summaries = []

    for idx, fpath in enumerate(pdf_files, 1):
        fname = os.path.basename(fpath)
        log("2", f"Parsing {idx}/{len(pdf_files)}: {fname}")

        try:
            with pdfplumber.open(fpath) as pdf:
                if not pdf.pages:
                    raise ValueError("PDF has no pages")

                preflight = preflight_pdf(pdf)
                parse_pdf = pdf
                if preflight["needs_ocr"]:
                    ocr_pages = read_ocr_sidecar(fpath)
                    if not ocr_pages:
                        errors.append({
                            "File": fname, "Error_Type": "NeedsOCR",
                            "Message": "No usable text layer. This PDF needs local OCR before it can be parsed.",
                            "Action": "Enable local OCR and run again. No file is uploaded.",
                        })
                        continue
                    preflight = {
                        "pages": len(ocr_pages), "text": "\n".join(ocr_pages),
                        "page_text": ocr_pages, "needs_ocr": False,
                        "sparse_text": sum(map(len, ocr_pages)) / len(ocr_pages) < 80,
                        "ocr_used": True,
                    }
                    parse_pdf = OCRTextPdf(ocr_pages)

                classification = classify_document(preflight["text"])
                page_types = {
                    result["winner"]["return_type"]
                    for page_text in preflight["page_text"]
                    if (result := classify_document(page_text))["accepted"]
                }
                if len(page_types) > 1:
                    errors.append({
                        "File": fname, "Error_Type": "MixedDocument",
                        "Message": "More than one statutory document type was detected in this PDF.",
                        "Action": "Split the PDF into individual documents, then re-drop them.",
                    })
                    continue
                if not classification["accepted"]:
                    labels = ", ".join(candidate["return_type"] for candidate in classification["candidates"])
                    errors.append({
                        "File": fname,
                        "Error_Type": "AmbiguousType" if labels else "UnknownType",
                        "Message": "Could not classify this PDF confidently." + (f" Candidates: {labels}." if labels else ""),
                        "Action": "Review the PDF and process it only after its statutory type is clear.",
                    })
                    continue
                winner = classification["winner"]
                return_type, doc_kind = winner["return_type"], winner["doc_kind"]
                audit_contexts[fname] = (preflight, classification)

                if preflight["ocr_used"] and return_type == "SB":
                    errors.append({
                        "File": fname, "Error_Type": "ScannedShippingBill",
                        "Message": "Scanned Shipping Bills are skipped because OCR cannot reliably preserve their tables and claim values.",
                        "Action": "Use the original digital ICEGATE PDF. No figures were extracted from this scan.",
                    })
                    continue

                if preflight["ocr_used"] and return_type in {"GSTR1", "GSTR3B"}:
                    errors.append({
                        "File": fname, "Error_Type": "NeedsStructuredOCR",
                        "Message": "This scanned layout needs table-aware OCR before its proven parser can be used.",
                        "Action": "Keep the original PDF for review; this run did not extract a record.",
                    })
                    continue

                # ── GSTR-1 ────────────────────────────────────────────────
                if return_type == "GSTR1":
                    res = parse_gstr1(fpath, errors, pdf=pdf)
                    if not res:
                        continue
                    meta = res["Metadata"]
                    sec_totals = res["Section_Totals"]

                    chk_errs = run_sanity_checks_gstr1(sec_totals, meta)
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
                    analysis_row, missing_fields = build_gstr3b_analysis_row(res, fname)
                    flag_codes = [e["Check"] for e in chk_errs]
                    if missing_fields:
                        flag_codes.append("GSTR3B_FIELDS_MISSING")
                    flags = "; ".join(dict.fromkeys(flag_codes))
                    status = "Review" if flags else "OK"
                    analysis_row.update({
                        "Status": status,
                        "Validation Findings": "; ".join(e["Check"] for e in chk_errs),
                        "Missing Fields": "; ".join(missing_fields),
                    })
                    gstr3b_analysis.append(analysis_row)

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
                # ── ESIC ──────────────────────────────────────────────────
                elif return_type == "ESIC":
                    res = parse_esic(parse_pdf, fname)
                    res["SourceFile"] = fname
                    raw_details["ESIC"].append(res)

                # ── PF (Challan / ECR-Return / Arrears / Payment) ─────────
                elif return_type in REGISTERED_HANDLERS:
                    record, detail = run_registered(
                        return_type, parse_pdf, fname, doc_kind, _consolidated_row
                    )
                    records.append(record)
                    raw_details[return_type].append(detail)

                # ── PTRC (FORM_IIIB Return / MTR-6 Challan) ────────────────
                # ── TDS ───────────────────────────────────────────────────
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
                    for row in sb_invoice_summary_rows(doc):
                        row["SourceFile"] = fname
                        sb_invoice_summaries.append(row)

                # ── eBRC (DGFT bank-realisation certificate) ──────────────
                # ── e-Way Bill (GST movement of goods) ─────────────────────
                else:
                    scanned = preflight["needs_ocr"]
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

    # ── Audit gate: no ambiguous or incomplete record reaches OK ───────────────
    evidence_rows = []
    finding_rows = []
    audited_records = []
    for record in records:
        context = audit_contexts.get(record.get("SourceFile"))
        if context is None:
            audited_records.append(record)
            continue
        preflight, classification = context
        audited, findings, evidence = audit_record(record, classification, preflight)
        audited_records.append(audited)
        finding_rows.extend(findings)
        evidence_rows.extend(evidence)
    records = audited_records

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
                "PeriodDate", "MonthName", "Status", "Confidence", "ConfidenceGrade",
                "ProfileVersion", "OCRUsed", "ValidationFindings", "Flags", "PrimaryAmount",
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
        if finding_rows:
            write_sheet(xw, pd.DataFrame(finding_rows), "Validation_Findings", sort=False)
        if evidence_rows:
            write_sheet(xw, pd.DataFrame(evidence_rows), "Review_Evidence", sort=False)
        if gstr3b_analysis:
            df_gstr3b_analysis = pd.DataFrame(gstr3b_analysis).reindex(
                columns=GSTR3B_ANALYSIS_COLUMNS
            )
            df_gstr3b_analysis = df_gstr3b_analysis.sort_values(
                ["Return Period", "GSTIN", "Source File"], na_position="last"
            )
            write_sheet(xw, df_gstr3b_analysis, "GSTR 3B", sort=False)
        for rtype, rlist in raw_details.items():
            if rlist:
                write_sheet(xw, _detail_df(rlist), rtype, sort=False)
        if sb_items:
            write_sheet(xw, pd.DataFrame(sb_items), "SB_Items", sort=False)
        if sb_invoice_summaries:
            write_sheet(xw, pd.DataFrame(sb_invoice_summaries), "SB_Invoice_Summary", sort=False)
        if errors:
            write_sheet(xw, pd.DataFrame(errors), "Parsing_Errors", sort=False)
        # xlsxwriter needs at least one visible sheet
        if df_all.empty and not errors and not sb_items:
            xw.book.add_worksheet("Empty")

    reviews = []
    for record in records:
        if record.get("Status") == "OK":
            continue
        source = record.get("SourceFile")
        reviews.append({
            "SourceFile": source,
            "ReturnType": record.get("ReturnType"),
            "DocKind": record.get("DocKind"),
            "Status": record.get("Status"),
            "Confidence": record.get("Confidence"),
            "ConfidenceGrade": record.get("ConfidenceGrade"),
            "ProfileVersion": record.get("ProfileVersion"),
            "Findings": [row for row in finding_rows if row.get("SourceFile") == source],
            "Evidence": [row for row in evidence_rows if row.get("SourceFile") == source],
        })

    log("3", f"Pipeline complete. {len(records)} records, {len(errors)} errors.")
    return {
        "workbook":       path_xlsx,
        "workbook_name":  workbook_name,
        "consolidated":   _json_records(df_all),
        "dashboard":      _json_records(df_dash),
        "reconciliation": reconciliation,
        "errors":         errors,
        "reviews":        reviews,
    }
