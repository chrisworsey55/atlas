const terminal = document.getElementById("terminal");

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
    document.getElementById("command-input").focus();
  }
});

setInterval(() => {
  const clock = document.getElementById("utc-clock");
  if (clock) clock.textContent = new Date().toISOString().slice(11, 19) + " UTC";
}, 1000);

