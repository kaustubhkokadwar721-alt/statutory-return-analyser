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


if __name__ == "__main__":
    unittest.main()
