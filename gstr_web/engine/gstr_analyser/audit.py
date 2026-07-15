"""Local-only preflight, classification, and audit trail for statutory PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class DocumentHandler:
    """One statutory document profile. Parsing remains in its specialised module."""

    return_type: str
    profile_version: str
    required_fields: tuple[str, ...]
    matcher: Callable[[str], tuple[int, str, list[str]]]


def _has(text: str, *markers: str) -> list[str]:
    return [marker for marker in markers if marker in text]


def _shipping_bill(text: str):
    hits = _has(text, "INDIAN CUSTOMS EDI SYSTEM", "SHIPPING BILL SUMMARY")
    return (100 if hits else 0, "Return", hits)


def _ebrc(text: str):
    hits = _has(text, "STATEMENT OF BANK REALISATION", "DIRECTORATE GENERAL OF FOREIGN TRADE", "REALISATION")
    return (100 if "STATEMENT OF BANK REALISATION" in hits or len(hits) == 2 else 0, "Return", hits)


def _ewb(text: str):
    hits = _has(text, "E-WAY BILL SYSTEM", "E-WAY BILL NO")
    return (100 if hits else 0, "Return", hits)


def _gstr1(text: str):
    hits = _has(text, "GSTR-1", "GSTR1")
    return (100 if hits else 0, "Return", hits)


def _gstr3b(text: str):
    hits = _has(text, "GSTR-3B", "GSTR3B")
    return (100 if hits else 0, "Return", hits)


def _pf(text: str):
    hits = _has(text, "PROVIDENT FUND ORGANISATION", "COMBINED CHALLAN OF A/C", "PAYMENT CONFIRMATION RECEIPT", "ELECTRONIC CHALLAN CUM RETURN", "(ECR)")
    if not hits:
        return 0, "Unknown", []
    if "COMBINED CHALLAN OF A/C" in hits:
        kind = "Challan"
    elif "PAYMENT CONFIRMATION RECEIPT" in hits:
        kind = "Payment"
    elif "ARREAR" in text and "ELECTRONIC CHALLAN CUM RETURN" not in text:
        kind = "Arrears"
    elif "ELECTRONIC CHALLAN CUM RETURN" in hits or "(ECR)" in hits:
        kind = "Return"
    else:
        kind = "Challan"
    return 90, kind, hits


def _esic(text: str):
    hits = _has(text, "CHALLAN PERIOD:", "EMPLOYEE'S STATE INSURANCE", "ESIC")
    return (90 if "CHALLAN PERIOD:" in hits and len(hits) > 1 else 0, "Challan", hits)


def _ptrc(text: str):
    hits = _has(text, "FORM_IIIB", "PROFESSION TAX", "PTRC", "MTR FORM", "00280012")
    if not hits:
        return 0, "Unknown", []
    kind = "Challan" if "MTR FORM" in hits or "00280012" in hits else "Return"
    return 85, kind, hits


def _tds(text: str):
    hits = _has(text, "INCOME TAX DEPARTMENT", "CHALLAN RECEIPT", "TAN", "DATE OF DEPOSIT", "NATURE OF PAYMENT")
    score = 90 if ("INCOME TAX DEPARTMENT" in hits or "CHALLAN RECEIPT" in hits) and len(hits) >= 2 else 0
    return score, "Challan", hits


HANDLERS = (
    DocumentHandler("SB", "icegate-v1", ("EntityID", "PeriodDate", "DocRef"), _shipping_bill),
    DocumentHandler("EBRC", "dgft-v1", ("EntityID", "PeriodDate", "DocRef"), _ebrc),
    DocumentHandler("EWB", "eway-v1", ("EntityID", "PeriodDate", "DocRef"), _ewb),
    DocumentHandler("GSTR3B", "gst-3b-v1", ("EntityID", "PeriodDate"), _gstr3b),
    DocumentHandler("GSTR1", "gst-1-v1", ("EntityID", "PeriodDate"), _gstr1),
    DocumentHandler("PF", "epfo-v1", ("EntityID", "PeriodDate", "DocRef"), _pf),
    DocumentHandler("ESIC", "esic-v1", ("EntityID", "PeriodDate", "DocRef"), _esic),
    DocumentHandler("PTRC", "ptrc-v1", ("EntityID", "PeriodDate", "DocRef"), _ptrc),
    DocumentHandler("TDS", "itns-v1", ("EntityID", "PeriodDate", "DocRef"), _tds),
)

def preflight_pdf(pdf) -> dict:
    """Inspect a PDF without retaining its text outside the current run."""
    page_text = [(page.extract_text() or "").strip() for page in pdf.pages]
    chars = sum(len(text) for text in page_text)
    pages = len(page_text)
    return {
        "pages": pages,
        "text": "\n".join(page_text),
        "page_text": page_text,
        "needs_ocr": pages > 0 and chars < 20,
        "sparse_text": pages > 0 and chars / pages < 80,
        "ocr_used": False,
    }


def classify_document(text: str) -> dict:
    """Return scored candidates; callers must reject ambiguous classifications."""
    upper = (text or "").upper()
    candidates = []
    for handler in HANDLERS:
        score, kind, markers = handler.matcher(upper)
        if score:
            candidates.append({
                "handler": handler,
                "return_type": handler.return_type,
                "doc_kind": kind,
                "score": score,
                "markers": markers,
            })
    candidates.sort(key=lambda candidate: candidate["score"], reverse=True)
    winner = candidates[0] if candidates else None
    runner_score = candidates[1]["score"] if len(candidates) > 1 else 0
    accepted = bool(winner and winner["score"] >= 70 and winner["score"] - runner_score >= 15)
    return {
        "accepted": accepted,
        "winner": winner,
        "candidates": candidates,
        "margin": winner["score"] - runner_score if winner else 0,
    }


def _missing(value) -> bool:
    return value is None or value == "" or str(value).strip().lower() in {"unknown", "nat", "none"}


def audit_record(record: dict, classification: dict, preflight: dict) -> tuple[dict, list[dict], list[dict]]:
    """Apply auditable, fail-closed status rules to one normalized record."""
    audited = dict(record)
    winner = classification["winner"]
    handler = winner["handler"] if winner else None
    findings = []
    evidence = []
    score = winner["score"] if winner else 0

    if preflight["sparse_text"]:
        findings.append(("SPARSE_TEXT", "Review", "Low extracted text density; verify fields against the source PDF."))
        score -= 15
    if preflight.get("ocr_used"):
        findings.append(("OCR_TEXT", "Review", "Fields were read by local OCR; verify them against the source PDF."))
        score -= 20
    if not classification["accepted"]:
        findings.append(("AMBIGUOUS_TYPE", "Review", "Document classification did not clear the acceptance margin."))
        score = min(score, 50)
    if handler:
        for field in handler.required_fields:
            value = audited.get(field)
            evidence.append({
                "SourceFile": audited.get("SourceFile"), "ReturnType": audited.get("ReturnType"),
                "Field": field, "Value": value, "RawValue": value, "Page": None,
                "Method": "local OCR + form parser" if preflight.get("ocr_used") else "form parser",
                "Anchor": "; ".join(winner["markers"]),
                "ProfileVersion": handler.profile_version,
            })
            if _missing(value):
                findings.append((f"{field.upper()}_MISSING", "Review", f"Required field {field} was not extracted."))
                score -= 25
    existing_flags = [flag.strip() for flag in str(audited.get("Flags") or "").split(";") if flag.strip()]
    findings.extend(("PARSER_CHECK", "Error" if audited.get("Status") == "Error" else "Review", flag) for flag in existing_flags)
    score = max(0, min(100, score))
    severity = "Error" if audited.get("Status") == "Error" else ("Review" if findings else "OK")
    codes = [code for code, _, _ in findings]
    audited["Status"] = severity
    audited["Flags"] = "; ".join(dict.fromkeys(existing_flags + codes))
    audited["Confidence"] = score
    audited["ConfidenceGrade"] = "High" if score >= 90 else ("Medium" if score >= 70 else "Low")
    audited["ProfileVersion"] = handler.profile_version if handler else "unclassified"
    audited["ValidationFindings"] = "; ".join(codes)
    audited["OCRUsed"] = bool(preflight.get("ocr_used"))
    finding_rows = [{
        "SourceFile": audited.get("SourceFile"), "ReturnType": audited.get("ReturnType"),
        "Code": code, "Severity": severity, "AffectedFields": "*", "Message": message,
    } for code, severity, message in findings]
    return audited, finding_rows, evidence
