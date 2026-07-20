import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ENGINE = Path(__file__).resolve().parents[1] / "web_app" / "engine"
sys.path.insert(0, str(ENGINE))

from document_analyser import handler_registry


class HandlerRegistryTests(unittest.TestCase):
    def test_pf_kind_selects_its_registered_parser(self):
        expected = {"ReturnType": "PF", "DocKind": "Return"}
        with patch.object(handler_registry, "parse_pf_ecr", return_value=expected) as parser:
            self.assertIs(handler_registry._parse_pf(None, "redacted.pdf", "Return"), expected)
        parser.assert_called_once_with(None, "redacted.pdf")

    def test_registered_handler_owns_validation_and_normalization(self):
        original = handler_registry.REGISTERED_HANDLERS["TDS"]
        handler_registry.REGISTERED_HANDLERS["TDS"] = handler_registry.RegisteredHandler(
            "TDS", lambda _pdf, _fname, _kind: {"PrimaryAmount": 42}, lambda _result: ["CHECK"]
        )
        try:
            record, detail = handler_registry.run_registered(
                "TDS", None, "redacted.pdf", "Challan",
                lambda result, filename, flags: {"file": filename, "flags": flags, "amount": result["PrimaryAmount"]},
            )
        finally:
            handler_registry.REGISTERED_HANDLERS["TDS"] = original
        self.assertIn("file", record)
        self.assertEqual(record["flags"], ["CHECK"])
        self.assertIsInstance(detail, dict)


if __name__ == "__main__":
    unittest.main()
