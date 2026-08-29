const targetLabels = [
  "bull",
  "bear",
  "sideways",
  "high_volatility",
  "low_volatility",
  "crash",
  "range_bound",
  "breakout",
];

let datasets = [];
let sessions = [];
let simulations = [];
let reports = [];
let currentView = "data";
let simulationStandardPath = "";
let activeReportSimulationId = "";
let activeRegimeRows = [];
const chartInstances = new Map();

const chartGroups = [
  ["total", "Total"],
  ["trend", "Trend"],
  ["volatility", "Volatility"],
  ["drawdown", "Drawdown"],
  ["volume", "Volume"],
  ["structure", "Structure"],
];

function parseLabels(value) {
  if (!value) return [];
  try {
    return JSON.parse(value);
  } catch {
    return [];
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatBytes(value) {
  if (!value) return "0 MB";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function formatNumber(value, digits = 2) {
  const number = Number(value || 0);
  return number.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function formatMoney(value) {
  return `${formatNumber(value)} USDT`;
}

async function refresh() {
  const health = await fetch("/api/health").then((response) => response.json());
  document.querySelector("#workspace").textContent = `Workspace: ${health.workspace}`;
  simulationStandardPath = health.simulation_standard_path || "";

  const response = await fetch("/api/datasets").then((item) => item.json());
  datasets = response.items || [];
  const sessionResponse = await fetch("/api/sessions").then((item) => item.json());
  sessions = sessionResponse.items || [];
  const simulationResponse = await fetch("/api/simulations").then((item) => item.json());
  simulations = simulationResponse.items || [];
  const reportResponse = await fetch("/api/reports").then((item) => item.json());
  reports = reportResponse.items || [];
  renderSessions();
  renderSessionOptions();
  renderSimulations();
  renderReports();
  renderMetrics();
  renderLabelDensity(datasets);
}

function renderMetrics() {
  const totalFiles = sessions.reduce((sum, item) => sum + (item.total_file_count || 0), 0);
  const globalSymbols = new Set(datasets.map((item) => item.symbol));
  const labels = new Set(datasets.flatMap((item) => parseLabels(item.labels)));

  document.querySelector("#dataset-count").textContent = totalFiles;
  document.querySelector("#symbol-count").textContent = globalSymbols.size;
  document.querySelector("#label-count").textContent = labels.size;
  document.querySelector("#session-count").textContent = sessions.length;
}

function switchView(view) {
  currentView = view;
  document.querySelectorAll("[data-nav]").forEach((button) => {
    button.classList.toggle("active", button.dataset.nav === view);
  });
  document.querySelectorAll("[data-view]").forEach((section) => {
    section.hidden = section.dataset.view !== view;
  });
  const titles = {
    data: "Data Management",
    simulations: "Simulations",
    reports: "Reports",
    "report-detail": "Report Analysis",
  };
  document.querySelector("#page-title").textContent = titles[view] || "Data Management";
}

function renderSessions() {
  const filter = document.querySelector("#session-filter").value.toLowerCase();
  const rows = sessions.filter((item) => JSON.stringify(item).toLowerCase().includes(filter));
  document.querySelector("#session-list").innerHTML = rows
    .map((item) => {
      const layers = item.agg_trades_file_count > 0 ? "klines + aggTrades" : "klines";
      return `
        <div class="session-item">
          <div class="session-main">
            <div class="session-title-row">
              <span class="status-pill ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
              <strong>${escapeHtml(item.interval)}</strong>
              <span>${escapeHtml(item.start_month)} -> ${escapeHtml(item.end_month)}</span>
            </div>
            <div class="session-stats">
              <span><b>${item.file_count || 0}/${item.target_file_count}</b><small>Klines</small></span>
              <span><b>${item.agg_trades_file_count || 0}</b><small>aggTrades</small></span>
              <span><b>${item.symbol_count || 0}</b><small>Symbols</small></span>
              <span><b>${formatBytes(item.disk_size_bytes)}</b><small>Disk</small></span>
              <span><b>${item.seed}</b><small>Seed</small></span>
            </div>
            <div class="session-path-row">
              <code>${escapeHtml(item.strategy_data_path)}</code>
              <button data-copy="${escapeHtml(item.strategy_data_path)}" type="button">Copy path</button>
            </div>
            <small class="session-meta">${escapeHtml(layers)} - ${escapeHtml(item.id)}</small>
          </div>
          <div class="session-actions">
            <button data-session="${escapeHtml(item.id)}" type="button">Inspect</button>
            <button data-classification="${escapeHtml(item.id)}" type="button">Classification</button>
            <button class="danger-button" data-delete-session="${escapeHtml(item.id)}" type="button">Delete</button>
          </div>
        </div>
      `;
    })
    .join("");
  document.querySelectorAll("[data-session]").forEach((button) => {
    button.addEventListener("click", () => openSessionDetail(button.dataset.session));
  });
  document.querySelectorAll("[data-classification]").forEach((button) => {
    button.addEventListener("click", () => openClassification(button.dataset.classification));
  });
  document.querySelectorAll("[data-delete-session]").forEach((button) => {
    button.addEventListener("click", () => deleteSession(button.dataset.deleteSession));
  });
  document.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", () => copyPath(button.dataset.copy, button));
  });
}

function renderSessionOptions() {
  const select = document.querySelector("#simulation-session");
  if (!select) return;
  const selectedSessionId = select.value;
  const readySessions = sessions.filter((item) => item.status === "ready");
  select.innerHTML = readySessions.length
    ? readySessions
        .map((item) => {
          const selected = item.id === selectedSessionId ? " selected" : "";
          const label = buildSessionSelectLabel(item);
          return `<option value="${escapeHtml(item.id)}" title="${escapeHtml(label)}"${selected}>${escapeHtml(
            label,
          )}</option>`;
        })
        .join("")
    : `<option value="">No ready sessions</option>`;
  renderSelectedSessionSummary();
}

function buildSessionSelectLabel(item) {
  const layers = item.agg_trades_file_count > 0 ? "klines + aggTrades" : "klines only";
  return [
    item.id,
    `${item.interval} ${item.start_month} -> ${item.end_month}`,
    `${item.file_count || 0}/${item.target_file_count || 0} klines`,
    `${item.symbol_count || 0} symbols`,
    `seed ${item.seed}`,
    layers,
  ].join(" | ");
}

function renderSelectedSessionSummary() {
  const summary = document.querySelector("#simulation-session-summary");
  const select = document.querySelector("#simulation-session");
  if (!summary || !select) return;

  const session = sessions.find((item) => item.id === select.value);
  if (!session) {
    summary.innerHTML = `<span>No ready session selected.</span>`;
    return;
  }

  const layers = session.agg_trades_file_count > 0 ? "klines + aggTrades" : "klines only";
  summary.innerHTML = `
    <strong>${escapeHtml(session.id)}</strong>
    <span>${escapeHtml(session.interval)} ${escapeHtml(session.start_month)} -> ${escapeHtml(
      session.end_month,
    )} | ${session.file_count || 0}/${session.target_file_count || 0} klines | ${
      session.symbol_count || 0
    } symbols | seed ${escapeHtml(session.seed)} | ${escapeHtml(layers)}</span>
    <code>${escapeHtml(session.strategy_data_path || session.path || "")}</code>
  `;
}

function renderSimulations() {
  const filter = document.querySelector("#simulation-filter").value.toLowerCase();
  const rows = simulations.filter((item) => JSON.stringify(item).toLowerCase().includes(filter));
  document.querySelector("#simulation-list").innerHTML = rows
    .map((item) => {
      const settings = item.settings || {};
      return `
        <div class="simulation-row">
          <div class="simulation-row-main">
            <div class="simulation-row-title">
              <span class="status-pill ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
              <strong>${escapeHtml(item.name)}</strong>
              <span>${escapeHtml(item.strategy_name)}</span>
            </div>
            <div class="simulation-row-stats">
              <span><b>${item.file_count || 0}</b><small>Files</small></span>
              <span><b>${item.error_count || 0}</b><small>Errors</small></span>
              <span><b>${formatBytes(item.disk_size_bytes)}</b><small>Disk</small></span>
              <span><b>${settings.fee_bps ?? 0}</b><small>Fee bps</small></span>
              <span><b>${settings.allow_short ? "Yes" : "No"}</b><small>Short</small></span>
            </div>
            <div class="session-path-row">
              <code>${escapeHtml(item.decisions_path)}</code>
              <button data-copy="${escapeHtml(item.decisions_path)}" type="button">Copy path</button>
            </div>
            <small class="session-meta">${escapeHtml(item.session_id)} - ${escapeHtml(item.id)}</small>
          </div>
          <div class="session-actions">
            <button data-run-simulation="${escapeHtml(item.id)}" type="button">Run</button>
            <button data-simulation="${escapeHtml(item.id)}" type="button">Inspect</button>
            <button class="danger-button" data-delete-simulation="${escapeHtml(item.id)}" type="button">Delete</button>
          </div>
        </div>
      `;
    })
    .join("");
  document.querySelectorAll("[data-simulation]").forEach((button) => {
    button.addEventListener("click", () => openSimulationDetail(button.dataset.simulation));
  });
  document.querySelectorAll("[data-run-simulation]").forEach((button) => {
    button.addEventListener("click", () => startSimulationRun(button.dataset.runSimulation, button));
  });
  document.querySelectorAll("[data-delete-simulation]").forEach((button) => {
    button.addEventListener("click", () => deleteSimulation(button.dataset.deleteSimulation));
  });
  document.querySelectorAll("#simulation-list [data-copy]").forEach((button) => {
    button.addEventListener("click", () => copyPath(button.dataset.copy, button));
  });
}

function renderReports() {
  const filter = document.querySelector("#report-filter").value.toLowerCase();
  const rows = reports.filter((item) => JSON.stringify(item).toLowerCase().includes(filter));
  document.querySelector("#report-list").innerHTML = rows.length
    ? rows
        .map((item) => {
          const summary = item.summary || {};
          return `
            <div class="report-row">
              <div class="simulation-row-main">
                <div class="simulation-row-title">
                  <span class="status-pill ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
                  <strong>${escapeHtml(item.name)}</strong>
                  <span>${escapeHtml(item.strategy_name)}</span>
                </div>
                <div class="simulation-row-stats">
                  <span><b>${formatNumber(summary.total_return_pct)}%</b><small>Total return</small></span>
                  <span><b>${formatMoney(summary.pnl)}</b><small>PnL</small></span>
                  <span><b>${summary.window_count || 0}</b><small>Samples</small></span>
                  <span><b>${summary.trade_count || 0}</b><small>Trades</small></span>
                  <span><b>${formatNumber(summary.winning_window_pct)}%</b><small>Consistency</small></span>
                </div>
                <small class="session-meta">${escapeHtml(item.session_id)} - ${escapeHtml(item.simulation_id)}</small>
              </div>
              <div class="session-actions">
                <button data-open-report="${escapeHtml(item.simulation_id)}" type="button">Open</button>
                <button class="danger-button" data-delete-report="${escapeHtml(item.simulation_id)}" type="button">Delete</button>
              </div>
            </div>
          `;
        })
        .join("")
    : `<div class="empty-state">No reports yet. Run a valid simulation to generate one.</div>`;
  document.querySelectorAll("[data-open-report]").forEach((button) => {
    button.addEventListener("click", () => openReportDetail(button.dataset.openReport));
  });
  document.querySelectorAll("[data-delete-report]").forEach((button) => {
    button.addEventListener("click", () => deleteReport(button.dataset.deleteReport));
  });
}

async function deleteReport(simulationId) {
  const confirmed = window.confirm(`Delete this report output?\n\n${simulationId}`);
  if (!confirmed) return;
  await fetch(`/api/reports/${simulationId}`, { method: "DELETE" }).then(async (response) => {
    if (!response.ok) {
      const body = await response.json();
      throw new Error(body.detail || "Report could not be deleted.");
    }
  });
  await refresh();
  if (currentView === "report-detail") {
    switchView("reports");
  }
}

async function startSimulationRun(simulationId, button) {
  const previous = button.textContent;
  button.disabled = true;
  button.textContent = "Running";
  try {
    const created = await fetch(`/api/simulations/${simulationId}/run`, { method: "POST" }).then(
      async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "Simulation run failed.");
        return body;
      },
    );
    pollSimulationRun(created.job_id, button, previous);
  } catch (error) {
    button.disabled = false;
    button.textContent = previous;
    window.alert(error.message);
  }
}

async function deleteSession(sessionId) {
  const confirmed = window.confirm(
    `Delete this session and all files inside it?\n\n${sessionId}`,
  );
  if (!confirmed) return;
  await fetch(`/api/sessions/${sessionId}`, { method: "DELETE" }).then(async (response) => {
    if (!response.ok) {
      const body = await response.json();
      throw new Error(body.detail || "Session could not be deleted.");
    }
  });
  await refresh();
}

async function deleteSimulation(simulationId) {
  const confirmed = window.confirm(
    `Delete this simulation, its catalog records, and all files inside it?\n\n${simulationId}`,
  );
  if (!confirmed) return;
  await fetch(`/api/simulations/${simulationId}`, { method: "DELETE" }).then(async (response) => {
    if (!response.ok) {
      const body = await response.json();
      throw new Error(body.detail || "Simulation could not be deleted.");
    }
  });
  closeSimulationDetail();
  await refresh();
}

async function openSessionDetail(sessionId) {
  const modal = document.querySelector("#session-modal");
  document.querySelector("#session-detail-title").textContent = sessionId;
  modal.hidden = false;
  const response = await fetch(`/api/sessions/${sessionId}`).then((item) => item.json());
  renderSessionDetail(response);
}

function renderSessionDetail(payload) {
  const session = payload.session;
  const layers = payload.layers || {};
  const agentPrompt = buildStrategyAgentPrompt(session);
  const layerRows = Object.entries(layers)
    .map(
      ([name, layer]) => `
        <tr>
          <td>${escapeHtml(name)}</td>
          <td>${layer.files}</td>
          <td>${layer.symbols}</td>
          <td>${layer.rows.toLocaleString()}</td>
          <td>${formatBytes(layer.bytes)}</td>
          <td><code>${escapeHtml(layer.path)}</code></td>
        </tr>
      `,
    )
    .join("");

  document.querySelector("#session-detail").innerHTML = `
    <div class="detail-grid">
      ${detailItem("Status", session.status)}
      ${detailItem("Interval", session.interval)}
      ${detailItem("Date range", `${session.start_month} -> ${session.end_month}`)}
      ${detailItem("Random seed", session.seed)}
      ${detailItem("Target klines", session.target_file_count)}
      ${detailItem("Ready klines", session.file_count || 0)}
      ${detailItem("aggTrades", session.agg_trades_file_count || 0)}
      ${detailItem("Symbols", session.symbol_count || 0)}
      ${detailItem("Disk", formatBytes(session.disk_size_bytes))}
      ${detailItem("Created", session.created_at)}
      ${detailItem("Completed", session.completed_at || "-")}
      ${detailItem("Source", `${session.source} / ${session.market}`)}
    </div>
    <div class="copy-panel">
      <label>Strategy agent prompt</label>
      <div class="copy-row">
        <code>${escapeHtml(agentPrompt)}</code>
        <button data-copy-prompt type="button">Copy prompt</button>
      </div>
      <label>Strategy data directory</label>
      <div class="copy-row">
        <code>${escapeHtml(session.strategy_data_path)}</code>
        <button data-copy="${escapeHtml(session.strategy_data_path)}" type="button">Copy</button>
      </div>
      <label>Klines directory</label>
      <div class="copy-row">
        <code>${escapeHtml(session.kline_data_path)}</code>
        <button data-copy="${escapeHtml(session.kline_data_path)}" type="button">Copy</button>
      </div>
      <label>aggTrades directory</label>
      <div class="copy-row">
        <code>${escapeHtml(session.agg_trades_data_path)}</code>
        <button data-copy="${escapeHtml(session.agg_trades_data_path)}" type="button">Copy</button>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Layer</th>
            <th>Files</th>
            <th>Symbols</th>
            <th>Rows</th>
            <th>Size</th>
            <th>Path</th>
          </tr>
        </thead>
        <tbody>${layerRows}</tbody>
      </table>
    </div>
    <details class="raw-detail">
      <summary>Raw session metadata</summary>
      <pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
    </details>
  `;
  document.querySelectorAll("#session-detail [data-copy]").forEach((button) => {
    button.addEventListener("click", () => copyPath(button.dataset.copy, button));
  });
  document.querySelector("#session-detail [data-copy-prompt]").addEventListener("click", (event) => {
    copyPath(agentPrompt, event.target);
  });
}

function buildStrategyAgentPrompt(session) {
  const manifestPath = `${session.path}\\manifest.json`;
  const klinePath = session.kline_data_path;
  const standardPath = session.simulation_standard_path || simulationStandardPath;
  return [
    `Read this MarketTestBench session manifest: ${manifestPath}`,
    `Read the parquet market data files from: ${klinePath}`,
    `Follow this simulation standard: ${standardPath}`,
    "For every item in manifest.json -> windows, load its session_path parquet file and produce one CSV containing all decisions.",
    "MarketTestBench standard initial cash = 10000 USDT. Calculate all sizing, stops, partial closes, and order tracking inside the strategy using this fixed capital base.",
    "The CSV must have exactly these required columns: window_id,timestamp,symbol,target_quantity,price",
    "Write sparse decision events only: include a row only when target_quantity changes. Do not copy every candle or every input row into the output CSV.",
    "Use the exact window_id and symbol from the manifest. target_quantity is the desired net base-asset quantity after the event: positive long, negative short, zero flat.",
    "price is the actual strategy fill price for that target change. Include slippage, spread, and execution assumptions in this price inside the strategy; MarketTestBench will not infer or adjust fill prices.",
    "Decision timestamps may be candle timestamps or intrabar event timestamps if the strategy uses trade-level data. If a window has no signal, omit that window's rows; it will be evaluated as flat. Save the final CSV as decisions.csv.",
  ].join("\n\n");
}

function detailItem(label, value) {
  return `
    <div class="detail-item">
      <small>${escapeHtml(label)}</small>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `;
}

async function copyPath(path, button) {
  await navigator.clipboard.writeText(path);
  const previous = button.textContent;
  button.textContent = "Copied";
  window.setTimeout(() => {
    button.textContent = previous;
  }, 1200);
}

function renderTargets() {
  document.querySelector("#label-grid").innerHTML = targetLabels
    .map((label) => `<span class="chip">${label}</span>`)
    .join("");
}

function renderLabelDensity(rows) {
  const counts = {};
  rows
    .filter((item) => item.data_type === "klines")
    .flatMap((item) => parseLabels(item.labels))
    .forEach((label) => {
      counts[label] = (counts[label] || 0) + 1;
    });
  const labels = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  document.querySelector("#label-grid").innerHTML =
    labels.length > 0
      ? labels.map(([label, count]) => `<span class="chip">${label}: ${count}</span>`).join("")
      : targetLabels.map((label) => `<span class="chip">${label}: 0</span>`).join("");
}

async function startDownload(event) {
  event.preventDefault();
  const mode = document.querySelector("#symbol-mode").value;
  const symbols = document
    .querySelector("#symbols")
    .value.split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const payload = {
    symbols: mode === "manual" ? symbols : [],
    volume_preset: mode === "manual" ? null : mode,
    interval: document.querySelector("#interval").value,
    start_month: document.querySelector("#start-month").value,
    end_month: document.querySelector("#end-month").value,
    month_count: Number(document.querySelector("#month-count").value),
    seed: Number(document.querySelector("#seed").value),
    workers: Number(document.querySelector("#workers").value),
    include_agg_trades: document.querySelector("#include-agg-trades").checked,
  };

  try {
    const created = await fetch("/api/downloads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(async (response) => {
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Download request failed.");
      return body;
    });
    pollJob(created.job_id);
  } catch (error) {
    document.querySelector("#job-summary").textContent = error.message;
  }
}

async function uploadSimulation(event) {
  event.preventDefault();
  const sessionId = document.querySelector("#simulation-session").value;
  const selectedFiles = Array.from(document.querySelector("#decision-files").files || []);
  if (!sessionId) {
    document.querySelector("#simulation-upload-summary").textContent = "Create a ready data session first.";
    return;
  }
  if (!selectedFiles.length) {
    document.querySelector("#simulation-upload-summary").textContent = "Select at least one CSV file.";
    return;
  }

  const formData = new FormData();
  formData.append("session_id", sessionId);
  formData.append("name", document.querySelector("#simulation-name").value);
  formData.append("strategy_name", document.querySelector("#strategy-name").value);
  formData.append("strategy_version", document.querySelector("#strategy-version").value);
  formData.append("fee_bps", document.querySelector("#fee-bps").value);
  formData.append("slippage_bps", "0");
  formData.append("allow_short", document.querySelector("#allow-short").checked ? "true" : "false");
  selectedFiles.forEach((file) => formData.append("files", file));

  document.querySelector("#simulation-upload-summary").textContent = "Uploading decisions...";
  document.querySelector("#simulation-validation-list").innerHTML = "";
  try {
    const created = await fetch("/api/simulations", {
      method: "POST",
      body: formData,
    }).then(async (response) => {
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Simulation upload failed.");
      return body;
    });
    document.querySelector(
      "#simulation-upload-summary",
    ).textContent = `${created.status}: ${created.file_count} files, ${created.row_count} decision rows`;
    await showSimulationValidation(created.simulation_id);
    await refresh();
  } catch (error) {
    document.querySelector("#simulation-upload-summary").textContent = error.message;
  }
}

async function showSimulationValidation(simulationId) {
  const detail = await fetch(`/api/simulations/${simulationId}`).then((item) => item.json());
  const issues = detail.validation_results || [];
  document.querySelector("#simulation-validation-list").innerHTML = issues.length
    ? issues
        .map(
          (issue) => `
            <div class="event failed">
              <strong>${escapeHtml(issue.issue_code)}</strong>
              <small>${escapeHtml(issue.file_name || "")} ${issue.row_number || ""} ${escapeHtml(
                issue.message,
              )}</small>
            </div>
          `,
        )
        .join("")
    : `<div class="event completed"><strong>Valid</strong><small>Decision files match the selected session.</small></div>`;
}

async function pollSimulationRun(jobId, button, previousLabel) {
  const status = await fetch(`/api/simulation-runs/${jobId}`).then((response) => response.json());
  if (status.status === "running" || status.status === "queued") {
    window.setTimeout(() => pollSimulationRun(jobId, button, previousLabel), 1500);
    return;
  }
  button.disabled = false;
  button.textContent = previousLabel;
  await refresh();
  if (status.status === "completed") {
    switchView("reports");
    openReportDetail(status.simulation_id);
    return;
  }
  window.alert((status.messages || ["Simulation run failed."])[0]);
}

async function openSimulationDetail(simulationId) {
  const modal = document.querySelector("#simulation-modal");
  document.querySelector("#simulation-detail-title").textContent = simulationId;
  modal.hidden = false;
  const detail = await fetch(`/api/simulations/${simulationId}`).then((item) => item.json());
  renderSimulationDetail(detail);
}

function renderSimulationDetail(payload) {
  const simulation = payload.simulation;
  const settings = simulation.settings || {};
  const files = payload.files || [];
  const validationResults = payload.validation_results || [];
  const fileRows = files
    .map(
      (file) => `
        <tr>
          <td>${escapeHtml(file.file_name)}</td>
          <td><span class="status-pill ${escapeHtml(file.status)}">${escapeHtml(file.status)}</span></td>
          <td>${file.row_count}</td>
          <td><code>${escapeHtml(file.path)}</code></td>
        </tr>
      `,
    )
    .join("");
  const validationRows = validationResults.length
    ? validationResults
        .map(
          (issue) => `
            <div class="event failed">
              <strong>${escapeHtml(issue.issue_code)}</strong>
              <small>${escapeHtml(issue.file_name || "")} ${issue.row_number || ""} ${escapeHtml(
                issue.message,
              )}</small>
            </div>
          `,
        )
        .join("")
    : `<div class="event completed"><strong>Valid</strong><small>No validation errors were recorded.</small></div>`;

  document.querySelector("#simulation-detail").innerHTML = `
    <div class="detail-grid">
      ${detailItem("Status", simulation.status)}
      ${detailItem("Simulation", simulation.name)}
      ${detailItem("Strategy", simulation.strategy_name)}
      ${detailItem("Version", simulation.strategy_version || "-")}
      ${detailItem("Session", simulation.session_id)}
      ${detailItem("Files", simulation.file_count || 0)}
      ${detailItem("Errors", simulation.error_count || 0)}
      ${detailItem("Disk", formatBytes(simulation.disk_size_bytes))}
      ${detailItem("Initial cash", settings.initial_cash ?? "-")}
      ${detailItem("Fee bps", settings.fee_bps ?? "-")}
      ${detailItem("Slippage bps", settings.slippage_bps ?? "-")}
      ${detailItem("Allow short", settings.allow_short ? "Yes" : "No")}
    </div>
    <div class="copy-panel">
      <label>Decisions directory</label>
      <div class="copy-row">
        <code>${escapeHtml(simulation.decisions_path)}</code>
        <button data-copy="${escapeHtml(simulation.decisions_path)}" type="button">Copy</button>
      </div>
      <label>Results directory</label>
      <div class="copy-row">
        <code>${escapeHtml(simulation.results_path)}</code>
        <button data-copy="${escapeHtml(simulation.results_path)}" type="button">Copy</button>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>File</th>
            <th>Status</th>
            <th>Rows</th>
            <th>Path</th>
          </tr>
        </thead>
        <tbody>${fileRows}</tbody>
      </table>
    </div>
    <div class="simulation-result">
      <strong>Validation</strong>
      <div class="event-list">${validationRows}</div>
    </div>
    <details class="raw-detail">
      <summary>Raw simulation metadata</summary>
      <pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
    </details>
  `;
  document.querySelectorAll("#simulation-detail [data-copy]").forEach((button) => {
    button.addEventListener("click", () => copyPath(button.dataset.copy, button));
  });
}

async function openReportDetail(simulationId) {
  const report = await fetch(`/api/reports/${simulationId}`).then(async (response) => {
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "Report could not be loaded.");
    return body;
  });
  switchView("report-detail");
  renderReportDetail(report);
}

function renderReportDetail(report) {
  disposeReportCharts();
  activeReportSimulationId = report.simulation.id;
  const summary = report.summary || {};
  const windows = report.window_metrics || [];
  const regimes = report.regime_summary || [];
  const equity = report.equity_curve || [];
  const displayTotal = totalMetricRow(windows);
  const rawMetadata = {
    simulation: report.simulation,
    settings: report.settings,
    summary: report.summary,
    artifacts: report.artifacts,
    artifact_row_limits: report.artifact_row_limits,
  };
  const labels = Array.from(
    new Set(windows.flatMap((item) => String(item.labels || "unlabeled").split("|"))),
  ).sort();
const defaultVisibleLabels = new Set(
    [...regimes]
      .sort((a, b) => Number(b.average_return_pct || 0) - Number(a.average_return_pct || 0))
      .slice(0, 5)
      .map((item) => item.label),
  );
  document.querySelector("#report-detail-name").textContent = report.simulation.name;
  document.querySelector("#report-detail").innerHTML = `
    <div class="detail-grid report-kpis">
      ${detailItem("Total return", `${formatNumber(displayTotal.average_return_pct)}%`)}
      ${detailItem("Avg PnL", formatMoney(displayTotal.pnl))}
      ${detailItem("Samples", summary.window_count || 0)}
      ${detailItem("Avg trades", formatNumber(displayTotal.trade_count))}
      ${detailItem("Avg balance usage", `${formatNumber(displayTotal.average_balance_usage_pct)}%`)}
      ${detailItem("Median sample", `${formatNumber(displayTotal.median_return_pct)}%`)}
      ${detailItem("Worst drawdown", `${formatNumber(displayTotal.max_drawdown_pct)}%`)}
      ${detailItem("Positive samples", `${formatNumber(displayTotal.winning_window_pct)}%`)}
      ${detailItem("Avg fees", formatMoney(displayTotal.fee_total))}
      ${detailItem("Avg slippage", formatMoney(displayTotal.slippage_total))}
      ${detailItem("Avg turnover", formatMoney(displayTotal.turnover))}
      ${detailItem("Best sample", `${formatNumber(displayTotal.best_return_pct)}%`)}
    </div>
    <div class="series-selector">
      <div class="series-selector-head">
        <strong>Visible series</strong>
        <div class="series-actions">
          <button type="button" data-series-action="total">Total only</button>
          <button type="button" data-series-action="top">Top 5 regimes</button>
          <button type="button" data-series-action="all">All regimes</button>
          <button type="button" data-series-action="clear">Clear regimes</button>
        </div>
      </div>
      <div id="series-selector-options">
        <label class="check-row"><input type="checkbox" value="__total__" checked /> <span>Total</span></label>
        ${labels
          .map(
            (label) =>
              `<label class="check-row"><input type="checkbox" value="${escapeHtml(label)}" ${
                defaultVisibleLabels.has(label) ? "checked" : ""
              } /> <span>${escapeHtml(label)}</span></label>`,
          )
          .join("")}
      </div>
    </div>
    <div class="report-chart-grid">
      <section class="chart-panel">
        <h3>Regime Consistency</h3>
        <div id="regime-chart"></div>
      </section>
      <section class="chart-panel">
        <h3>Return Distribution</h3>
        <div id="return-distribution-chart"></div>
      </section>
      <section class="chart-panel wide">
        <h3>Average Equity</h3>
        <div id="equity-chart"></div>
      </section>
      <section class="chart-panel">
        <h3>Average Drawdown</h3>
        <div id="drawdown-chart"></div>
      </section>
      <section class="chart-panel">
        <h3>Average Balance Usage</h3>
        <div id="balance-usage-chart"></div>
      </section>
      <section class="chart-panel">
        <h3>Fee and Slippage by Regime</h3>
        <div id="cost-chart"></div>
      </section>
      <section class="chart-panel">
        <h3>Turnover and Trades by Regime</h3>
        <div id="activity-chart"></div>
      </section>
      <section class="chart-panel">
        <h3>Consistency Score by Regime</h3>
        <div id="consistency-chart"></div>
      </section>
      <section class="chart-panel wide">
        <h3>Return vs Drawdown by Regime</h3>
        <div id="scatter-chart"></div>
      </section>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Series</th>
            <th>Samples</th>
            <th>Avg return</th>
            <th>Median return</th>
            <th>Drawdown</th>
            <th>Avg fees</th>
            <th>Avg slippage</th>
            <th>Avg trades</th>
            <th>Avg turnover</th>
          </tr>
        </thead>
        <tbody id="report-regime-table"></tbody>
      </table>
    </div>
    <details class="raw-detail">
      <summary>Raw report metadata</summary>
      <pre>${escapeHtml(JSON.stringify(rawMetadata, null, 2))}</pre>
    </details>
  `;

  const redraw = () => {
    const selectedSeries = selectedReportSeries();
    const aggregateSeries = buildAggregateSeries({
      windows,
      equity,
      regimes,
      selectedSeries,
    });
    const selectedRegimes = regimes.filter((item) => selectedSeries.has(item.label));
    renderRegimeChart(selectedRegimes);
    renderReturnDistributionChart(aggregateSeries.metricRows);
    renderAggregateLineChart("#equity-chart", aggregateSeries.equitySeries, " USDT", 340);
    renderAggregateLineChart("#drawdown-chart", aggregateSeries.drawdownSeries, "%", 270);
    renderAggregateLineChart("#balance-usage-chart", aggregateSeries.usageSeries, "%", 270);
    renderCostChart(aggregateSeries.metricRows);
    renderActivityChart(aggregateSeries.metricRows);
    renderConsistencyChart(aggregateSeries.metricRows);
    renderScatterChart(aggregateSeries.metricRows);
    activeRegimeRows = aggregateSeries.metricRows;
    renderRegimeTable(aggregateSeries.metricRows);
  };
  document.querySelectorAll("#series-selector-options input").forEach((input) => {
    input.addEventListener("change", redraw);
  });
  document.querySelectorAll("[data-series-action]").forEach((button) => {
    button.addEventListener("click", () => {
      applySeriesAction(button.dataset.seriesAction, defaultVisibleLabels);
      redraw();
    });
  });
  redraw();
}

function selectedReportSeries() {
  const selected = new Set();
  document.querySelectorAll("#series-selector-options input:checked").forEach((input) => {
    selected.add(input.value);
  });
  return selected;
}

function applySeriesAction(action, defaultVisibleLabels) {
  document.querySelectorAll("#series-selector-options input").forEach((input) => {
    if (input.value === "__total__") {
      input.checked = action !== "clear";
      return;
    }
    if (action === "total" || action === "clear") {
      input.checked = false;
    } else if (action === "top") {
      input.checked = defaultVisibleLabels.has(input.value);
    } else if (action === "all") {
      input.checked = true;
    }
  });
}

function disposeReportCharts() {
  chartInstances.forEach((chart) => chart.dispose());
  chartInstances.clear();
}

function renderChart(selector, option, height = 320) {
  const element = document.querySelector(selector);
  if (!element) return;
  if (!window.echarts) {
    element.innerHTML = `<div class="empty-state">Chart library could not be loaded.</div>`;
    return;
  }
  chartInstances.get(selector)?.dispose();
  element.innerHTML = "";
  element.style.height = `${height}px`;
  const chart = window.echarts.init(element, null, { renderer: "canvas" });
  chart.setOption(
    {
      animation: false,
      color: ["#1f6f4a", "#356ac3", "#b83a2f", "#8a5a12", "#5b6f1f", "#7a4ea3", "#147d7e", "#9b3d68"],
      textStyle: {
        color: "#415044",
        fontFamily: "Inter, Segoe UI, sans-serif",
      },
      tooltip: {
        trigger: "axis",
        appendToBody: true,
        confine: true,
        backgroundColor: "#ffffff",
        borderColor: "#d9dfd8",
        textStyle: { color: "#17211b" },
      },
      grid: { left: 58, right: 28, top: 42, bottom: 56, containLabel: true },
      ...option,
    },
    true,
  );
  chartInstances.set(selector, chart);
}

function chartDataZoom() {
  return [
    { type: "inside", throttle: 40 },
    { type: "slider", height: 18, bottom: 12, borderColor: "#d9dfd8", fillerColor: "rgba(31, 111, 74, 0.14)" },
  ];
}

function renderRegimeChart(rows) {
  renderChart("#regime-chart", {
    tooltip: {
      trigger: "item",
      formatter: (params) => {
        const row = rows[params.dataIndex];
        return `${escapeHtml(row.label)}<br>Return: ${formatNumber(row.average_return_pct)}%<br>Positive: ${formatNumber(
          row.winning_window_pct,
        )}%<br>Samples: ${row.window_count}`;
      },
    },
    xAxis: { type: "value", axisLabel: { formatter: "{value}%" }, splitLine: { lineStyle: { color: "#edf1ec" } } },
    yAxis: { type: "category", data: rows.map((item) => item.label), axisLabel: { width: 110, overflow: "truncate" } },
    series: [
      {
        type: "bar",
        data: rows.map((item) => Number(item.average_return_pct || 0)),
        itemStyle: {
          color: (params) => (params.value >= 0 ? "#1f6f4a" : "#b83a2f"),
          borderRadius: 4,
        },
        label: { show: true, position: "right", formatter: ({ value }) => `${formatNumber(value)}%` },
      },
    ],
  });
}

function renderReturnDistributionChart(rows) {
  const chartRows = rows.filter((item) => item.series !== "Total");
  renderChart("#return-distribution-chart", {
    tooltip: {
      trigger: "item",
      formatter: (params) => {
        const row = chartRows[params.dataIndex];
        return `${escapeHtml(row.series)}<br>Worst: ${formatNumber(row.worst_return_pct)}%<br>Median: ${formatNumber(
          row.median_return_pct,
        )}%<br>Best: ${formatNumber(row.best_return_pct)}%`;
      },
    },
    xAxis: { type: "value", axisLabel: { formatter: "{value}%" }, splitLine: { lineStyle: { color: "#edf1ec" } } },
    yAxis: { type: "category", data: chartRows.map((item) => item.series), axisLabel: { width: 110, overflow: "truncate" } },
    series: [
      {
        name: "Worst to best",
        type: "custom",
        encode: { x: [0, 1], y: 2 },
        data: chartRows.map((item, index) => [item.worst_return_pct, item.best_return_pct, index, item.median_return_pct]),
        renderItem: (params, api) => {
          const y = api.coord([0, api.value(2)])[1];
          const start = api.coord([api.value(0), api.value(2)])[0];
          const end = api.coord([api.value(1), api.value(2)])[0];
          const medianX = api.coord([api.value(3), api.value(2)])[0];
          return {
            type: "group",
            children: [
              {
                type: "rect",
                shape: { x: Math.min(start, end), y: y - 5, width: Math.abs(end - start), height: 10 },
                style: { fill: "#8fb86d" },
              },
              {
                type: "rect",
                shape: { x: medianX - 1.5, y: y - 11, width: 3, height: 22 },
                style: { fill: "#17211b" },
              },
            ],
          };
        },
      },
    ],
  });
}

function renderAggregateLineChart(selector, series, ySuffix, height) {
  renderLineChart(selector, series, { ySuffix, height });
}

function renderCostChart(rows) {
  renderChart("#cost-chart", {
    legend: { top: 0 },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      valueFormatter: (value) => formatMoney(value),
    },
    xAxis: { type: "value", splitLine: { lineStyle: { color: "#edf1ec" } } },
    yAxis: { type: "category", data: rows.map((item) => item.series), axisLabel: { width: 110, overflow: "truncate" } },
    series: [
      { name: "Avg fees", type: "bar", stack: "cost", data: rows.map((item) => item.fee_total) },
      { name: "Avg slippage", type: "bar", stack: "cost", data: rows.map((item) => item.slippage_total) },
    ],
  });
}

function renderActivityChart(rows) {
  renderChart("#activity-chart", {
    legend: { top: 0 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: [
      { type: "value", name: "Turnover", splitLine: { lineStyle: { color: "#edf1ec" } } },
      { type: "value", name: "Trades", splitLine: { show: false } },
    ],
    yAxis: { type: "category", data: rows.map((item) => item.series), axisLabel: { width: 110, overflow: "truncate" } },
    series: [
      { name: "Avg turnover", type: "bar", data: rows.map((item) => item.turnover), tooltip: { valueFormatter: formatMoney } },
      { name: "Avg trades", type: "bar", xAxisIndex: 1, data: rows.map((item) => item.trade_count), tooltip: { valueFormatter: formatNumber } },
    ],
  });
}

function renderConsistencyChart(rows) {
  const scored = rows
    .map((item) => {
      const returnPct = item.average_return_pct;
      const drawdown = Math.abs(item.max_drawdown_pct);
      const usage = item.average_balance_usage_pct;
      const score = returnPct - drawdown * 0.6 - usage * 0.03;
      return { ...item, score };
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, 30);
  renderChart("#consistency-chart", {
    tooltip: {
      trigger: "item",
      formatter: (params) => `${escapeHtml(scored[params.dataIndex].series)}<br>Score: ${formatNumber(params.value)}`,
    },
    xAxis: { type: "value", splitLine: { lineStyle: { color: "#edf1ec" } } },
    yAxis: { type: "category", data: scored.map((item) => item.series), axisLabel: { width: 110, overflow: "truncate" } },
    series: [
      {
        type: "bar",
        data: scored.map((item) => item.score),
        itemStyle: { color: (params) => (params.value >= 0 ? "#1f6f4a" : "#b83a2f"), borderRadius: 4 },
        label: { show: true, position: "right", formatter: ({ value }) => formatNumber(value) },
      },
    ],
  });
}

function renderScatterChart(rows) {
  renderChart("#scatter-chart", {
    tooltip: {
      trigger: "item",
      formatter: (params) => {
        const row = params.data.row;
        return `${escapeHtml(row.series)}<br>Return: ${formatNumber(row.average_return_pct)}%<br>Drawdown: ${formatNumber(
          row.max_drawdown_pct,
        )}%<br>Avg usage: ${formatNumber(row.average_balance_usage_pct)}%`;
      },
    },
    xAxis: { type: "value", name: "Drawdown %", axisLabel: { formatter: "{value}%" }, splitLine: { lineStyle: { color: "#edf1ec" } } },
    yAxis: { type: "value", name: "Return %", axisLabel: { formatter: "{value}%" }, splitLine: { lineStyle: { color: "#edf1ec" } } },
    dataZoom: chartDataZoom(),
    series: [
      {
        type: "scatter",
        symbolSize: (data) => Math.min(32, Math.max(10, 10 + Number(data[2] || 0) / 4)),
        data: rows.map((item) => ({
          value: [item.max_drawdown_pct, item.average_return_pct, item.average_balance_usage_pct],
          row: item,
          label: item.series,
        })),
        label: { show: true, formatter: (params) => params.data.label, position: "right" },
        itemStyle: { color: (params) => (params.data.row.average_return_pct >= 0 ? "#1f6f4a" : "#b83a2f") },
      },
    ],
  }, 380);
}

function renderRegimeTable(rows) {
  document.querySelector("#report-regime-table").innerHTML = rows
    .map(
      (item) => `
        <tr data-regime-row="${escapeHtml(item.series)}">
          <td>${escapeHtml(item.series)}</td>
          <td>${item.window_count}</td>
          <td>${formatNumber(item.average_return_pct)}%</td>
          <td>${formatNumber(item.median_return_pct)}%</td>
          <td>${formatNumber(item.max_drawdown_pct)}%</td>
          <td>${formatMoney(item.fee_total)}</td>
          <td>${formatMoney(item.slippage_total)}</td>
          <td>${formatNumber(item.trade_count)}</td>
          <td>${formatMoney(item.turnover)}</td>
        </tr>
      `,
    )
    .join("");
  document.querySelectorAll("[data-regime-row]").forEach((row) => {
    row.addEventListener("click", () => openRegimeDrilldown(row.dataset.regimeRow));
  });
}

function openRegimeDrilldown(seriesName) {
  const row = activeRegimeRows.find((item) => item.series === seriesName);
  if (!row) return;
  const samples = [...(row.samples || [])].sort(
    (a, b) => Number(b.return_pct || 0) - Number(a.return_pct || 0),
  );
  document.querySelector("#regime-detail-title").textContent = `${seriesName} - ${samples.length} samples`;
  document.querySelector("#regime-detail").innerHTML = `
    <div class="detail-grid report-kpis">
      ${detailItem("Avg return", `${formatNumber(row.average_return_pct)}%`)}
      ${detailItem("Median return", `${formatNumber(row.median_return_pct)}%`)}
      ${detailItem("Drawdown", `${formatNumber(row.max_drawdown_pct)}%`)}
      ${detailItem("Positive samples", `${formatNumber(row.winning_window_pct)}%`)}
      ${detailItem("Avg fees", formatMoney(row.fee_total))}
      ${detailItem("Avg slippage", formatMoney(row.slippage_total))}
      ${detailItem("Avg trades", formatNumber(row.trade_count))}
      ${detailItem("Avg turnover", formatMoney(row.turnover))}
    </div>
    <div class="drilldown-note">Rows are the source windows behind this aggregate, sorted by return.</div>
    <div class="table-wrap drilldown-table">
      <table>
        <thead>
          <tr>
            <th>Window</th>
            <th>Symbol</th>
            <th>Labels</th>
            <th>Return</th>
            <th>Drawdown</th>
            <th>Avg usage</th>
            <th>Fees</th>
            <th>Slippage</th>
            <th>Trades</th>
            <th>Turnover</th>
          </tr>
        </thead>
        <tbody>
          ${samples
            .map(
              (sample) => `
                <tr>
                  <td>${escapeHtml(sample.window_id || "")}</td>
                  <td>${escapeHtml(sample.symbol || "")}</td>
                  <td>${escapeHtml(sample.labels || "unlabeled")}</td>
                  <td>${formatNumber(sample.return_pct)}%</td>
                  <td>${formatNumber(sample.max_drawdown_pct)}%</td>
                  <td>${formatNumber(sample.average_balance_usage_pct)}%</td>
                  <td>${formatMoney(sample.fee_total)}</td>
                  <td>${formatMoney(sample.slippage_total)}</td>
                  <td>${formatNumber(sample.trade_count, 0)}</td>
                  <td>${formatMoney(sample.turnover)}</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
  document.querySelector("#regime-modal").hidden = false;
}

function closeRegimeDrilldown() {
  document.querySelector("#regime-modal").hidden = true;
}

function buildAggregateSeries({ windows, equity, regimes, selectedSeries }) {
  const windowById = Object.fromEntries(windows.map((item) => [item.window_id, item]));
  const selectedLabels = Array.from(selectedSeries).filter((item) => item !== "__total__");
  const metricRows = [];
  if (selectedSeries.has("__total__")) {
    metricRows.push(totalMetricRow(windows));
  }
  metricRows.push(
    ...regimes
      .filter((item) => selectedLabels.includes(item.label))
      .map((item) =>
        regimeMetricRow(
          item,
          windows.filter((windowItem) =>
            String(windowItem.labels || "unlabeled").split("|").includes(item.label),
          ),
        ),
      ),
  );

  const equitySeries = [];
  const drawdownSeries = [];
  const usageSeries = [];
  if (selectedSeries.has("__total__")) {
    equitySeries.push(aggregateEquityRows("Total", equity, "equity", 0));
    drawdownSeries.push(aggregateEquityRows("Total", equity, "drawdown_pct", 0));
    usageSeries.push(aggregateEquityRows("Total", equity, "balance_usage_pct", 0));
  }
  selectedLabels.forEach((label, index) => {
    const labelRows = equity.filter((row) =>
      String(windowById[row.window_id]?.labels || "unlabeled").split("|").includes(label),
    );
    equitySeries.push(aggregateEquityRows(label, labelRows, "equity", index + 1));
    drawdownSeries.push(aggregateEquityRows(label, labelRows, "drawdown_pct", index + 1));
    usageSeries.push(aggregateEquityRows(label, labelRows, "balance_usage_pct", index + 1));
  });
  return {
    metricRows,
    equitySeries: equitySeries.filter((item) => item.points.length),
    drawdownSeries: drawdownSeries.filter((item) => item.points.length),
    usageSeries: usageSeries.filter((item) => item.points.length),
  };
}

function totalMetricRow(windows) {
  const returns = windows.map((item) => Number(item.return_pct || 0));
  return {
    series: "Total",
    window_count: windows.length,
    pnl: average(windows.map((item) => Number(item.pnl || 0))),
    trade_count: average(windows.map((item) => Number(item.trade_count || 0))),
    average_return_pct: average(returns),
    median_return_pct: median(returns),
    best_return_pct: returns.length ? Math.max(...returns) : 0,
    worst_return_pct: returns.length ? Math.min(...returns) : 0,
    winning_window_pct: percentage(returns.filter((value) => value > 0).length, windows.length),
    max_drawdown_pct: Math.min(...windows.map((item) => Number(item.max_drawdown_pct || 0)), 0),
    average_balance_usage_pct: average(windows.map((item) => Number(item.average_balance_usage_pct || 0))),
    fee_total: average(windows.map((item) => Number(item.fee_total || 0))),
    slippage_total: average(windows.map((item) => Number(item.slippage_total || 0))),
    turnover: average(windows.map((item) => Number(item.turnover || 0))),
    samples: windows,
  };
}

function regimeMetricRow(item, matchingWindows) {
  const sampleCount = Math.max(matchingWindows.length, 1);
  return {
    series: item.label,
    window_count: Number(item.window_count || 0),
    trade_count: Number(item.trade_count || 0) / sampleCount,
    average_return_pct: Number(item.average_return_pct || 0),
    median_return_pct: Number(item.median_return_pct || 0),
    best_return_pct: Number(item.best_return_pct || 0),
    worst_return_pct: Number(item.worst_return_pct || 0),
    winning_window_pct: Number(item.winning_window_pct || 0),
    max_drawdown_pct: Number(item.max_drawdown_pct || 0),
    average_balance_usage_pct: average(
      matchingWindows.map((windowItem) => Number(windowItem.average_balance_usage_pct || 0)),
    ),
    fee_total: Number(item.fee_total || 0) / sampleCount,
    slippage_total: Number(item.slippage_total || 0) / sampleCount,
    turnover: Number(item.turnover || 0) / sampleCount,
    samples: matchingWindows,
  };
}

function aggregateEquityRows(name, rows, field, colorIndex) {
  const grouped = groupBy(rows, "window_id");
  const buckets = {};
  Object.values(grouped).forEach((items) => {
    items.forEach((item, index) => {
      buckets[index] = buckets[index] || [];
      buckets[index].push(Number(item[field] || 0));
    });
  });
  return {
    name,
    color: chartColor(colorIndex),
    points: Object.entries(buckets).map(([index, values]) => ({
      x: Number(index),
      y: average(values),
    })),
  };
}

function average(values) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function median(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const midpoint = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[midpoint] : (sorted[midpoint - 1] + sorted[midpoint]) / 2;
}

function percentage(value, total) {
  return total ? (value / total) * 100 : 0;
}

function renderLineChart(selector, series, options = {}) {
  if (!series.length || series.every((item) => item.points.length === 0)) {
    document.querySelector(selector).innerHTML = `<div class="empty-state">No chart data.</div>`;
    return;
  }
  const allPoints = series.flatMap((item) => item.points);
  let minY = Math.min(...allPoints.map((item) => item.y));
  let maxY = Math.max(...allPoints.map((item) => item.y));
  const yPadding = Math.max((maxY - minY) * 0.08, Math.abs(maxY || 1) * 0.0005);
  minY -= yPadding;
  maxY += yPadding;
  renderChart(
    selector,
    {
      legend: { top: 0, type: "scroll" },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        valueFormatter: (value) => `${formatNumber(value)}${options.ySuffix || ""}`,
      },
      xAxis: { type: "value", name: "Step", splitLine: { lineStyle: { color: "#edf1ec" } } },
      yAxis: {
        type: "value",
        min: minY,
        max: maxY,
        axisLabel: { formatter: (value) => `${formatNumber(value)}${options.ySuffix || ""}` },
        splitLine: { lineStyle: { color: "#edf1ec" } },
      },
      dataZoom: chartDataZoom(),
      series: series.map((item) => ({
        name: item.name,
        type: "line",
        showSymbol: false,
        symbol: "circle",
        symbolSize: 6,
        sampling: "lttb",
        smooth: false,
        lineStyle: { width: 2 },
        data: item.points.map((point) => [point.x, point.y]),
      })),
    },
    options.height || 300,
  );
}

function groupBy(rows, key) {
  return rows.reduce((groups, item) => {
    const value = item[key] || "unknown";
    groups[value] = groups[value] || [];
    groups[value].push(item);
    return groups;
  }, {});
}

function chartColor(index) {
  const colors = [
    "#1f6f4a",
    "#356ac3",
    "#b83a2f",
    "#8a5a12",
    "#5b6f1f",
    "#7a4ea3",
    "#147d7e",
    "#9b3d68",
  ];
  return colors[index % colors.length];
}

function getChartTooltip() {
  let tooltip = document.querySelector("#chart-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = "chart-tooltip";
    tooltip.hidden = true;
    document.body.appendChild(tooltip);
  }
  return tooltip;
}

function showChartTooltip(event, target) {
  const tooltip = getChartTooltip();
  tooltip.textContent = target.dataset.chartTooltip || "";
  tooltip.style.borderColor = target.dataset.chartColor || "#17211b";
  tooltip.hidden = false;
  moveChartTooltip(event);
}

function moveChartTooltip(event) {
  const tooltip = getChartTooltip();
  const offset = 14;
  const bounds = tooltip.getBoundingClientRect();
  const left = Math.min(window.innerWidth - bounds.width - 12, event.clientX + offset);
  const top = Math.min(window.innerHeight - bounds.height - 12, event.clientY + offset);
  tooltip.style.left = `${Math.max(12, left)}px`;
  tooltip.style.top = `${Math.max(12, top)}px`;
}

function hideChartTooltip() {
  const tooltip = document.querySelector("#chart-tooltip");
  if (tooltip) tooltip.hidden = true;
}

async function updateSymbolsForMode() {
  const mode = document.querySelector("#symbol-mode").value;
  const symbolInput = document.querySelector("#symbols");
  if (mode === "manual") {
    symbolInput.disabled = false;
    return;
  }
  symbolInput.disabled = true;
  symbolInput.value = "Loading symbols...";
  try {
    const response = await fetch(`/api/symbols/top-volume/${mode}`).then((item) => item.json());
    symbolInput.value = response.symbols.join(",");
  } catch (error) {
    symbolInput.value = `Could not load symbols: ${error.message}`;
  }
}

async function openClassification(sessionId) {
  const modal = document.querySelector("#classification-modal");
  document.querySelector("#classification-session").textContent = sessionId;
  modal.hidden = false;
  const response = await fetch(`/api/sessions/${sessionId}/classification`).then((item) =>
    item.json(),
  );
  renderClassificationBars(response.groups || {});
}

function closeClassification() {
  document.querySelector("#classification-modal").hidden = true;
}

function closeSessionDetail() {
  document.querySelector("#session-modal").hidden = true;
}

function closeSimulationDetail() {
  document.querySelector("#simulation-modal").hidden = true;
}

function renderClassificationBars(groups) {
  document.querySelector("#classification-bars").innerHTML = chartGroups
    .map(([key, title]) => renderBarGroup(title, groups[key] || {}))
    .join("");
}

function renderBarGroup(title, counts) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, value]) => sum + value, 0);
  const rows = entries.length
    ? entries
        .map(([label, value]) => {
          const percent = total ? (value / total) * 100 : 0;
          return `
            <div class="bar-row">
              <div class="bar-label">
                <strong>${escapeHtml(label)}</strong>
                <span>${value} - ${percent.toFixed(1)}%</span>
              </div>
              <div class="bar-track"><div class="bar-fill" style="width: ${percent}%"></div></div>
            </div>
          `;
        })
        .join("")
    : `<div class="empty-chart">${escapeHtml(title)}<br><small>No classification data</small></div>`;
  return `
    <section class="bar-card">
      <h3>${escapeHtml(title)}</h3>
      ${rows}
    </section>
  `;
}

async function pollJob(jobId) {
  const status = await fetch(`/api/downloads/${jobId}`).then((response) => response.json());
  renderJob(status);
  if (status.status === "running" || status.status === "queued") {
    window.setTimeout(() => pollJob(jobId), 1500);
    return;
  }
  refresh();
}

function renderJob(job) {
  const target = job.target_valid_files || 100;
  const valid = job.valid_files || 0;
  const attempted = job.attempted_files || 0;
  const candidates = job.candidate_files || job.candidate_months || 0;
  const percent = Math.min(100, Math.round((valid / target) * 100));
  document.querySelector("#progress-fill").style.width = `${percent}%`;

  const message = job.messages && job.messages.length ? ` - ${job.messages[0]}` : "";
  const session = job.session_path ? ` - session: ${job.session_path}` : "";
  const aggTrades =
    job.agg_trades_files === undefined ? "" : `, ${job.agg_trades_files || 0} aggTrades`;
  document.querySelector(
    "#job-summary",
  ).textContent = `${job.status}: ${valid}/${target} valid klines${aggTrades}, ${attempted}/${candidates} candidates tried${session}${message}`;

  const events = (job.events || []).slice(-80).reverse();
  document.querySelector("#event-list").innerHTML = events
    .map((event) => {
      const state =
        event.type === "file_failed"
          ? "failed"
          : event.type === "file_missing"
            ? "missing"
            : event.type === "file_completed"
              ? "completed"
              : "";
      const title =
        event.type === "file_started"
          ? "Downloading"
          : event.type === "file_failed"
            ? "Failed"
            : event.type === "file_missing"
              ? "Data unavailable"
              : event.type === "file_completed"
                ? event.result === "skipped"
                  ? "Already ready"
                  : "Normalized"
                : event.type === "resolving_symbols"
                  ? "Preparing"
                  : event.type === "symbols_resolved"
                    ? "Symbols ready"
                    : "Planned";
      const detail =
        event.message ||
        `${event.symbol || ""} ${event.interval || ""} ${event.year_month || ""}${
          event.agg_trades ? ` + aggTrades ${event.agg_trades}` : ""
        }`;
      return `
        <div class="event ${state}">
          <strong>${title}</strong>
          <small>${escapeHtml(detail)}</small>
        </div>
      `;
    })
    .join("");
}

document.querySelector("#download-form").addEventListener("submit", startDownload);
document.querySelector("#simulation-form").addEventListener("submit", uploadSimulation);
document.querySelector("#decision-files").addEventListener("change", (event) => {
  const count = event.target.files.length;
  document.querySelector("#selected-file-count").textContent =
    count === 0 ? "No files selected" : `${count} file${count === 1 ? "" : "s"} selected`;
});
document.querySelector("#refresh").addEventListener("click", refresh);
document.querySelector("#session-filter").addEventListener("input", renderSessions);
document.querySelector("#simulation-filter").addEventListener("input", renderSimulations);
document.querySelector("#simulation-session").addEventListener("change", renderSelectedSessionSummary);
document.querySelector("#report-filter").addEventListener("input", renderReports);
document.querySelector("#symbol-mode").addEventListener("change", updateSymbolsForMode);
document.querySelector("#close-classification").addEventListener("click", closeClassification);
document.querySelector("#close-session").addEventListener("click", closeSessionDetail);
document.querySelector("#close-simulation").addEventListener("click", closeSimulationDetail);
document.querySelector("#close-regime").addEventListener("click", closeRegimeDrilldown);
document.querySelector("#back-to-reports").addEventListener("click", () => switchView("reports"));
document.querySelector("#delete-open-report").addEventListener("click", () => {
  if (activeReportSimulationId) deleteReport(activeReportSimulationId);
});
function handleChartTooltipMove(event) {
  const target = event.target.closest?.("[data-chart-tooltip]");
  if (target) {
    showChartTooltip(event, target);
  } else {
    hideChartTooltip();
  }
}

document.addEventListener("pointermove", handleChartTooltipMove);
document.addEventListener("mousemove", handleChartTooltipMove);
document.addEventListener("pointerleave", hideChartTooltip);
window.addEventListener("resize", () => {
  chartInstances.forEach((chart) => chart.resize());
});
document.querySelector("#workers").addEventListener("input", (event) => {
  document.querySelector("#workers-value").textContent = event.target.value;
});
document.querySelectorAll("[data-nav]").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.nav));
});
renderTargets();
switchView(currentView);
refresh();
