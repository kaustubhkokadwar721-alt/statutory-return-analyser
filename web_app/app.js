"use strict";

// ---- config ----
const PYODIDE_INDEX = "./pyodide/";
const ENGINE_ZIP    = "engine.zip";
const OCR_PDFJS     = "./ocr/pdf.min.mjs";
const OCR_PDF_WORKER = "./ocr/pdf.worker.min.mjs";
const LOCAL_WHEELS  = [
  "./wheels/charset_normalizer-3.4.7-py3-none-any.whl",
  "./wheels/pdfminer_six-20260107-py3-none-any.whl",
  "./wheels/pdfplumber-0.11.9-py3-none-any.whl",
  "./wheels/xlsxwriter-3.2.9-py3-none-any.whl",
];

// ---- state ----
let pyodide    = null;
let ready      = false;
let pickedFiles = [];   // [{name, displayName, bytes}] name is unique in the sandbox
let consolidated   = [];  // unified ledger rows (one per document)
let dashboard      = [];  // head × DocKind × FY summary rows
let reconciliation = [];  // per-period declared-vs-paid tie-out rows
let parseErrors    = [];  // files that could not be parsed at all
let reviews        = [];  // local audit evidence for records needing attention
let pdfjsPromise    = null;
let activeMode      = "auto";

// ---- dom ----
const $ = (s) => document.querySelector(s);
const dot        = $("#dot");
const statusText = $("#statusText");
const logEl      = $("#log");
const runBtn     = $("#run");
const filesEl    = $("#files");
const dropEl     = $("#drop");
const picker     = $("#picker");
const resultsEl  = $("#results");
const resultsTab = $("#tabResults");
const ocrEnabled = $("#ocrEnabled");
const modeButtons = [...document.querySelectorAll(".mode-btn")];

function setStatus(text, cls) {
  statusText.textContent = text;
  dot.className = "dot " + (cls || "");
}
function log(msg) {
  logEl.classList.add("show");
  logEl.textContent += msg + "\n";
  logEl.scrollTop = logEl.scrollHeight;
}
function fmtSize(n) {
  return n < 1024 ? n + " B"
       : n < 1048576 ? (n / 1024).toFixed(0) + " KB"
       : (n / 1048576).toFixed(1) + " MB";
}

function maybeEnableRun() {
  runBtn.disabled = !(ready && pickedFiles.length > 0);
}

// ---- workspace tabs: Drop & parse | Results (appears after a run) ----
const TABS = [
  { tab: $("#tabDrop"),    pane: $("#paneDrop") },
  { tab: $("#tabResults"), pane: $("#paneResults") },
];
function selectTab(idx) {
  TABS.forEach(({ tab, pane }, i) => {
    const on = i === idx;
    tab.setAttribute("aria-selected", on ? "true" : "false");
    tab.tabIndex = on ? 0 : -1;
    pane.classList.toggle("active", on);
    pane.hidden = !on;
  });
}
TABS.forEach(({ tab }, i) => {
  tab.addEventListener("click", () => selectTab(i));
  tab.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const next = (i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;
    if (TABS[next].tab.hidden) return;
    selectTab(next);
    TABS[next].tab.focus();
  });
});

// ---- document-type identity (icons + hues match the sprite/theme) ----
const TYPE_META = {
  GSTR1:  { icon: "i-gstr1",  cls: "t-gstr1",  label: "GSTR-1" },
  GSTR3B: { icon: "i-gstr3b", cls: "t-gstr3b", label: "GSTR-3B" },
  TDS:    { icon: "i-tds",    cls: "t-tds",    label: "TDS" },
  PF:     { icon: "i-pf",     cls: "t-pf",     label: "PF" },
  ESIC:   { icon: "i-esic",   cls: "t-esic",   label: "ESIC" },
  PTRC:   { icon: "i-ptrc",   cls: "t-ptrc",   label: "PTRC" },
  SB:     { icon: "i-sb",     cls: "t-sb",     label: "Ship. Bill" },
  EBRC:   { icon: "i-ebrc",   cls: "t-ebrc",   label: "eBRC" },
  EWB:    { icon: "i-ewb",    cls: "t-ewb",    label: "e-Way Bill" },
  BANK:   { icon: "i-bank",   cls: "t-bank",   label: "Bank" },
  FD:     { icon: "i-fd",     cls: "t-fd",     label: "Fixed Deposit" },
};
function typeCell(rt) {
  const m = TYPE_META[rt];
  if (!m) return esc(rt);
  return `<span class="tcell ${m.cls}"><svg viewBox="0 0 24 24" aria-hidden="true"><use href="#${m.icon}"/></svg>${m.label}</span>`;
}

// ---- document-kind badge: Return / Challan / Payment / Arrears ----
const KIND_CLASS = {
  Return: "k-return", Challan: "k-challan", Payment: "k-payment", Arrears: "k-arrears",
  Statement: "k-return", Certificate: "k-payment",
};
function kindCell(k) {
  if (!k) return "—";
  return `<span class="kcell ${KIND_CLASS[k] || ""}">${esc(k)}</span>`;
}

// ---- file selection ----
let fileTags = {};  // name -> {type, status} once parsed

function setMode(mode) {
  if (!["auto", "bank"].includes(mode) || mode === activeMode) return;
  activeMode = mode;
  modeButtons.forEach((button) => {
    const selected = button.dataset.mode === mode;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-checked", selected ? "true" : "false");
  });
  document.getElementById("statutoryTypes").hidden = mode === "bank";
  document.getElementById("bankingTypes").hidden = mode !== "bank";
  document.getElementById("dropHelp").textContent = mode === "bank"
    ? "bank, loan and fixed-deposit PDFs · or click to browse"
    : "any mix of the nine types · or click to browse";
  document.getElementById("runHint").textContent = mode === "bank"
    ? "Checks every statement against its balances"
    : "Auto-detects each document’s type";
  ocrEnabled.parentElement.title = mode === "bank"
    ? "Runs local OCR in this browser. Scanned bank tables stay review-only unless their row structure is clear."
    : "Runs the bundled OCR engine in this browser only.";
  fileTags = {};
  consolidated = []; dashboard = []; reconciliation = []; parseErrors = []; reviews = [];
  resultsTab.hidden = true;
  renderFiles();
  selectTab(0);
}

modeButtons.forEach((button) => button.addEventListener("click", () => setMode(button.dataset.mode)));

function uniqueSandboxName(filename) {
  const used = new Set(pickedFiles.map((file) => file.name.toLowerCase()));
  if (!used.has(filename.toLowerCase())) return filename;
  const match = /^(.*?)(\.pdf)$/i.exec(filename) || ["", filename, ""];
  for (let copy = 2; ; copy += 1) {
    const candidate = `${match[1]}__${copy}${match[2]}`;
    if (!used.has(candidate.toLowerCase())) return candidate;
  }
}

function displayFileName(file) {
  return file.name === file.displayName ? file.name : `${file.displayName} (copy)`;
}

async function addFiles(fileList) {
  for (const f of fileList) {
    if (!f.name.toLowerCase().endsWith(".pdf")) continue;
    const bytes = new Uint8Array(await f.arrayBuffer());
    const name = uniqueSandboxName(f.name);
    pickedFiles.push({ name, displayName: f.name, bytes });
    delete fileTags[name];
  }
  renderFiles();
  maybeEnableRun();
}

function removeFile(name) {
  pickedFiles = pickedFiles.filter((p) => p.name !== name);
  delete fileTags[name];
  renderFiles();
  maybeEnableRun();
}

function renderFiles() {
  const bar = document.getElementById("filesBar");
  const chips = document.getElementById("fileChips");

  document.querySelector(".drop-card").classList.toggle("has-files", pickedFiles.length > 0);

  if (!pickedFiles.length) {
    bar.innerHTML = "";
    chips.innerHTML = "";
    filesEl.innerHTML = "";
    return;
  }

  const totalBytes = pickedFiles.reduce((s, f) => s + f.bytes.length, 0);
  bar.innerHTML =
    `<span class="files-n">${pickedFiles.length} document${pickedFiles.length > 1 ? "s" : ""} · ${fmtSize(totalBytes)}</span>` +
    `<button type="button" class="clear-all" id="clearAll">Clear all</button>`;
  bar.querySelector("#clearAll").addEventListener("click", () => {
    pickedFiles = []; fileTags = {};
    renderFiles(); maybeEnableRun();
  });

  // aggregate chips: per-type counts + review/unreadable, once tags exist
  const byType = {}; let review = 0, unreadable = 0;
  for (const f of pickedFiles) {
    const t = fileTags[f.name];
    if (!t) continue;
    if (t.status === "unreadable") { unreadable++; continue; }
    byType[t.type] = (byType[t.type] || 0) + 1;
    if (t.status && t.status !== "OK") review++;
  }
  let chipHtml = Object.entries(byType)
    .sort((a, b) => b[1] - a[1])
    .map(([ty, n]) => {
      const m = TYPE_META[ty];
      return `<span class="fchip ${m ? m.cls : ""}">${n} ${esc(m ? m.label : ty)}</span>`;
    }).join("");
  if (review)     chipHtml += `<span class="fchip review">${review} review</span>`;
  if (unreadable) chipHtml += `<span class="fchip err">${unreadable} unreadable</span>`;
  chips.innerHTML = chipHtml;

  filesEl.innerHTML = "";
  for (const f of pickedFiles) {
    const tag = fileTags[f.name];
    const div = document.createElement("div");
    div.className = "f";
    let tagHtml = "";
    if (tag) {
      if (tag.status === "unreadable") {
        tagHtml = `<span class="ftag err">unreadable</span>`;
      } else {
        const m = TYPE_META[tag.type];
        const ic = m ? `<svg viewBox="0 0 24 24" aria-hidden="true"><use href="#${m.icon}"/></svg>` : "";
        tagHtml = `<span class="ftag ${m ? m.cls : ""}">${ic}${esc(m ? m.label : tag.type)}</span>` +
                  (tag.status !== "OK" ? `<span class="pill ${(tag.status || "").toLowerCase()}">${esc(tag.status)}</span>` : "");
      }
    }
    div.innerHTML =
      `<span class="nm" title="${esc(displayFileName(f))}">${esc(displayFileName(f))}</span>${tagHtml}` +
      `<span class="sz">${fmtSize(f.bytes.length)}</span>` +
      `<button type="button" class="rm" aria-label="Remove ${esc(displayFileName(f))}">&times;</button>`;
    div.querySelector(".rm").addEventListener("click", () => removeFile(f.name));
    filesEl.appendChild(div);
  }
}

dropEl.addEventListener("click", () => picker.click());
dropEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); picker.click(); }
});
picker.addEventListener("change", (e) => addFiles(e.target.files));
["dragover", "dragenter"].forEach((ev) =>
  dropEl.addEventListener(ev, (e) => { e.preventDefault(); dropEl.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) =>
  dropEl.addEventListener(ev, (e) => { e.preventDefault(); dropEl.classList.remove("over"); }));
dropEl.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

// ---- boot diagnostics: a visible ✔/⏳/✖ checklist so a failed boot on an
// unfamiliar machine says exactly which stage died, not just "something broke" ----
const DIAG_STEPS = [
  "Browser supported",
  "Python runtime (WebAssembly)",
  "Data libraries (pandas)",
  "PDF engine (pdfplumber)",
  "Return engine",
];
const diagEl = $("#bootDiag");
let diagCurrent = -1;

function diagRender() {
  diagEl.hidden = false;
  diagEl.innerHTML = DIAG_STEPS.map((label, i) => {
    const cls = i < diagCurrent ? "ok" : i === diagCurrent ? "busy" : "";
    const mark = i < diagCurrent ? "✔" : i === diagCurrent ? "" : "";
    return `<li class="diag-step ${cls}"><span class="diag-mark">${mark}</span>${esc(label)}</li>`;
  }).join("");
}
function diagStart(i) {
  diagCurrent = i;
  diagRender();
}
function diagFail(i, reason) {
  diagCurrent = i;
  diagRender();
  const li = diagEl.children[i];
  li.classList.remove("busy");
  li.classList.add("err");
  li.querySelector(".diag-mark").textContent = "✖";
  const reasonEl = document.createElement("div");
  reasonEl.className = "diag-reason";
  reasonEl.textContent = reason;
  li.appendChild(reasonEl);
}
function diagDone() {
  diagCurrent = DIAG_STEPS.length;
  diagRender();
  setTimeout(() => { diagEl.hidden = true; }, 1500);
}

// ---- boot Pyodide ----
async function fetchBinary(url, what) {
  let res;
  try {
    res = await fetch(url);
  } catch (e) {
    throw new Error(`Could not fetch ${what} (${url}). ` +
      (location.protocol === "file:"
        ? "This page was opened from the filesystem — browsers block fetch() on file:// pages. Serve the folder over HTTP (e.g. `python -m http.server`) and open http://localhost instead."
        : "Check the network connection and that the file is deployed alongside index.html."));
  }
  if (!res.ok) {
    throw new Error(`Server returned ${res.status} for ${what} (${url}). ` +
      "If this is a custom web server (e.g. IIS), make sure it serves .zip, .whl, .wasm and .json files.");
  }
  return res.arrayBuffer();
}

async function boot() {
  let step = 0;
  diagStart(step);
  try {
    if (location.protocol === "file:") {
      throw new Error("This app cannot run from a file:// URL — browsers block WebAssembly and fetch() there. " +
        "Serve the folder over HTTP (e.g. run `python -m http.server` inside it) and open http://localhost:8000.");
    }
    if (typeof WebAssembly === "undefined") {
      throw new Error("This browser does not support WebAssembly. Use a current version of Chrome, Edge, Firefox or Safari.");
    }
    if (typeof loadPyodide === "undefined") {
      throw new Error("pyodide.js did not load. Check that the pyodide/ folder is deployed next to index.html " +
        "and that no extension or content-security policy is blocking scripts.");
    }

    step = 1; diagStart(step);
    setStatus("Loading Python runtime…", "busy");
    pyodide = await loadPyodide({ indexURL: PYODIDE_INDEX });

    step = 2; diagStart(step);
    setStatus("Loading data libraries…", "busy");
    await pyodide.loadPackage(["micropip", "Pillow", "cryptography", "pandas"]);

    step = 3; diagStart(step);
    setStatus("Installing PDF engine…", "busy");
    pyodide.globals.set("wheel_list", LOCAL_WHEELS);
    await pyodide.runPythonAsync(`
import micropip
await micropip.install(list(wheel_list), deps=False)
    `);

    step = 4; diagStart(step);
    setStatus("Loading return engine…", "busy");
    const zipBuf = await fetchBinary(ENGINE_ZIP, "the return engine");
    await pyodide.unpackArchive(zipBuf, "zip");
    await pyodide.runPythonAsync("import web_bootstrap");

    ready = true;
    diagDone();
    setStatus("Ready — 100% offline, nothing leaves this device.", "ok");
    maybeEnableRun();
  } catch (e) {
    diagFail(step, e.message);
    setStatus(
      location.protocol === "file:"
        ? "Open with the Windows launcher or local server."
        : "Engine failed to load. See details below.",
      "err"
    );
    log("BOOT ERROR:\n" + e.message +
      "\n\nCommon causes: opening the page from file://, a web server that blocks .whl/.wasm/.zip files, " +
      "an ad-blocker or strict content-security policy, or a very old browser.");
    console.error(e);
  }
}

// ---- run pipeline ----
let runStamp = "";  // per-run date-time suffix so repeat downloads never collide

function newRunStamp() {
  const d = new Date(), p = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}-${p(d.getMinutes())}`;
}
function stampName(filename) {
  const i = filename.lastIndexOf(".");
  return i === -1 ? `${filename}_${runStamp}` : `${filename.slice(0, i)}_${runStamp}${filename.slice(i)}`;
}

async function loadPdfRenderer() {
  if (!pdfjsPromise) {
    pdfjsPromise = import(OCR_PDFJS)
      .then((pdfjs) => {
        pdfjs.GlobalWorkerOptions.workerSrc = OCR_PDF_WORKER;
        return pdfjs;
      })
      .catch((error) => {
        pdfjsPromise = null;
        throw error;
      });
  }
  return pdfjsPromise;
}

async function runLocalOcr(files) {
  const pdfjs = await loadPdfRenderer();
  const worker = await window.Tesseract.createWorker("eng", 1, {
    workerPath: "./ocr/worker.min.js",
    corePath: "./ocr/core",
    langPath: "./ocr/lang",
    gzip: false,
    cacheMethod: "none",
    workerBlobURL: false,
  });
  try {
    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      log(`  [OCR] ${index + 1}/${files.length}: ${displayFileName(file)}`);
      const task = pdfjs.getDocument({ data: file.bytes.slice() });
      const pdfDocument = await task.promise;
      const pageText = [];
      try {
        for (let pageNo = 1; pageNo <= pdfDocument.numPages; pageNo += 1) {
          const page = await pdfDocument.getPage(pageNo);
          const viewport = page.getViewport({ scale: 2 });
          const canvas = document.createElement("canvas");
          canvas.width = Math.ceil(viewport.width);
          canvas.height = Math.ceil(viewport.height);
          const context = canvas.getContext("2d", { alpha: false });
          await page.render({ canvasContext: context, viewport, background: "#ffffff" }).promise;
          const result = await worker.recognize(canvas);
          pageText.push((result.data.text || "").trim());
          canvas.width = 1;
          canvas.height = 1;
          page.cleanup();
        }
      } finally {
        await pdfDocument.destroy();
      }
      const text = pageText.join("\f").trim();
      if (text.length < 20) {
        log(`  [OCR] No usable text found: ${displayFileName(file)}`);
        continue;
      }
      pyodide.FS.writeFile(`/work/in/${file.name}.ocr.txt`, new TextEncoder().encode(text));
    }
  } finally {
    await worker.terminate();
  }
}

async function ocrScannedFiles(errors) {
  const names = new Set(errors.filter((error) => error.Type === "NeedsOCR").map((error) => error.File));
  const files = pickedFiles.filter((file) => names.has(file.name));
  if (!files.length) return;
  if (!window.Tesseract) throw new Error("The local OCR component did not load. Refresh the page and try again.");

  let lastError;
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      await runLocalOcr(files);
      return;
    } catch (error) {
      lastError = error;
      if (attempt === 1) {
        pdfjsPromise = null;
        log("  [OCR] Local OCR did not start. Retrying once...");
      }
    }
  }
  const reason = lastError instanceof Error ? lastError.message : String(lastError);
  throw new Error(`Local OCR could not complete after a retry: ${reason}`);
}

async function runEngine() {
  pyodide.globals.set("run_kind", activeMode);
  const resultJson = await pyodide.runPythonAsync(`
import web_bootstrap, json
result = web_bootstrap.run(str(run_kind), "/work/in", "/work/out", progress_cb=progress_cb)
json.dumps(result)
  `);
  return JSON.parse(resultJson);
}

runBtn.addEventListener("click", async () => {
  if (!ready || pickedFiles.length === 0) return;
  runBtn.disabled = true;
  modeButtons.forEach((button) => { button.disabled = true; });
  consolidated = []; dashboard = []; reconciliation = []; parseErrors = []; reviews = [];
  resultsEl.classList.remove("show");
  // release blob URLs from the previous run before discarding the buttons
  resultsEl.querySelectorAll("a[href^='blob:']").forEach((a) => URL.revokeObjectURL(a.href));
  resultsEl.innerHTML = "";
  logEl.textContent = "";
  setStatus("Processing…", "busy");

  try {
    const FS = pyodide.FS;
    await pyodide.runPythonAsync(`
import shutil, os
for d in ("/work/in", "/work/out"):
    if os.path.isdir(d): shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)
    `);
    for (const f of pickedFiles) FS.writeFile("/work/in/" + f.name, f.bytes);
    log(`${pickedFiles.length} PDF(s) written to sandbox. ${
      activeMode === "bank" ? "Identifying bank layouts and checking balances" : "Auto-detecting return types"
    }…`);

    const progress = (step, detail) => log(`  [${step}] ${detail || ""}`);
    pyodide.globals.set("progress_cb", progress);

    let result = await runEngine();
    const initialErrors = (result.errors || []).map((error) => ({
      File: error.File, Type: error.Error_Type, Message: error.Message, Action: error.Action,
    }));
    if (ocrEnabled.checked && initialErrors.some((error) => error.Type === "NeedsOCR")) {
      setStatus("Reading scanned PDFs locally...", "busy");
      await ocrScannedFiles(initialErrors);
      log("  [OCR] Re-running the parser with local OCR text.");
      result = await runEngine();
    }
    runStamp = newRunStamp();

    consolidated   = result.consolidated   || [];
    dashboard      = result.dashboard      || [];
    reconciliation = result.reconciliation || [];
    parseErrors    = (result.errors || []).map((e) => ({
      File: e.File, Type: e.Error_Type, Message: e.Message, Action: e.Action,
    }));
    reviews        = result.reviews || [];

    // one Excel workbook — the sole deliverable
    if (result.workbook) {
      addWorkbookResult(FS.readFile(result.workbook), result.workbook_name || "Statutory_Returns.xlsx", consolidated.length);
    }

    // tag each picked file with its detected head / kind / outcome
    fileTags = {};
    for (const r of consolidated) {
      if (!fileTags[r.SourceFile] || r.Status !== "OK")
        fileTags[r.SourceFile] = { type: r.ReturnType, kind: r.DocKind, status: r.Status };
    }
    for (const e2 of parseErrors) fileTags[e2.File] = { type: "", status: "unreadable" };
    renderFiles();

    renderDashboard();
    renderReconciliation();
    renderReviews();

    resultsEl.classList.add("show");
    setStatus(`Done — ${pickedFiles.length} PDF(s) processed, ${consolidated.length} record(s), workbook ready.`, "ok");
    log("COMPLETE.");
    // reveal the Results tab and take the user straight to it
    resultsTab.hidden = false;
    document.getElementById("tabResultsN").textContent = String(consolidated.length);
    selectTab(1);
    document.getElementById("paneResults").scrollTop = 0;
  } catch (e) {
    const reason = e instanceof Error ? e.message : String(e);
    setStatus("Processing stopped. See details below.", "err");
    log("ERROR:\n" + reason);
    console.error(e);
  } finally {
    runBtn.disabled = false;
    modeButtons.forEach((button) => { button.disabled = false; });
    maybeEnableRun();
  }
});

// ---- dashboard rendering ----
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const money = (n) => (Number(n) || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
const period = (r) => {
  const d = (r.PeriodDate || "").slice(0, 7);
  return d && d !== "nan" ? d : (r.MonthName && r.MonthName !== "Unknown" ? r.MonthName : "—");
};

function renderDashboard() {
  const n = consolidated.length;
  const failed = parseErrors.length;
  const by = (s) => consolidated.filter((r) => r.Status === s).length;
  // Declared = what returns owe; Paid = what challans/payments settled. Summing
  // across kinds would double/triple-count the same liability, so keep them apart.
  const sumKind = (kinds) => consolidated
    .filter((r) => kinds.includes(r.DocKind))
    .reduce((s, r) => s + (Number(r.PrimaryAmount) || 0), 0);
  const declared = sumKind(["Return"]);
  const paid     = sumKind(["Challan", "Payment"]);
  const flaggable = by("Review") + by("Error") > 0;
  const kpis = [
    ["Documents", n + failed, "", false],
    ["Clean", by("OK"), "ok", false],
    ["Review", by("Review"), "review", flaggable],
    ["Errors", by("Error"), "error", flaggable],
  ];
  if (failed) kpis.push(["Unreadable", failed, "error", false]);
  if (activeMode === "bank") {
    const extractedRows = consolidated.reduce((sum, row) => sum + (Number(row.RowsExtracted) || 0), 0);
    kpis.push(["Rows extracted", extractedRows, "", false]);
  } else {
    kpis.push(["Declared ₹", money(declared), "", false]);
    kpis.push(["Paid ₹", money(paid), "", false]);
  }
  document.getElementById("kpis").innerHTML = kpis
    .map(([l, v, c, click]) =>
      `<div class="kpi ${c}${click ? " clickable" : ""}"${click ? ` role="button" tabindex="0" data-filter="1" aria-label="Show flagged records"` : ""}>` +
      `<div class="kpi-v">${v}</div><div class="kpi-l">${l}</div></div>`)
    .join("");
  // clicking Review / Errors jumps to the flagged records
  document.querySelectorAll(".kpi.clickable").forEach((el) => {
    const go = () => {
      document.getElementById("flaggedOnly").checked = true;
      renderRecords();
      document.getElementById("recTable").scrollIntoView({ behavior: "smooth", block: "nearest" });
    };
    el.addEventListener("click", go);
    el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
  });
  document.getElementById("dashTable").innerHTML = dashTableHTML();
  renderRecordFilters();
  renderRecords();
}

function dashTableHTML() {
  if (!dashboard.length) return "";
  const head = ["Head", "Document", "FY", "Docs", "OK", "Review", "Err", "Periods", "Amount ₹"];
  const body = dashboard.map((d) => `<tr>
      <td>${typeCell(d.ReturnType)}</td>
      <td>${kindCell(d.DocKind)}</td>
      <td>${esc(d.FY)}</td>
      <td class="num">${d.Records}</td>
      <td class="num">${d.OK}</td>
      <td class="num rev">${d.Review}</td>
      <td class="num err">${d.Errors}</td>
      <td class="num">${d.Periods}</td>
      <td class="num">${money(d.TotalAmount)}</td></tr>`).join("");
  return `<table class="tbl"><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
}

const STATUS_RANK = { Error: 0, Review: 1, OK: 2 };

function setRecordFilterOptions(id, emptyLabel, values) {
  const select = document.getElementById(id);
  const current = select.value;
  select.innerHTML = `<option value="">${emptyLabel}</option>` +
    values.map((value) => `<option value="${esc(value)}">${esc(value)}</option>`).join("");
  select.value = values.includes(current) ? current : "";
}

function renderRecordFilters() {
  setRecordFilterOptions("filterType", "All types", [...new Set(consolidated.map((row) => row.ReturnType).filter(Boolean))].sort());
  setRecordFilterOptions("filterFY", "All years", [...new Set(consolidated.map((row) => row.FY).filter(Boolean))].sort().reverse());
  const statuses = ["Error", "Review", "OK"].filter((status) => consolidated.some((row) => row.Status === status));
  setRecordFilterOptions("filterStatus", "All states", statuses);
}

function renderRecords() {
  const flaggedOnly = document.getElementById("flaggedOnly").checked;
  const typeFilter = document.getElementById("filterType").value;
  const fyFilter = document.getElementById("filterFY").value;
  const statusFilter = document.getElementById("filterStatus").value;
  let rows = consolidated.slice();
  const flagged = rows.filter((r) => r.Status !== "OK").length;
  if (flaggedOnly) rows = rows.filter((r) => r.Status !== "OK");
  if (typeFilter) rows = rows.filter((r) => r.ReturnType === typeFilter);
  if (fyFilter) rows = rows.filter((r) => r.FY === fyFilter);
  if (statusFilter) rows = rows.filter((r) => r.Status === statusFilter);

  // exceptions first: the reviewer should never hunt for the row that needs attention
  rows.sort((a, b) =>
    (STATUS_RANK[a.Status] ?? 3) - (STATUS_RANK[b.Status] ?? 3) ||
    String(a.ReturnType).localeCompare(b.ReturnType) ||
    String(a.FY).localeCompare(b.FY) ||
    (Number(a.MonthIndex) || 0) - (Number(b.MonthIndex) || 0));

  const cnt = document.getElementById("recCount");
  cnt.textContent = flaggedOnly
    ? `${rows.length} flagged of ${consolidated.length}`
    : `${consolidated.length} record${consolidated.length !== 1 ? "s" : ""}` +
      (flagged ? ` · ${flagged} flagged` : " · all clean");

  const head = ["", "Head", "Document", "Entity", "FY", "Period", "Ref", "Amount ₹", "Flags", "Source"];
  head.splice(8, 0, "Audit");
  head.splice(10, 0, "Evidence");
  const body = rows.map((r) => {
    const st = (r.Status || "").toLowerCase();
    return `<tr>
      <td><span class="pill ${st}">${esc(r.Status)}</span></td>
      <td>${typeCell(r.ReturnType)}</td>
      <td>${kindCell(r.DocKind)}</td>
      <td class="ell" title="${esc(r.EntityName)} (${esc(r.EntityID)})">${esc(r.EntityID)}</td>
      <td>${esc(r.FY)}</td>
      <td>${esc(period(r))}</td>
      <td class="ell ref" title="${esc(r.DocRef)}">${esc(r.DocRef || "—")}</td>
      <td class="num">${money(r.PrimaryAmount)}</td>
      <td class="num audit-score">${r.Confidence == null ? "-" : `${esc(r.Confidence)}/100`}</td>
      <td class="flags">${esc(r.Flags)}</td>
      <td>${r.Status === "OK" ? "-" : `<button type="button" class="evidence-btn" data-review-source="${esc(r.SourceFile)}">Open</button>`}</td>
      <td class="ell src" title="${esc(r.SourceFile)}">${esc(r.SourceFile)}</td></tr>`;
  }).join("");
  document.getElementById("recTable").innerHTML =
    `<table class="tbl rec"><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;

  document.querySelectorAll(".evidence-btn").forEach((button) => {
    button.addEventListener("click", () => {
      const detail = [...document.querySelectorAll(".review-detail")]
        .find((item) => item.dataset.reviewSource === button.dataset.reviewSource);
      if (!detail) return;
      detail.open = true;
      detail.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });

  renderBadFiles();
}

function renderBadFiles() {
  const el = document.getElementById("badFiles");
  if (!parseErrors.length) { el.innerHTML = ""; return; }
  const labels = {
    NeedsOCR: "Needs OCR", NeedsStructuredOCR: "Needs structured OCR",
    MixedDocument: "Mixed document", AmbiguousType: "Needs review", UnknownType: "Unknown type",
    EncryptedPDF: "Password protected", UnsupportedDocument: "Different document",
    UnknownBankLayout: "Unknown bank layout",
  };
  const reviewTypes = new Set(Object.keys(labels));
  el.innerHTML =
    `<div class="bad-head">Not parsed (${parseErrors.length})</div>` +
    parseErrors.map((e) => `<div class="bad">
        <span class="pill ${reviewTypes.has(e.Type) ? "review" : "error"}">${esc(labels[e.Type] || "Unreadable")}</span>
        <span class="bad-nm" title="${esc(e.File)}">${esc(e.File)}</span>
        <span class="bad-why">${esc(e.Message)}${e.Action ? ` ${esc(e.Action)}` : ""}</span>
      </div>`).join("");
}

function renderReviews() {
  const sec = document.getElementById("reviewSec");
  const el = document.getElementById("reviewDetails");
  if (!sec || !el) return;
  if (!reviews.length) { sec.hidden = true; el.innerHTML = ""; return; }
  sec.hidden = false;
  el.innerHTML = reviews.map((review) => {
    const findings = (review.Findings || []).map((finding) =>
      `<li><b>${esc(finding.Code)}</b> - ${esc(finding.Message)}</li>`).join("") || "<li>No additional details.</li>";
    const evidence = (review.Evidence || []).map((item) =>
      `<tr><td>${esc(item.Field)}</td><td>${esc(item.Value)}</td><td>${esc(item.Method)}</td><td>${esc(item.Page || "-")}</td></tr>`).join("") ||
      "<tr><td colspan=\"4\">No field evidence recorded.</td></tr>";
    return `<details class="review-detail" data-review-source="${esc(review.SourceFile)}">
      <summary><span class="pill review">${esc(review.Status || "Review")}</span> ${esc(review.SourceFile)} - ${esc(review.ConfidenceGrade || "Low")} audit score (${esc(review.Confidence ?? "-")}/100)</summary>
      <div class="review-meta">${esc(review.ReturnType)} / ${esc(review.DocKind)} / profile ${esc(review.ProfileVersion)}</div>
      <ul>${findings}</ul>
      <table class="tbl"><thead><tr><th>Field</th><th>Extracted value</th><th>Method</th><th>Page</th></tr></thead><tbody>${evidence}</tbody></table>
    </details>`;
  }).join("");
}

// ---- reconciliation: per-period declared-vs-paid tie-out ----
function renderReconciliation() {
  const el = document.getElementById("reconTable");
  const sec = document.getElementById("reconSec");
  if (!el || !sec) return;
  if (!reconciliation.length) { sec.hidden = true; el.innerHTML = ""; return; }
  sec.hidden = false;

  if (activeMode === "bank") {
    const rows = reconciliation.slice().sort((a, b) =>
      String(a.Status).localeCompare(String(b.Status)) ||
      String(a.Bank).localeCompare(String(b.Bank)) ||
      String(a.SourceFile).localeCompare(String(b.SourceFile)));
    const matched = rows.filter((row) => row.Status === "PASS").length;
    document.getElementById("reconCount").textContent = `${matched}/${rows.length} balanced`;
    const head = ["Bank", "Account", "Opening ₹", "Debits ₹", "Credits ₹", "Expected close ₹", "Closing ₹", "Difference", "Status"];
    const body = rows.map((row) => {
      const cls = row.Status === "PASS" ? "ok" : "review";
      return `<tr>
        <td>${esc(row.Bank)}</td>
        <td class="ell ref" title="${esc(row.AccountNumber)}">${esc(row.AccountNumber || "—")}</td>
        <td class="num">${money(row.OpeningBalance)}</td>
        <td class="num">${money(row.TotalDebit)}</td>
        <td class="num">${money(row.TotalCredit)}</td>
        <td class="num">${money(row.ExpectedClosing)}</td>
        <td class="num">${money(row.ClosingBalance)}</td>
        <td class="num ${Math.abs(Number(row.Difference) || 0) > 0.05 ? "err" : ""}">${money(row.Difference)}</td>
        <td><span class="pill ${cls}">${esc(row.Status)}</span></td></tr>`;
    }).join("");
    el.innerHTML =
      `<table class="tbl"><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
    return;
  }

  const rank = { Mismatch: 0, "Unpaid?": 1, "No demand doc": 1 };
  const rows = reconciliation.slice().sort((a, b) =>
    (rank[a.Status] ?? 2) - (rank[b.Status] ?? 2) ||
    String(a.ReturnType).localeCompare(b.ReturnType) ||
    String(a.PeriodDate).localeCompare(b.PeriodDate));

  const matched = rows.filter((r) => r.Status === "Matched").length;
  document.getElementById("reconCount").textContent =
    `${matched}/${rows.length} matched`;

  const head = ["Head", "Period", "Docs", "Declared ₹", "Challan ₹", "Payment ₹", "Δ", "Status"];
  const body = rows.map((r) => {
    const cls = r.Status === "Matched" ? "ok" : "error";
    return `<tr>
      <td>${typeCell(r.ReturnType)}</td>
      <td>${esc(r.PeriodDate ? r.PeriodDate.slice(0, 7) : "—")}</td>
      <td class="num${Number(r.Docs) > 1 ? " rev" : ""}">${esc(r.Docs)}</td>
      <td class="num">${money(r.Declared)}</td>
      <td class="num">${money(r.Challan)}</td>
      <td class="num">${money(r.Payment)}</td>
      <td class="num ${Number(r.Delta) ? "err" : ""}">${r.Delta ? money(r.Delta) : "—"}</td>
      <td><span class="pill ${cls}">${esc(r.Status)}</span></td></tr>`;
  }).join("");
  el.innerHTML =
    `<table class="tbl"><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
}

document.getElementById("flaggedOnly").addEventListener("change", renderRecords);
["filterType", "filterFY", "filterStatus"].forEach((id) => {
  document.getElementById(id).addEventListener("change", renderRecords);
});

function addWorkbookResult(bytes, name, recordCount) {
  const filename = stampName(name);
  const url = URL.createObjectURL(new Blob([bytes],
    { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));

  const div = document.createElement("div");
  div.className = "dl dl-all";
  const workbookContents = activeMode === "bank"
    ? "transactions, deposits, balance checks and review findings"
    : "every ledger, dashboard and reconciliation";
  div.innerHTML =
    `<span class="dl-ic"><svg viewBox="0 0 24 24" aria-hidden="true"><use href="#i-csv"/></svg></span>` +
    `<div class="n">Workbook<span class="s">${esc(filename)} · ${fmtSize(bytes.length)} — ${esc(workbookContents)} in one Excel file</span></div>`;

  const a = document.createElement("a");
  a.className = "btn";
  a.href = url;
  a.download = filename;
  a.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><use href="#i-download"/></svg>Download Excel`;
  div.appendChild(a);
  resultsEl.appendChild(div);
}

boot();

// ---- offline cache: precache the ~60MB runtime so repeat launches are
// instant and the "nothing leaves this device" pledge holds even with no
// network. Silently skipped where service workers are unavailable/blocked
// (some corporate policies) — the app then behaves exactly as before. ----
if ("serviceWorker" in navigator && location.protocol !== "file:") {
  navigator.serviceWorker.register("./sw.js").catch(() => {});
}
