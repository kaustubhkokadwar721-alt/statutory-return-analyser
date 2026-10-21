"""Native-text parsers for Form 27A and Form 26Q acknowledgements."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

import pandas as pd


_FORM27A_RE = re.compile(r"FORM\s+NO\.?\s*27A\b", re.IGNORECASE)
_FORM26Q_RECEIPT_RE = re.compile(r"FORM\s+NO\.\s*:\s*FORM\s+26Q\b", re.IGNORECASE)


def _text(pdf) -> str:
    return "\n".join((page.extract_text() or "") for page in pdf.pages)


def _tables(pdf) -> list[list[list[str | None]]]:
    tables = []
    for page in pdf.pages:
        if not hasattr(page, "extract_tables"):
            raise ValueError("Form 27A/26Q receipt requires native ruled-table extraction; OCR is unsupported")
        tables.extend(page.extract_tables() or [])
    return tables


def _line(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _field(text: str, label: str) -> str:
    match = re.search(rf"{label}\s*:\s*([^\r\n]+)", text, re.IGNORECASE)
    return _line(match.group(1)) if match else ""


def _amount(value) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", "").strip())
    except InvalidOperation:
        return Decimal("0")


def _float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _date(value: str):
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%d-%b-%Y"):
        try:
            return pd.to_datetime(value, format=fmt)
        except (TypeError, ValueError):
            pass
    return None


def _iso(value) -> str | None:
    return value.strftime("%Y-%m-%d") if value is not None and not pd.isna(value) else None


def _assessment_year(fy: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{2})", fy.strip())
    if not match:
        return ""
    start = int(match.group(1))
    return f"{start + 1}-{str(start + 2)[-2:]}"


def _quarter_start(fy: str, quarter: str):
    match = re.match(r"(\d{4})", fy)
    if not match or quarter not in {"Q1", "Q2", "Q3", "Q4"}:
        return None
    start = int(match.group(1))
    month = {"Q1": 4, "Q2": 7, "Q3": 10, "Q4": 1}[quarter]
    year = start if quarter != "Q4" else start + 1
    return pd.Timestamp(year=year, month=month, day=1)


def _check(name: str, expected, actual) -> dict:
    return {
        "Check": name,
        "Expected": expected,
        "Actual": actual,
        "Status": "pass" if expected == actual else "fail",
    }


def _flags(checks: list[dict]) -> list[str]:
    return [
        re.sub(r"[^A-Z0-9]+", "_", check["Check"].upper()).strip("_")
        for check in checks if check["Status"] == "fail"
    ]


def _named_tables(tables) -> list[list[list[str | None]]]:
    return [
        table for table in tables
        if table and table[0] and re.search(r"\(a\)\s*Name", _line(table[0][0]), re.IGNORECASE)
    ]


def parse_form27a(pdf, fname: str) -> dict:
    """Parse one native Form 27A control sheet."""
    full_text = _text(pdf)
    if not _FORM27A_RE.search(full_text):
        raise ValueError("Not a Form 27A document")
    tables = _tables(pdf)

    tan_match = re.search(r"Tax\s+Deduction\s+Account\s+No\.\s*([A-Z]{4}\d{5}[A-Z])", full_text, re.IGNORECASE)
    pan_match = re.search(r"Permanent\s+Account\s+No\.\s*([A-Z]{5}\d{4}[A-Z])", full_text, re.IGNORECASE)
    return_form_match = re.search(r"\(c\)\s*Form\s+No\.\s*(24Q|26Q|27Q|27EQ)\b", full_text, re.IGNORECASE)
    quarter_match = re.search(r"filed\s+on\s+computer\s+media\s+for\s+the\s+period\s+(Q[1-4])\b", full_text, re.IGNORECASE)
    period_match = re.search(r"From\s+(\d{2}/\d{2}/\d{2})\s+to\s+(\d{2}/\d{2}/\d{2})", full_text, re.IGNORECASE)
    fy_match = re.search(r"Financial\s+Year\s+(\d{4}-\d{2})", full_text, re.IGNORECASE)
    ay_match = re.search(r"Assessment\s+year\s+(\d{4}-\d{2})", full_text, re.IGNORECASE)
    previous_match = re.search(r"Previous\s+receipt\s+number\s+([A-Z0-9-]+)", full_text, re.IGNORECASE)
    file_hash_line = re.search(r"^File\s+Hash([^\r\n]*)", full_text, re.IGNORECASE | re.MULTILINE)

    tan = tan_match.group(1).upper() if tan_match else ""
    pan = pan_match.group(1).upper() if pan_match else ""
    return_form = return_form_match.group(1).upper() if return_form_match else ""
    quarter = quarter_match.group(1).upper() if quarter_match else ""
    fy = fy_match.group(1) if fy_match else ""
    assessment_year = ay_match.group(1) if ay_match else ""
    period_from = _date(period_match.group(1)) if period_match else None
    period_to = _date(period_match.group(2)) if period_match else None
    previous_receipt = previous_match.group(1) if previous_match else ""
    file_hash = "".join(re.findall(r"\d+", file_hash_line.group(1))) if file_hash_line else ""

    names = _named_tables(tables)
    entity_name = _line(names[0][0][1]) if names and len(names[0][0]) > 1 else ""
    responsible_name = _line(names[1][0][1]) if len(names) > 1 and len(names[1][0]) > 1 else ""
    responsible_pan = ""
    if len(names) > 1:
        for row in names[1]:
            if row and re.search(r"\(b\)\s*PAN", _line(row[0]), re.IGNORECASE):
                responsible_pan = _line(row[1]).upper() if len(row) > 1 else ""
                break

    control_table = next((
        table for table in tables
        if table and table[0] and any("Return Type" in _line(cell) for cell in table[0])
    ), [])
    detail_rows = [row for row in control_table[1:] if row and _line(row[0]).isdigit()]
    detail_row = detail_rows[0] if detail_rows else []
    total_row = next((row for row in control_table[1:] if row and _line(row[0]).lower() == "total"), detail_row)
    filing_type = _line(detail_row[1]) if len(detail_row) > 1 else ""
    deductee_records = int(_amount(total_row[2])) if len(total_row) > 2 else 0
    amount_paid = _amount(total_row[3]) if len(total_row) > 3 else Decimal("0")
    tax_deducted = _amount(total_row[4]) if len(total_row) > 4 else Decimal("0")
    tax_deposited = _amount(total_row[5]) if len(total_row) > 5 else Decimal("0")

    filing_dates = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", full_text)
    filing_date = _date(filing_dates[-1]) if filing_dates else None
    expected_start = _quarter_start(fy, quarter)
    expected_end = expected_start + pd.DateOffset(months=3) - pd.Timedelta(days=1) if expected_start is not None else None
    detail_records = sum(int(_amount(row[2])) for row in detail_rows if len(row) > 2)
    detail_paid = sum((_amount(row[3]) for row in detail_rows if len(row) > 3), Decimal("0"))
    detail_deducted = sum((_amount(row[4]) for row in detail_rows if len(row) > 4), Decimal("0"))
    detail_deposited = sum((_amount(row[5]) for row in detail_rows if len(row) > 5), Decimal("0"))
    checks = [
        _check("TAN format", True, bool(re.fullmatch(r"[A-Z]{4}\d{5}[A-Z]", tan))),
        _check("Deductor PAN format", True, bool(re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", pan))),
        _check("Entity name present", True, bool(entity_name)),
        _check("Return form present", True, bool(return_form)),
        _check("Quarter present", True, bool(quarter)),
        _check("Assessment year present", True, bool(assessment_year)),
        _check("Control totals present", True, bool(control_table and total_row)),
        _check("Control deductee records total", deductee_records, detail_records),
        _check("Control amount paid total", _float(amount_paid), _float(detail_paid)),
        _check("Control tax deducted total", _float(tax_deducted), _float(detail_deducted)),
        _check("Control tax deposited total", _float(tax_deposited), _float(detail_deposited)),
        _check("Filing date present", True, filing_date is not None),
    ]
    if expected_start is not None and period_from is not None:
        checks.append(_check("Quarter matches period", _iso(expected_start), _iso(period_from)))
    if expected_end is not None and period_to is not None:
        checks.append(_check("Quarter end matches period", _iso(expected_end), _iso(period_to)))
    if fy and assessment_year:
        checks.append(_check("Assessment year matches financial year", _assessment_year(fy), assessment_year))
    if "CORRECTION" in filing_type.upper():
        checks.append(_check("Correction receipt present", True, bool(previous_receipt and previous_receipt.upper() != "NA")))
    flags = _flags(checks)
    common = {"SourceFile": fname, "TAN": tan, "Return Form": return_form, "Quarter": quarter}
    check_rows = [{**common, **check} for check in checks]

    return {
        "ReturnType": "TDS", "DocKind": "Form 27A",
        "EntityID": tan or "Unknown", "EntityName": entity_name or "Unknown",
        "FY": fy or "Unknown", "Assessment Year": assessment_year,
        "Quarter": quarter, "Return Form": return_form,
        "PeriodDate": expected_start or period_from,
        "Period From": _iso(period_from), "Period To": _iso(period_to),
        "TAN": tan, "PAN": pan, "Previous Receipt Number": previous_receipt,
        "File Hash": file_hash, "Filing Type": filing_type,
        "Deductee Records": deductee_records, "Amount Paid": _float(amount_paid),
        "Tax Deducted": _float(tax_deducted), "Tax Deposited": _float(tax_deposited),
        "Responsible Person": responsible_name, "Responsible Person PAN": responsible_pan,
        "PrimaryAmount": _float(tax_deposited), "DocRef": file_hash or previous_receipt,
        "FilingDate": _iso(filing_date), "Validation Status": "fail" if flags else "pass",
        "Validation Flags": flags, "Validation Checks": check_rows,
    }


def parse_form26q_receipt(pdf, fname: str) -> dict:
    """Parse one native Form 26Q e-filing acknowledgement receipt."""
    full_text = _text(pdf)
    if not (_FORM26Q_RECEIPT_RE.search(full_text) and "Acknowledgement Receipt" in full_text):
        raise ValueError("Not a Form 26Q acknowledgement receipt")
    _tables(pdf)

    entity_id = _field(full_text, r"PAN/TAN").upper()
    entity_name = _field(full_text, r"Name")
    return_form = re.search(r"Form\s+No\.\s*:\s*Form\s+(26Q)\b", full_text, re.IGNORECASE).group(1).upper()
    fy = _field(full_text, r"Financial\s+Year")
    printed_ay = _field(full_text, r"Assessment\s+Year")
    assessment_year = printed_ay if re.fullmatch(r"\d{4}-\d{2}", printed_ay) else _assessment_year(fy)
    quarter = _field(full_text, r"Quarter").upper()
    filing_type = _field(full_text, r"Filing\s+Type")
    match = re.search(
        r"e-Filing\s+Acknowledgement\s+Number\s+Date\s+of\s+e-Filing\s+(\d+)",
        full_text, re.IGNORECASE,
    )
    acknowledgement = match.group(1) if match else ""
    rrr_match = re.search(r"RRR\s+Number\s+(\d+)", full_text, re.IGNORECASE)
    rrr_number = rrr_match.group(1) if rrr_match else ""
    filing_match = re.search(r"Date\s+of\s+e-Filing\s+(?:\d+\s+)?(\d{2}-[A-Za-z]{3}-\d{4})", full_text, re.IGNORECASE)
    filing_date = _date(filing_match.group(1)) if filing_match else None
    period_date = _quarter_start(fy, quarter)
    checks = [
        _check("TAN present", True, bool(re.fullmatch(r"[A-Z]{4}\d{5}[A-Z]", entity_id))),
        _check("Quarter present", True, bool(quarter)),
        _check("Assessment year present", True, bool(assessment_year)),
        _check("Acknowledgement number present", True, bool(acknowledgement)),
    ]
    flags = _flags(checks)
    return {
        "ReturnType": "TDS", "DocKind": "Form 26Q Receipt",
        "EntityID": entity_id or "Unknown", "EntityName": entity_name or "Unknown",
        "FY": fy or "Unknown", "Assessment Year": assessment_year,
        "Assessment Year Source": "printed" if assessment_year == printed_ay else "derived from FY",
        "Quarter": quarter, "Return Form": return_form, "Filing Type": filing_type,
        "PeriodDate": period_date, "Acknowledgement Number": acknowledgement,
        "RRR Number": rrr_number, "PrimaryAmount": 0,
        "DocRef": acknowledgement or rrr_number, "FilingDate": _iso(filing_date),
        "Validation Status": "fail" if flags else "pass", "Validation Flags": flags,
        "Validation Checks": [{"SourceFile": fname, **check} for check in checks],
    }
