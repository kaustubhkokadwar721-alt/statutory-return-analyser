import sys
import unittest
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[1] / "web_app" / "engine"
sys.path.insert(0, str(ENGINE))

from document_analyser.audit import audit_record, classify_document, preflight_pdf
from web_bootstrap import classify_ocr_probe


class _Page:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


class _Pdf:
    def __init__(self, *pages):
        self.pages = [_Page(page) for page in pages]


class AuditTests(unittest.TestCase):
    def test_classifies_a_known_gstr1_form(self):
        result = classify_document("GSTR-1 GSTIN of the supplier")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["winner"]["return_type"], "GSTR1")
        self.assertEqual(result["winner"]["doc_kind"], "Return")

    def test_rejects_two_equally_likely_forms(self):
        result = classify_document("GSTR-1 GSTR-3B")
        self.assertFalse(result["accepted"])
        self.assertEqual(result["margin"], 0)

    def test_preflight_marks_image_only_pdf_for_local_ocr(self):
        preflight = preflight_pdf(_Pdf("", " "))
        self.assertTrue(preflight["needs_ocr"])

    def test_preflight_does_not_read_remaining_pages_after_empty_first_page(self):
        class UnreadableLaterPage:
            def extract_text(self):
                raise AssertionError("preflight should stop after page 1")

        pdf = _Pdf("")
        pdf.pages.append(UnreadableLaterPage())
        preflight = preflight_pdf(pdf)
        self.assertTrue(preflight["needs_ocr"])
        self.assertEqual(preflight["pages"], 2)

    def test_first_page_shipping_bill_probe_stops_after_identification(self):
        result = classify_ocr_probe(
            "SHIPPING BILL IEC/Br 1234567890 FOB VALUE 1000 RODTEP 20")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["return_type"], "SB")
        self.assertEqual(result["ocr_policy"], "identify_then_skip")

    def test_rodtep_alone_does_not_identify_a_shipping_bill(self):
        result = classify_ocr_probe("Statement showing RODTEP amount")
        self.assertFalse(result["accepted"])

    def test_shipping_probe_tolerates_common_ocr_spacing_and_digit_errors(self):
        result = classify_ocr_probe("INDIAN CUST0MS ED1 SYSTEM SH1PPING B1LL SUMMARY")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["ocr_policy"], "identify_then_skip")

    def test_missing_required_field_cannot_be_ok(self):
        classification = classify_document("GSTR-1 GSTIN of the supplier")
        preflight = preflight_pdf(_Pdf("GSTR-1 GSTIN of the supplier"))
        audited, findings, evidence = audit_record({
            "ReturnType": "GSTR1", "DocKind": "Return", "EntityID": "Unknown",
            "PeriodDate": "2025-04-01", "Status": "OK", "Flags": "", "SourceFile": "redacted.pdf",
        }, classification, preflight)
        self.assertEqual(audited["Status"], "Review")
        self.assertLess(audited["Confidence"], 90)
        self.assertIn("ENTITYID_MISSING", audited["ValidationFindings"])
        self.assertEqual(len(evidence), 2)
        self.assertTrue(findings)


if __name__ == "__main__":
    unittest.main()
