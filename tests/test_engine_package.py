import sys
import unittest
from pathlib import Path


WEB = Path(__file__).resolve().parents[1] / "gstr_web"
sys.path.insert(0, str(WEB))

import package_engine


class EnginePackageTests(unittest.TestCase):
    def test_browser_archive_matches_canonical_engine_source(self):
        self.assertTrue(package_engine.verify())


if __name__ == "__main__":
    unittest.main()
