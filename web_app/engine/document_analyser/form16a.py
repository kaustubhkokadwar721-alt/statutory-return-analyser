"""Native-text parser for TRACES Form 16A TDS certificates.

Document class: ruled, digitally generated PDF with an embedded text layer.
Detection assumptions: the certificate identifies itself as FORM NO. 16A and
contains the standard payment, quarterly-summary, and deposit tables.  OCR is
intentionally unsupported because it cannot preserve the financial table grid.

Validation checks reconcile printed totals to line rows, the quarterly summary
to deposit details, verification amounts to the summary, serial continuity,
PAN/TAN formats, and payment dates to the stated certificate period.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

import pandas as pd


_PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
_TAN_RE = re.compile(r"^[A-Z]{4}\d{5}[A-Z]$")
_DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d/%b/%Y", "%d %b %Y")


def _cell(value) -> str:
    if value is None:
        return ""
    return re.sub(r"[ \t]+", " ", str(value).replace("\r", "")).strip()


def _values(row) -> list[str]:
    return [value for cell in row if (value := _cell(cell))]


def _line(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _amount(value) -> Decimal | None:
    text = _line(str(value or ""))
    match = re.search(r"(?<![A-Za-z0-9])\(?-?[\d,]+(?:\.\d+)?\)?", text)
    if not match:
        return None
    raw = match.group(0).replace(",", "")
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _float(value: Decimal | None) -> float:
    return float(value or Decimal("0"))


def _date(value: str):
    text = _line(value)
    match = re.search(r"\d{1,2}[-/ ](?:[A-Za-z]{3}|\d{1,2})[-/ ]\d{4}", text)
    candidate = match.group(0) if match else text
    for fmt in _DATE_FORMATS:
        try:
            return pd.to_datetime(candidate, format=fmt)
        except (TypeError, ValueError):
            pass
    return None


def _iso(value) -> str | None:
    return value.strftime("%Y-%m-%d") if value is not None else None


def _name_address(value: str) -> tuple[str, str]:
    lines = [_line(part) for part in (value or "").splitlines() if _line(part)]
    return (lines[0] if lines else "Unknown", " | ".join(lines))


def _is_serial(value: str) -> bool:
    return bool(re.fullmatch(r"\d+", _line(value)))


def _serials_contiguous(rows: list[dict], field: str) -> bool:
    serials = [int(row[field]) for row in rows]
    return bool(serials) and serials == list(range(1, len(serials) + 1))


def _check(name: str, expected, actual, *, tolerance: Decimal = Decimal("0.01")) -> dict:
    if isinstance(expected, Decimal) or isinstance(actual, Decimal):
        expected_value = expected if isinstance(expected, Decimal) else Decimal(str(expected))
        actual_value = actual if isinstance(actual, Decimal) else Decimal(str(actual))
        difference = actual_value - expected_value
        ok = abs(difference) <= tolerance
        return {
            "Check": name, "Expected": float(expected_value), "Actual": float(actual_value),
            "Difference": float(difference), "Status": "pass" if ok else "fail",
        }
    ok = expected == actual
    return {
        "Check": name, "Expected": expected, "Actual": actual,
        "Difference": None, "Status": "pass" if ok else "fail",
    }


def _fy_from_assessment_year(assessment_year: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{2})", assessment_year or "")
    if not match:
        return "Unknown"
    ay_start = int(match.group(1))
    return f"{ay_start - 1}-{str(ay_start)[-2:]}"


def parse_form16a(pdf, fname: str) -> dict:
    """Parse one native TRACES Form 16A PDF into summary and line-level records."""
    page_text = [(page.extract_text() or "") for page in pdf.pages]
    full_text = "\n".join(page_text)
    if not re.search(r"FORM\s+NO\.?\s*16A\b", full_text, re.IGNORECASE):
        raise ValueError("Not a Form 16A certificate")

    tables: list[tuple[int, list[list[str]]]] = []
    for page_number, page in enumerate(pdf.pages, 1):
        extractor = getattr(page, "extract_tables", None)
        if not callable(extractor):
            raise ValueError("Form 16A requires native ruled-table extraction; OCR/text-only input is unsupported")
        for table in extractor() or []:
            tables.append((page_number, [_values(row) for row in table]))
    if not tables:
        raise ValueError("Form 16A tables were not found; OCR/text-only input is unsupported")

    certificate_no = ""
    last_updated = None
    deductor_name = deductor_address = ""
    deductee_name = deductee_address = ""
    deductor_pan = deductor_tan = deductee_pan = ""
    assessment_year = ""
    period_from = period_to = None

    # Metadata comes from the ruled header on page one.  Labels are detected,
    # never assumed to live at fixed row/column indexes.
    first_page_rows = [rows for page_number, rows in tables if page_number == 1]
    for rows in first_page_rows:
        for index, values in enumerate(rows):
            joined = _line(" | ".join(values))
            cert_match = re.search(r"Certificate\s+No\.?\s*:?[ ]*([A-Z0-9]+)", joined, re.IGNORECASE)
            if cert_match:
                certificate_no = cert_match.group(1).upper()
            updated_match = re.search(r"Last\s+updated\s+on\s+(\d{1,2}-[A-Za-z]{3}-\d{4})", joined, re.IGNORECASE)
            if updated_match:
                last_updated = _date(updated_match.group(1))

            upper = joined.upper()
            if "NAME AND ADDRESS OF THE DEDUCTOR" in upper and index + 1 < len(rows):
                pair = rows[index + 1]
                if len(pair) >= 2:
                    deductor_name, deductor_address = _name_address(pair[0])
                    deductee_name, deductee_address = _name_address(pair[-1])
            elif "PAN OF THE DEDUCTOR" in upper and "TAN OF THE DEDUCTOR" in upper and index + 1 < len(rows):
                ids = [value.upper() for value in rows[index + 1]]
                pans = [value for value in ids if _PAN_RE.fullmatch(value)]
                tans = [value for value in ids if _TAN_RE.fullmatch(value)]
                deductor_pan = pans[0] if pans else ""
                deductee_pan = pans[-1] if len(pans) >= 2 else ""
                deductor_tan = tans[0] if tans else ""
            elif "ASSESSMENT YEAR" in upper and "PERIOD" in upper and index + 1 < len(rows):
                period_values = rows[index + 1]
                for value in period_values:
                    if not assessment_year:
                        ay_match = re.fullmatch(r"\d{4}-\d{2}", _line(value))
                        if ay_match:
                            assessment_year = ay_match.group(0)
                    value_upper = value.upper()
                    if value_upper.startswith("FROM"):
                        period_from = _date(value)
                    elif value_upper.startswith("TO"):
                        period_to = _date(value)

    # Continuation-page headers are a safe fallback for the four identifiers.
    if not certificate_no:
        match = re.search(r"Certificate\s+Number\s*:\s*([A-Z0-9]+)", full_text, re.IGNORECASE)
        certificate_no = match.group(1).upper() if match else ""
    if not deductor_tan:
        match = re.search(r"TAN\s+of\s+Deductor\s*:\s*([A-Z]{4}\d{5}[A-Z])", full_text, re.IGNORECASE)
        deductor_tan = match.group(1).upper() if match else ""
    if not deductee_pan:
        match = re.search(r"PAN\s+of\s+Deductee\s*:\s*([A-Z]{5}\d{4}[A-Z])", full_text, re.IGNORECASE)
        deductee_pan = match.group(1).upper() if match else ""
    if not assessment_year:
        match = re.search(r"Assessment\s+Year\s*:\s*(\d{4}-\d{2})", full_text, re.IGNORECASE)
        assessment_year = match.group(1) if match else ""

    payments: list[dict] = []
    deposits: list[dict] = []
    quarterly: list[dict] = []
    exceptions: list[dict] = []
    printed_payment_total = printed_book_total = printed_challan_total = None

    for page_number, rows in tables:
        state = None
        for values in rows:
            if not values:
                continue
            joined = _line(" | ".join(values))
            upper = joined.upper()

            if "SUMMARY OF PAYMENT" in upper or ("AMOUNT PAID/ CREDITED" in upper and "NATURE OF PAYMENT" in upper):
                state = "payment"
                continue
            if "SUMMARY OF TAX DEDUCTED" in upper or (values[0].upper() == "QUARTER" and "RECEIPT" in upper):
                state = "summary"
                continue
            if "THROUGH BOOK ADJUSTMENT" in upper or "BOOK IDENTIFICATION NUMBER" in upper:
                state = "book"
                continue
            if "THROUGH CHALLAN" in upper or "CHALLAN IDENTIFICATION NUMBER" in upper or (
                "BSR CODE" in upper and "CHALLAN SERIAL NUMBER" in upper
            ):
                state = "challan"
                continue

            if values[0].upper().startswith("TOTAL (RS.)"):
                total = next((_amount(value) for value in values[1:] if _amount(value) is not None), None)
                if total is not None:
                    if state == "payment":
                        printed_payment_total = total
                    elif state == "book":
                        printed_book_total = total
                    elif state == "challan":
                        printed_challan_total = total
                continue

            if state == "summary" and re.fullmatch(r"Q[1-4]", values[0].upper()) and len(values) >= 4:
                deducted, deposited = _amount(values[-2]), _amount(values[-1])
                if deducted is None or deposited is None:
                    exceptions.append({"Page": page_number, "Section": "Quarterly Summary", "RawRow": joined})
                else:
                    quarterly.append({
                        "Quarter": values[0].upper(), "Receipt Number": _line(values[1]),
                        "Tax Deducted": deducted, "Tax Deposited": deposited,
                        "Source Page": page_number,
                    })
                continue

            if state == "payment" and _is_serial(values[0]):
                if len(values) < 4:
                    exceptions.append({"Page": page_number, "Section": "Payments", "RawRow": joined})
                    continue
                amount = _amount(values[1])
                paid_on = _date(values[-1])
                if amount is None or paid_on is None:
                    exceptions.append({"Page": page_number, "Section": "Payments", "RawRow": joined})
                    continue
                payments.append({
                    "Payment S.No.": int(values[0]), "Amount Paid/Credited": amount,
                    "Nature of Payment": _line(values[2]),
                    "Deductee Reference No.": _line(" ".join(values[3:-1])),
                    "Payment Date": paid_on, "Source Page": page_number,
                })
                continue

            if state in {"book", "challan"} and _is_serial(values[0]):
                minimum = 6
                if len(values) < minimum:
                    exceptions.append({"Page": page_number, "Section": state.title(), "RawRow": joined})
                    continue
                tax = _amount(values[1])
                deposited_on = _date(values[-3])
                if tax is None or deposited_on is None:
                    exceptions.append({"Page": page_number, "Section": state.title(), "RawRow": joined})
                    continue
                if state == "challan":
                    row = {
                        "Deposit Method": "Challan", "Deposit S.No.": int(values[0]),
                        "Tax Deposited": tax, "BSR Code": _line(values[-4]),
                        "Deposit Date": deposited_on, "Challan Serial Number": _line(values[-2]),
                        "Matching Status": _line(values[-1]).upper(), "Source Page": page_number,
                    }
                else:
                    row = {
                        "Deposit Method": "Book Adjustment", "Deposit S.No.": int(values[0]),
                        "Tax Deposited": tax, "Form 24G Receipt Number": _line(values[-4]),
                        "DDO Serial Number": _line(values[-2]), "Deposit Date": deposited_on,
                        "Matching Status": _line(values[-1]).upper(), "Source Page": page_number,
                    }
                deposits.append(row)

    # Guard against any table engine that repeats continuation rows.
    payments = list({(row["Payment S.No."], row["Payment Date"], row["Amount Paid/Credited"]): row for row in payments}.values())
    payments.sort(key=lambda row: row["Payment S.No."])
    deposits = list({(row["Deposit Method"], row["Deposit S.No."], row["Deposit Date"], row["Tax Deposited"]): row for row in deposits}.values())
    deposits.sort(key=lambda row: (row["Deposit Method"], row["Deposit S.No."]))

    payment_sum = sum((row["Amount Paid/Credited"] for row in payments), Decimal("0"))
    deposit_sum = sum((row["Tax Deposited"] for row in deposits), Decimal("0"))
    summary_deducted = sum((row["Tax Deducted"] for row in quarterly), Decimal("0"))
    summary_deposited = sum((row["Tax Deposited"] for row in quarterly), Decimal("0"))

    verify_match = re.search(
        r"certify\s+that\s+a\s+sum\s+of\s+Rs\.?\s*([\d,]+(?:\.\d+)?)\b.*?has\s+been\s+deducted\s+and\s+a\s+sum\s+of\s+Rs\.?\s*([\d,]+(?:\.\d+)?)",
        full_text, re.IGNORECASE | re.DOTALL,
    )
    verified_deducted = _amount(verify_match.group(1)) if verify_match else None
    verified_deposited = _amount(verify_match.group(2)) if verify_match else None

    place_match = re.search(r"^Place\s+(.+)$", full_text, re.IGNORECASE | re.MULTILINE)
    verification_date_match = re.search(r"^Date\s+(\d{1,2}-[A-Za-z]{3}-\d{4})", full_text, re.IGNORECASE | re.MULTILINE)
    designation_match = re.search(r"Designation\s*:\s*(.+?)\s+Full\s+Name\s*:\s*(.+)$", full_text, re.IGNORECASE | re.MULTILINE)
    verification_date = _date(verification_date_match.group(1)) if verification_date_match else None

    checks: list[dict] = []
    checks.append(_check("Payment rows present", True, bool(payments)))
    checks.append(_check("Payment serial continuity", True, _serials_contiguous(payments, "Payment S.No.")))
    if printed_payment_total is not None:
        checks.append(_check("Payment total", printed_payment_total, payment_sum))
    checks.append(_check("Quarterly summary present", True, bool(quarterly)))
    checks.append(_check("Deposit rows present", True, bool(deposits)))
    if deposits:
        # Serial numbering restarts between book-adjustment and challan sections.
        for method in sorted({row["Deposit Method"] for row in deposits}):
            subset = [row for row in deposits if row["Deposit Method"] == method]
            checks.append(_check(f"{method} serial continuity", True, _serials_contiguous(subset, "Deposit S.No.")))
    checks.append(_check("Deposits vs quarterly summary", summary_deposited, deposit_sum))
    printed_deposit_total = (printed_book_total or Decimal("0")) + (printed_challan_total or Decimal("0"))
    if printed_book_total is not None or printed_challan_total is not None:
        checks.append(_check("Deposit printed total", printed_deposit_total, deposit_sum))
    if verified_deducted is not None:
        checks.append(_check("Verification tax deducted", summary_deducted, verified_deducted))
    if verified_deposited is not None:
        checks.append(_check("Verification tax deposited", summary_deposited, verified_deposited))
    if period_from is not None and period_to is not None and payments:
        dates_in_period = all(period_from <= row["Payment Date"] <= period_to for row in payments)
        checks.append(_check("Payment dates within period", True, dates_in_period))
    checks.append(_check("No unparsed financial rows", 0, len(exceptions)))

    metadata_flags = []
    for value, flag in (
        (certificate_no, "CERTIFICATE?"), (deductor_tan, "TAN?"),
        (deductor_pan, "DEDUCTOR_PAN?"), (deductee_pan, "DEDUCTEE_PAN?"),
        (assessment_year, "AY?"), (period_from, "PERIOD_FROM?"), (period_to, "PERIOD_TO?"),
    ):
        if not value:
            metadata_flags.append(flag)
    if deductor_pan and not _PAN_RE.fullmatch(deductor_pan):
        metadata_flags.append("DEDUCTOR_PAN_FORMAT")
    if deductee_pan and not _PAN_RE.fullmatch(deductee_pan):
        metadata_flags.append("DEDUCTEE_PAN_FORMAT")
    if deductor_tan and not _TAN_RE.fullmatch(deductor_tan):
        metadata_flags.append("TAN_FORMAT")

    failed_checks = [re.sub(r"[^A-Z0-9]+", "_", check["Check"].upper()).strip("_") for check in checks if check["Status"] == "fail"]
    matching_flags = sorted({f"MATCHING_{row['Matching Status'] or 'UNKNOWN'}" for row in deposits if row.get("Matching Status") != "F"})
    flags = metadata_flags + failed_checks + matching_flags

    fy = _fy_from_assessment_year(assessment_year)
    quarter = quarterly[0]["Quarter"] if quarterly else ""
    sections = sorted({row["Nature of Payment"] for row in payments if row["Nature of Payment"]})

    # Add traceability keys only after validation calculations so line rows stay
    # compact while the returned output remains directly exportable.
    common = {
        "Certificate No": certificate_no, "TAN of Deductor": deductor_tan,
        "PAN of Deductee": deductee_pan, "Assessment Year": assessment_year,
        "Quarter": quarter, "SourceFile": fname,
    }
    payment_rows = [{**common, **row, "Amount Paid/Credited": _float(row["Amount Paid/Credited"]), "Payment Date": _iso(row["Payment Date"])} for row in payments]
    deposit_rows = [{**common, **row, "Tax Deposited": _float(row["Tax Deposited"]), "Deposit Date": _iso(row["Deposit Date"])} for row in deposits]
    check_rows = [{**common, **check} for check in checks]

    return {
        "ReturnType": "TDS", "DocKind": "Certificate", "Form": "16A",
        "EntityID": deductor_tan or "Unknown", "EntityName": deductor_name or "Unknown",
        "CounterpartyID": deductee_pan or "Unknown", "CounterpartyName": deductee_name or "Unknown",
        "FY": fy, "Assessment Year": assessment_year, "Quarter": quarter,
        "PeriodDate": period_from, "Period From": _iso(period_from), "Period To": _iso(period_to),
        "Certificate No": certificate_no, "Last Updated": _iso(last_updated),
        "Deductor PAN": deductor_pan, "Deductor TAN": deductor_tan,
        "Deductor Name": deductor_name, "Deductor Address": deductor_address,
        "Deductee PAN": deductee_pan, "Deductee Name": deductee_name,
        "Deductee Address": deductee_address, "Sections": ", ".join(sections),
        "Payment Count": len(payment_rows), "Payment Total": _float(payment_sum),
        "Tax Deducted": _float(summary_deducted), "Tax Deposited": _float(summary_deposited),
        "Deposit Count": len(deposit_rows), "Deposit Detail Total": _float(deposit_sum),
        "Verification Tax Deducted": _float(verified_deducted),
        "Verification Tax Deposited": _float(verified_deposited),
        "Verification Place": _line(place_match.group(1)) if place_match else "",
        "Verification Date": _iso(verification_date),
        "Signatory Designation": _line(designation_match.group(1)) if designation_match else "",
        "Signatory Name": _line(designation_match.group(2)) if designation_match else "",
        "PrimaryAmount": _float(summary_deposited), "Total Amount Paid": _float(summary_deposited),
        "Crosscheck Diff": _float(summary_deposited - deposit_sum),
        "DocRef": certificate_no, "FilingDate": _iso(verification_date or last_updated),
        "Validation Status": "pass" if not flags else "fail",
        "Validation Flags": flags, "Exception Count": len(exceptions),
        "Payments": payment_rows, "Deposits": deposit_rows,
        "Validation Checks": check_rows, "Exceptions": exceptions,
    }
