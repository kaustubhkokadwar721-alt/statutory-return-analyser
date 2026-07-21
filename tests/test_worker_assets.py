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


if __name__ == "__main__":
    unittest.main()
