"""Shared extractors and fail-closed checks for bank documents."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Iterable

from .profiles import BankProfile, normalise_header


AMOUNT_RE = re.compile(r"[-+]?\(?\d[\d,]*(?:\.\d+)?\)?")
DATE_FORMATS = (
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d %b %Y",
    "%d-%b-%Y",
    "%m/%d/%Y",
    "%d-%m-%y",
    "%d/%m/%y",
)


def clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


def parse_amount(value: object) -> float | None:
    text = clean_text(value)
    if not text or text in {"-", "--", "NA", "N/A"}:
        return None
    match = AMOUNT_RE.search(text.replace("₹", "").replace("`", ""))
    if not match:
        return None
    token = match.group(0)
    negative = token.startswith("-") or (token.startswith("(") and token.endswith(")"))
    try:
        number = float(token.strip("()+-").replace(",", ""))
    except ValueError:
        return None
    return -number if negative else number


def parse_date(value: object) -> str | None:
    text = clean_text(value)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def signed_balance(value: object, balance_type: object = "", debt_default: bool = False) -> float | None:
    number = parse_amount(value)
    if number is None:
        return None
    text = f"{clean_text(value)} {clean_text(balance_type)}".upper()
    if "DR" in text or (debt_default and "CR" not in text):
        return -abs(number)
    if "CR" in text:
        return abs(number)
    return number


def _header_map(row: Iterable[object]) -> dict[str, int]:
    result = {}
    for index, value in enumerate(row):
        header = normalise_header(value)
        if header and header not in result:
            result[header] = index
    return result


def _find_transaction_header(table: list[list[object]]) -> tuple[int, dict[str, int]] | None:
    for index, row in enumerate(table[:8]):
        mapping = _header_map(row)
        if "date" in mapping and "balance" in mapping and (
            "description" in mapping or "debit" in mapping or "credit" in mapping
        ):
            return index, mapping
    return None


def _cell(row: list[object], mapping: dict[str, int], name: str) -> str:
    index = mapping.get(name)
    return clean_text(row[index]) if index is not None and index < len(row) else ""


def _transaction_from_row(
    row: list[object],
    mapping: dict[str, int],
    profile: BankProfile,
    page_number: int,
) -> dict | None:
    date = parse_date(_cell(row, mapping, "date"))
    description = _cell(row, mapping, "description")
    debit = parse_amount(_cell(row, mapping, "debit"))
    credit = parse_amount(_cell(row, mapping, "credit"))
    debit = abs(debit) if debit is not None else None
    credit = abs(credit) if credit is not None else None
    balance = signed_balance(
        _cell(row, mapping, "balance"),
        _cell(row, mapping, "balance type"),
        profile.balance_is_debt,
    )
    if not date:
        return None
    if debit is None and credit is None and balance is None:
        return None
    return {
        "TransactionDate": date,
        "ValueDate": parse_date(_cell(row, mapping, "value date")),
        "Description": description,
        "Reference": _cell(row, mapping, "reference"),
        "Debit": debit or 0.0,
        "Credit": credit or 0.0,
        "Balance": balance,
        "BalanceType": _cell(row, mapping, "balance type").upper(),
        "Channel": _cell(row, mapping, "channel"),
        "Page": page_number,
        "Method": "profile table",
    }


def extract_table_transactions(pdf, profile: BankProfile) -> tuple[list[dict], list[dict]]:
    transactions = []
    evidence = []
    active_mapping = None
    for page_number, page in enumerate(pdf.pages, start=1):
        for table in page.extract_tables() or []:
            header = _find_transaction_header(table)
            if header:
                header_index, mapping = header
                active_mapping = mapping
                rows = table[header_index + 1 :]
            elif active_mapping and table and parse_date(_cell(table[0], active_mapping, "date")):
                mapping = active_mapping
                rows = table
            else:
                continue
            for row in rows:
                transaction = _transaction_from_row(row, mapping, profile, page_number)
                if transaction:
                    transactions.append(transaction)
                    evidence.append({
                        "Field": "Transaction",
                        "Value": transaction["Balance"],
                        "RawValue": clean_text(row),
                        "Page": page_number,
                        "Method": "profile table",
                        "Anchor": ", ".join(mapping),
                    })
    return transactions, evidence


def _label_value(text: str, label: str) -> str:
    match = re.search(rf"(?im)^{re.escape(label)}\s*:?\s*(.+)$", text)
    return clean_text(match.group(1)) if match else ""


def extract_citi_transactions(page_text: list[str]) -> tuple[list[dict], list[dict]]:
    text = "\n".join(page_text)
    chunks = re.split(r"(?im)^Transaction Description\s+", text)[1:]
    transactions = []
    evidence = []
    for chunk in chunks:
        description, _, rest = chunk.partition("\n")
        amount = parse_amount(_label_value(rest, "Cheque Amount/Transaction Amount"))
        direction = _label_value(rest, "Debit/Credit").upper()
        date = parse_date(_label_value(rest, "Value Date"))
        if not amount or not date or direction not in {"DEBIT", "CREDIT"}:
            continue
        amount = abs(amount)
        transaction = {
            "TransactionDate": date,
            "ValueDate": date,
            "Description": clean_text(description),
            "Reference": _label_value(rest, "Customer Reference") or _label_value(rest, "Bank Reference"),
            "Debit": amount if direction == "DEBIT" else 0.0,
            "Credit": amount if direction == "CREDIT" else 0.0,
            "Balance": None,
            "BalanceType": "",
            "Channel": _label_value(rest, "Product Type"),
            "Page": None,
            "Method": "profile key-value",
        }
        transactions.append(transaction)
        evidence.append({
            "Field": "Transaction",
            "Value": amount,
            "RawValue": f"{description} | {direction}",
            "Page": None,
            "Method": "profile key-value",
            "Anchor": "Transaction Description; Cheque Amount/Transaction Amount; Debit/Credit",
        })
    return transactions, evidence


def _find_deposit_header(table: list[list[object]]) -> tuple[int, dict[str, int]] | None:
    for index, row in enumerate(table[:8]):
        mapping = _header_map(row)
        if "deposit number" in mapping and "principal" in mapping:
            return index, mapping
    return None


def extract_deposits(pdf, profile: BankProfile) -> tuple[list[dict], list[dict]]:
    deposits = []
    evidence = []
    for page_number, page in enumerate(pdf.pages, start=1):
        for table in page.extract_tables() or []:
            header = _find_deposit_header(table)
            if not header:
                continue
            header_index, mapping = header
            for row in table[header_index + 1 :]:
                number = _cell(row, mapping, "deposit number")
                principal = parse_amount(_cell(row, mapping, "principal"))
                if not number or principal is None:
                    continue
                deposit = {
                    "DepositNumber": number,
                    "DepositDate": parse_date(_cell(row, mapping, "deposit date")),
                    "Principal": principal,
                    "MaturityDate": parse_date(_cell(row, mapping, "maturity date")),
                    "InterestRate": parse_amount(_cell(row, mapping, "interest rate")),
                    "MaturityAmount": parse_amount(_cell(row, mapping, "maturity amount")),
                    "GrossInterest": parse_amount(_cell(row, mapping, "gross interest")),
                    "InterestPaid": parse_amount(_cell(row, mapping, "interest paid")),
                    "TDS": parse_amount(_cell(row, mapping, "tds")),
                    "Page": page_number,
                    "Method": "profile table",
                }
                deposits.append(deposit)
                evidence.append({
                    "Field": "Deposit",
                    "Value": principal,
                    "RawValue": clean_text(row),
                    "Page": page_number,
                    "Method": "profile table",
                    "Anchor": ", ".join(mapping),
                })
    return deposits, evidence


def _extract_first(text: str, patterns: Iterable[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.M)
        if match:
            return clean_text(match.group(1))
    return ""


def _extract_last(text: str, pattern: str) -> str:
    matches = re.findall(pattern, text, re.I | re.M)
    return clean_text(matches[-1]) if matches else ""


def extract_metadata(text: str, profile: BankProfile) -> dict:
    account_number = _extract_first(
        text,
        (
            r"(?:Account Number|Account No|Account/ID)\s*:?\s*([A-Z0-9X*-]{5,})",
            r"Statement of Axis Bank Account No\s*:?\s*([A-Z0-9X*-]{5,})",
            r"(?:UCIC No|Customer No|CIF No)\s*:?\s*([A-Z0-9X*-]{5,})",
        ),
    )
    account_name = _extract_first(
        text,
        (
            r"(?:Account Name|Account Holder Names)\s*:?\s*([^\n]+)",
            r"(?m)^Name\s*:\s*([^\n]+)",
            r"(?m)^([A-Z][A-Z0-9 .&()/-]{4,})\s*\nJoint Holder",
            r"(?m)^To,\s*\n([^\n]+)",
        ),
    )
    account_type = _extract_first(
        text,
        (r"(?m)^(?:Account Type|Type Of Account|Scheme|Product)\s*:?\s*([^\n]+)",),
    )
    currency = _extract_first(text, (r"(?m)^(?:Account Currency|Currency)\s*:?\s*([A-Z]{3})\b",)) or "INR"
    period_match = re.search(
        r"(?:period|Statement From)\s*(?:\(From\s*:?)?\s*(\d{1,2}[-/][A-Za-z0-9]{2,3}[-/]\d{2,4})"
        r"\s*(?:To|through|-)\s*:?\s*(\d{1,2}[-/][A-Za-z0-9]{2,3}[-/]\d{2,4})",
        text,
        re.I,
    )
    period_from = parse_date(period_match.group(1)) if period_match else None
    period_to = parse_date(period_match.group(2)) if period_match else None
    opening = parse_amount(_extract_first(text, (r"Opening (?:Available |Ledger )?Balance\s*:?\s*([()0-9,.\-]+)",)))
    closing = parse_amount(_extract_last(
        text,
        r"(?:Current / Closing (?:Available |Ledger )?Balance|Closing Balance)\s*:?\s*([()0-9,.\-]+)",
    ))
    if profile.balance_is_debt:
        opening = -abs(opening) if opening is not None else None
        closing = -abs(closing) if closing is not None else None
    return {
        "AccountNumber": account_number,
        "AccountName": account_name,
        "AccountType": account_type,
        "Currency": currency,
        "PeriodFrom": period_from,
        "PeriodTo": period_to,
        "OpeningBalance": opening,
        "ClosingBalance": closing,
    }


def infer_balances(metadata: dict, transactions: list[dict]) -> None:
    if not transactions:
        return
    first = transactions[0]
    last = transactions[-1]
    if metadata.get("OpeningBalance") is None and first.get("Balance") is not None:
        metadata["OpeningBalance"] = first["Balance"] + first["Debit"] - first["Credit"]
    if metadata.get("ClosingBalance") is None and last.get("Balance") is not None:
        metadata["ClosingBalance"] = last["Balance"]
    if metadata.get("PeriodFrom") is None:
        metadata["PeriodFrom"] = first.get("TransactionDate")
    if metadata.get("PeriodTo") is None:
        metadata["PeriodTo"] = last.get("TransactionDate")


def validate_statement(metadata: dict, transactions: list[dict]) -> tuple[list[dict], dict]:
    findings = []
    tolerance = 0.05
    dated = sum(bool(row.get("TransactionDate")) for row in transactions)
    if not transactions:
        findings.append(("NO_TRANSACTIONS", "Review", "No transaction rows were extracted."))
    elif dated != len(transactions):
        findings.append(("TRANSACTION_DATE_MISSING", "Review", "One or more transaction dates are missing."))

    invalid_sides = [
        row for row in transactions
        if (abs(row.get("Debit") or 0) > tolerance) == (abs(row.get("Credit") or 0) > tolerance)
    ]
    if invalid_sides:
        findings.append(("DEBIT_CREDIT_CONFLICT", "Review", "A row has both or neither debit and credit."))

    running_mismatches = 0
    previous = metadata.get("OpeningBalance")
    for row in transactions:
        current = row.get("Balance")
        if previous is not None and current is not None:
            expected = previous - row["Debit"] + row["Credit"]
            if not math.isclose(expected, current, abs_tol=tolerance):
                running_mismatches += 1
        if current is not None:
            previous = current
    if running_mismatches:
        findings.append((
            "RUNNING_BALANCE_MISMATCH",
            "Review",
            f"{running_mismatches} transaction balance(s) do not reconcile.",
        ))

    total_debit = sum(row.get("Debit") or 0 for row in transactions)
    total_credit = sum(row.get("Credit") or 0 for row in transactions)
    opening = metadata.get("OpeningBalance")
    closing = metadata.get("ClosingBalance")
    difference = None
    if opening is not None and closing is not None:
        expected_closing = opening - total_debit + total_credit
        difference = closing - expected_closing
        if not math.isclose(expected_closing, closing, abs_tol=tolerance):
            findings.append(("SUMMARY_BALANCE_MISMATCH", "Review", "Opening balance and transaction totals do not reach closing balance."))
    else:
        findings.append(("SUMMARY_BALANCE_MISSING", "Review", "Opening or closing balance is missing."))

    reconciliation = {
        "OpeningBalance": opening,
        "TotalDebit": total_debit,
        "TotalCredit": total_credit,
        "ExpectedClosing": (opening - total_debit + total_credit) if opening is not None else None,
        "ClosingBalance": closing,
        "Difference": difference,
        "RunningMismatches": running_mismatches,
        "Status": "PASS" if not findings else "REVIEW",
    }
    return [
        {"Code": code, "Severity": severity, "Message": message}
        for code, severity, message in findings
    ], reconciliation


def validate_deposits(deposits: list[dict]) -> list[dict]:
    findings = []
    if not deposits:
        return [{"Code": "NO_DEPOSITS", "Severity": "Review", "Message": "No deposit rows were extracted."}]
    missing = [
        row for row in deposits
        if not row.get("DepositNumber") or row.get("Principal") is None
    ]
    if missing:
        findings.append({
            "Code": "DEPOSIT_FIELDS_MISSING",
            "Severity": "Review",
            "Message": "One or more deposits are missing their number or principal.",
        })
    return findings
