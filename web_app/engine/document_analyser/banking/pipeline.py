"""Folder pipeline for bank statements and deposit documents."""

from __future__ import annotations

import os
from datetime import date

import pandas as pd
import pdfplumber

from ..ocr import read_ocr_sidecar
from ..ui import write_sheet
from .parser import (
    extract_citi_transactions,
    extract_deposits,
    extract_metadata,
    extract_table_transactions,
    infer_balances,
    validate_deposits,
    validate_statement,
)
from .profiles import classify_bank_document


def _json_records(frame: pd.DataFrame) -> list[dict]:
    if frame.empty:
        return []
    return frame.where(pd.notna(frame), None).to_dict("records")


def _fy(period: str | None) -> str:
    if not period:
        return "Unknown"
    try:
        parsed = date.fromisoformat(period)
    except ValueError:
        return "Unknown"
    start = parsed.year if parsed.month >= 4 else parsed.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def _finding(source: str, return_type: str, code: str, severity: str, message: str) -> dict:
    return {
        "SourceFile": source,
        "ReturnType": return_type,
        "Code": code,
        "Severity": severity,
        "AffectedFields": "*",
        "Message": message,
    }


def _error(source: str, error_type: str, message: str, action: str = "Review the source document.") -> dict:
    return {"File": source, "Error_Type": error_type, "Message": message, "Action": action}


def run_bank_pipeline(input_dir: str, output_dir: str, progress_cb=None) -> dict:
    """Extract supported bank documents locally and produce one auditable workbook."""
    os.makedirs(output_dir, exist_ok=True)
    files = sorted(name for name in os.listdir(input_dir) if name.lower().endswith(".pdf"))
    records = []
    transactions = []
    deposits = []
    reconciliation = []
    finding_rows = []
    evidence_rows = []
    errors = []

    def log(step: str, detail: str) -> None:
        if progress_cb:
            progress_cb(step, detail)

    for index, filename in enumerate(files, start=1):
        source_path = os.path.join(input_dir, filename)
        log("BANK", f"{index}/{len(files)} {filename}")
        try:
            with pdfplumber.open(source_path) as pdf:
                native_page_text = [(page.extract_text() or "").strip() for page in pdf.pages]
                ocr_page_text = read_ocr_sidecar(source_path)
                ocr_used = bool(ocr_page_text) and sum(map(len, native_page_text)) < 20
                page_text = ocr_page_text if ocr_used else native_page_text
                text = "\n".join(page_text)
                if not text.strip():
                    errors.append(_error(
                        filename,
                        "NeedsOCR",
                        "This PDF has no usable text layer.",
                        "Turn on OCR Scanned PDFs and run again.",
                    ))
                    continue

                classification = classify_bank_document(text, page_text)
                if classification["mixed"]:
                    errors.append(_error(
                        filename,
                        "MixedDocument",
                        "This PDF contains statements from more than one bank.",
                        "Split it into one bank account per PDF before processing.",
                    ))
                    continue
                if classification["unsupported"] and not classification["accepted"]:
                    _, unsupported_type, _ = classification["unsupported"]
                    errors.append(_error(
                        filename,
                        "UnsupportedDocument",
                        f"This is a {unsupported_type}, not a supported Indian bank or deposit statement.",
                        "Use a matching statement parser.",
                    ))
                    continue
                if not classification["accepted"]:
                    errors.append(_error(
                        filename,
                        "UnknownBankLayout",
                        "The bank or statement layout could not be identified safely.",
                        "Review the file and add a versioned layout profile.",
                    ))
                    continue

                winner = classification["winner"]
                profile = winner["profile"]
                metadata = extract_metadata(text, profile)
                source_findings = []
                source_evidence = []

                if profile.parser == "deposit_table":
                    source_deposits, source_evidence = extract_deposits(pdf, profile) if not ocr_used else ([], [])
                    source_findings = validate_deposits(source_deposits)
                    if ocr_used:
                        source_findings.append({
                            "Code": "STRUCTURED_OCR_REQUIRED",
                            "Severity": "Review",
                            "Message": "The scanned deposit table needs coordinate-aware local OCR.",
                        })
                    for row in source_deposits:
                        row.update({
                            "SourceFile": filename,
                            "Bank": profile.bank,
                            "AccountName": metadata["AccountName"],
                            "AccountNumber": metadata["AccountNumber"],
                            "Currency": metadata["Currency"],
                            "ProfileVersion": profile.version,
                        })
                    deposits.extend(source_deposits)
                    primary_amount = sum(row.get("Principal") or 0 for row in source_deposits)
                    period_to = max((row.get("MaturityDate") for row in source_deposits if row.get("MaturityDate")), default=None)
                    return_type = "FD"
                    doc_kind = "Certificate" if "Certificate" in profile.document_type else "Statement"
                    row_count = len(source_deposits)
                else:
                    if ocr_used:
                        source_transactions, source_evidence = [], []
                    elif profile.parser == "key_value":
                        source_transactions, source_evidence = extract_citi_transactions(page_text)
                    else:
                        source_transactions, source_evidence = extract_table_transactions(pdf, profile)
                    infer_balances(metadata, source_transactions)
                    source_findings, source_reconciliation = validate_statement(metadata, source_transactions)
                    if ocr_used:
                        source_findings.append({
                            "Code": "STRUCTURED_OCR_REQUIRED",
                            "Severity": "Review",
                            "Message": "The scanned transaction table needs coordinate-aware local OCR.",
                        })
                    source_reconciliation.update({
                        "SourceFile": filename,
                        "Bank": profile.bank,
                        "AccountNumber": metadata["AccountNumber"],
                    })
                    reconciliation.append(source_reconciliation)
                    for row in source_transactions:
                        row.update({
                            "SourceFile": filename,
                            "Bank": profile.bank,
                            "AccountName": metadata["AccountName"],
                            "AccountNumber": metadata["AccountNumber"],
                            "AccountType": metadata["AccountType"],
                            "Currency": metadata["Currency"],
                            "ProfileVersion": profile.version,
                        })
                    transactions.extend(source_transactions)
                    primary_amount = metadata.get("ClosingBalance") or 0
                    period_to = metadata.get("PeriodTo")
                    return_type = "BANK"
                    doc_kind = "Statement"
                    row_count = len(source_transactions)

                required_metadata = {
                    "AccountNumber": "account number",
                    "AccountName": "account holder name",
                    "Currency": "currency",
                    "PeriodFrom": "period start",
                    "PeriodTo": "period end",
                }
                for field, label in required_metadata.items():
                    value = metadata.get(field)
                    source_evidence.append({
                        "Field": field,
                        "Value": value,
                        "RawValue": value,
                        "Page": None,
                        "Method": "profile metadata",
                        "Anchor": "; ".join(winner["markers"]),
                    })
                    if value in (None, ""):
                        source_findings.append({
                            "Code": f"{field.upper()}_MISSING",
                            "Severity": "Review",
                            "Message": f"The {label} was not extracted.",
                        })
                if ocr_used:
                    source_findings.append({
                        "Code": "OCR_TEXT",
                        "Severity": "Review",
                        "Message": "Local OCR was used; verify extracted fields against the PDF.",
                    })

                confidence = winner["score"] + (20 if not source_findings else 0)
                confidence -= 20 if ocr_used else 0
                confidence -= min(60, 15 * len(source_findings))
                confidence = max(0, min(100, confidence))
                status = "Review" if source_findings else "OK"
                codes = [item["Code"] for item in source_findings]
                record = {
                    "ReturnType": return_type,
                    "DocKind": doc_kind,
                    "EntityID": metadata["AccountNumber"],
                    "EntityName": metadata["AccountName"],
                    "FY": _fy(period_to),
                    "PeriodDate": period_to,
                    "MonthName": "",
                    "MonthIndex": 0,
                    "Status": status,
                    "Confidence": confidence,
                    "ConfidenceGrade": "High" if confidence >= 90 else ("Medium" if confidence >= 70 else "Low"),
                    "ProfileVersion": profile.version,
                    "OCRUsed": ocr_used,
                    "ValidationFindings": "; ".join(codes),
                    "Flags": "; ".join(codes),
                    "PrimaryAmount": primary_amount,
                    "DocRef": metadata["AccountNumber"],
                    "FilingDate": None,
                    "SourceFile": filename,
                    "Bank": profile.bank,
                    "DocumentType": profile.document_type,
                    "AccountType": metadata["AccountType"],
                    "Currency": metadata["Currency"],
                    "PeriodFrom": metadata["PeriodFrom"],
                    "PeriodTo": period_to,
                    "OpeningBalance": metadata["OpeningBalance"],
                    "ClosingBalance": metadata["ClosingBalance"],
                    "RowsExtracted": row_count,
                }
                records.append(record)

                for item in source_findings:
                    finding_rows.append(_finding(
                        filename,
                        return_type,
                        item["Code"],
                        item["Severity"],
                        item["Message"],
                    ))
                for item in source_evidence:
                    evidence_rows.append({
                        "SourceFile": filename,
                        "ReturnType": return_type,
                        **item,
                        "ProfileVersion": profile.version,
                    })
        except Exception as exc:
            exception_name = type(exc).__name__
            error_type = "EncryptedPDF" if (
                "password" in str(exc).lower() or exception_name == "PdfminerException"
            ) else exception_name
            action = "Remove the PDF password locally and try again." if error_type == "EncryptedPDF" else "Review the file."
            errors.append(_error(filename, error_type, str(exc)[:300], action))

    df_records = pd.DataFrame(records)
    df_transactions = pd.DataFrame(transactions)
    df_deposits = pd.DataFrame(deposits)
    df_reconciliation = pd.DataFrame(reconciliation)
    df_findings = pd.DataFrame(finding_rows)
    df_evidence = pd.DataFrame(evidence_rows)
    df_errors = pd.DataFrame(errors)
    df_dashboard = pd.DataFrame()
    if not df_records.empty:
        df_dashboard = df_records.groupby(["ReturnType", "DocKind", "FY"]).agg(
            Records=("Status", "count"),
            OK=("Status", lambda values: (values == "OK").sum()),
            Review=("Status", lambda values: (values == "Review").sum()),
            Errors=("Status", lambda values: (values == "Error").sum()),
            Periods=("PeriodDate", "nunique"),
            TotalAmount=("PrimaryAmount", "sum"),
        ).reset_index()

    workbook_name = "Bank_Statements.xlsx"
    workbook_path = os.path.join(output_dir, workbook_name)
    with pd.ExcelWriter(workbook_path, engine="xlsxwriter") as writer:
        write_sheet(writer, df_records, "Bank_Summary", sort=False)
        write_sheet(writer, df_transactions, "Transactions", sort=False)
        write_sheet(writer, df_deposits, "Fixed_Deposits", sort=False)
        write_sheet(writer, df_reconciliation, "Reconciliation", sort=False)
        write_sheet(writer, df_findings, "Validation_Findings", sort=False)
        write_sheet(writer, df_evidence, "Review_Evidence", sort=False)
        write_sheet(writer, df_errors, "Parsing_Errors", sort=False)
        if all(frame.empty for frame in (
            df_records,
            df_transactions,
            df_deposits,
            df_reconciliation,
            df_findings,
            df_evidence,
            df_errors,
        )):
            writer.book.add_worksheet("Empty")

    reviews = []
    for record in records:
        if record["Status"] == "OK":
            continue
        source = record["SourceFile"]
        reviews.append({
            "SourceFile": source,
            "ReturnType": record["ReturnType"],
            "DocKind": record["DocKind"],
            "Status": record["Status"],
            "Confidence": record["Confidence"],
            "ConfidenceGrade": record["ConfidenceGrade"],
            "ProfileVersion": record["ProfileVersion"],
            "Findings": [item for item in finding_rows if item["SourceFile"] == source],
            "Evidence": [item for item in evidence_rows if item["SourceFile"] == source],
        })

    log("BANK", f"Complete: {len(records)} documents, {len(errors)} not parsed")
    return {
        "workbook": workbook_path,
        "workbook_name": workbook_name,
        "consolidated": _json_records(df_records),
        "dashboard": _json_records(df_dashboard),
        "reconciliation": _json_records(df_reconciliation),
        "errors": errors,
        "reviews": reviews,
    }
