import sys
import unittest
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[1] / "gstr_web" / "engine"
sys.path.insert(0, str(ENGINE))

from gstr_analyser.compliance_parsers import parse_tds
from gstr_analyser.handler_registry import _validate_tds


class _Page:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


class _Pdf:
    def __init__(self, text):
        self.pages = [_Page(text)]


class TdsParserTests(unittest.TestCase):
    def test_extracts_payment_matching_fields_from_itns_281(self):
        text = """
ITNS No. : 281
TAN : TEST12345A
Name : Example Services Private Limited
Assessment Year : 2025-26
Financial Year : 2024-25
Major Head : Income Tax (Other than Companies) (0021)
Minor Head : TDS/TCS Payable by Taxpayer (200)
Nature of Payment : 94J
Amount (in Rs.) : \u20b9 1,200
Amount (in words) : Rupees One Thousand Two Hundred Only
CIN : 25043000000001BANK
Mode of Payment : Net Banking
Bank Name : Example Bank
Bank Reference Number : 1234567890
Date of Deposit : 30-Apr-2025
BSR code : 6390031
Challan No : 18530
Tender Date : 30/04/2025
A Tax \u20b9 1,200
B Surcharge \u20b9 0
C Cess \u20b9 0
D Interest \u20b9 0
E Penalty \u20b9 0
F Fee under section 234E \u20b9 0
"""
        result = parse_tds(_Pdf(text), "redacted.pdf")

        self.assertEqual(result["ITNS No"], "281")
        self.assertEqual(result["Major Head Code"], "0021")
        self.assertEqual(result["Minor Head Code"], "200")
        self.assertEqual(result["Payment Mode"], "Net Banking")
        self.assertEqual(result["Bank Name"], "Example Bank")
        self.assertEqual(result["Bank Reference Number"], "1234567890")
        self.assertEqual(result["BSR Code"], "6390031")
        self.assertEqual(result["Tender Date"], "2025-04-30")
        self.assertEqual(result["Amount in Words"], "Rupees One Thousand Two Hundred Only")
        self.assertEqual(_validate_tds({**result, "PrimaryAmount": result["Total Amount Paid"]}), [])

    def test_extracts_pan_schedule_and_new_three_part_breakup(self):
        text = """
PAN : TESTP1234A
Name : Example Individual
Tax Year : 2026-27
Major Head : Income Tax (Other than Companies) (0021)
Minor Head : Schedule C :- TDS on Payment to Resident Contractors and Professionals (800)
Amount (in Rs.) : \u20b9 2
Amount (in words) : Rupees Two Only
CIN : 26071500347638BANK
Acknowledgement Number : CSA0000001
Mode of Payment : UPI
Bank Name : Example Bank
Bank Reference Number : CPAGEXAMPLE
Date of Deposit : 15-Jul-2026
BSR code : 0002271
Challan No : 94678
Tender Date : 15/07/2026
(a) Amount deducted \u20b9 2
(b) Interest \u20b9 0
(c) Fee \u20b9 0
"""
        result = parse_tds(_Pdf(text), "redacted-new.pdf")

        self.assertEqual(result["EntityID"], "TESTP1234A")
        self.assertEqual(result["Taxpayer ID Type"], "PAN")
        self.assertEqual(result["FY"], "2026-27")
        self.assertEqual(result["Tax Year"], "2026-27")
        self.assertEqual(result["Acknowledgement Number"], "CSA0000001")
        self.assertEqual(result["Payment Schedule"], "Schedule C")
        self.assertEqual(result["Payment Description"], "TDS on Payment to Resident Contractors and Professionals (800)")
        self.assertEqual(result["Tax"], 2.0)
        self.assertEqual(result["Crosscheck Diff"], 0.0)
        self.assertIn("SECTION?", _validate_tds({**result, "PrimaryAmount": result["Total Amount Paid"]}))


if __name__ == "__main__":
    unittest.main()
