import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ENGINE = Path(__file__).resolve().parents[1] / "web_app" / "engine"
sys.path.insert(0, str(ENGINE))

from document_analyser.audit import classify_document
from document_analyser.form16a import parse_form16a
from document_analyser import handler_registry
from web_bootstrap import classify_ocr_probe


class _Page:
    def __init__(self, text, tables):
        self.text = text
        self.tables = tables

    def extract_text(self):
        return self.text

    def extract_tables(self):
        return self.tables


class _Pdf:
    def __init__(self, *pages):
        self.pages = list(pages)


def _certificate(*, payment_total="300.00", summary_deposited="30.00"):
    page_one_text = """
FORM NO. 16A
Certificate under section 203 of the Income-tax Act, 1961 for tax deducted at source
Certificate No.CERT001 Last updated on 06-Aug-2025
"""
    page_one_table = [
        ["FORM NO. 16A"],
        ["Certificate No.CERT001", "Last updated on 06-Aug-2025"],
        ["Name and address of the deductor", "Name and address of the deductee"],
        ["EXAMPLE DEDUCTOR PRIVATE LIMITED\nPUNE", "EXAMPLE DEDUCTEE LLP\nMUMBAI"],
        ["PAN of the deductor", "TAN of the deductor", "PAN of the deductee"],
        ["ABCDE1234F", "ABCD12345E", "FGHIJ5678K"],
        ["CIT (TDS)", "Assessment Year", "Period"],
        ["Commissioner", "2026-27", "From\n01-Apr-2025", "To\n30-Jun-2025"],
        ["Summary of payment"],
        ["Sl. No.", "Amount paid/ credited", "Nature of payment**", "Deductee Reference No.", "Date of payment/ credit"],
        ["1", "100.00", "194C", "REF-1", "10-04-2025"],
        ["2", "200.00", "194C", "", "12-05-2025"],
        ["Total (Rs.)", payment_total],
        ["Summary of tax deducted at source in respect of Deductee"],
        ["Quarter", "Receipt Numbers of Original Quarterly Statements of TDS", "Amount of Tax Deducted", "Amount of Tax Deposited"],
        ["Q1", "RECEIPT1", "30.00", summary_deposited],
        ["I. DETAILS OF TAX DEDUCTED AND DEPOSITED THROUGH BOOK ADJUSTMENT"],
        ["Total (Rs.)"],
        ["II. DETAILS OF TAX DEDUCTED AND DEPOSITED THROUGH CHALLAN"],
        ["Sl. No.", "Tax deposited", "BSR Code", "Date", "Challan Serial Number", "Status"],
        ["1", "10.00", "0000001", "07-05-2025", "10001", "F"],
    ]
    page_two_text = """
Certificate Number:CERT001 TAN of Deductor:ABCD12345E PAN of Deductee:FGHIJ5678K Assessment Year:2026-27
II. DETAILS OF TAX DEDUCTED AND DEPOSITED IN THE CENTRAL GOVERNMENT ACCOUNT THROUGH CHALLAN
Verification
I, TEST SIGNATORY, working in the capacity of AUTHORISED SIGNATORY do hereby certify that a sum of Rs. 30.00 has been deducted and a sum of Rs. 30.00 has been deposited to the credit of the Central Government.
Place PUNE
Date 14-Aug-2025
Designation:AUTHORISED SIGNATORY Full Name:TEST SIGNATORY
"""
    page_two_table = [
        ["II. DETAILS OF TAX DEDUCTED AND DEPOSITED THROUGH CHALLAN"],
        ["Sl. No.", "Tax deposited", "BSR Code", "Date", "Challan Serial Number", "Status"],
        ["2", "20.00", "0000001", "07-06-2025", "10002", "F"],
        ["Total (Rs.)", "30.00"],
    ]
    return _Pdf(_Page(page_one_text, [page_one_table]), _Page(page_two_text, [page_two_table]))


class Form16AParserTests(unittest.TestCase):
    def test_classifies_form16a_as_native_only_tds_certificate(self):
        result = classify_document(
            "FORM NO. 16A Certificate under section 203 TAN of the deductor "
            "INCOME TAX DEPARTMENT DATE OF DEPOSIT NATURE OF PAYMENT"
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(result["winner"]["return_type"], "TDS")
        self.assertEqual(result["winner"]["doc_kind"], "Certificate")
        self.assertEqual(result["winner"]["handler"].ocr_policy, "native_only")
        self.assertEqual(classify_ocr_probe("FORM NO. 16A Certificate under section 203")["ocr_policy"], "native_only")

    def test_parses_multi_page_certificate_and_reconciles_every_total(self):
        result = parse_form16a(_certificate(), "synthetic.pdf")

        self.assertEqual(result["EntityID"], "ABCD12345E")
        self.assertEqual(result["CounterpartyID"], "FGHIJ5678K")
        self.assertEqual(result["FY"], "2025-26")
        self.assertEqual(result["Quarter"], "Q1")
        self.assertEqual(result["Payment Count"], 2)
        self.assertEqual(result["Deposit Count"], 2)
        self.assertEqual(result["Payment Total"], 300.0)
        self.assertEqual(result["Tax Deposited"], 30.0)
        self.assertEqual(result["Deposit Detail Total"], 30.0)
        self.assertEqual(result["Validation Status"], "pass")
        self.assertEqual(result["Validation Flags"], [])
        self.assertEqual(result["Exception Count"], 0)
        self.assertTrue(all(check["Status"] == "pass" for check in result["Validation Checks"]))
        self.assertEqual([row["Payment S.No."] for row in result["Payments"]], [1, 2])
        self.assertEqual([row["Deposit S.No."] for row in result["Deposits"]], [1, 2])

    def test_mismatches_fail_closed_with_specific_flags(self):
        result = parse_form16a(
            _certificate(payment_total="301.00", summary_deposited="31.00"),
            "synthetic-mismatch.pdf",
        )

        self.assertEqual(result["Validation Status"], "fail")
        self.assertIn("PAYMENT_TOTAL", result["Validation Flags"])
        self.assertIn("DEPOSITS_VS_QUARTERLY_SUMMARY", result["Validation Flags"])
        self.assertIn("VERIFICATION_TAX_DEPOSITED", result["Validation Flags"])

    def test_registry_dispatches_certificate_to_form16a_parser(self):
        expected = {"ReturnType": "TDS", "DocKind": "Certificate", "PrimaryAmount": 30}
        with patch.object(handler_registry, "parse_form16a", return_value=expected) as parser:
            self.assertIs(handler_registry._parse_tds(None, "synthetic.pdf", "Certificate"), expected)
        parser.assert_called_once_with(None, "synthetic.pdf")

    def test_rejects_text_only_or_ocr_adapter(self):
        class TextPage:
            def extract_text(self):
                return "FORM NO. 16A Certificate under section 203"

        with self.assertRaisesRegex(ValueError, "native ruled-table"):
            parse_form16a(_Pdf(TextPage()), "ocr.pdf")


if __name__ == "__main__":
    unittest.main()
