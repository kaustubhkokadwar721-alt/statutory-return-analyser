"use strict";

const PYODIDE_INDEX = new URL("./pyodide/", self.location.href).href;
const ENGINE_ZIP = new URL("./engine.zip", self.location.href).href;
const LOCAL_WHEELS = [
  "./wheels/charset_normalizer-3.4.7-py3-none-any.whl",
  "./wheels/pdfminer_six-20260107-py3-none-any.whl",
  "./wheels/pdfplumber-0.11.9-py3-none-any.whl",
  "./wheels/xlsxwriter-3.2.9-py3-none-any.whl",
].map((path) => new URL(path, self.location.href).href);

let pyodide = null;
let ready = false;

function postBoot(step, status) {
  self.postMessage({ type: "boot-progress", step, status });
}

function errorText(error) {
  return error instanceof Error ? error.message : String(error);
}

async function fetchBinary(url, what) {
  let response;
  try {
    response = await fetch(url);
  } catch (error) {
    throw new Error(`Could not fetch ${what} (${url}). Check the local deployment.`);
  }
  if (!response.ok) throw new Error(`Server returned ${response.status} for ${what} (${url}).`);
  return response.arrayBuffer();
}

async function boot() {
  try {
    postBoot(1, "Loading Python runtime...");
    self.importScripts(new URL("./pyodide/pyodide.js", self.location.href).href);
    pyodide = await self.loadPyodide({ indexURL: PYODIDE_INDEX });

    postBoot(2, "Loading data libraries...");
    await pyodide.loadPackage(["micropip", "Pillow", "cryptography", "pandas"]);

    postBoot(3, "Installing PDF engine...");
    pyodide.globals.set("wheel_list", LOCAL_WHEELS);
    await pyodide.runPythonAsync(`
import micropip
await micropip.install(list(wheel_list), deps=False)
    `);
    pyodide.globals.delete("wheel_list");

    postBoot(4, "Loading return engine...");
    const zipBuffer = await fetchBinary(ENGINE_ZIP, "the return engine");
    await pyodide.unpackArchive(zipBuffer, "zip");
    await pyodide.runPythonAsync("import web_bootstrap");

    ready = true;
    self.postMessage({ type: "ready" });
  } catch (error) {
    self.postMessage({ type: "boot-error", error: errorText(error) });
  }
}

async function classify(text) {
  pyodide.globals.set("ocr_probe_text", text);
  try {
    const resultJson = await pyodide.runPythonAsync(`
import web_bootstrap, json
json.dumps(web_bootstrap.classify_ocr_probe(str(ocr_probe_text)))
    `);
    return JSON.parse(resultJson);
  } finally {
    pyodide.globals.delete("ocr_probe_text");
  }
}

async function run(payload) {
  const FS = pyodide.FS;
  await pyodide.runPythonAsync(`
import shutil, os
for d in ("/work/in", "/work/out"):
    if os.path.isdir(d): shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)
  `);

  for (const file of payload.files || []) {
    FS.writeFile(`/work/in/${file.name}`, new Uint8Array(file.bytes));
  }
  for (const sidecar of payload.ocrSidecars || []) {
    FS.writeFile(`/work/in/${sidecar.name}.ocr.txt`, new TextEncoder().encode(sidecar.text));
  }

  const progress = (step, detail) => {
    self.postMessage({ type: "progress", step: String(step || ""), detail: String(detail || "") });
  };
  pyodide.globals.set("run_kind", payload.kind || "auto");
  pyodide.globals.set("run_shard", Boolean(payload.shard));
  pyodide.globals.set("progress_cb", progress);
  try {
    const resultJson = await pyodide.runPythonAsync(`
import web_bootstrap, json
result = web_bootstrap.run(
    str(run_kind), "/work/in", "/work/out",
    progress_cb=progress_cb, shard=bool(run_shard),
)
json.dumps(result)
    `);
    const result = JSON.parse(resultJson);
    let workbookBytes = null;
    if (result.workbook) {
      const bytes = FS.readFile(result.workbook);
      workbookBytes = bytes.slice().buffer;
    }
    return { result, workbookBytes };
  } finally {
    pyodide.globals.delete("run_kind");
    pyodide.globals.delete("run_shard");
    pyodide.globals.delete("progress_cb");
  }
}

async function combine(payload) {
  const progress = (step, detail) => {
    self.postMessage({ type: "progress", step: String(step || ""), detail: String(detail || "") });
  };
  pyodide.globals.set("shard_results_json", JSON.stringify(payload.results || []));
  pyodide.globals.set("progress_cb", progress);
  try {
    const resultJson = await pyodide.runPythonAsync(`
import json, os, shutil, web_bootstrap
if os.path.isdir("/work/out"):
    shutil.rmtree("/work/out")
os.makedirs("/work/out", exist_ok=True)
result = web_bootstrap.combine(
    json.loads(str(shard_results_json)), "/work/out", progress_cb=progress_cb
)
json.dumps(result)
    `);
    const result = JSON.parse(resultJson);
    let workbookBytes = null;
    if (result.workbook) {
      const bytes = pyodide.FS.readFile(result.workbook);
      workbookBytes = bytes.slice().buffer;
    }
    return { result, workbookBytes };
  } finally {
    pyodide.globals.delete("shard_results_json");
    pyodide.globals.delete("progress_cb");
  }
}

self.addEventListener("message", async (event) => {
  const { id, action, payload } = event.data || {};
  if (!id) return;
  if (!ready) {
    self.postMessage({ type: "response", id, ok: false, error: "The local engine is not ready." });
    return;
  }
  try {
    const value = action === "classify" ? await classify(payload.text || "")
      : action === "run" ? await run(payload)
      : action === "combine" ? await combine(payload)
      : (() => { throw new Error(`Unknown worker action: ${action}`); })();
    const transfer = value && value.workbookBytes ? [value.workbookBytes] : [];
    self.postMessage({ type: "response", id, ok: true, value }, transfer);
  } catch (error) {
    self.postMessage({ type: "response", id, ok: false, error: errorText(error) });
  }
});

boot();
