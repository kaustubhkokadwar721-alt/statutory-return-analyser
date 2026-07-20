import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web_app" / "engine"))

from document_analyser.banking.parser import (
    extract_table_transactions,
    infer_balances,
    signed_balance,
    validate_statement,
)
from document_analyser.banking.profiles import PROFILES, classify_bank_document


class FakePage:
    def __init__(self, tables):
        self.tables = tables

    def extract_tables(self):
        return self.tables


class FakePdf:
    def __init__(self, pages):
        self.pages = [FakePage(tables) for tables in pages]


def profile(code):
    return next(item for item in PROFILES if item.code == code)


class BankClassificationTests(unittest.TestCase):
    def test_axis_counterparty_names_do_not_create_mixed_document(self):
        text = (
            "AXIS BANK\nStatement of Axis Bank Account No: 123456789\n"
            "Tran Date Particulars Debit Credit Balance\nOpening Balance\n"
            "Payment to State Bank of India and HDFC Bank\nClosing Balance"
        )
        result = classify_bank_document(text, [text])
        self.assertTrue(result["accepted"])
        self.assertFalse(result["mixed"])
        self.assertEqual(result["winner"]["profile"].code, "axis")

    def test_mutual_fund_is_not_treated_as_bank_statement(self):
        text = "KOTAK MUTUAL FUND\nFolio No. 123\nNAV(INR)\nBalance Units"
        result = classify_bank_document(text, [text])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["unsupported"][1], "Investment Statement")


class BankTableTests(unittest.TestCase):
    def test_header_mapping_continues_on_next_page(self):
        pdf = FakePdf([
            [[
                ["Tran Date", "Particulars", "Debit", "Credit", "Balance"],
                ["01-04-2025", "Payment", "100.00", "", "900.00"],
            ]],
            [[
                ["02-04-2025", "Receipt", "", "50.00", "950.00"],
                ["", "CLOSING BALANCE", "", "", "950.00"],
            ]],
        ])
        rows, _ = extract_table_transactions(pdf, profile("axis"))
        self.assertEqual(len(rows), 2)
        metadata = {"OpeningBalance": None, "ClosingBalance": None, "PeriodFrom": None, "PeriodTo": None}
        infer_balances(metadata, rows)
        findings, reconciliation = validate_statement(metadata, rows)
        self.assertEqual(findings, [])
        self.assertEqual(reconciliation["Status"], "PASS")
        self.assertAlmostEqual(metadata["OpeningBalance"], 1000.0)
        self.assertAlmostEqual(metadata["ClosingBalance"], 950.0)

    def test_debt_balance_is_normalised_to_negative(self):
        self.assertEqual(signed_balance("1,250.00", "DR"), -1250.0)
        self.assertEqual(signed_balance("1,250.00", "CR"), 1250.0)

    def test_balance_conflict_fails_closed(self):
        rows = [{
            "TransactionDate": "2025-04-01",
            "Debit": 100.0,
            "Credit": 0.0,
            "Balance": 950.0,
        }]
        metadata = {"OpeningBalance": 1000.0, "ClosingBalance": 950.0}
        findings, reconciliation = validate_statement(metadata, rows)
        self.assertEqual(reconciliation["Status"], "REVIEW")
        self.assertIn("RUNNING_BALANCE_MISMATCH", {item["Code"] for item in findings})


if __name__ == "__main__":
    unittest.main()
