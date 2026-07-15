import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gstr_web" / "engine"))

from gstr_analyser.audit import audit_record
from gstr_analyser.ocr import OCRTextPdf, read_ocr_sidecar


class OCRAdapterTests(unittest.TestCase):
    def test_sidecar_preserves_page_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = pathlib.Path(directory) / "scan.pdf"
            (pathlib.Path(str(pdf_path) + ".ocr.txt")).write_text("first\fsecond", encoding="utf-8")
            pdf = OCRTextPdf(read_ocr_sidecar(str(pdf_path)))
        self.assertEqual([page.extract_text() for page in pdf.pages], ["first", "second"])

    def test_ocr_record_is_always_reviewed(self):
        handler = type("Handler", (), {"profile_version": "v1", "required_fields": ("EntityID",)})()
        classification = {"winner": {"handler": handler, "score": 90, "markers": ["TAN"]}, "accepted": True}
        record = {"SourceFile": "scan.pdf", "ReturnType": "TDS", "Status": "OK", "Flags": "", "EntityID": "ABCDE1234F"}
        audited, findings, evidence = audit_record(record, classification, {"sparse_text": False, "ocr_used": True})
        self.assertEqual(audited["Status"], "Review")
        self.assertTrue(audited["OCRUsed"])
        self.assertIn("OCR_TEXT", audited["ValidationFindings"])
        self.assertEqual(evidence[0]["Method"], "local OCR + form parser")
        self.assertEqual(findings[0]["Code"], "OCR_TEXT")


if __name__ == "__main__":
    unittest.main()
