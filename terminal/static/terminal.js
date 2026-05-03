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

function switchWorkspace(target) {
  document.querySelectorAll(".workspace").forEach((workspace) => {
    workspace.classList.toggle("active", workspace.id === target);
  });
  terminal.dataset.workspace = target;
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
