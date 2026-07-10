"use strict";

// ---- config ----
const PYODIDE_INDEX = "./pyodide/";
const ENGINE_ZIP    = "engine.zip";
const LOCAL_WHEELS  = [
  "./wheels/charset_normalizer-3.4.7-py3-none-any.whl",
  "./wheels/pdfminer_six-20260107-py3-none-any.whl",
  "./wheels/pdfplumber-0.11.9-py3-none-any.whl",
  "./wheels/xlsxwriter-3.2.9-py3-none-any.whl",
  "./wheels/mdurl-0.1.2-py3-none-any.whl",
  "./wheels/markdown_it_py-4.2.0-py3-none-any.whl",
  "./wheels/pygments-2.20.0-py3-none-any.whl",
  "./wheels/rich-15.0.0-py3-none-any.whl",
];

// ---- state ----
let pyodide    = null;
let ready      = false;
let pickedFiles = [];   // [{name, bytes}]
let outputs    = {};
let consolidated = [];  // parsed rows of All_Returns_Consolidated.csv
let dashboard    = [];  // parsed rows of Dashboard_Summary.csv
let parseErrors  = [];  // files that could not be parsed at all

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
const resultsPanel = $("#resultsPanel");

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

// ---- file selection ----
async function addFiles(fileList) {
  for (const f of fileList) {
    if (!f.name.toLowerCase().endsWith(".pdf")) continue;
    const bytes = new Uint8Array(await f.arrayBuffer());
    pickedFiles = pickedFiles.filter((p) => p.name !== f.name);
    pickedFiles.push({ name: f.name, bytes });
  }
  renderFiles();
  maybeEnableRun();
}

function renderFiles() {
  filesEl.innerHTML = "";
  for (const f of pickedFiles) {
    const div = document.createElement("div");
    div.className = "f";
    div.innerHTML = `<span class="nm">${f.name}</span><span class="sz">${fmtSize(f.bytes.length)}</span>`;
    filesEl.appendChild(div);
  }
}

dropEl.addEventListener("click", () => picker.click());
picker.addEventListener("change", (e) => addFiles(e.target.files));
["dragover", "dragenter"].forEach((ev) =>
  dropEl.addEventListener(ev, (e) => { e.preventDefault(); dropEl.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) =>
  dropEl.addEventListener(ev, (e) => { e.preventDefault(); dropEl.classList.remove("over"); }));
dropEl.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

// ---- boot Pyodide ----
async function boot() {
  try {
    setStatus("Loading Python runtime…", "busy");
    pyodide = await loadPyodide({ indexURL: PYODIDE_INDEX });

    setStatus("Loading data libraries…", "busy");
    await pyodide.loadPackage(["micropip", "Pillow", "cryptography", "pandas"]);

    setStatus("Installing PDF engine…", "busy");
    pyodide.globals.set("wheel_list", LOCAL_WHEELS);
    await pyodide.runPythonAsync(`
import micropip
await micropip.install(list(wheel_list), deps=False)
    `);

    setStatus("Loading return engine…", "busy");
    const zipBuf = await (await fetch(ENGINE_ZIP)).arrayBuffer();
    await pyodide.unpackArchive(zipBuf, "zip");
    await pyodide.runPythonAsync("import web_bootstrap");

    ready = true;
    setStatus("Ready — 100% offline, nothing leaves this device.", "ok");
    maybeEnableRun();
  } catch (e) {
    setStatus("Engine failed to load: " + e.message, "err");
    log("BOOT ERROR:\n" + e.message);
    console.error(e);
  }
}

// ---- run pipeline ----
runBtn.addEventListener("click", async () => {
  if (!ready || pickedFiles.length === 0) return;
  runBtn.disabled = true;
  outputs = {};
  consolidated = []; dashboard = []; parseErrors = [];
  resultsPanel.style.display = "none";
  document.getElementById("dashPanel").style.display = "none";
  document.getElementById("recPanel").style.display = "none";
  resultsEl.classList.remove("show");
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
    log(`${pickedFiles.length} PDF(s) written to sandbox. Auto-detecting return types…`);

    const progress = (step, detail) => log(`  [${step}] ${detail || ""}`);
    pyodide.globals.set("progress_cb", progress);

    const jsonFiles = await pyodide.runPythonAsync(`
import web_bootstrap, json
files_list = web_bootstrap.run("auto", "/work/in", "/work/out", progress_cb=progress_cb)
json.dumps(files_list)
    `);
    const files = JSON.parse(jsonFiles);

    for (const f of files) {
      addResult(f.label, f.desc, f.path, FS);
    }

    // ---- in-browser dashboard from the CSVs the engine just wrote ----
    try {
      consolidated = parseCSV(FS.readFile("/work/out/All_Returns_Consolidated.csv", { encoding: "utf8" }));
      dashboard    = readMaybe(FS, "/work/out/Dashboard_Summary.csv");
      parseErrors  = readMaybe(FS, "/work/out/Parsing_Errors.csv");
      renderDashboard();
    } catch (e) {
      console.warn("Dashboard render skipped:", e);
    }

    resultsPanel.style.display = "block";
    resultsEl.classList.add("show");
    setStatus(`Done — ${pickedFiles.length} PDF(s) processed, ${files.length} CSV(s) ready.`, "ok");
    log("COMPLETE.");
  } catch (e) {
    setStatus("Processing failed.", "err");
    log("ERROR:\n" + e.message);
    console.error(e);
  } finally {
    runBtn.disabled = false;
    maybeEnableRun();
  }
});

// ---- dashboard rendering ----
function readMaybe(FS, path) {
  try { return parseCSV(FS.readFile(path, { encoding: "utf8" })); }
  catch { return []; }
}

// RFC-4180-ish CSV parser (handles quoted fields, embedded commas/newlines)
function parseCSV(text) {
  const rows = []; let row = [], cur = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; }
      else cur += c;
    } else if (c === '"') q = true;
    else if (c === ",") { row.push(cur); cur = ""; }
    else if (c === "\r") { /* skip */ }
    else if (c === "\n") { row.push(cur); rows.push(row); row = []; cur = ""; }
    else cur += c;
  }
  if (cur !== "" || row.length) { row.push(cur); rows.push(row); }
  if (!rows.length) return [];
  const hdr = rows.shift();
  return rows
    .filter((r) => r.some((v) => v !== ""))
    .map((r) => Object.fromEntries(hdr.map((h, i) => [h, r[i] ?? ""])));
}

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
  const liab = consolidated.reduce((s, r) => s + (Number(r.PrimaryAmount) || 0), 0);
  const kpis = [
    ["Documents", n + failed, ""],
    ["Clean", by("OK"), "ok"],
    ["Review", by("Review"), "review"],
    ["Errors", by("Error"), "error"],
  ];
  if (failed) kpis.push(["Unreadable", failed, "error"]);
  kpis.push(["Total value ₹", money(liab), ""]);
  document.getElementById("kpis").innerHTML = kpis
    .map(([l, v, c]) => `<div class="kpi ${c}"><div class="kpi-v">${v}</div><div class="kpi-l">${l}</div></div>`)
    .join("");
  document.getElementById("dashTable").innerHTML = dashTableHTML();
  renderRecords();
  document.getElementById("dashPanel").style.display = "block";
  document.getElementById("recPanel").style.display = "block";
}

function dashTableHTML() {
  if (!dashboard.length) return "";
  const head = ["Return", "FY", "Docs", "OK", "Review", "Err", "Periods", "Value ₹"];
  const body = dashboard.map((d) => `<tr>
      <td>${esc(d.ReturnType)}</td><td>${esc(d.FY)}</td>
      <td class="num">${d.Records}</td>
      <td class="num">${d.OK}</td>
      <td class="num rev">${d.Review}</td>
      <td class="num err">${d.Errors}</td>
      <td class="num">${d.Periods}</td>
      <td class="num">${money(d.TotalPrimaryAmt)}</td></tr>`).join("");
  return `<table class="tbl"><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
}

function renderRecords() {
  const flaggedOnly = document.getElementById("flaggedOnly").checked;
  let rows = consolidated.slice();
  if (flaggedOnly) rows = rows.filter((r) => r.Status !== "OK");
  const head = ["", "Return", "Entity", "FY", "Period", "Value ₹", "Flags", "Source"];
  const body = rows.map((r) => {
    const st = (r.Status || "").toLowerCase();
    return `<tr>
      <td><span class="pill ${st}">${esc(r.Status)}</span></td>
      <td>${esc(r.ReturnType)}</td>
      <td class="ell" title="${esc(r.EntityName)} (${esc(r.EntityID)})">${esc(r.EntityID)}</td>
      <td>${esc(r.FY)}</td>
      <td>${esc(period(r))}</td>
      <td class="num">${money(r.PrimaryAmount)}</td>
      <td class="flags">${esc(r.Flags)}</td>
      <td class="ell src" title="${esc(r.SourceFile)}">${esc(r.SourceFile)}</td></tr>`;
  }).join("");
  document.getElementById("recTable").innerHTML =
    `<table class="tbl rec"><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
}

document.getElementById("flaggedOnly").addEventListener("change", renderRecords);

function addResult(label, desc, fsPath, FS) {
  const bytes    = FS.readFile(fsPath);
  const filename = fsPath.split("/").pop();
  const blob     = new Blob([bytes], { type: "text/csv" });
  const url      = URL.createObjectURL(blob);

  const div = document.createElement("div");
  div.className = "dl";
  div.innerHTML = `<div class="n">${label}<span class="s">${filename} · ${fmtSize(bytes.length)} — ${desc}</span></div>`;

  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.textContent = "Download";
  div.appendChild(a);
  resultsEl.appendChild(div);
  outputs[label] = { filename, bytes };
}

boot();
