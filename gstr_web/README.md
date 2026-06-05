# GSTR Return Analyser — Web (offline, browser-only)

Drop GSTR-1 / GSTR-3B portal PDFs → audit-ready Excel, **100% in the browser**.
No install, no server, no network. Runs the existing Python engine via Pyodide (Python→WASM).

## Run it
Open `index.html` in any modern browser. That's it.
(For local dev with the file:// fetch restrictions, serve the folder: `python -m http.server` then open `http://localhost:8000`.)

## Layout
```
index.html        ← markup + ALL UI TEXT (single source). Edit copy here once.
app.js            ← engine glue: boot Pyodide, run pipeline, downloads
theme.js          ← theme switcher (persists choice in localStorage)
web_bootstrap.py  ← (inside engine.zip) serial-executor shim + run()
engine.zip        ← the gstr_analyser Python package (parsers/checks/analytics)
engine/           ← unzipped source of engine.zip (edit here, then re-zip)
themes/
  base.css        ← shared structure/layout, variable-driven
  swiss.css …     ← 10 skins (set CSS variables + light decoration)
pyodide/          ← vendored Pyodide runtime + package wheels (offline)
wheels/           ← vendored pure-Python wheels (pdfplumber, rich, …)
fonts/            ← vendored Swiss-theme fonts (default theme = fully offline)
designs/          ← static design-preview mockups + gallery.html (reference only)
```

## Editing UI text
All visible text lives **once** in `index.html` (masthead, section kickers, button,
footer). Themes are CSS-only — they never contain copy. Edit `index.html` → every
theme updates. Section numbers ("01" / "I" / "[01]") are CSS counters in each theme,
not text.

## Themes
- 10 themes, switchable via the picker (top-right). Default = **Swiss Signal**.
- Each `themes/<name>.css` overrides CSS variables defined in `themes/base.css`
  (`--bg --ink --accent --font-display …`) plus a few decoration rules.
- **Add a theme:** copy a skin, tweak variables, add an `<option>` in `index.html`.
- Only the default (Swiss) fonts are vendored locally; other themes `@import` their
  fonts from Google when first selected (cosmetic only — no client data ever leaves).

## Editing the extraction engine
1. Edit Python under `engine/gstr_analyser/…`
2. Re-zip:  `python -c "import os,zipfile; z=zipfile.ZipFile('engine.zip','w',zipfile.ZIP_DEFLATED); [z.write(os.path.join(d,f), os.path.relpath(os.path.join(d,f),'engine').replace(os.sep,'/')) for d,_,fs in os.walk('engine') for f in fs]; z.close()"`
   (arcnames MUST use forward slashes, or Pyodide can't unpack.)

## Rebuilding the offline bundle
- Pyodide + wheels:  `python build_offline.py`
- Swiss fonts:       `python fonts_vendor.py`

## Security
Files are parsed in the browser's WASM sandbox. Open DevTools → Network: it stays
empty (verified: 0 external requests on the default theme). Nothing is uploaded,
stored, or sent anywhere.

## Note before shipping
`app.js` exposes a `window.__GSTR_TEST__` hook used for automated testing.
Harmless, but remove it for a public release.
