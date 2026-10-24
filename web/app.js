(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const LANE_COLORS = { text: "#f5a524", decisions: "#38d6f5", baseline: "#9b8cff" };
  const LANE_GLYPHS = { text: "T", decisions: "D", baseline: "C" };
  const LANE_LABELS = { text: "Texto", decisions: "Decisiones", baseline: "Control" };
  const WINNER_LABELS = { text: "texto", decisions: "decisiones", tie: "empate" };
  const STATUS_LABELS = {
    waiting: "en espera",
    running: "en marcha",
    solved: "resuelto",
    unsolved: "sin ruta",
    error: "error",
    cancelled: "cancelado",
  };

  const EMPTY_STATE_HTML = `
    <span class="eyebrow">Sin carrera</span>
    <h2>Elige el laberinto, dos modelos y pulsa iniciar.</h2>
    <p>
      Verás cada token avanzar en vivo. Los dos carriles usan el mismo laberinto y el mismo
      reloj; gana la primera ruta verificada.
    </p>`;

  const state = {
    bootstrap: null,
    preview: null,
    race: null,
    raceId: null,
    stream: null,
    pollTimer: null,
    laneNodes: new Map(),
    laneOrder: [],
    anim: new Map(),
    replay: null,
    archived: false,
    present: false,
    lastLogSignature: "",
    toastTimer: null,
    previewTimer: null,
  };

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }
    if (!response.ok) {
      const detail = payload && (payload.detail || payload.error);
      throw new Error(typeof detail === "string" ? detail : `HTTP ${response.status}`);
    }
    return payload;
  }

  function toast(message) {
    const el = $("#toast");
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => el.classList.remove("show"), 2800);
  }

  function formatMs(ms) {
    if (!Number.isFinite(ms) || ms < 0) ms = 0;
    const total = Math.floor(ms);
    const minutes = Math.floor(total / 60000);
    const seconds = Math.floor((total % 60000) / 1000);
    const millis = total % 1000;
    return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
  }

  function formatClock(iso) {
    if (!iso) return "--:--:--";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "--:--:--";
    return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`;
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function hexToRgba(hex, alpha) {
    const raw = hex.replace("#", "");
    const value = parseInt(raw.length === 3 ? raw.split("").map((c) => c + c).join("") : raw, 16);
    const r = (value >> 16) & 255;
    const g = (value >> 8) & 255;
    const b = value & 255;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  function intValue(id, fallback, min, max) {
    const parsed = Number.parseInt($(id).value, 10);
    if (!Number.isFinite(parsed)) return fallback;
    return clamp(parsed, min, max);
  }

  function setUrl() {
    const params = new URLSearchParams();
    if (state.present) params.set("present", "1");
    if (state.raceId) params.set("race", state.raceId);
    const query = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
  }

  function clearAnimation() {
    state.anim.clear();
    state.replay = null;
  }

  function animFor(kind, start) {
    let anim = state.anim.get(kind);
    if (!anim) {
      anim = {
        x: start[0],
        y: start[1],
        revealStart: null,
        revealRaceId: null,
      };
      state.anim.set(kind, anim);
    }
    return anim;
  }

  // -------------------------------------------------------------------------
  // bootstrap / preview / history
  // -------------------------------------------------------------------------

  async function loadBootstrap() {
    try {
      const data = await api("/api/bootstrap");
      state.bootstrap = data;
      renderKeyStatus("#key-nam", "Nam", data.keys.nam);
      renderKeyStatus("#key-openrouter", "OpenRouter", data.keys.openrouter);
      populateModels(data);
    } catch (error) {
      renderKeyStatus("#key-nam", "Nam", { ok: false, detail: "no disponible" });
      renderKeyStatus("#key-openrouter", "OpenRouter", { ok: false, detail: "no disponible" });
      toast(`No se pudo cargar el estado: ${error.message}`);
    }
  }

  function renderKeyStatus(selector, label, status) {
    const el = $(selector);
    if (!el) return;
    const ok = Boolean(status && status.ok);
    el.classList.toggle("ok", ok);
    el.classList.toggle("bad", !ok);
    $("span:last-child", el).textContent = `${label === "Nam" ? "" : ""}${status?.detail || "sin datos"}`;
  }

  function populateModels(data) {
    const textSelect = $("#text-model");
    const decisionSelect = $("#decisions-model");
    const textCurrent = textSelect.value;
    const decisionCurrent = decisionSelect.value;

    const textModels = (data.nam_models || []).map((model) => ({ id: model.id, name: model.id }));
    if (!textModels.some((model) => model.id === data.defaults.text_model)) {
      textModels.unshift({ id: data.defaults.text_model, name: data.defaults.text_model });
    }
    textSelect.innerHTML = "";
    for (const model of textModels) {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = model.name;
      textSelect.appendChild(option);
    }
    textSelect.value = textCurrent || data.defaults.text_model;

    const decisionModels = (data.decision_models || []).map((model) => ({
      id: model.id,
      name: model.name || model.id,
    }));
    if (!decisionModels.some((model) => model.id === data.defaults.decisions_model)) {
      decisionModels.unshift({
        id: data.defaults.decisions_model,
        name: data.defaults.decisions_model,
      });
    }
    const heuristic = { id: data.heuristic_model, name: "Control heurístico (sin API)" };
    if (!decisionModels.some((model) => model.id === heuristic.id)) decisionModels.push(heuristic);

    decisionSelect.innerHTML = "";
    for (const model of decisionModels) {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = model.name;
      decisionSelect.appendChild(option);
    }
    decisionSelect.value = decisionCurrent || data.defaults.decisions_model;

    $("#width").value = data.defaults.width;
    $("#height").value = data.defaults.height;
    $("#seed").value = data.defaults.seed;
    $("#attempts").value = data.defaults.text_max_attempts;
    $("#budget").value = data.defaults.max_junction_calls;
    $("#baseline").checked = Boolean(data.defaults.include_baseline);
  }

  function schedulePreview() {
    clearTimeout(state.previewTimer);
    state.previewTimer = setTimeout(loadMazePreview, 260);
  }

  async function loadMazePreview() {
    const width = intValue("#width", 31, 5, 31);
    const height = intValue("#height", 31, 5, 31);
    const seed = intValue("#seed", 42, 0, 2147483647);
    $("#width").value = width;
    $("#height").value = height;
    $("#seed").value = seed;
    try {
      const maze = await api(`/api/maze?width=${width}&height=${height}&seed=${seed}`);
      state.preview = maze;
      $("#preview-badge").textContent = `semilla ${maze.seed}`;
      renderPreviewStats(maze);
      if (!state.race) renderRaceMeta(null, maze);
      drawPreview();
    } catch (error) {
      $("#preview-stats").innerHTML = `<span class="eyebrow">Solver exacto</span><div class="gt-line"><span class="warn">${error.message}</span></div>`;
    }
  }

  function renderPreviewStats(maze) {
    $("#preview-stats").innerHTML = `
      <span class="eyebrow">Solver exacto</span>
      <div class="gt-line">
        <strong class="ok">resoluble</strong>
        <span>·</span>
        <strong>${maze.optimal_steps}</strong><span>pasos óptimos</span>
        <span>·</span>
        <strong>${maze.dead_ends}</strong><span>callejones</span>
        <span>·</span>
        <strong>${maze.junctions}</strong><span>cruces</span>
      </div>`;
  }

  async function loadHistory() {
    try {
      const data = await api("/api/races?limit=14");
      renderHistory(data.races || []);
    } catch (error) {
      $("#history").innerHTML = `<p class="muted">No se pudo cargar el archivo.</p>`;
    }
  }

  function renderHistory(races) {
    const container = $("#history");
    container.innerHTML = "";
    if (!races.length) {
      container.innerHTML = `<p class="muted">Sin carreras guardadas.</p>`;
      return;
    }
    for (const race of races) {
      const item = document.createElement("div");
      item.className = "history-item";
      item.tabIndex = 0;

      const main = document.createElement("div");
      const title = document.createElement("div");
      title.className = "h-title";
      title.textContent = `${race.config.width}×${race.config.height} · semilla ${race.config.seed}`;
      const sub = document.createElement("div");
      sub.className = "h-sub";
      const date = race.started_at || race.created_at;
      const winner = WINNER_LABELS[race.winner] || "sin ganador";
      sub.textContent = `${formatClock(date)} · ${winner}`;
      main.append(title, sub);

      const win = document.createElement("div");
      win.className = `h-win ${race.winner || ""}`;
      const textMs = race.summary?.text_ms;
      const decisionMs = race.summary?.decisions_ms;
      const short = (ms) => `${(ms / 1000).toFixed(1)}s`;
      win.textContent = textMs && decisionMs ? `T ${short(textMs)} · D ${short(decisionMs)}` : STATUS_LABELS[race.status] || race.status;

      item.append(main, win);
      item.addEventListener("click", () => loadArchivedRace(race.id));
      item.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") loadArchivedRace(race.id);
      });
      container.appendChild(item);
    }
  }

  // -------------------------------------------------------------------------
  // race lifecycle
  // -------------------------------------------------------------------------

  function collectRaceConfig() {
    const width = intValue("#width", 31, 5, 31);
    const height = intValue("#height", 31, 5, 31);
    const seed = intValue("#seed", 42, 0, 2147483647);
    const textModel = $("#text-model").value;
    const decisionsModel = $("#decisions-model").value;
    if (!textModel || !decisionsModel) throw new Error("Selecciona los dos modelos");
    return {
      width,
      height,
      seed,
      text_model: textModel,
      decisions_model: decisionsModel,
      text_max_attempts: intValue("#attempts", 2, 1, 5),
      max_junction_calls: intValue("#budget", 80, 0, 500),
      include_baseline: $("#baseline").checked,
    };
  }

  async function startRace() {
    if (state.race && state.race.status === "running") return;
    let payload;
    try {
      payload = collectRaceConfig();
    } catch (error) {
      toast(error.message);
      return;
    }
    setStartBusy(true);
    try {
      closeStream();
      clearAnimation();
      state.archived = false;
      state.lastLogSignature = "";
      const race = await api("/api/races", { method: "POST", body: JSON.stringify(payload) });
      state.raceId = race.id;
      applyRace(race, { resetLanes: true });
      connectStream(race.id);
      setUrl();
      toast("Carrera iniciada");
    } catch (error) {
      toast(`No se pudo iniciar: ${error.message}`);
    } finally {
      setStartBusy(false);
      updateControls();
    }
  }

  async function cancelRace() {
    if (!state.raceId) return;
    try {
      const result = await api(`/api/races/${state.raceId}/cancel`, { method: "POST" });
      applyRace(result.race || state.race);
      closeStream();
      toast("Carrera cancelada");
    } catch (error) {
      toast(`No se pudo cancelar: ${error.message}`);
    }
  }

  async function resetRace() {
    if (state.race && state.raceId && ["running", "created"].includes(state.race.status)) {
      try {
        await api(`/api/races/${state.raceId}/cancel`, { method: "POST" });
      } catch (error) {
        // The race may have finished between the click and the request.
      }
    }
    closeStream();
    state.race = null;
    state.raceId = null;
    state.archived = false;
    clearAnimation();
    state.laneNodes.clear();
    state.laneOrder = [];
    state.lastLogSignature = "";
    $("#lanes").innerHTML = `<div class="empty-state" id="empty-state">${EMPTY_STATE_HTML}</div>`;
    $("#compare").innerHTML = "";
    $("#event-log").innerHTML = `<p class="muted">Esperando una carrera…</p>`;
    $("#race-clock").textContent = "00:00.000";
    renderRaceMeta(null, state.preview);
    setUrl();
    updateControls();
    drawPreview();
  }

  async function loadArchivedRace(id) {
    closeStream();
    try {
      const race = await api(`/api/races/${id}`);
      clearAnimation();
      const live = race.status === "running" || race.status === "created";
      state.archived = !live;
      state.raceId = race.id;
      applyRace(race, { resetLanes: true, archived: !live });
      if (live) connectStream(id);
      else if (race.status !== "running" && race.status !== "created") snapAnimationsToEnd(race);
      setUrl();
      toast(live ? "Carrera en vivo cargada" : "Carrera cargada del archivo");
    } catch (error) {
      toast(`No se pudo cargar: ${error.message}`);
    }
  }

  function replayRace() {
    if (!state.race) return;
    const solved = Object.values(state.race.lanes).some((lane) => lane.status === "solved");
    if (!solved) return;
    state.replay = { startedAt: performance.now(), duration: 1900 };
    for (const [kind, lane] of Object.entries(state.race.lanes)) {
      const start = lane.path?.[0] || state.race.maze.start;
      const anim = animFor(kind, start);
      anim.x = start[0];
      anim.y = start[1];
      anim.revealStart = null;
    }
    toast("Repitiendo las rutas");
  }

  function connectStream(id) {
    closeStream();
    if (!window.EventSource) {
      startPolling(id);
      return;
    }
    const source = new EventSource(`/api/races/${id}/stream`);
    state.stream = source;
    source.onmessage = (event) => {
      try {
        applyRace(JSON.parse(event.data));
      } catch (error) {
        // A malformed frame should not kill the live view.
      }
    };
    source.onerror = () => {
      if (state.raceId !== id) return;
      closeStream();
      startPolling(id);
    };
  }

  function closeStream() {
    if (state.stream) {
      state.stream.close();
      state.stream = null;
    }
    stopPolling();
  }

  function startPolling(id) {
    stopPolling();
    state.pollTimer = setInterval(async () => {
      if (state.raceId !== id) {
        stopPolling();
        return;
      }
      try {
        const race = await api(`/api/races/${id}`);
        applyRace(race);
        if (["done", "error", "cancelled"].includes(race.status)) stopPolling();
      } catch (error) {
        stopPolling();
      }
    }, 420);
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  function applyRace(race, options = {}) {
    if (!race) return;
    state.race = race;
    state.raceId = race.id;
    if (options.archived) state.archived = true;
    renderRaceMeta(race);
    renderLanes(race, options);
    renderCompare(race);
    renderEventLog(race);
    updateControls(race);
    if (["done", "error", "cancelled"].includes(race.status)) {
      closeStream();
      loadHistory();
    }
  }

  function snapAnimationsToEnd(race) {
    for (const [kind, lane] of Object.entries(race.lanes)) {
      const anim = animFor(kind, race.maze.start);
      const end = lane.path?.[lane.path.length - 1] || lane.position || race.maze.start;
      anim.x = end[0];
      anim.y = end[1];
      if (kind === "text") {
        anim.revealStart = performance.now() - 100000;
        anim.revealRaceId = race.id;
      }
    }
  }

  function setStartBusy(busy) {
    const label = busy ? "Iniciando…" : "Iniciar carrera";
    $("#start").textContent = label;
    $("#present-start").textContent = label;
    $("#start").disabled = busy;
    $("#present-start").disabled = busy;
  }

  function updateControls(race = state.race) {
    const running = Boolean(race && (race.status === "running" || race.status === "created"));
    const hasRace = Boolean(race);
    const solved = Boolean(race && Object.values(race.lanes).some((lane) => lane.status === "solved"));

    $("#start").disabled = running;
    $("#present-start").disabled = running;
    $("#cancel").disabled = !running;
    $("#reset").disabled = !hasRace;
    $("#present-reset").disabled = !hasRace;
    $("#replay").disabled = !solved;
    $("#present-replay").disabled = !solved;
    $("#width").disabled = running;
    $("#height").disabled = running;
    $("#seed").disabled = running;
    $("#text-model").disabled = running;
    $("#decisions-model").disabled = running;
    $("#attempts").disabled = running;
    $("#budget").disabled = running;
    $("#baseline").disabled = running;

    const hint = $("#hint");
    if (state.archived) {
      hint.textContent = "Estás viendo una carrera guardada. Reinicia para preparar la siguiente.";
    } else if (running) {
      hint.textContent = "Carrera en curso. El reloj se detiene por carril cuando su ruta queda verificada.";
    } else if (hasRace && race.status === "done") {
      hint.textContent = "Carrera terminada. Repite las rutas o prepara un laberinto nuevo.";
    } else {
      hint.textContent =
        "El carril de texto pide la ruta completa a Nam. El de decisiones navega cruce a cruce con OpenRouter; el harness retrocede en los callejones sin salida.";
    }
  }

  function renderRaceMeta(race, preview = state.preview) {
    const el = $("#race-meta");
    if (race) {
      const archived = state.archived ? " · archivo" : "";
      el.textContent = `${race.config.width} × ${race.config.height} · semilla ${race.config.seed} · ruta óptima ${race.ground_truth.optimal_steps} pasos${archived}`;
    } else if (preview) {
      el.textContent = `${preview.width} × ${preview.height} · semilla ${preview.seed} · ruta óptima ${preview.optimal_steps} pasos`;
    } else {
      el.textContent = "Preparando circuito…";
    }
  }

  // -------------------------------------------------------------------------
  // lane DOM
  // -------------------------------------------------------------------------

  function createLaneNode(kind, lane) {
    const root = document.createElement("article");
    root.className = "lane";
    root.dataset.kind = kind;
    root.innerHTML = `
      <div class="lane-top">
        <div class="lane-identity">
          <span class="lane-glyph" data-ref="glyph"></span>
          <div style="min-width:0">
            <strong class="lane-model" data-ref="model"></strong>
            <span class="lane-provider" data-ref="provider"></span>
          </div>
        </div>
        <div class="lane-status">
          <span class="status-pill" data-ref="status"></span>
          <span class="lane-clock" data-ref="clock">00:00.000</span>
        </div>
      </div>
      <div class="lane-canvas-wrap">
        <canvas class="maze-canvas" data-ref="canvas"></canvas>
        <div class="lane-overlay" data-ref="overlay">
          <strong data-ref="overlay-title"></strong>
          <span data-ref="overlay-sub"></span>
        </div>
      </div>
      <div class="lane-metrics">
        <div class="metric"><span>Pasos</span><strong data-ref="steps">0</strong></div>
        <div class="metric"><span>Celdas</span><strong data-ref="cells">1</strong></div>
        <div class="metric"><span>Llamadas</span><strong data-ref="calls">0</strong></div>
        <div class="metric"><span>Tokens</span><strong data-ref="tokens">0</strong></div>
      </div>
      <div class="lane-feed"><span class="feed-dot"></span><span class="feed-text" data-ref="feed">esperando salida</span></div>`;

    const node = {
      root,
      glyph: $('[data-ref="glyph"]', root),
      model: $('[data-ref="model"]', root),
      provider: $('[data-ref="provider"]', root),
      status: $('[data-ref="status"]', root),
      clock: $('[data-ref="clock"]', root),
      canvas: $('[data-ref="canvas"]', root),
      overlay: $('[data-ref="overlay"]', root),
      overlayTitle: $('[data-ref="overlay-title"]', root),
      overlaySub: $('[data-ref="overlay-sub"]', root),
      steps: $('[data-ref="steps"]', root),
      cells: $('[data-ref="cells"]', root),
      calls: $('[data-ref="calls"]', root),
      tokens: $('[data-ref="tokens"]', root),
      feed: $('[data-ref="feed"]', root),
    };
    node.glyph.textContent = LANE_GLYPHS[kind] || "?";
    node.root.style.setProperty("--accent", LANE_COLORS[kind] || "#8891a3");
    node.root.style.setProperty("--accent-soft", hexToRgba(LANE_COLORS[kind] || "#8891a3", 0.12));
    return node;
  }

  function renderLanes(race, options = {}) {
    const lanesEl = $("#lanes");
    const empty = $("#empty-state");
    if (empty) empty.remove();
    const keys = Object.keys(race.lanes);
    const changed =
      options.resetLanes ||
      !state.laneNodes.size ||
      state.laneOrder.join(",") !== keys.join(",") ||
      keys.some((kind) => !state.laneNodes.has(kind));

    if (changed) {
      lanesEl.innerHTML = "";
      state.laneNodes.clear();
      state.laneOrder = keys;
      for (const kind of keys) {
        const node = createLaneNode(kind, race.lanes[kind]);
        lanesEl.appendChild(node.root);
        state.laneNodes.set(kind, node);
      }
    }

    for (const kind of keys) {
      updateLaneNode(kind, race.lanes[kind], race);
    }
  }

  function updateLaneNode(kind, lane, race) {
    const node = state.laneNodes.get(kind);
    if (!node) return;
    node.root.classList.toggle("solved", lane.status === "solved");
    node.root.classList.toggle("errored", lane.status === "error" || lane.status === "unsolved");
    node.model.textContent = lane.model;
    node.provider.textContent = `${LANE_LABELS[kind] || kind} · ${lane.provider}`;
    node.status.className = `status-pill status-${lane.status}`;
    node.status.textContent = STATUS_LABELS[lane.status] || lane.status;

    const stats = lane.stats || {};
    node.steps.textContent = String(stats.steps ?? lane.solution?.steps ?? 0);
    node.cells.textContent = String(stats.unique_cells ?? lane.visited?.length ?? 1);
    node.calls.textContent = String(lane.calls ?? 0);
    node.tokens.textContent = String(lane.tokens?.total ?? 0);

    const efficiency = lane.solution?.efficiency;
    const last = lane.trace && lane.trace.length ? lane.trace[lane.trace.length - 1] : null;
    if (lane.error) {
      node.feed.textContent = `error · ${lane.error}`;
    } else if (lane.status === "solved") {
      const pct = Number.isFinite(efficiency) ? `${Math.round(efficiency * 100)}%` : "—";
      node.feed.textContent = `ruta verificada · ${lane.solution?.steps ?? stats.steps ?? 0} pasos · eficiencia ${pct}`;
    } else if (lane.status === "unsolved") {
      node.feed.textContent = lane.verification?.error || "sin ruta verificada";
    } else if (lane.status === "cancelled") {
      node.feed.textContent = "carrera cancelada";
    } else if (last) {
      node.feed.textContent = last.message;
    } else {
      node.feed.textContent = "esperando salida";
    }

    const showOverlay = lane.status === "waiting" || (kind === "text" && lane.status === "running");
    node.overlay.classList.toggle("show", showOverlay);
    if (showOverlay) {
      if (lane.status === "waiting") {
        node.overlayTitle.textContent = "En espera";
        node.overlaySub.textContent = "la carrera arranca en breve";
      } else {
        node.overlayTitle.textContent = "Nam resolviendo";
        node.overlaySub.textContent = "recibiendo la ruta completa";
      }
    }

    if (kind === "text" && lane.status === "solved") {
      const start = lane.path?.[0] || race.maze.start;
      const anim = animFor(kind, start);
      if (anim.revealStart === null || anim.revealRaceId !== race.id) {
        anim.revealStart = performance.now();
        anim.revealRaceId = race.id;
      }
    }
  }

  // -------------------------------------------------------------------------
  // compare / log
  // -------------------------------------------------------------------------

  function renderCompare(race) {
    const container = $("#compare");
    if (!race) {
      container.innerHTML = "";
      return;
    }
    const lanes = ["text", "decisions", "baseline"]
      .map((kind) => ({ kind, lane: race.lanes[kind] }))
      .filter((item) => item.lane);
    const eligible = lanes.filter((item) => ["text", "decisions"].includes(item.kind));
    const solved = eligible.filter((item) => item.lane.status === "solved" && item.lane.elapsed_ms != null);
    const winner = race.winner;

    let title = "Carrera en curso";
    let mark = "…";
    let cls = "";
    let sub = "ambos carriles compitiendo";
    if (winner === "text") {
      title = "Gana el carril de texto";
      mark = "T";
      cls = "win-text";
      sub = `${escapeHtml(race.lanes.text.model)} · ${formatMs(race.lanes.text.elapsed_ms)}`;
    } else if (winner === "decisions") {
      title = "Gana el carril de decisiones";
      mark = "D";
      cls = "win-decisions";
      sub = `${escapeHtml(race.lanes.decisions.model)} · ${formatMs(race.lanes.decisions.elapsed_ms)}`;
    } else if (winner === "tie") {
      title = "Empate técnico";
      mark = "=";
      cls = "win-tie";
      sub = "ambos carriles resueltos";
    } else if (race.status === "done") {
      title = "Sin ganador";
      mark = "×";
      sub = "ningún carril verificó una ruta";
    } else if (solved.length === 1) {
      title = `${LANE_LABELS[solved[0].kind] || solved[0].kind} ya tiene ruta`;
      mark = LANE_GLYPHS[solved[0].kind] || "·";
      cls = solved[0].kind === "decisions" ? "win-decisions" : "win-text";
      sub = `${formatMs(solved[0].lane.elapsed_ms)} · esperando al otro carril`;
    }

    let deltaText = "";
    if (solved.length === 2) {
      const diff = Math.abs(solved[0].lane.elapsed_ms - solved[1].lane.elapsed_ms);
      const speedup =
        solved[0].lane.elapsed_ms > 0 && solved[1].lane.elapsed_ms > 0
          ? Math.max(solved[0].lane.elapsed_ms, solved[1].lane.elapsed_ms) / Math.min(solved[0].lane.elapsed_ms, solved[1].lane.elapsed_ms)
          : null;
      deltaText = ` · Δ ${formatMs(diff)}${speedup ? ` · ×${speedup.toFixed(2)}` : ""}`;
    }

    const rows = lanes
      .map(({ kind, lane }) => {
        const ms = lane.elapsed_ms != null ? lane.elapsed_ms : liveElapsed(lane);
        const steps = lane.solution?.steps ?? lane.stats?.steps ?? 0;
        const efficiency = lane.solution?.efficiency;
        const finiteMs = Number.isFinite(ms) ? ms : 0;
        const maxMs = Math.max(...lanes.map((item) => item.lane.elapsed_ms || liveElapsed(item.lane) || 1), 1);
        const width = lane.status === "solved" ? clamp((finiteMs / maxMs) * 100, 5, 100) : lane.status === "running" ? clamp((finiteMs / maxMs) * 100, 8, 100) : 3;
        const statusText =
          lane.status === "solved"
            ? `${formatMs(finiteMs)} · ${steps} pasos${Number.isFinite(efficiency) ? ` · ${Math.round(efficiency * 100)}%` : ""}`
            : lane.status === "running"
              ? `${formatMs(finiteMs)} · en curso`
              : STATUS_LABELS[lane.status] || lane.status;
        return `
          <div class="compare-row" style="--accent:${LANE_COLORS[kind] || "#8891a3"}">
            <span class="compare-name">${LANE_LABELS[kind] || kind}</span>
            <div class="compare-bar-shell"><div class="compare-bar" style="width:${width}%"></div></div>
            <span class="compare-value">${statusText}</span>
          </div>`;
      })
      .join("");

    container.innerHTML = `
      <div class="winner-line">
        <div class="winner-title ${cls}"><span class="winner-mark">${mark}</span><span>${title}</span></div>
        <div class="winner-sub">${sub}${deltaText}</div>
      </div>
      <div class="compare-rows">${rows}</div>`;
  }

  function liveElapsed(lane) {
    if (lane.elapsed_ms != null) return lane.elapsed_ms;
    if (lane.started_at) return Date.now() - Date.parse(lane.started_at);
    return null;
  }

  function renderEventLog(race) {
    const container = $("#event-log");
    if (!race) {
      container.innerHTML = `<p class="muted">Esperando una carrera…</p>`;
      return;
    }
    const entries = [];
    for (const event of race.events || []) {
      entries.push({ at: event.at, kind: "race", message: event.message });
    }
    for (const [kind, lane] of Object.entries(race.lanes)) {
      for (const entry of (lane.trace || []).slice(-18)) {
        entries.push({ at: entry.at, kind, message: entry.message });
      }
    }
    entries.sort((a, b) => String(a.at).localeCompare(String(b.at)));
    const visible = entries.slice(-60);
    const signature = visible.map((entry) => `${entry.at}|${entry.kind}|${entry.message}`).join("||");
    if (signature === state.lastLogSignature) return;
    state.lastLogSignature = signature;

    container.innerHTML = "";
    if (!visible.length) {
      container.innerHTML = `<p class="muted">Esperando eventos…</p>`;
      return;
    }
    for (const entry of visible) {
      const row = document.createElement("div");
      row.className = "log-row";
      const time = document.createElement("span");
      time.className = "log-time";
      time.textContent = formatClock(entry.at);
      const tag = document.createElement("span");
      tag.className = `log-tag ${entry.kind}`;
      tag.textContent = entry.kind === "race" ? "race" : LANE_LABELS[entry.kind] || entry.kind;
      const message = document.createElement("span");
      message.className = "log-message";
      message.textContent = entry.message;
      row.append(time, tag, message);
      container.appendChild(row);
    }
    container.scrollTop = container.scrollHeight;
  }

  // -------------------------------------------------------------------------
  // canvas rendering
  // -------------------------------------------------------------------------

  function fitCanvas(canvas) {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const width = Math.round(rect.width * dpr);
    const height = Math.round(rect.height * dpr);
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, width: rect.width, height: rect.height };
  }

  function geometry(width, height, cols, rows, padding = 10) {
    const cell = Math.min((width - padding * 2) / cols, (height - padding * 2) / rows);
    const ox = (width - cell * cols) / 2;
    const oy = (height - cell * rows) / 2;
    return {
      cell,
      ox,
      oy,
      cx: (x) => ox + (x + 0.5) * cell,
      cy: (y) => oy + (y + 0.5) * cell,
    };
  }

  function pointFor(pos, geo) {
    return [geo.cx(pos[0]), geo.cy(pos[1])];
  }

  function drawWalls(ctx, maze, geo, color) {
    const { cell, ox, oy } = geo;
    ctx.beginPath();
    for (let y = 0; y < maze.height; y += 1) {
      for (let x = 0; x < maze.width; x += 1) {
        const walls = maze.walls[y * maze.width + x];
        const left = ox + x * cell;
        const top = oy + y * cell;
        if (walls & 1) {
          ctx.moveTo(left, top);
          ctx.lineTo(left + cell, top);
        }
        if (walls & 8) {
          ctx.moveTo(left, top);
          ctx.lineTo(left, top + cell);
        }
        if (x === maze.width - 1 && walls & 2) {
          ctx.moveTo(left + cell, top);
          ctx.lineTo(left + cell, top + cell);
        }
        if (y === maze.height - 1 && walls & 4) {
          ctx.moveTo(left, top + cell);
          ctx.lineTo(left + cell, top + cell);
        }
      }
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(1, cell * 0.08);
    ctx.lineCap = "square";
    ctx.stroke();
  }

  function drawVisited(ctx, lane, maze, geo, accent) {
    if (!lane.visited || !lane.visited.length) return;
    ctx.fillStyle = hexToRgba(accent, 0.085);
    const inset = Math.max(0.5, geo.cell * 0.045);
    for (const cell of lane.visited) {
      if (!Array.isArray(cell)) continue;
      const left = geo.ox + cell[0] * geo.cell + inset;
      const top = geo.oy + cell[1] * geo.cell + inset;
      ctx.fillRect(left, top, geo.cell - inset * 2, geo.cell - inset * 2);
    }
  }

  function strokePath(ctx, cells, maze, geo, color, width, dash = null) {
    if (!cells || cells.length < 2) return;
    ctx.beginPath();
    cells.forEach((cell, index) => {
      const x = geo.cx(cell[0]);
      const y = geo.cy(cell[1]);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    if (dash) ctx.setLineDash(dash);
    ctx.stroke();
    if (dash) ctx.setLineDash([]);
  }

  function drawGoal(ctx, maze, geo, accent, now, solved) {
    const [gx, gy] = pointFor(maze.goal, geo);
    const pulse = 0.5 + 0.5 * Math.sin(now / 430);
    const radius = geo.cell * (0.24 + 0.035 * pulse);
    ctx.save();
    ctx.translate(gx, gy);
    ctx.rotate(Math.PI / 4);
    ctx.shadowColor = solved ? "#39d69d" : hexToRgba(accent, 0.7);
    ctx.shadowBlur = solved ? 16 : 10;
    ctx.fillStyle = solved ? "rgba(57,214,157,0.28)" : "rgba(245,165,36,0.15)";
    ctx.strokeStyle = solved ? "#39d69d" : hexToRgba(accent, 0.85);
    ctx.lineWidth = Math.max(1, geo.cell * 0.075);
    ctx.beginPath();
    ctx.rect(-radius, -radius, radius * 2, radius * 2);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  function drawStart(ctx, maze, geo, accent) {
    const [sx, sy] = pointFor(maze.start, geo);
    ctx.strokeStyle = hexToRgba(accent, 0.75);
    ctx.lineWidth = Math.max(1, geo.cell * 0.07);
    ctx.beginPath();
    ctx.arc(sx, sy, geo.cell * 0.18, 0, Math.PI * 2);
    ctx.stroke();
  }

  function drawAgent(ctx, geo, accent, x, y, now, moving) {
    const radius = geo.cell * 0.26;
    const pulse = 0.5 + 0.5 * Math.sin(now / 280);
    ctx.save();
    ctx.shadowColor = accent;
    ctx.shadowBlur = 16 + pulse * 8;
    ctx.fillStyle = accent;
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = "rgba(255,255,255,0.92)";
    ctx.beginPath();
    ctx.arc(x, y, radius * 0.36, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = hexToRgba(accent, moving ? 0.55 : 0.3);
    ctx.lineWidth = Math.max(1, geo.cell * 0.055);
    ctx.beginPath();
    ctx.arc(x, y, radius * (1.45 + pulse * 0.25), 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  function pathSlice(lane, maze, now) {
    const full = lane.path && lane.path.length ? lane.path : [maze.start];
    if (state.replay && lane.status === "solved") {
      const progress = clamp((now - state.replay.startedAt) / state.replay.duration, 0, 1);
      const count = Math.max(2, Math.floor(progress * (full.length - 1)) + 1);
      return { points: full.slice(0, count), progress };
    }
    if (lane.kind === "text" && lane.status === "solved") {
      const anim = state.anim.get("text");
      if (anim && anim.revealStart !== null) {
        const duration = clamp(full.length * 26, 900, 2600);
        const progress = clamp((now - anim.revealStart) / duration, 0, 1);
        const count = Math.max(2, Math.floor(progress * (full.length - 1)) + 1);
        return { points: full.slice(0, count), progress };
      }
    }
    return { points: full, progress: 1 };
  }

  function drawLaneCanvas(kind, lane, race, now) {
    const node = state.laneNodes.get(kind);
    if (!node) return;
    const fit = fitCanvas(node.canvas);
    if (!fit) return;
    const { ctx, width, height } = fit;
    const maze = race.maze;
    const accent = LANE_COLORS[kind] || "#8891a3";
    ctx.clearRect(0, 0, width, height);

    const padding = Math.max(8, Math.min(width, height) * 0.035);
    const geo = geometry(width, height, maze.width, maze.height, padding);

    const optimal = race.ground_truth?.solution || maze.solution;
    if ($("#show-optimal").checked && optimal) {
      strokePath(ctx, optimal, maze, geo, "rgba(57,214,157,0.18)", geo.cell * 0.12, [geo.cell * 0.16, geo.cell * 0.24]);
    }

    drawVisited(ctx, lane, maze, geo, accent);

    if (lane.trail && lane.trail.length > 1) {
      strokePath(ctx, lane.trail, maze, geo, hexToRgba(accent, 0.2), geo.cell * 0.1);
    }

    const slice = pathSlice(lane, maze, now);
    strokePath(ctx, slice.points, maze, geo, hexToRgba(accent, 0.85), geo.cell * 0.16);
    ctx.save();
    ctx.shadowColor = accent;
    ctx.shadowBlur = 12;
    strokePath(ctx, slice.points, maze, geo, hexToRgba(accent, 0.45), geo.cell * 0.075);
    ctx.restore();

    drawWalls(ctx, maze, geo, "rgba(139,151,170,0.5)");
    drawStart(ctx, maze, geo, accent);
    drawGoal(ctx, maze, geo, accent, now, lane.status === "solved");

    const lastPoint = slice.points[slice.points.length - 1] || maze.start;
    const target = pointFor(lastPoint, geo);
    const anim = animFor(kind, maze.start);
    if (state.replay || lane.status === "solved") {
      anim.x = target[0];
      anim.y = target[1];
    } else {
      anim.x += (target[0] - anim.x) * 0.3;
      anim.y += (target[1] - anim.y) * 0.3;
    }
    const moving = Math.abs(target[0] - anim.x) + Math.abs(target[1] - anim.y) > 0.5;
    drawAgent(ctx, geo, accent, anim.x, anim.y, now, moving || lane.status === "running");

    if (lane.status === "solved") {
      const label = lane.solution?.efficiency != null ? `${Math.round(lane.solution.efficiency * 100)}% óptima` : "resuelto";
      ctx.save();
      ctx.font = `600 ${Math.max(9, geo.cell * 0.32)}px "SFMono-Regular", Menlo, monospace`;
      ctx.fillStyle = "rgba(57,214,157,0.9)";
      ctx.textAlign = "right";
      ctx.fillText(label, width - padding, padding + geo.cell * 0.22);
      ctx.restore();
    }
  }

  function drawPreview() {
    const canvas = $("#preview-canvas");
    if (!canvas || !state.preview) return;
    const fit = fitCanvas(canvas);
    if (!fit) return;
    const { ctx, width, height } = fit;
    const maze = state.preview;
    ctx.clearRect(0, 0, width, height);
    const padding = Math.max(8, Math.min(width, height) * 0.055);
    const geo = geometry(width, height, maze.width, maze.height, padding);
    strokePath(ctx, maze.solution, maze, geo, "rgba(245,165,36,0.32)", geo.cell * 0.13, [geo.cell * 0.16, geo.cell * 0.24]);
    drawWalls(ctx, maze, geo, "rgba(139,151,170,0.52)");
    drawStart(ctx, maze, geo, "#f5a524");
    drawGoal(ctx, maze, geo, "#f5a524", performance.now(), false);
  }

  // -------------------------------------------------------------------------
  // frame loop
  // -------------------------------------------------------------------------

  function frame(now) {
    if (state.race) {
      updateClocks();
      for (const [kind, lane] of Object.entries(state.race.lanes)) {
        drawLaneCanvas(kind, lane, state.race, now);
      }
      if (state.replay && now - state.replay.startedAt > state.replay.duration + 80) {
        state.replay = null;
      }
    }
    window.requestAnimationFrame(frame);
  }

  function updateClocks() {
    const clock = $("#race-clock");
    const race = state.race;
    if (race && race.started_at) {
      const end = race.finished_at ? Date.parse(race.finished_at) : Date.now();
      clock.textContent = formatMs(end - Date.parse(race.started_at));
    } else {
      clock.textContent = "00:00.000";
    }
    for (const [kind, node] of state.laneNodes) {
      const lane = race.lanes[kind];
      if (!lane) continue;
      const ms = liveElapsed(lane);
      node.clock.textContent = ms == null ? "00:00.000" : formatMs(ms);
    }
  }

  // -------------------------------------------------------------------------
  // presentation mode + wiring
  // -------------------------------------------------------------------------

  function enterPresent(updateUrl = true) {
    state.present = true;
    document.body.classList.add("present");
    if (updateUrl) setUrl();
  }

  function exitPresent() {
    state.present = false;
    document.body.classList.remove("present");
    setUrl();
  }

  function toggleFullscreen() {
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    } else {
      document.documentElement.requestFullscreen().catch(() => toast("Pantalla completa no disponible"));
    }
  }

  function wireUI() {
    $("#start").addEventListener("click", startRace);
    $("#present-start").addEventListener("click", startRace);
    $("#cancel").addEventListener("click", cancelRace);
    $("#reset").addEventListener("click", resetRace);
    $("#present-reset").addEventListener("click", resetRace);
    $("#replay").addEventListener("click", replayRace);
    $("#present-replay").addEventListener("click", replayRace);
    $("#present").addEventListener("click", () => enterPresent(true));
    $("#present-exit").addEventListener("click", exitPresent);
    $("#present-fullscreen").addEventListener("click", toggleFullscreen);
    $("#refresh-history").addEventListener("click", loadHistory);
    $("#new-maze").addEventListener("click", () => {
      $("#seed").value = Math.floor(Math.random() * 2147483647);
      loadMazePreview();
    });
    for (const id of ["#width", "#height", "#seed"]) {
      $(id).addEventListener("change", schedulePreview);
      $(id).addEventListener("input", schedulePreview);
    }
    document.addEventListener("keydown", (event) => {
      const target = event.target;
      const typing = target && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName);
      if (event.key === "Escape" && document.fullscreenElement) {
        document.exitFullscreen().catch(() => {});
        return;
      }
      if (typing) return;
      if (event.key === "f" || event.key === "F") {
        event.preventDefault();
        if (state.present) exitPresent();
        else enterPresent(true);
      }
      if (event.key === "Escape" && state.present) exitPresent();
    });
    window.addEventListener("resize", () => {
      drawPreview();
    });
    document.addEventListener("fullscreenchange", () => {
      window.requestAnimationFrame(() => {
        drawPreview();
        if (state.race) {
          for (const [kind, lane] of Object.entries(state.race.lanes)) {
            drawLaneCanvas(kind, lane, state.race, performance.now());
          }
        }
      });
    });
  }

  async function init() {
    wireUI();
    const params = new URLSearchParams(window.location.search);
    if (params.get("present") === "1") enterPresent(false);
    await Promise.allSettled([loadBootstrap(), loadMazePreview(), loadHistory()]);
    const raceId = params.get("race");
    if (raceId) {
      await loadArchivedRace(raceId);
    }
    updateControls();
    window.requestAnimationFrame(frame);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
