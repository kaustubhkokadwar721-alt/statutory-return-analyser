import sys
import unittest
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[1] / "web_app" / "engine"
sys.path.insert(0, str(ENGINE))

from document_analyser.audit import classify_document
from document_analyser.form27a import parse_form26q_receipt, parse_form27a
from document_analyser.statutory_pipeline import _reconcile
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
    def __init__(self, text, tables):
        self.pages = [_Page(text, tables)]


def _form27a():
    text = """
File Hash 0000000000001 1011765
Form No. 27A
Form for furnishing information with the statement of deduction / collection of tax at source filed on computer media for the period Q2
(From 01/07/25 to 30/09/25 (dd/mm/yy)#)
1 (a) Tax Deduction Account No. PNEK14089F (d) Financial Year 2025-26
(b) Permanent Account No. AAGCK3531R (e) Assessment year 2026-27
(c) Form No. 26Q (f) Previous receipt number 410004937756573
4 Control totals
Date:11/11/2025
"""
    deductor = [["(a) Name", "EXAMPLE PRIVATE LIMITED"], ["(b) Type of deductor*", "COMPANY"]]
    responsible = [["(a)Name", "TEST PERSON"], ["(b)PAN", "ABCDE1234F"]]
    totals = [
        ["Sr. No.", "Return Type", "No. of deductee / party records", "Amount paid", "Tax deducted", "Tax deposited"],
        ["1", "CORRECTION TYPE (C3)", "4", "3903464.00", "3904.00", "3905.00"],
        ["Total", "", "4", "3903464.00", "3904.00", "3905.00"],
    ]
    return _Pdf(text, [deductor, responsible, totals])


def _form26q_receipt():
    text = """
Acknowledgement Receipt of Income Tax Forms
(Other Than Income Tax Return)
e-Filing Acknowledgement Number Date of e-Filing
534325590111125 11-Nov-2025
RRR Number
770000353839581
Name : EXAMPLE PRIVATE LIMITED
PAN/TAN : PNEK14089F
Form No. : Form 26Q
Assessment Year : -
Financial Year : 2025-26
Quarter : Q2
Filing Type : Correction
"""
    return _Pdf(text, [["e-Filing Acknowledgement Number", "Date of e-Filing"]])


def _record(kind, source, *, entity="PNEK14089F", quarter="Q2", ay="2026-27"):
    return {
        "ReturnType": "TDS", "DocKind": kind, "EntityID": entity,
        "Return Form": "26Q", "Quarter": quarter, "Assessment Year": ay,
        "PeriodDate": "2025-07-01", "SourceFile": source,
        "Status": "OK", "Flags": "", "PrimaryAmount": 0,
    }


class Form27AParserTests(unittest.TestCase):
    def test_classifies_native_only_form27a_and_form26q_receipt(self):
        form = classify_document("FORM NO. 27A CONTROL TOTALS TAX DEDUCTION ACCOUNT NO.")
        receipt = classify_document(
            "ACKNOWLEDGEMENT RECEIPT OF INCOME TAX FORMS FORM NO. : FORM 26Q "
            "E-FILING ACKNOWLEDGEMENT NUMBER RRR NUMBER QUARTER : Q2"
        )
        self.assertEqual((form["winner"]["doc_kind"], form["winner"]["handler"].ocr_policy), ("Form 27A", "native_only"))
        self.assertEqual((receipt["winner"]["doc_kind"], receipt["winner"]["handler"].ocr_policy), ("Form 26Q Receipt", "native_only"))
        self.assertEqual(classify_ocr_probe("FORM NO. 27A CONTROL TOTALS TAX DEDUCTION ACCOUNT NO.")["ocr_policy"], "native_only")

    def test_parses_form27a_metadata_and_control_totals(self):
        result = parse_form27a(_form27a(), "27a.pdf")
        self.assertEqual(result["EntityID"], "PNEK14089F")
        self.assertEqual(result["Return Form"], "26Q")
        self.assertEqual(result["Quarter"], "Q2")
        self.assertEqual(result["Assessment Year"], "2026-27")
        self.assertEqual(result["Deductee Records"], 4)
        self.assertEqual(result["Tax Deposited"], 3905.0)
        self.assertEqual(result["Filing Type"], "CORRECTION TYPE (C3)")
        self.assertEqual(result["Validation Flags"], [])

    def test_parses_26q_receipt_and_derives_assessment_year(self):
        result = parse_form26q_receipt(_form26q_receipt(), "26q.pdf")
        self.assertEqual(result["EntityID"], "PNEK14089F")
        self.assertEqual(result["Quarter"], "Q2")
        self.assertEqual(result["Assessment Year"], "2026-27")
        self.assertEqual(result["Assessment Year Source"], "derived from FY")
        self.assertEqual(result["Acknowledgement Number"], "534325590111125")
        self.assertEqual(result["Validation Flags"], [])

    def test_control_total_mismatch_fails_closed(self):
        pdf = _form27a()
        pdf.pages[0].tables[-1][-1][5] = "3906.00"
        result = parse_form27a(pdf, "27a-mismatch.pdf")
        self.assertEqual(result["Validation Status"], "fail")
        self.assertIn("CONTROL_TAX_DEPOSITED_TOTAL", result["Validation Flags"])

    def test_reconciliation_matches_same_entity_quarter_and_assessment_year(self):
        records = [_record("Form 27A", "27a.pdf"), _record("Form 26Q Receipt", "26q.pdf")]
        rows = _reconcile(records)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Status"], "Matched")
        self.assertEqual(rows[0]["Form 27A Quarter"], "Q2")
        self.assertEqual(rows[0]["Form 26Q Assessment Year"], "2026-27")

    def test_reconciliation_flags_period_mismatch_within_same_entity(self):
        records = [
            _record("Form 27A", "27a.pdf", quarter="Q1"),
            _record("Form 26Q Receipt", "26q.pdf", quarter="Q2"),
        ]
        rows = _reconcile(records)
        self.assertEqual(rows[0]["Status"], "Mismatch")
        self.assertTrue(all("TDS_RETURN_PERIOD_MISMATCH" in row["Flags"] for row in records))

    def test_reconciliation_does_not_compare_different_entities(self):
        records = [
            _record("Form 27A", "27a.pdf", entity="AAAA00000A"),
            _record("Form 26Q Receipt", "26q.pdf", entity="BBBB00000B"),
        ]
        self.assertEqual(_reconcile(records), [])
        self.assertTrue(all(row["Status"] == "OK" for row in records))


if __name__ == "__main__":
    unittest.main()
