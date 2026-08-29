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
let currentView = "data";
let simulationStandardPath = "";

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
  renderSessions();
  renderSessionOptions();
  renderSimulations();
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
  document.querySelector("#page-title").textContent =
    view === "simulations" ? "Simulations" : "Data Management";
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
  select.innerHTML = sessions
    .filter((item) => item.status === "ready")
    .map(
      (item) =>
        `<option value="${escapeHtml(item.id)}">${escapeHtml(item.interval)} ${escapeHtml(
          item.start_month,
        )} -> ${escapeHtml(item.end_month)} (${item.file_count || 0} files)</option>`,
    )
    .join("");
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
  document.querySelectorAll("[data-delete-simulation]").forEach((button) => {
    button.addEventListener("click", () => deleteSimulation(button.dataset.deleteSimulation));
  });
  document.querySelectorAll("#simulation-list [data-copy]").forEach((button) => {
    button.addEventListener("click", () => copyPath(button.dataset.copy, button));
  });
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
    "The CSV must have exactly these required columns: window_id,timestamp,symbol,target_quantity",
    "Write sparse decision events only: include a row only when target_quantity changes. Do not copy every candle or every input row into the output CSV.",
    "Use the exact window_id and symbol from the manifest. target_quantity is the desired net base-asset quantity after the event: positive long, negative short, zero flat. If a window has no signal, omit that window's rows; it will be evaluated as flat.",
    "Decision timestamps may be candle timestamps or intrabar event timestamps if the strategy uses trade-level data. Save the final CSV as decisions.csv.",
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
  formData.append("slippage_bps", document.querySelector("#slippage-bps").value);
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
document.querySelector("#symbol-mode").addEventListener("change", updateSymbolsForMode);
document.querySelector("#close-classification").addEventListener("click", closeClassification);
document.querySelector("#close-session").addEventListener("click", closeSessionDetail);
document.querySelector("#close-simulation").addEventListener("click", closeSimulationDetail);
document.querySelector("#workers").addEventListener("input", (event) => {
  document.querySelector("#workers-value").textContent = event.target.value;
});
document.querySelectorAll("[data-nav]").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.nav));
});
renderTargets();
switchView(currentView);
refresh();
