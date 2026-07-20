"""Registered parser, normalizer, and validation bundles for standard forms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .compliance_parsers import (
    parse_ebrc, parse_ewb, parse_pf, parse_pf_arrears, parse_pf_ecr,
    parse_pf_payment, parse_ptrc, parse_ptrc_challan, parse_tds,
)


@dataclass(frozen=True)
class RegisteredHandler:
    return_type: str
    parser: Callable
    validator: Callable[[dict], list[str]]


def _standard_flags(identity_flag: str) -> Callable[[dict], list[str]]:
    def validate(result: dict) -> list[str]:
        flags = []
        if result.get("EntityID") in ("Unknown", ""):
            flags.append(identity_flag)
        if result.get("PeriodDate") is None:
            flags.append("PERIOD?")
        if not result.get("PrimaryAmount"):
            flags.append("AMT?")
        return flags
    return validate


def _parse_pf(pdf, fname: str, doc_kind: str) -> dict:
    parsers = {
        "Return": parse_pf_ecr,
        "Arrears": parse_pf_arrears,
        "Payment": parse_pf_payment,
        "Challan": parse_pf,
    }
    return parsers.get(doc_kind, parse_pf)(pdf, fname)


def _validate_pf(result: dict) -> list[str]:
    flags = _standard_flags("ENTITY?")(result)
    if result.get("DocKind") == "Challan":
        employee = result.get("Employee_EPF_AC01", 0)
        employer = result.get("Employer_EPF_AC01", 0) + result.get("Employer_EPS_AC10", 0)
        if employer > 0 and abs(employee - employer) / max(employer, 1) > 0.05:
            flags.append("EE<>ER?")
    return flags


def _parse_ptrc(pdf, fname: str, doc_kind: str) -> dict:
    return parse_ptrc_challan(pdf, fname) if doc_kind == "Challan" else parse_ptrc(pdf, fname)


def _parse_tds(pdf, fname: str, _doc_kind: str) -> dict:
    result = parse_tds(pdf, fname)
    result["PrimaryAmount"] = result.get("Total Amount Paid", 0)
    return result


def _validate_tds(result: dict) -> list[str]:
    flags = []
    if result.get("EntityID") in ("Unknown", ""):
        flags.append("PAN?" if result.get("Taxpayer ID Type") == "PAN" else "TAN?")
    if result.get("PeriodDate") is None:
        flags.append("MONTH?")
    if abs(result.get("Crosscheck Diff", 0)) > 1.0:
        flags.append("CROSSCHECK")
    if result.get("Section", "Unknown") == "Unknown":
        flags.append("SECTION?")
    for field, flag in (("CIN", "CIN?"), ("BSR Code", "BSR?"), ("Challan No", "CHALLAN?"), ("Minor Head", "MINOR_HEAD?")):
        if not result.get(field):
            flags.append(flag)
    if result.get("PrimaryAmount", 0) <= 0:
        flags.append("AMT?")
    if result.get("PeriodEstimated"):
        flags.append("PERIOD_EST")
    return flags


REGISTERED_HANDLERS = {
    "PF": RegisteredHandler("PF", _parse_pf, _validate_pf),
    "PTRC": RegisteredHandler("PTRC", _parse_ptrc, _standard_flags("TIN?")),
    "TDS": RegisteredHandler("TDS", _parse_tds, _validate_tds),
    "EBRC": RegisteredHandler("EBRC", lambda pdf, fname, _kind: parse_ebrc(pdf, fname), _standard_flags("ENTITY?")),
    "EWB": RegisteredHandler("EWB", lambda pdf, fname, _kind: parse_ewb(pdf, fname), _standard_flags("ENTITY?")),
}


def run_registered(return_type: str, pdf, fname: str, doc_kind: str, make_row: Callable) -> tuple[dict, dict]:
    """Run a registered form and return its normalized ledger row plus detail row."""
    handler = REGISTERED_HANDLERS[return_type]
    result = handler.parser(pdf, fname, doc_kind)
    result["SourceFile"] = fname
    return make_row(result, fname, handler.validator(result)), result
