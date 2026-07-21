import inspect
import sys
import unittest
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[1] / "web_app" / "engine"
sys.path.insert(0, str(ENGINE))

from document_analyser.gstr1.checks import run_sanity_checks_gstr1


class Gstr1CheckContractTests(unittest.TestCase):
    def test_sanity_check_contract_accepts_totals_and_metadata(self):
        parameters = inspect.signature(run_sanity_checks_gstr1).parameters
        self.assertEqual(tuple(parameters), ("section_totals", "meta"))


if __name__ == "__main__":
    unittest.main()
