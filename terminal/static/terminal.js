const terminal = document.getElementById("terminal");
const commandInput = document.getElementById("command-input");
const commandForm = document.getElementById("command-form");
const statusLine = document.getElementById("status-line");
const commandHistory = [];
let historyIndex = 0;
const commandNames = [
  "/screen ",
  "/cycle",
  "/briefing",
  "/pnl",
  "/status",
  "/shannon",
  "/janus",
  "/backtest run",
  "/trade ",
  "/help",
];
const panels = {
  "portfolio-summary": "/terminal/api/portfolio/summary",
  "portfolio-positions": "/terminal/api/portfolio/positions",
  "portfolio-risk": "/terminal/api/portfolio/risk",
  "portfolio-pnl": "/terminal/api/portfolio/pnl",
  "portfolio-decisions": "/terminal/api/portfolio/decisions",
  "agents-overview": "/terminal/api/agents/overview",
  "agents-execution": "/terminal/api/agents/execution-log",
  "agents-prompts": "/terminal/api/agents/prompts",
  "shannon-status": "/terminal/api/shannon/status",
  "shannon-queue": "/terminal/api/shannon/queue",
  "shannon-items": "/terminal/api/shannon/items",
  "shannon-scouts": "/terminal/api/shannon/scouts",
  "simons-patterns": "/terminal/api/simons/patterns",
  "simons-signals": "/terminal/api/simons/signals",
  "simons-backtest": "/terminal/api/simons/backtest",
  "janus-regime": "/terminal/api/janus/regime",
  "janus-weights": "/terminal/api/janus/weights",
  "janus-reweighting": "/terminal/api/janus/reweighting",
  "backtest-darwin": "/terminal/api/backtest/darwin",
  "backtest-fitness": "/terminal/api/backtest/fitness",
  "backtest-equity": "/terminal/api/backtest/equity",
  "backtest-ablations": "/terminal/api/backtest/ablations",
  "kalshi-summary": "/terminal/api/kalshi/summary",
  "kalshi-trades": "/terminal/api/kalshi/trades",
  "kalshi-positions": "/terminal/api/kalshi/positions",
  "intel-tracker": "/terminal/api/intel/tracker",
  "intel-deadline": "/terminal/api/intel/deadline",
  "intel-entities": "/terminal/api/intel/entities",
  "intel-news": "/terminal/api/intel/news",
  "graham-screen": "/terminal/api/graham",
};

function switchWorkspace(target) {
  document.querySelectorAll(".workspace").forEach((workspace) => {
    workspace.classList.toggle("active", workspace.id === target);
  });
  terminal.dataset.workspace = target;
  refreshActiveWorkspace();
}

document.querySelectorAll(".function-row button").forEach((button) => {
  button.addEventListener("click", () => switchWorkspace(button.dataset.target));
});

document.addEventListener("keydown", (event) => {
  if (/^F[1-8]$/.test(event.key)) {
    event.preventDefault();
    switchWorkspace(event.key);
  }
  if (event.key === "Escape") {
    commandInput.focus();
  }
});

setInterval(() => {
  const clock = document.getElementById("utc-clock");
  if (clock) clock.textContent = new Date().toISOString().slice(11, 19) + " UTC";
}, 1000);

function fmt(value) {
  if (value === null || value === undefined) return "--";
  if (typeof value === "number") {
    if (Math.abs(value) >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(value);
}

function clsForNumber(value) {
  return Number(value) < 0 ? "negative" : "positive";
}

function escapeHtml(value) {
  return fmt(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
}

function kv(data, keys = null) {
  const entries = keys ? keys.map((key) => [key, data?.[key]]) : Object.entries(data || {});
  return `<div class="kv">${entries.map(([key, value]) => `<span>${escapeHtml(key)}</span><span>${escapeHtml(value)}</span>`).join("")}</div>`;
}

function table(rows, columns) {
  const safeRows = Array.isArray(rows) ? rows : [];
  return `<table class="data-table"><thead><tr>${columns.map((col) => `<th>${escapeHtml(col.label)}</th>`).join("")}</tr></thead><tbody>${safeRows.map((row) => `<tr>${columns.map((col) => `<td>${escapeHtml(typeof col.value === "function" ? col.value(row) : row[col.value])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function renderPanel(id, payload) {
  const panel = document.querySelector(`#${id} .panel-body`);
  if (!panel) return;
  if (payload.status === "NOT_WIRED") {
    panel.innerHTML = `<div class="not-wired">NOT WIRED -- ${escapeHtml(payload.reason)}</div>`;
    return;
  }
  if (payload.status === "ERROR") {
    panel.innerHTML = `<div class="error-banner">ERROR -- ${escapeHtml(payload.reason)}</div>`;
    return;
  }
  const stale = payload.stale ? `<div class="error-banner">STALE -- ${escapeHtml(payload.file_mtime || payload.as_of)}</div>` : "";
  const data = payload.data;
  if (id === "portfolio-summary") {
    panel.innerHTML = stale + kv(data, ["portfolio_value", "pnl", "cash", "cash_pct", "exposure", "positions_count", "last_updated"]);
  } else if (id === "portfolio-positions") {
    panel.innerHTML = stale + table(data, [
      { label: "TICKER", value: (r) => r.ticker || r.symbol },
      { label: "SHARES", value: (r) => r.shares || r.quantity },
      { label: "PRICE", value: (r) => r.current_price || r.price || r.entry_price },
      { label: "VALUE", value: (r) => r.market_value || r.planned_value || r.value },
      { label: "PNL", value: (r) => r.pnl || r.unrealized_pnl },
    ]);
  } else if (id === "portfolio-decisions") {
    panel.innerHTML = stale + table(data, [
      { label: "TIME", value: (r) => r.timestamp || r.date },
      { label: "EXEC", value: (r) => r.executed },
      { label: "TRADE", value: (r) => JSON.stringify(r.trade || r.action || "").slice(0, 80) },
      { label: "REASON", value: (r) => r.reason },
    ]);
  } else if (id === "agents-overview") {
    panel.innerHTML = stale + `<div>COUNT: ${escapeHtml(data.agent_count)}</div>` + table(data.agents, [
      { label: "AGENT", value: "name" },
      { label: "WEIGHT", value: "weight" },
      { label: "CONV", value: "conviction" },
      { label: "SHARPE", value: "rolling_sharpe" },
      { label: "VIEW", value: "last_view" },
    ]);
  } else if (id === "shannon-status") {
    panel.innerHTML = `<div class="error-banner">SHANNON STALE -- ${escapeHtml(data.message)} | MTIME ${escapeHtml(payload.file_mtime)}</div>`;
  } else if (id === "shannon-queue") {
    panel.innerHTML = stale + kv(data, ["row_count", "newest_as_of"]) + table(data.rows, [
      { label: "TICKER", value: "ticker" },
      { label: "AS_OF", value: "as_of" },
      { label: "DIR", value: "direction" },
      { label: "CONV", value: "conviction" },
      { label: "TYPE", value: "catalyst_type" },
    ]);
  } else if (id === "kalshi-summary") {
    panel.innerHTML = stale + `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  } else if (id === "graham-screen") {
    if (payload.status === "NOT_RUN") {
      panel.innerHTML = `<div class="not-wired">NOT_RUN -- ${escapeHtml(payload.reason || "No GRAHAM output exists")}</div>`;
      return;
    }
    const rows = data.top_10 || [];
    const meta = data.meta || {};
    panel.innerHTML = stale
      + `<div>Last run: ${escapeHtml(meta.date)} | Scanned: ${escapeHtml(meta.universe_count)} | Passing: ${escapeHtml(meta.passing_count)}</div>`
      + table(rows, [
        { label: "RANK", value: "rank" },
        { label: "TICKER", value: "ticker" },
        { label: "PRICE", value: (r) => r.current_price },
        { label: "NCAV/SH", value: (r) => r.ncav_per_share },
        { label: "DISC%", value: (r) => r.ncav_discount_pct },
        { label: "QUALITY", value: "ncav_quality" },
      ])
      + `<div>Full report: ${escapeHtml(meta.portfolio_path || "")}</div>`;
  } else if (Array.isArray(data)) {
    panel.innerHTML = stale + `<pre>${escapeHtml(JSON.stringify(data.slice(-20), null, 2))}</pre>`;
  } else {
    panel.innerHTML = stale + `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  }
}

async function refreshPanel(id, url) {
  try {
    const response = await fetch(url);
    renderPanel(id, await response.json());
  } catch (error) {
    renderPanel(id, { status: "ERROR", reason: error.message });
  }
}

async function refreshHeader() {
  try {
    const response = await fetch("/terminal/api/header");
    const payload = await response.json();
    const healthDot = document.getElementById("health-dot");
    if (healthDot) healthDot.classList.toggle("stale", Boolean(payload.health?.red_dot));
    const snapshot = document.getElementById("snapshot-age");
    if (snapshot && payload.snapshot) snapshot.textContent = payload.snapshot.label;
    const portfolio = payload.portfolio?.data || {};
    document.getElementById("header-pnl").innerHTML = `${payload.health?.trade_ready ? "TRADE READY" : "TRADE BLOCKED"} | PNL: <span class="${clsForNumber(portfolio.pnl)}">${escapeHtml(portfolio.pnl)}</span>`;
    document.getElementById("header-cash").textContent = `CASH: ${fmt(portfolio.cash_pct)}%`;
    const hour = new Date().getUTCHours();
    document.getElementById("market-session").textContent = hour >= 13 && hour < 20 ? "SESSION: US OPEN" : "SESSION: CLOSED";
  } catch (error) {
    statusLine.textContent = "HEADER ERROR: " + error.message;
  }
}

function refreshActiveWorkspace() {
  const active = document.querySelector(".workspace.active");
  if (!active) return;
  active.querySelectorAll(".panel").forEach((panel) => {
    const url = panels[panel.id];
    if (url) refreshPanel(panel.id, url);
  });
}

refreshHeader();
refreshActiveWorkspace();
setInterval(refreshHeader, 15000);
setInterval(refreshActiveWorkspace, 30000);

commandForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const command = commandInput.value.trim();
  if (!command) return;
  commandHistory.push(command);
  historyIndex = commandHistory.length;
  commandInput.value = "";
  statusLine.textContent = "RUNNING " + command;
  try {
    const response = await fetch("/terminal/api/commands/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command }),
    });
    const payload = await response.json();
    if (payload.ui_action && /^F[1-8]$/.test(payload.ui_action)) {
      switchWorkspace(payload.ui_action);
    }
    if (payload.ui_action === "ticker") {
      terminal.dataset.ticker = command.toUpperCase();
    }
    const tail = (payload.output || []).slice(-3).join(" | ");
    statusLine.textContent = `${payload.status}: ${tail || command}`;
  } catch (error) {
    statusLine.textContent = "ERROR: " + error.message;
  }
});

commandInput.addEventListener("keydown", (event) => {
  if (event.key === "ArrowUp") {
    event.preventDefault();
    historyIndex = Math.max(0, historyIndex - 1);
    commandInput.value = commandHistory[historyIndex] || "";
  }
  if (event.key === "ArrowDown") {
    event.preventDefault();
    historyIndex = Math.min(commandHistory.length, historyIndex + 1);
    commandInput.value = commandHistory[historyIndex] || "";
  }
  if (event.key === "Tab") {
    event.preventDefault();
    const current = commandInput.value;
    const match = commandNames.find((name) => name.startsWith(current));
    if (match) commandInput.value = match;
  }
});

commandInput.focus();
