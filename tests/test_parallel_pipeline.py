import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[1] / "web_app" / "engine"
sys.path.insert(0, str(ENGINE))

from document_analyser.statutory_pipeline import combine_shard_results, _normalise_filing_date


def _record(source, return_type, amount, reference):
    return {
        "ReturnType": return_type,
        "DocKind": "Return",
        "EntityID": "TEST123",
        "EntityName": "Synthetic Entity",
        "FY": "2025-26",
        "PeriodDate": "2025-04-01",
        "MonthName": "April",
        "MonthIndex": 1,
        "Status": "OK",
        "Confidence": 100,
        "ConfidenceGrade": "High",
        "ProfileVersion": "test-v1",
        "OCRUsed": False,
        "ValidationFindings": "",
        "Flags": "",
        "PrimaryAmount": amount,
        "DocRef": reference,
        "FilingDate": "2025-04-20",
        "SourceFile": source,
    }


def _shard(record, detail_key):
    raw = {key: [] for key in ("GSTR1", "ESIC", "PF", "PTRC", "TDS", "SB", "EBRC", "EWB")}
    raw[detail_key].append({"SourceFile": record["SourceFile"], "Value": record["PrimaryAmount"]})
    return {
        "consolidated": [record],
        "errors": [],
        "shard_data": {
            "raw_details": raw,
            "gstr3b_analysis": [],
            "sb_items": [],
            "findings": [],
            "evidence": [],
        },
    }


class ParallelPipelineTests(unittest.TestCase):
    def test_iso_filing_date_is_not_reinterpreted(self):
        self.assertEqual(_normalise_filing_date("2025-06-12"), "2025-06-12")

    def test_combines_shards_into_one_workbook(self):
        shards = [
            _shard(_record("one.pdf", "SB", 100, "SB1"), "SB"),
            _shard(_record("two.pdf", "GSTR3B", 200, "ARN2"), "SB"),
        ]
        with tempfile.TemporaryDirectory() as output_dir:
            result = combine_shard_results(shards, output_dir)
            self.assertEqual(len(result["consolidated"]), 2)
            self.assertEqual(sum(row["Records"] for row in result["dashboard"]), 2)
            self.assertEqual(result["errors"], [])
            workbook = Path(result["workbook"])
            self.assertTrue(workbook.is_file())
            with zipfile.ZipFile(workbook) as archive:
                workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
            self.assertIn('name="Consolidated"', workbook_xml)
            self.assertIn('name="Dashboard"', workbook_xml)
            self.assertIn('name="SB"', workbook_xml)


if __name__ == "__main__":
    unittest.main()
