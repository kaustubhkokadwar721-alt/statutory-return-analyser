# Statutory Return Analyser Web App

The supported product is a browser-only statutory return analyser. PDFs, OCR text,
and generated workbooks stay in browser memory. Nothing is uploaded or saved by the app.

## Run locally

```bash
python -m http.server 8000
```

Open `http://localhost:8000`. The app needs HTTP; opening `index.html` directly does
not work because browsers restrict WebAssembly and local fetches.

## Main parts

```
index.html             page markup
app.js                 browser UI, local OCR, and worker bridge
engine.worker.js       background Pyodide parser; keeps the UI responsive
themes/workspace.css   current visual theme
engine/                maintained parser source
engine.zip             browser package made from engine/
pyodide/ and wheels/   local Python runtime and dependencies
ocr/                   local PDF rendering and OCR runtime
```

`engine/document_analyser/statutory_pipeline.py` handles statutory documents, while
`engine/document_analyser/banking/pipeline.py` handles bank and fixed-deposit documents.
Each document family keeps its specialised profiles and checks in its own module. Do
not edit `engine.zip` directly.

## Rebuild and verify

```bash
python package_engine.py
python package_engine.py --verify
python vendor_ocr.py --verify
```

`build_offline.py` refreshes the local Pyodide runtime and Python wheels when their
versions need to change. It requires internet access only while building, never while
the deployed app is processing documents.
