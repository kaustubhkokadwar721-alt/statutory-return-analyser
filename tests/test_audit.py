import sys
import unittest
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[1] / "web_app" / "engine"
sys.path.insert(0, str(ENGINE))

from document_analyser.audit import audit_record, classify_document, preflight_pdf


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
