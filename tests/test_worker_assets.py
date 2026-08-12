import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web_app"


class WorkerAssetTests(unittest.TestCase):
    def test_parser_runs_in_a_web_worker(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        worker = (WEB / "engine.worker.js").read_text(encoding="utf-8")
        index = (WEB / "index.html").read_text(encoding="utf-8")

        self.assertIn('new Worker("./engine.worker.js")', app)
        self.assertIn('importScripts(new URL("./pyodide/pyodide.js"', worker)
        self.assertNotIn('<script src="./pyodide/pyodide.js"></script>', index)
        self.assertNotIn("localStorage", worker)
        self.assertNotIn("indexedDB", worker)

    def test_run_progress_reports_real_work(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        index = (WEB / "index.html").read_text(encoding="utf-8")
        pipeline = (WEB / "engine" / "document_analyser" / "statutory_pipeline.py").read_text(encoding="utf-8")

        self.assertIn('id="progressParsed"', index)
        self.assertIn('id="progressFlags"', index)
        self.assertIn('id="progressWorkbook"', index)
        self.assertIn("handleEngineProgress", app)
        self.assertIn("Validation complete.", pipeline)
        self.assertIn("Workbook written.", pipeline)

    def test_detection_notice_precedes_the_file_queue(self):
        index = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertLess(index.index('id="runHint"'), index.index('id="filesTable"'))

    def test_two_worker_pool_has_one_final_combiner(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        worker = (WEB / "engine.worker.js").read_text(encoding="utf-8")

        self.assertIn("ensureSecondaryWorker", app)
        self.assertIn("balanceFilesForWorkers", app)
        self.assertIn('engineRequest("combine"', app)
        self.assertIn('action === "combine"', worker)

    def test_form16a_is_presented_as_a_distinct_supported_document(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        index = (WEB / "index.html").read_text(encoding="utf-8")

        self.assertIn('<li class="type">TDS Challan</li>', index)
        self.assertIn('>Form 16A</li>', index)
        self.assertIn("any mix of the ten types", index)
        self.assertIn("Form 16A needs the original digital PDF", index)
        self.assertIn('label: "Form 16A"', app)
        self.assertIn('NativeTextRequired: "Original digital PDF required"', app)

    def test_scanned_form16a_stops_after_identification(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")

        self.assertIn('["identify_then_skip", "native_only"].includes(probe.ocr_policy)', app)
        self.assertIn("Scanned Form 16A identified from page 1", app)


if __name__ == "__main__":
    unittest.main()
