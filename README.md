# Statutory Return Analyser

Turn statutory-return PDFs — **GSTR-1, GSTR-3B, TDS (ITNS-281), PF ECR, ESIC, PTRC,
and ICEGATE Shipping Bills** — into clean, verified CSV ledgers with a compliance
overview, **entirely in your browser**. No upload, no server, no install.

### ▶ Use it now (one click)

**https://kaustubhkokadwar721-alt.github.io/statutory-return-analyser/**

Drop your PDFs → the engine auto-detects each return type → read the dashboard, download the ledgers.

---

## Why it's safe for client data

Everything runs **client-side** via [Pyodide](https://pyodide.org) (Python compiled to
WebAssembly). Your PDFs are parsed in an in-memory sandbox and never sent anywhere —
open DevTools → Network and watch it stay empty.

The whole app (Python runtime, libraries, fonts) is **vendored locally**, so once the page
loads it makes **zero network calls**. Download the folder and open `index.html` straight
from disk for a fully air-gapped run.

## What you get

Drop any mix of the seven document types. The engine detects each one and produces:

| Output | Contents |
|--------|----------|
| **Overview** (on screen) | KPI cards (documents, clean / review / error), a per-return × FY summary, and an exceptions-first records table with status pills |
| **All_Returns_Consolidated.csv** | Every return on one normalized schema — pivot / SUMIFS ready |
| **Dashboard_Summary.csv** | Filing counts, pass rates, and totals grouped by return type and FY |
| **`<type>`_Details.csv** | Full parsed fields per return type |
| **SB_Items.csv** | Shipping-bill line items — HS code, description, quantity, rate, FOB — one row per item across all bills |

Each row carries a **Status** (OK / Review / Error), the **Flags** that triggered it, the
headline amount, plus traceability metadata: source filename, document reference
(ARN / challan / TRRN / SB number), and filing date. Sanity checks include GSTR-3B
RCM cross-checks and CGST/SGST symmetry, TDS component tie-outs, PF contribution
reconciliation, and PTRC period validation. PTRC also breaks out the salary-slab
particulars where the form version prints them.

Shipping bills get the deepest verification: declared invoice / item / container counts
are checked against what was parsed, the FOB total against the sum of item-level FOB
values, and drawback & RODTEP claims against their per-item rows — so a bill only
shows **OK** when its own arithmetic ties out. Scanned (image-only) shipping bills are
surfaced as *Unreadable* with instructions to OCR them first.

## Design

A single premium theme (`themes/prime.css`): a calm, institutional layout with a
financial serif (Spectral) for headings and a humanist sans (Hanken Grotesk) for data,
with saturated colour reserved for status. All fonts are vendored, so it works offline.

---

## Run locally

No build step. Any static server works:

```bash
cd gstr_web
python -m http.server 8000
# open http://localhost:8000
```

(Opening `index.html` via `file://` also works in most browsers.)

## How it works

```
PDFs (in browser)
  → Pyodide writes them to an in-memory filesystem
  → run_unified_pipeline auto-detects each return type and parses it
     (pdfplumber → pandas → sanity checks → normalized CSVs)
  → app.js reads the CSVs back and renders the dashboard + downloads
```

The browser engine is `gstr_web/engine/` (a Pyodide-friendly build of the parser package);
`web_bootstrap.run("auto", …)` drives `gstr_analyser/pipeline_csv.py`. After editing any
engine file, rebuild `engine.zip` (Python `zipfile`, forward-slash arcnames, rooted at
`engine/`) so the browser picks up the change.

## Repo layout

```
gstr_web/            # the browser app (deployed to Pages)
  index.html         #   UI
  app.js             #   Pyodide glue (boot, run, render dashboard, download)
  themes/prime.css   #   the theme
  fonts/             #   vendored woff2 (Spectral + Hanken Grotesk)
  pyodide/  wheels/  #   vendored runtime + Python wheels
  engine/            #   parser package, zipped to engine.zip
    gstr_analyser/pipeline_csv.py       # unified auto-detect pipeline
    gstr_analyser/compliance_parsers.py # ESIC / PF / PTRC / TDS parsers
gstr_analyser_src/   # original desktop package (CLI / TUI, GSTR-1/3B)
```

## Rebuilding the offline bundle

```bash
cd gstr_web
python build_offline.py    # vendor Pyodide runtime + Python wheels
```

## License

MIT
