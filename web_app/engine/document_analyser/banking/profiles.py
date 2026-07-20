"""Versioned layout profiles for supported bank documents."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class BankProfile:
    code: str
    bank: str
    document_type: str
    version: str
    anchors: tuple[tuple[str, int], ...]
    required_headers: tuple[str, ...] = ()
    balance_is_debt: bool = False
    parser: str = "table"

    def score(self, text: str) -> tuple[int, list[str]]:
        upper = text.upper()
        hits = [(marker, weight) for marker, weight in self.anchors if marker in upper]
        return min(100, sum(weight for _, weight in hits)), [marker for marker, _ in hits]


PROFILES = (
    BankProfile(
        "idfc-fd",
        "IDFC FIRST Bank",
        "Fixed Deposit Statement",
        "idfc-fd-v1",
        (
            ("IDFC FIRST", 35),
            ("LIST OF FIXED DEPOSITS", 40),
            ("FD ACCOUNT NO", 25),
            ("MATURITY AMOUNT", 10),
        ),
        ("fd account no", "principal amount", "maturity date"),
        parser="deposit_table",
    ),
    BankProfile(
        "hdfc-interest",
        "HDFC Bank",
        "Deposit Interest Certificate",
        "hdfc-interest-v1",
        (
            ("HDFC BANK", 35),
            ("DETAILS OF INTEREST", 35),
            ("DEPOSIT NO", 20),
            ("GROSS INTEREST", 20),
        ),
        ("deposit no", "deposit amount", "gross interest"),
        parser="deposit_table",
    ),
    BankProfile(
        "axis",
        "Axis Bank",
        "Bank Statement",
        "axis-account-v1",
        (
            ("AXIS BANK", 35),
            ("STATEMENT OF AXIS BANK ACCOUNT", 40),
            ("TRAN DATE", 10),
            ("OPENING BALANCE", 10),
            ("CLOSING BALANCE", 10),
        ),
        ("tran date", "particulars", "debit", "credit", "balance"),
    ),
    BankProfile(
        "sbi",
        "State Bank of India",
        "Bank Statement",
        "sbi-account-v1",
        (
            ("STATE BANK OF INDIA", 35),
            ("STATEMENT OF ACCOUNT", 35),
            ("ACCOUNT NUMBER", 10),
            ("ACCOUNT DESCRIPTION", 15),
            ("REF NO./CHEQUE NO", 15),
            ("BALANCE", 10),
        ),
        ("date", "debit", "credit", "balance"),
    ),
    BankProfile(
        "bom",
        "Bank of Maharashtra",
        "Bank Statement",
        "bom-account-v1",
        (
            ("BANK OF MAHARASHTRA", 45),
            ("MAHABANK.CO.IN", 35),
            ("ACCOUNT DETAILS", 15),
            ("CHEQUE/REFERENCE NO", 15),
            ("AVAILABLE BALANCE", 10),
        ),
        ("date", "particulars", "debit", "credit", "balance"),
    ),
    BankProfile(
        "federal",
        "Federal Bank",
        "Bank Statement",
        "federal-account-v1",
        (
            ("FEDERAL BANK", 45),
            ("BALANCE TYPE", 15),
            ("WITHDRAWALS", 15),
            ("DEPOSITS", 15),
        ),
        ("date", "particulars", "withdrawals", "deposits", "balance"),
        balance_is_debt=True,
    ),
    BankProfile(
        "citi",
        "Citibank",
        "Bank Statement",
        "citi-details-v1",
        (
            ("CITIDIRECT", 35),
            ("ACCOUNT STATEMENT DETAILS REPORT", 40),
            ("CHEQUE AMOUNT/TRANSACTION AMOUNT", 15),
            ("DEBIT/CREDIT", 10),
        ),
        parser="key_value",
    ),
)


UNSUPPORTED_PROFILES = (
    (
        "Investment Statement",
        (
            ("MUTUAL FUND", 35),
            ("FOLIO NO", 25),
            ("BALANCE UNITS", 25),
            ("NAV(INR)", 20),
        ),
    ),
    (
        "Foreign Bank Statement",
        (
            ("CITIZENS", 30),
            ("CITIZENS BANK", 40),
            ("COMMERCIAL ACCOUNT STATEMENT", 40),
            ("COMMERCIAL CHECKING", 30),
            ("PROVIDENCE, RI", 30),
            ("MEMBER FDIC", 20),
        ),
    ),
)


def _page_bank_markers(page_text: list[str]) -> set[str]:
    banks = set()
    for page in page_text:
        scored = []
        for profile in PROFILES:
            score, _ = profile.score(page)
            if score:
                scored.append((score, profile.bank))
        scored.sort(reverse=True)
        if scored:
            runner = scored[1][0] if len(scored) > 1 else 0
            if scored[0][0] >= 60 and scored[0][0] - runner >= 15:
                banks.add(scored[0][1])
    return banks


def classify_bank_document(text: str, page_text: list[str]) -> dict:
    """Score known layouts and reject ties, mixed bundles, and adjacent documents."""
    upper = (text or "").upper()
    unsupported = []
    for name, anchors in UNSUPPORTED_PROFILES:
        hits = [(marker, weight) for marker, weight in anchors if marker in upper]
        score = sum(weight for _, weight in hits)
        if score:
            unsupported.append((score, name, [marker for marker, _ in hits]))
    unsupported.sort(reverse=True)

    candidates = []
    for profile in PROFILES:
        score, hits = profile.score(upper)
        if score:
            candidates.append({"profile": profile, "score": score, "markers": hits})
    candidates.sort(key=lambda item: item["score"], reverse=True)

    page_banks = _page_bank_markers(page_text)
    mixed = len(page_banks) > 1
    winner = candidates[0] if candidates else None
    runner = candidates[1]["score"] if len(candidates) > 1 else 0
    unsupported_winner = unsupported[0] if unsupported else None
    accepted = bool(
        winner
        and winner["score"] >= 60
        and winner["score"] - runner >= 15
        and not mixed
        and not (unsupported_winner and unsupported_winner[0] >= winner["score"])
    )
    return {
        "accepted": accepted,
        "winner": winner,
        "candidates": candidates,
        "margin": winner["score"] - runner if winner else 0,
        "mixed": mixed,
        "page_banks": sorted(page_banks),
        "unsupported": unsupported_winner,
    }


def normalise_header(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    aliases = {
        "transaction date": "date",
        "tran date": "date",
        "post date": "date",
        "value date": "value date",
        "details": "description",
        "particulars": "description",
        "transaction description": "description",
        "chq no": "reference",
        "ref no cheque no": "reference",
        "cheque reference no": "reference",
        "cheque details": "reference",
        "withdrawals": "debit",
        "deposits": "credit",
        "balance type": "balance type",
        "fd account no": "deposit number",
        "deposit no": "deposit number",
        "fd date": "deposit date",
        "principal amount": "principal",
        "deposit amount": "principal",
        "int rate": "interest rate",
        "roi p a": "interest rate",
        "maturity amount": "maturity amount",
        "gross interest paid credited during the year": "gross interest",
        "interest paid": "interest paid",
        "tds paid": "tds",
        "tds amount": "tds",
    }
    cleaned = text.strip()
    for alias, canonical in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if cleaned == alias or cleaned.startswith(alias + " "):
            return canonical
    return cleaned
