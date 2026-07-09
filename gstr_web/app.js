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
  resultsPanel.style.display = "none";
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
