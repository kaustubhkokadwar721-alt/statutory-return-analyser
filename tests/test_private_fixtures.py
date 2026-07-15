"""Optional local regression checks. The directories are intentionally git-ignored."""

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "gstr_web" / "engine"
FIXTURES = ROOT / "tests" / "private_fixtures"
EXPECTED = ROOT / "tests" / "private_expected"
sys.path.insert(0, str(ENGINE))

from gstr_analyser.pipeline_csv import run_unified_pipeline


@unittest.skipUnless(FIXTURES.is_dir() and EXPECTED.is_dir(), "private client fixtures are not installed")
class PrivateFixtureTests(unittest.TestCase):
    def test_expected_fields_match_local_goldens(self):
        with tempfile.TemporaryDirectory() as output_dir:
            result = run_unified_pipeline(str(FIXTURES), output_dir)
        rows = {row["SourceFile"]: row for row in result["consolidated"]}
        for expected_file in sorted(EXPECTED.glob("*.json")):
            expected = json.loads(expected_file.read_text(encoding="utf-8"))
            filename = expected["SourceFile"]
            self.assertIn(filename, rows, filename)
            for field, value in expected["Expected"].items():
                self.assertEqual(rows[filename].get(field), value, f"{filename}: {field}")


if __name__ == "__main__":
    unittest.main()
