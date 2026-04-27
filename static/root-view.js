// SPDX-License-Identifier: 0BSD
(() => {
  const root = document;
  const screen = root.querySelector(".screen");
  const screenSvg = screen ? screen.querySelector("svg") : null;
  const powerButton = root.querySelector(".power");
  const leftButtons = Array.from(root.querySelectorAll(".stack--left .btn"));
  const rightButtons = Array.from(root.querySelectorAll(".stack--right .btn"));
  const bottomButtons = Array.from(root.querySelectorAll(".bottom-grid .btn"));

  const DOM = {
    power: powerButton,
    ramiona: leftButtons[0],
    przedramiona: leftButtons[1],
    nogi: leftButtons[2],
    sila_nacisku_plus: leftButtons[3],
    sila_nacisku_minus: leftButtons[4],
    masaz_posladkow: leftButtons[5],
    szyja: rightButtons[0],
    do_przodu_do_tylu_2: rightButtons[1],
    plecy_i_talia: rightButtons[2],
    do_przodu_do_tylu_1: rightButtons[3],
    predkosc_plus: rightButtons[4],
    predkosc_minus: rightButtons[5],
    masaz_stop: bottomButtons[0],
    pauza: bottomButtons[1],
    czas: bottomButtons[2],
    grawitacja_zero: bottomButtons[3],
    oparcie_w_gore: bottomButtons[4],
    predkosc_masazu_stop: bottomButtons[5],
    ogrzewanie: bottomButtons[6],
    masaz_calego_ciala: bottomButtons[7],
    tryb_automatyczny: bottomButtons[8],
    oparcie_w_dol: bottomButtons[9]
  };

  const MANAGED_LAYERS = [
    "Background",
    "Body",
    "Ramiona",
    "Przedramiona",
    "Nogi",
    "Masaz_Posladkow",
    "Masaz_Stop",
    "Ogrzewanie",
    "Szyja",
    "? Szyja",
    "Plecy_i_talia",
    "? Plecy_i_talia",
    "Sila_nacisku-TEXT",
    "Sila_nacisku-LVL1",
    "Sila_nacisku-LVL2",
    "Sila_nacisku-LVL3",
    "PredkoscTEXT",
    "Predkosc-LVL1",
    "Predkosc-LVL2",
    "Predkosc-LVL3",
    "Predkosc_masazu_stop",
    "Predkosc_masazu_stop-LVL1",
    "Predkosc_masazu_stop-LVL2",
    "Predkosc_masazu_stop-LVL3",
    "Czas-TEXT",
    "Czas-NUMBER",
    "SHAPE_CHECK-TEXT",
    "Tryb_manualny",
    "Tryb_automatyczny",
    "Tryb_automatyczny-A",
    "Tryb_automatyczny-B",
    "Tryb_automatyczny-C",
    "Tryb_automatyczny-D"
  ];

  const buttonToCommand = new Map(
    Object.entries(DOM)
      .filter(([command, button]) => command !== "power" && button)
      .map(([command, button]) => [button, command])
  );

  const svgLayers = new Map();
  let pollTimer = null;

  function readLayerLabel(element) {
    return (
      element.getAttribute("data-layer") ||
      element.getAttribute("inkscape:label") ||
      element.getAttribute("label") ||
      Array.from(element.attributes || []).find((attribute) =>
        attribute.name.endsWith(":label")
      )?.value ||
      ""
    );
  }

  function buildSvgLayerMap() {
    if (!screenSvg) return;
    screenSvg.querySelectorAll("*").forEach((element) => {
      const label = readLayerLabel(element);
      if (!label) return;
      if (!svgLayers.has(label)) {
        svgLayers.set(label, []);
      }
      svgLayers.get(label).push(element);
    });
  }

  function withLayer(label, callback) {
    const elements = svgLayers.get(label) || [];
    elements.forEach(callback);
  }

  function setLayerVisible(label, visible) {
    withLayer(label, (element) => {
      element.style.display = visible ? "" : "none";
    });
  }

  function setSvgTextContent(element, value) {
    const tspans = Array.from(element.querySelectorAll("tspan"));
    if (!tspans.length) {
      element.textContent = String(value);
      return;
    }
    tspans.forEach((tspan, index) => {
      tspan.textContent = index === tspans.length - 1 ? String(value) : "";
    });
  }

  function setLayerText(label, value) {
    withLayer(label, (element) => {
      setSvgTextContent(element, value);
    });
  }

  function expandCumulativeLevelLayers(visible) {
    const expanded = new Set(visible);
    [
      "Sila_nacisku-LVL",
      "Predkosc-LVL",
      "Predkosc_masazu_stop-LVL"
    ].forEach((prefix) => {
      for (let level = 3; level >= 1; level -= 1) {
        if (expanded.has(`${prefix}${level}`)) {
          for (let fill = 1; fill < level; fill += 1) {
            expanded.add(`${prefix}${fill}`);
          }
        }
      }
    });
    return expanded;
  }

  function renderLayers(state) {
    const visible = expandCumulativeLevelLayers(
      new Set((state.layers && state.layers.visible) || [])
    );
    MANAGED_LAYERS.forEach((label) => {
      setLayerVisible(label, visible.has(label));
    });
    const textLayers = (state.layers && state.layers.text) || {};
    Object.entries(textLayers).forEach(([label, value]) => {
      setLayerText(label, value);
    });
  }

  function paintBlocked(button) {
    button.setAttribute("aria-disabled", "false");
    button.dataset.blocked = "false";
    button.style.opacity = "";
    button.style.filter = "";
    button.style.cursor = "";
  }

  function renderButtons(state) {
    if (DOM.power) {
      DOM.power.classList.toggle("is-active", !!state.power_on);
      DOM.power.setAttribute("aria-pressed", String(!!state.power_on));
    }

    Object.entries(DOM).forEach(([command, button]) => {
      if (!button || command === "power") return;
      const meta = state.buttons ? state.buttons[command] : null;
      const active = !!(meta && meta.active);
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
      paintBlocked(button);
    });
  }

  function render(state) {
    renderLayers(state);
    renderButtons(state);
    if (screen) {
      screen.classList.add("is-ready");
    }
    window.__chairBridgeState = state;
  }

  async function refreshState() {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`State fetch failed: ${response.status}`);
    }
    const state = await response.json();
    render(state);
    scheduleNextPoll(state.poll_hint_ms || 350);
  }

  function scheduleNextPoll(delayMs) {
    window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(() => {
      refreshState().catch(handleError);
    }, delayMs);
  }

  async function sendCommand(command) {
    const response = await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command })
    });
    if (!response.ok) {
      throw new Error(`Command failed: ${response.status}`);
    }
    const payload = await response.json();
    render(payload.state);
  }

  function handleError(error) {
    console.error(error);
    scheduleNextPoll(1200);
  }

  buildSvgLayerMap();

  root.addEventListener("click", (event) => {
    const button = event.target.closest(".js-toggle");
    if (!button) return;

    if (button === DOM.power) {
      sendCommand("power").catch(handleError);
      return;
    }

    const command = buttonToCommand.get(button);
    if (!command) return;
    sendCommand(command).catch(handleError);
  });

  refreshState().catch(handleError);
})();
