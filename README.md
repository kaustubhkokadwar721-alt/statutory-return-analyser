# GSTR Return Analyser

Convert **GSTR-1** and **GSTR-3B** PDFs from the GST portal into audit-ready Excel
workbooks — **entirely in your browser**. No upload, no server, no install.

### ▶ Use it now (one click)

**https://kaustubhkokadwar721-alt.github.io/gstr-return-analyser/**

Pick a return type → drop your PDFs → download the Excel ledgers. That's it.

---

## Why it's safe for client data

Everything runs **client-side** in your browser via [Pyodide](https://pyodide.org)
(Python compiled to WebAssembly). Your PDFs are parsed in a sandbox and never sent
anywhere — open the browser's DevTools → Network tab and watch it stay empty.

The whole app (Python runtime, libraries, fonts) is **vendored locally**, so once the
page loads it makes **zero network calls**. You can also download the folder and open
`index.html` straight from disk — fully offline / air-gappable.

## What you get

For each batch of returns, two workbooks:

| Workbook | Contents |
|----------|----------|
| **Auditor Master** | Sanity checks, exceptions log, liability reconciliation, raw section tables |
| **Analytics Master** | Executive summary, fact tables, taxpayer/calendar dimensions |

Sanity checks include liability-vs-footer tie-outs, ITC reconciliation, RCM
cross-checks, HSN totals, and more (GSTR-1: 6 checks · GSTR-3B: 3 checks).

## 10 themes

A theme picker (top-right) switches between 10 tasteful skins — Swiss, private-bank
gold, financial-press ledger, brutalist, neo-bank, audit terminal, institutional,
art-deco, minimal luxe, editorial. All fonts are vendored, so every theme works
offline. Your choice persists across visits.

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
PDF (in browser)
  → Pyodide writes it to an in-memory filesystem
  → the same Python engine used by the desktop tool runs unchanged
     (pdfplumber → pandas → sanity checks → analytics → XlsxWriter)
  → .xlsx bytes handed back to the browser as a download
```

The browser engine is a thin wrapper (`gstr_web/engine/web_bootstrap.py`) over the
package in [`gstr_analyser_src/`](gstr_analyser_src/) — the desktop CLI/TUI version.
Output is byte-for-byte identical to the desktop run.

## Repo layout

```
gstr_web/            # the browser app (deployed to Pages)
  index.html         #   UI + theme picker
  app.js             #   Pyodide glue (boot, run, download)
  theme.js           #   theme switcher
  themes/            #   base.css + 10 skins (content-agnostic)
  fonts/             #   vendored woff2 (all themes offline)
  pyodide/  wheels/  #   vendored runtime + Python wheels
  engine/            #   copy of the GSTR engine, zipped to engine.zip
gstr_analyser_src/   # original desktop package (CLI / TUI)
```

## Rebuilding the offline bundle

```bash
cd gstr_web
python build_offline.py        # vendor Pyodide runtime + Python wheels
python vendor_all_fonts.py     # vendor every theme's fonts as local woff2
```

## License

MIT
