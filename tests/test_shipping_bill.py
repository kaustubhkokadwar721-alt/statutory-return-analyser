import sys
import unittest
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[1] / "web_app" / "engine"
sys.path.insert(0, str(ENGINE))

from document_analyser.shipping_bill import parse_part1, sb_detail_rows, sb_invoice_summary_rows


def word(text, x0, top):
    return {"text": text, "x0": x0, "x1": x0 + 12, "top": top, "bottom": top + 8}


def line(*words):
    return {"top": words[0]["top"], "words": list(words),
            "text": " ".join(item["text"] for item in words)}


class ShippingBillTests(unittest.TestCase):
    def test_reads_rodtep_by_column_and_keeps_part1_invoice_summary(self):
        claim_header = line(
            word("4.IGST", 350, 100), word("VALUE", 378, 100),
            word("5.RODTEP", 420, 100), word("AMT", 462, 100),
            word("6.ROSCTL", 506, 100), word("AMT", 548, 100),
        )
        claim_values = line(word("0", 96, 110), word("0", 162, 110),
                            word("409829", 441, 110), word("0", 533, 110))
        invoice_header = line(
            word("1.SNO", 346, 120), word("2.INV", 398, 120),
            word("NO.", 420, 120), word("3.", 473, 120),
            word("INV", 482, 120), word("AMT.", 497, 120),
            word("4.CURRENC", 528, 120),
        )
        invoice_row = line(word("1", 356, 130), word("INV-001", 386, 130),
                           word("688290", 482, 130), word("USD", 543, 130))
        cin_header = line(word("4.", 106, 140), word("CIN", 115, 140),
                          word("NO.", 132, 140))
        lines = [claim_header, claim_values, invoice_header, invoice_row, cin_header]
        words = [item for current in lines for item in current["words"]]

        parsed = parse_part1(lines, words)

        self.assertEqual(parsed["rodtep_amt"], 409829)
        self.assertEqual(parsed["rosctl_amt"], 0)
        self.assertEqual(parsed["invoice_summary"], [{
            "sno": 1, "invoice_no": "INV-001", "amount": 688290, "currency": "USD",
        }])
        rows = sb_invoice_summary_rows({"sb_no": "123", "sb_date": "01-APR-25",
                                        "invoice_summary": parsed["invoice_summary"]})
        self.assertEqual(rows[0]["Invoice_No"], "INV-001")

    def test_joins_invoice_summary_to_file_details(self):
        rows = sb_detail_rows({
            "sb_no": "123",
            "sb_date": "01-APR-25",
            "iec": "9876543210",
            "fob_value_inr": 500000,
            "invoice_summary": [
                {"sno": 1, "invoice_no": "INV-001", "amount": 6000, "currency": "USD"},
                {"sno": 2, "invoice_no": "INV-002", "amount": 7000, "currency": "EUR"},
            ],
        })

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["IEC"], "9876543210")
        self.assertEqual(rows[0]["FOB_INR"], 500000)
        self.assertEqual(rows[0]["Invoice_No"], "INV-001")
        self.assertEqual(rows[1]["Invoice_Amount"], 7000)


if __name__ == "__main__":
    unittest.main()
