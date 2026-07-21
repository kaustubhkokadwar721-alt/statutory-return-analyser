import sys
import unittest
from pathlib import Path

import pandas as pd


ENGINE = Path(__file__).resolve().parents[1] / "web_app" / "engine"
sys.path.insert(0, str(ENGINE))

from document_analyser.gstr3b.checks import run_sanity_checks_gstr3b
from document_analyser.gstr3b.reporting import build_analysis_row


class GSTR3BReportingTests(unittest.TestCase):
    def setUp(self):
        self.parsed = {
            "Metadata": {
                "Year": "2025-26", "Period": "February", "Period_Year": "Feb-26",
                "GSTIN": "27AAAAA0000A1Z5", "Legal_Name": "Example Limited",
                "Trade_Name": "Example", "ARN": "AA2702260000001",
                "Date_of_ARN": "18/03/2026",
            },
            "Table_3_1": pd.DataFrame([
                ["(a) Outward taxable supplies (other than zero rated, nil rated and exempted)", 100, 18, 9, 9],
                ["(b) Outward taxable supplies (zero rated)", 200, 10, 0, 0],
                ["(c ) Other outward supplies (nil rated, exempted)", 300, 0, 0, 0],
                ["(d) Inward supplies (liable to reverse charge)", 50, 5, 4.5, 4.5],
            ], columns=["Nature of Supplies", "Total taxable value", "Integrated tax", "Central tax", "State/UT tax"]),
            "Table_4_ITC": pd.DataFrame([
                ["(1) Import of goods", 20, 10, 10, "A. ITC Available"],
                ["(5) All other ITC", 5, 2, 2, "A. ITC Available"],
                ["(1) Rules 38, 42 and 43", 2, 1, 1, "B. ITC Reversed"],
                ["C. Net ITC available (A-B)", 23, 11, 11, "C. Net ITC available (A-B)"],
                ["(2) Ineligible ITC under section 16(4)", 99, 99, 99, "C. Net ITC available (A-B)"],
            ], columns=["Details", "Integrated tax", "Central tax", "State/UT tax", "Section"]),
            "Table_6_1": pd.DataFrame([
                ["(A) Other than reverse charge", "Integrated tax", 10, 3, 2, 1, 2],
                ["(A) Other than reverse charge", "Central tax", 4, 5, 0, 3, 4],
                ["(A) Other than reverse charge", "State/UT tax", 6, 0, 5, 5, 6],
                ["(B) Reverse charge", "Integrated tax", 0, 0, 0, 7, 8],
                ["(B) Reverse charge", "Central tax", 0, 0, 0, 9, 10],
                ["(B) Reverse charge", "State/UT tax", 0, 0, 0, 11, 12],
            ], columns=["Section", "Description", "ITC_Integrated", "ITC_Central", "ITC_State_UT", "Interest_paid_cash", "Late_fee_paid_cash"]),
        }

    def test_builds_analysis_ready_row(self):
        row, missing = build_analysis_row(self.parsed, "return.pdf")

        self.assertEqual(missing, [])
        self.assertEqual(row["Return Period"], "2026-02")
        self.assertEqual(row["Date of filing"], "2026-03-18")
        self.assertEqual(row["Output IGST"], 28)
        self.assertEqual(row["RCM CGST Payable"], 4.5)
        self.assertEqual(row["Total Input IGST"], 25)
        self.assertEqual(row["Ineligible IGST"], 2)
        self.assertEqual(row["Net Input IGST"], 23)
        self.assertEqual(row["IGST to CGST"], 4)
        self.assertEqual(row["CGST to IGST"], 3)
        self.assertEqual(row["SGST to IGST"], 2)
        self.assertEqual(row["IGST Payable"], 18)
        self.assertEqual(row["CGST Payable"], 4.5)
        self.assertEqual(row["SGST Payable"], 2.5)
        self.assertEqual(row["Interest paid"], 36)
        self.assertEqual(row["Late Fees paid"], 42)

    def test_missing_table_is_blank_and_flagged_not_zero(self):
        self.parsed["Table_6_1"] = None
        row, missing = build_analysis_row(self.parsed, "return.pdf")

        self.assertIsNone(row["IGST to IGST"])
        self.assertIsNone(row["IGST Payable"])
        self.assertIn("IGST to IGST", missing)
        self.assertIn("IGST Payable", missing)

    def test_itc_check_uses_only_reported_net_row(self):
        _, findings = run_sanity_checks_gstr3b(
            {"Table_4_ITC": self.parsed["Table_4_ITC"]},
            "27AAAAA0000A1Z5",
            "Feb-26",
        )

        self.assertFalse(any(row["Check"].startswith("ITC_Math") for row in findings))


if __name__ == "__main__":
    unittest.main()
