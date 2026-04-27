// SPDX-License-Identifier: 0BSD
const stateUrl = "/api/state";
const commandUrl = "/api/command";
const mount = document.getElementById("svgMount");
const serialStatus = document.getElementById("serialStatus");
const modeStatus = document.getElementById("modeStatus");
const frameStatus = document.getElementById("frameStatus");
const byteDump = document.getElementById("byteDump");
const syncStatus = document.getElementById("syncStatus");
const timeStatus = document.getElementById("timeStatus");
const timeSource = document.getElementById("timeSource");
const intensityStatus = document.getElementById("intensityStatus");
const speedStatus = document.getElementById("speedStatus");
const footSpeedStatus = document.getElementById("footSpeedStatus");
const historyList = document.getElementById("historyList");
const logList = document.getElementById("logList");
const powerButton = document.querySelector('.power[data-command="power"]');
const commandButtons = new Map(
  [...document.querySelectorAll("[data-command]")].map((button) => [button.dataset.command, button])
);

let svgRoot = null;
let layerMap = new Map();
let textLayerMap = new Map();
let pollTimer = null;

async function loadDisplay() {
  const response = await fetch("/display.svg", { cache: "no-store" });
  const markup = await response.text();
  mount.innerHTML = markup;
  svgRoot = mount.querySelector("svg");
  if (!svgRoot) {
    throw new Error("Display SVG did not load");
  }

  layerMap = new Map();
  textLayerMap = new Map();
  svgRoot.querySelectorAll("[data-layer]").forEach((element) => {
    const label = element.getAttribute("data-layer");
    if (!label) return;
    layerMap.set(label, element);
    if (element.tagName.toLowerCase() === "text") {
      textLayerMap.set(label, element);
    }
  });
}

function setVisibleLayers(visibleLabels, textValues) {
  if (!svgRoot) return;
  const visibleSet = new Set(visibleLabels);
  layerMap.forEach((element, label) => {
    element.style.display = visibleSet.has(label) ? "" : "none";
  });
  Object.entries(textValues || {}).forEach(([label, value]) => {
    const textElement = textLayerMap.get(label);
    if (textElement) {
      textElement.textContent = value;
    }
  });
}

function renderList(target, items, formatter) {
  target.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("li");
    empty.textContent = "No data";
    target.appendChild(empty);
    return;
  }
  items.forEach((item) => {
    const node = document.createElement("li");
    node.textContent = formatter(item);
    target.appendChild(node);
  });
}

function renderState(state) {
  if (serialStatus) {
    serialStatus.textContent = state.connected
      ? `${state.port_name}${state.listening ? " - listen on" : ""}`
      : state.port_name;
  }
  if (modeStatus) {
    modeStatus.textContent = state.power_on
      ? `${state.mode.toUpperCase()}${state.auto_profile ? ` - ${state.auto_profile}` : ""}`
      : "OFF";
  }
  if (frameStatus) {
    frameStatus.textContent = state.raw_frame
      ? `${state.frame_signature} - ${state.raw_frame.map((value) => value.toString(16).padStart(2, "0")).join(" ")}`
      : "No frame";
  }
  if (byteDump) {
    byteDump.textContent = `Byte 3..6: ${state.bytes_3_to_6.map((value) => value.toString(16).padStart(2, "0")).join(" ")}`;
  }
  if (syncStatus) {
    const mode = state.sync.frame_live ? "live board frames" : "semantic fallback";
    const readiness = state.board_ready ? "board ready" : "waiting for firmware";
    syncStatus.textContent = `${mode} - ${readiness}`;
  }
  if (timeStatus) {
    timeStatus.textContent = state.time_text || "--";
  }
  if (timeSource) {
    timeSource.textContent = state.sync.time_source;
  }
  if (intensityStatus) {
    intensityStatus.textContent = `L${state.levels.intensity}`;
  }
  if (speedStatus) {
    speedStatus.textContent = `L${state.levels.speed}`;
  }
  if (footSpeedStatus) {
    footSpeedStatus.textContent = `L${state.levels.foot_speed}`;
  }

  setVisibleLayers(state.layers.visible, state.layers.text);

  Object.entries(state.buttons).forEach(([command, meta]) => {
    const button = commandButtons.get(command);
    if (!button) return;
    button.classList.toggle("is-active", Boolean(meta.active));
    button.classList.toggle("is-blocked", Boolean(meta.blocked));
    button.disabled = Boolean(meta.blocked);
  });

  powerButton.classList.toggle("is-active", Boolean(state.power_on));

  if (historyList) {
    renderList(
      historyList,
      state.command_history.slice().reverse(),
      (item) => `${new Date(item.at * 1000).toLocaleTimeString()}  ${item.command}`
    );
  }
  if (logList) {
    renderList(logList, state.backend_log.slice().reverse(), (item) => item);
  }
}

async function refreshState() {
  const response = await fetch(stateUrl, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`State fetch failed: ${response.status}`);
  }
  const state = await response.json();
  renderState(state);
  scheduleNextPoll(state.poll_hint_ms || 350);
}

function scheduleNextPoll(delayMs) {
  window.clearTimeout(pollTimer);
  pollTimer = window.setTimeout(() => {
    refreshState().catch(handleError);
  }, delayMs);
}

async function sendCommand(command) {
  const response = await fetch(commandUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command }),
  });
  if (!response.ok) {
    throw new Error(`Command failed: ${response.status}`);
  }
  const payload = await response.json();
  renderState(payload.state);
}

function handleError(error) {
  console.error(error);
  if (serialStatus) {
    serialStatus.textContent = `Error: ${error.message}`;
  }
  scheduleNextPoll(1200);
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-command]");
  if (!button) return;
  const command = button.dataset.command;
  sendCommand(command).catch(handleError);
});

Promise.resolve()
  .then(loadDisplay)
  .then(refreshState)
  .catch(handleError);
