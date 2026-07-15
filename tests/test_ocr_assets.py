import sys
import unittest
from pathlib import Path


WEB = Path(__file__).resolve().parents[1] / "gstr_web"
sys.path.insert(0, str(WEB))

import vendor_ocr


class OCRAssetTests(unittest.TestCase):
    def test_vendored_ocr_assets_match_the_pinned_hashes(self):
        self.assertTrue(vendor_ocr.verify())


if __name__ == "__main__":
    unittest.main()
