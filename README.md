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
WebAssembly). Your PDFs are parsed in an in-memory sandbox and never sent anywhere.

The whole app (Python runtime, libraries, fonts) is **vendored locally**, so once the page
loads it makes **zero network calls** — open DevTools → Network and watch it stay empty
after boot. A [service worker](web_app/sw.js) caches the runtime on first visit, so later
launches are instant and the app keeps working **fully offline** (real air-gap use — pull
the network cable after one load and it still parses).

> **Serve it over HTTP, don't open it from disk.** Browsers block WebAssembly and `fetch()`
> on `file://` pages, so double-clicking `index.html` will not work — the app detects this
> and tells you to serve the folder instead (see [Run locally](#run-locally)). Any static
> host works, including a folder shared on an internal server.

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
skipped, even after local OCR identifies them, because their tables and claim values
cannot be verified safely.

## Design

A single premium theme (`themes/prime.css`): a calm, institutional layout with a
financial serif (Spectral) for headings and a humanist sans (Hanken Grotesk) for data,
with saturated colour reserved for status. All fonts are vendored, so it works offline.

The maintained [web style guide](docs/web-style-guide.md) defines the design principles,
tokens, components, task patterns, content rules, accessibility target, privacy rules,
and visual acceptance checks for future UI work.

---

## Run locally

No build step. Any static server works:

```bash
cd web_app
python -m http.server 8000
# open http://localhost:8000
```

Opening `index.html` directly via `file://` will **not** work — browsers block WebAssembly
and `fetch()` on filesystem pages. The app checks for this at startup and shows a message
telling you to serve it over HTTP. It needs a URL, not a double-click.

## Deploying it

It's a static folder — host `web_app/` anywhere that serves files over HTTP. The current
build is on GitHub Pages (see the link at the top). Two things to check on other hosts:

- **All paths are relative**, so it works under a subpath (e.g. `example.com/tools/returns/`)
  without changes.
- **The host must serve `.wasm`, `.whl`, `.zip`, and `.json`.** nginx, Apache, and GitHub
  Pages do by default. **IIS does not** — it refuses unknown extensions, so the Python
  wheels 404 and the engine won't boot. Add a MIME map in `web.config`:

  ```xml
  <staticContent>
    <mimeMap fileExtension=".wasm" mimeType="application/wasm" />
    <mimeMap fileExtension=".whl"  mimeType="application/octet-stream" />
    <mimeMap fileExtension=".zip"  mimeType="application/zip" />
    <mimeMap fileExtension=".json" mimeType="application/json" />
  </staticContent>
  ```

If boot fails, the on-screen **diagnostics checklist** names the exact stage that broke
(browser support → runtime → libraries → engine) and why — so a locked-down-environment
failure is a one-line diagnosis, not a guess.

## How it works

```
PDFs (in browser)
  → Pyodide writes them to an in-memory filesystem
  → run_unified_pipeline auto-detects each return type and parses it
     (pdfplumber → pandas → sanity checks → normalized CSVs)
  → app.js reads the CSVs back and renders the dashboard + downloads
```

The browser engine is `web_app/engine/` (a Pyodide-friendly build of the parser package);
`web_bootstrap.run("auto", …)` drives `document_analyser/statutory_pipeline.py`, while
bank mode drives `document_analyser/banking/pipeline.py`. After editing any
engine file, rebuild `engine.zip` (Python `zipfile`, forward-slash arcnames, rooted at
`engine/`) so the browser picks up the change.

## Repo layout

```
web_app/             # the browser app (deployed to Pages)
  index.html         #   UI (+ noscript / old-browser guards)
  app.js             #   Pyodide glue (boot, diagnostics, run, render, download)
  sw.js              #   service worker — offline cache of the runtime
  themes/prime.css   #   the theme
  fonts/             #   vendored woff2 (Spectral + Hanken Grotesk)
  pyodide/  wheels/  #   vendored runtime + Python wheels
  engine/            #   maintained parser package, zipped to engine.zip
    document_analyser/statutory_pipeline.py # statutory auto-detect pipeline
    document_analyser/banking/              # bank and fixed-deposit pipeline
    document_analyser/compliance_parsers.py # ESIC / PF / PTRC / TDS parsers
docs/                # small product and future-work notes
desktop_launcher/    # local-only Windows launcher and portable-package builder
legacy/              # historical desktop, Power Query, and workbook material
  desktop-analyser/  #   old desktop application (not maintained)
  powerquery/        #   old Power Query scripts (not deployed)
```

## Rebuilding the offline bundle

```bash
cd web_app
python package_engine.py   # rebuild engine.zip from engine/
python build_offline.py    # refresh vendored Pyodide runtime + Python wheels
```

## Portable Windows package

The browser app is the only parser engine. For clients who need a reliable offline
copy without a first-time browser download, build the local launcher package:

```bash
python desktop_launcher/build_portable.py
```

It creates a portable folder and ZIP under `release/`. The launcher serves the same
browser app only on `127.0.0.1`; it does not upload documents or contain a second parser.

## License

MIT
