const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.28.3/full/";
const APP_VERSION = "20260723-author-merge";
const MODULE_FILES = ["claim_mapping.py", "scope_rules.py", "converter.py"];

const els = {
  status: document.getElementById("runtimeStatus"),
  log: document.getElementById("log"),
  metrics: document.getElementById("metrics"),
  runButton: document.getElementById("runButton"),
  dataFiles: document.getElementById("dataFiles"),
  accountFile: document.getElementById("accountFile"),
  articleFile: document.getElementById("articleFile"),
  aliasFile: document.getElementById("aliasFile"),
  apiKey: document.getElementById("apiKey"),
  claimEmailFilter: document.getElementById("claimEmailFilter"),
  downloadXlsx: document.getElementById("downloadXlsx"),
  downloadCsv: document.getElementById("downloadCsv"),
};

let pyodideReadyPromise = null;
let pyodide = null;
let objectUrls = [];

function setStatus(text, kind = "") {
  els.status.textContent = text;
  els.status.className = `status ${kind}`.trim();
}

function logLine(text = "") {
  els.log.textContent += `${text}\n`;
  els.log.scrollTop = els.log.scrollHeight;
}

function clearDownloads() {
  for (const url of objectUrls) URL.revokeObjectURL(url);
  objectUrls = [];
  for (const link of [els.downloadXlsx, els.downloadCsv]) {
    link.removeAttribute("href");
    link.classList.add("disabled");
  }
}

function makeDownload(link, bytes, mime) {
  const blob = new Blob([bytes], { type: mime });
  const url = URL.createObjectURL(blob);
  objectUrls.push(url);
  link.href = url;
  link.classList.remove("disabled");
}

function fileNameSafe(name) {
  return String(name || "upload")
    .replace(/[\\/:\0]/g, "_")
    .replace(/^\.+$/, "upload");
}

async function writeUploadedFile(file, path) {
  if (!file) return null;
  const bytes = new Uint8Array(await file.arrayBuffer());
  pyodide.FS.writeFile(path, bytes);
  return path;
}

async function loadRuntime() {
  if (pyodideReadyPromise) return pyodideReadyPromise;

  pyodideReadyPromise = (async () => {
    setStatus("加载中", "busy");
    logLine("加载 Python 运行环境...");
    pyodide = await loadPyodide({ indexURL: PYODIDE_URL });
    pyodide.setStdout({ batched: (text) => logLine(text) });
    pyodide.setStderr({ batched: (text) => logLine(text) });

    logLine("加载 pandas/openpyxl 等依赖...");
    await pyodide.loadPackage(["micropip", "pandas", "xlrd", "requests"]);
    const micropip = pyodide.pyimport("micropip");
    await micropip.install(["openpyxl"]);

    pyodide.FS.mkdirTree("/app");
    pyodide.FS.mkdirTree("/work");
    for (const file of MODULE_FILES) {
      const response = await fetch(`../${file}?v=${APP_VERSION}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`无法加载 ${file}: HTTP ${response.status}`);
      pyodide.FS.writeFile(`/app/${file}`, await response.text(), { encoding: "utf8" });
    }

    await pyodide.runPythonAsync(`
import sys
sys.path.insert(0, "/app")
from converter import run_conversion
`);
    setStatus("可处理", "ready");
    logLine("运行环境就绪。");
    return pyodide;
  })().catch((error) => {
    setStatus("加载失败", "error");
    logLine(error.stack || String(error));
    pyodideReadyPromise = null;
    throw error;
  });

  return pyodideReadyPromise;
}

function selectedMode() {
  return document.querySelector('input[name="mode"]:checked')?.value || "local";
}

function renderMetrics(stats) {
  const items = [
    ["全部数据", stats.total],
    ["本校成果", stats.local],
    ["校外成果", stats.external_ready],
    ["待确认", stats.pending],
    ["需补邮箱", stats.missing_email],
  ];
  els.metrics.innerHTML = items
    .map(([label, value]) => `<div class="metric"><strong>${Number(value || 0)}</strong><span>${label}</span></div>`)
    .join("");
}

async function runConversionInBrowser() {
  clearDownloads();
  els.metrics.innerHTML = "";
  els.log.textContent = "";

  const dataFiles = Array.from(els.dataFiles.files || []);
  if (!dataFiles.length) {
    logLine("请至少选择一个数据文件。");
    return;
  }

  els.runButton.disabled = true;
  setStatus("处理中", "busy");

  try {
    await loadRuntime();
    const session = `/work/session_${Date.now()}`;
    pyodide.FS.mkdirTree(session);

    const inputPaths = [];
    for (const [idx, file] of dataFiles.entries()) {
      const path = `${session}/input_${idx}_${fileNameSafe(file.name)}`;
      await writeUploadedFile(file, path);
      inputPaths.push(path);
    }

    const accountPath = await writeUploadedFile(els.accountFile.files?.[0], `${session}/account_${fileNameSafe(els.accountFile.files?.[0]?.name)}`);
    const articlePath = await writeUploadedFile(els.articleFile.files?.[0], `${session}/article_${fileNameSafe(els.articleFile.files?.[0]?.name)}`);
    const aliasPath = await writeUploadedFile(els.aliasFile.files?.[0], `${session}/alias_${fileNameSafe(els.aliasFile.files?.[0]?.name)}`);
    const outputPath = `${session}/博文阁导入_文献数据合并.xlsx`;
    const csvPath = `${session}/博文阁导入_全部数据.csv`;

    pyodide.globals.set("INPUT_PATHS_JSON", JSON.stringify(inputPaths));
    pyodide.globals.set("OUTPUT_PATH", outputPath);
    pyodide.globals.set("CSV_PATH", csvPath);
    pyodide.globals.set("MODE", selectedMode());
    pyodide.globals.set("ACCOUNT_PATH", accountPath || "");
    pyodide.globals.set("ARTICLE_PATH", articlePath || "");
    pyodide.globals.set("ALIAS_PATH", aliasPath || "");
    pyodide.globals.set("SCOPUS_API_KEY", els.apiKey.value.trim());
    pyodide.globals.set("CLAIM_EMAIL_FILTER", els.claimEmailFilter.value.trim());

    const stats = await pyodide.runPythonAsync(`
import json
import pandas as pd
from converter import run_conversion

stats = run_conversion(
    json.loads(INPUT_PATHS_JSON),
    OUTPUT_PATH,
    MODE,
    accounts_path=ACCOUNT_PATH or None,
    article_library_path=ARTICLE_PATH or None,
    alias_path=ALIAS_PATH or None,
    scopus_api_key=SCOPUS_API_KEY or None,
    claim_email_filter=CLAIM_EMAIL_FILTER or None,
)
all_df = pd.read_excel(OUTPUT_PATH, sheet_name="全部数据", dtype=str)
all_df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
json.dumps(stats, ensure_ascii=False)
`);

    renderMetrics(JSON.parse(stats));
    makeDownload(
      els.downloadXlsx,
      pyodide.FS.readFile(outputPath),
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    );
    makeDownload(els.downloadCsv, pyodide.FS.readFile(csvPath), "text/csv;charset=utf-8");
    setStatus("已完成", "ready");
    logLine("处理完成，可以下载结果。");
  } catch (error) {
    setStatus("处理失败", "error");
    logLine(error.stack || String(error));
  } finally {
    els.runButton.disabled = false;
  }
}

els.runButton.addEventListener("click", runConversionInBrowser);
setStatus("未加载");
