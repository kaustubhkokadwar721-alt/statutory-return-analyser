"""Optional local bank regression checks; source PDFs remain outside Git."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "web_app" / "engine"
EXPECTED = ROOT / "tests" / "private_bank_expected"
FIXTURES = Path(os.environ.get("BANK_PRIVATE_FIXTURES", ""))
sys.path.insert(0, str(ENGINE))

from document_analyser.banking import run_bank_pipeline


@unittest.skipUnless(
    os.environ.get("BANK_PRIVATE_FIXTURES") and FIXTURES.is_dir() and EXPECTED.is_dir(),
    "private bank fixtures are not configured",
)
class PrivateBankFixtureTests(unittest.TestCase):
    def test_expected_fields_match_local_goldens(self):
        with tempfile.TemporaryDirectory() as output_dir:
            result = run_bank_pipeline(str(FIXTURES), output_dir)
        rows = {row["SourceFile"]: row for row in result["consolidated"]}
        errors = {row["File"]: row for row in result["errors"]}
        for expected_file in sorted(EXPECTED.glob("*.json")):
            expected = json.loads(expected_file.read_text(encoding="utf-8"))
            filename = expected["SourceFile"]
            actual = errors.get(filename) if expected.get("Error") else rows.get(filename)
            self.assertIsNotNone(actual, filename)
            for field, value in expected["Expected"].items():
                self.assertEqual(actual.get(field), value, f"{filename}: {field}")


if __name__ == "__main__":
    unittest.main()
