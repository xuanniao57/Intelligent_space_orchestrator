const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const DEFAULT_ROBOT_BASE_URL = "http://127.0.0.1:8731";
const DEFAULT_SPRAY_GATEWAY_URL = "http://192.168.1.50:22001";
const DEFAULT_SMART_PLUG_IP = "192.168.1.156";
const DEFAULT_PLUG_TCP_ENDPOINT = "192.168.1.50:8080";

const state = {
  page: "monitor",
  activeFrame: "heat",
  turns: [],
  conversation: [],
  worldStates: {},
  ioRegistry: null,
  inputSelection: [],
  outputSelection: [],
  inputLayerFilter: "all",
  outputCategoryFilter: "all",
  selectedStepId: null,
  busy: false,
};

function cstNow() {
  const now = new Date();
  const cst = new Date(now.getTime() + (8 * 60 + now.getTimezoneOffset()) * 60000);
  return cst.toISOString().replace("Z", "+08:00");
}

function frameId(prefix) {
  return `${prefix}_${Date.now()}`;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function baseFrame(kind) {
  return {
    message_type: "scene_semantic_frame",
    frame_id: frameId(`ssf_${kind}`),
    timestamp: cstNow(),
    source_id: "field_semantic_fusion",
    time_window: { aggregation: "rolling", duration_sec: 8 },
    confidence: 0.84,
    priority: 0.62,
  };
}

function buildHeatFrame() {
  return {
    ...baseFrame("heat"),
    source_id: "terminal.thermal_crowd_fusion",
    space_id: "cooling_zone_01",
    scene: {
      situation_id: "heat_cooling_loop",
      summary: "热感上升：温度偏高，人群出现轻微热不适。",
      intent_hint: "cooling_request",
      tags: ["hot", "human_hot", "mood_unhappy", "cooling_request"],
    },
    semantics: {
      environment: { label: "hot", level: "warning", values: { temperature_c: 33.4, humidity: 0.51 }, tags: ["hot"] },
      crowd: { label: "crowded", level: "watch", values: { density: 0.74, person_count: 18 }, tags: ["crowded"] },
      emotion: { label: "uncomfortable", level: "watch", values: { negative_ratio: 0.31 }, tags: ["mood_unhappy"] },
    },
    entities: [{ id: "visitor_group_01", type: "person_group", zone: "cooling_zone_01", attributes: { heat_gesture: true } }],
    events: [{ type: "thermal_discomfort_detected", confidence: 0.88 }],
    affordances: [
      { action: "spray_mist", target_zone: "cooling_zone_01" },
      { action: "deliver_ice_water", target_zone: "cooling_handoff_01" },
    ],
    safety: { level: "normal", robot_speed_limit_mps: 0.25, dry_run: true },
    raw_refs: [
      { terminal_id: "thermal_grid_01", modality: "temperature" },
      { terminal_id: "g1_rgb_camera", modality: "rgb" },
      { terminal_id: "g1_depth_camera", modality: "depth" },
      { terminal_id: "g1_microphone", modality: "audio" },
    ],
    semantic_tags: ["hot", "human_hot", "mood_unhappy", "cooling_request"],
    priority: 0.72,
  };
}

function buildHeatFeedbackFrame() {
  return {
    ...baseFrame("heat_feedback"),
    source_id: "terminal.feedback_fusion",
    space_id: "cooling_zone_01",
    scene: {
      situation_id: "cooling_feedback",
      summary: "清凉联动后热感下降，访客状态回到中性。",
      intent_hint: "observe_and_confirm",
      tags: ["cooling_effect_confirmed", "mood_neutral"],
    },
    semantics: {
      environment: { label: "comfortable", level: "normal", values: { temperature_c: 28.1 }, tags: ["comfortable"] },
      emotion: { label: "neutral", level: "normal", values: { negative_ratio: 0.08 }, tags: ["mood_neutral"] },
    },
    events: [{ type: "cooling_effect_observed", confidence: 0.81 }],
    affordances: [{ action: "observe" }],
    safety: { level: "normal" },
    raw_refs: [{ terminal_id: "g1_ack_perception", modality: "ack" }],
    semantic_tags: ["cooling_effect_confirmed", "mood_neutral"],
    priority: 0.38,
  };
}

function buildMusicFrame() {
  return {
    ...baseFrame("music"),
    source_id: "terminal.soundscape_fusion",
    space_id: "sound_cocktail_zone_01",
    scene: {
      situation_id: "music_cocktail_loop",
      summary: "多维声音活跃且略嘈杂，需要转译为更舒展的音乐层。",
      intent_hint: "music_cocktail",
      tags: ["sound_cocktail", "loud", "lively", "music"],
    },
    semantics: {
      soundscape: { label: "lively_noisy", level: "watch", values: { noise_db: 72.6, tempo_hint_bpm: 92 }, tags: ["loud", "lively"] },
      crowd: { label: "active", level: "normal", values: { person_count: 12 }, tags: ["moderate"] },
      emotion: { label: "mixed", level: "normal", values: { positive_ratio: 0.47 }, tags: ["mood_mixed"] },
    },
    events: [{ type: "sound_cocktail_detected", confidence: 0.86 }],
    affordances: [
      { action: "play_music_mix" },
      { action: "project_sound_wave" },
    ],
    safety: { level: "normal", robot_action_required: false },
    raw_refs: [
      { terminal_id: "ambient_mic_array", modality: "audio" },
      { terminal_id: "g1_microphone", modality: "audio" },
    ],
    semantic_tags: ["sound_cocktail", "loud", "lively", "music"],
    priority: 0.66,
  };
}

function buildMusicFeedbackFrame() {
  return {
    ...baseFrame("music_feedback"),
    source_id: "terminal.sound_feedback_fusion",
    space_id: "sound_cocktail_zone_01",
    scene: {
      situation_id: "music_feedback",
      summary: "声画介入后声场更稳定，空间氛围保持活跃。",
      intent_hint: "observe_and_confirm",
      tags: ["soundscape_balanced", "mood_bright"],
    },
    semantics: {
      soundscape: { label: "balanced", level: "normal", values: { noise_db: 63.2 }, tags: ["quiet_enough"] },
      emotion: { label: "bright", level: "normal", values: { positive_ratio: 0.62 }, tags: ["mood_bright"] },
    },
    events: [{ type: "soundscape_balance_observed", confidence: 0.79 }],
    affordances: [{ action: "observe" }],
    safety: { level: "normal" },
    raw_refs: [{ terminal_id: "speaker_projection_ack", modality: "ack" }],
    semantic_tags: ["soundscape_balanced", "mood_bright"],
    priority: 0.36,
  };
}

function buildFrame(name) {
  if (name === "heat-feedback") return buildHeatFeedbackFrame();
  if (name === "music") return buildMusicFrame();
  if (name === "music-feedback") return buildMusicFeedbackFrame();
  return buildHeatFrame();
}

function routeToPage(pathname = window.location.pathname) {
  if (pathname.endsWith("/input-lab")) return "input-lab";
  if (pathname.endsWith("/output-lab")) return "output-lab";
  return "monitor";
}

function setPage(page, push = false) {
  state.page = page;
  $$(".page").forEach((pageNode) => pageNode.classList.remove("active"));
  const node = page === "input-lab" ? $("#inputLabPage") : page === "output-lab" ? $("#outputLabPage") : $("#monitorPage");
  node?.classList.add("active");
  $$(".nav-link").forEach((link) => link.classList.toggle("active", link.dataset.page === page));
  if (push) {
    const nextPath = page === "input-lab" ? "/agent-console/input-lab" : page === "output-lab" ? "/agent-console/output-lab" : "/agent-console";
    window.history.pushState({ page }, "", nextPath);
  }
}

function setActiveFrame(name) {
  state.activeFrame = name;
  $$(".preset").forEach((button) => button.classList.toggle("active", button.dataset.frame === name));
  const frame = buildFrame(name);
  if ($("#semanticText")) $("#semanticText").value = frame.scene?.summary || "";
  if ($("#semanticJson")) $("#semanticJson").value = JSON.stringify(frame, null, 2);
}

async function fetchJson(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json; charset=utf-8" } : {}),
      ...(options.headers || {}),
    },
  });
  const raw = await response.text();
  let payload = {};
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = { raw };
    }
  }
  if (!response.ok) {
    throw new Error(payload.error || payload.message || payload.detail || `HTTP ${response.status}`);
  }
  return payload;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function scrubForDisplay(value) {
  if (Array.isArray(value)) return value.map(scrubForDisplay);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, child]) => {
      const cleanKey = key.replaceAll("hermes", "runtime").replaceAll("Hermes", "Runtime");
      return [cleanKey, scrubForDisplay(child)];
    }));
  }
  if (typeof value === "string") {
    return value
      .replaceAll("Hermes", "中枢运行时")
      .replaceAll("hermes", "runtime");
  }
  return value;
}

function pretty(value) {
  return escapeHtml(JSON.stringify(scrubForDisplay(value ?? {}), null, 2));
}

function clip(value, length = 120) {
  const text = String(value ?? "");
  return text.length > length ? `${text.slice(0, length - 1)}...` : text;
}

function last(list) {
  return list && list.length ? list[list.length - 1] : null;
}

function statusClass(status) {
  const normalized = String(status || "").toLowerCase();
  if (["ok", "received", "complete", "completed", "planned", "sent"].includes(normalized)) return "ok";
  if (["failed", "blocked", "error", "needs_review"].includes(normalized)) return "bad";
  if (["pending", "issued", "running", "timeout", "skipped_fast_layer"].includes(normalized)) return "warn";
  return "muted";
}

function commandType(command) {
  return command?.command?.type || "unknown";
}

function taskIdFor(command) {
  return command?.command?.params?.task_id;
}

function robotBaseUrl() {
  return ($("#robotUrl")?.value || DEFAULT_ROBOT_BASE_URL).trim().replace(/\/$/, "");
}

function sprayGatewayUrl() {
  return ($("#sprayUrl")?.value || DEFAULT_SPRAY_GATEWAY_URL).trim().replace(/\/$/, "");
}

function smartPlugIp() {
  return ($("#smartPlugIp")?.value || DEFAULT_SMART_PLUG_IP).trim();
}

function plugTcpEndpoint() {
  return ($("#plugTcpEndpoint")?.value || DEFAULT_PLUG_TCP_ENDPOINT).trim();
}

function outputRoutingOverrides() {
  return {
    spray_gateway: { direct_http: sprayGatewayUrl() },
  };
}

function renderSprayGatewayStatus(payload, failedMessage = "") {
  const node = $("#sprayGatewayStatus");
  if (!node) return;
  if (!payload) {
    node.className = "gateway-status muted";
    node.textContent = "等待检测：中控 → 喷雾网关 → 智能插座";
    return;
  }
  const plug = payload.smart_plug || {};
  const gatewayText = payload.gateway_reachable ? "HTTP 网关可达" : "HTTP 网关不可达";
  const plugText = plug.connected ? "智能插座已接入" : "智能插座未接入";
  const detail = failedMessage || payload.error || payload.upstream?.error || payload.upstream?.stage || "";
  const mode = payload.gateway_reachable && plug.connected ? "ok" : payload.gateway_reachable ? "warn" : "bad";
  node.className = `gateway-status ${mode}`;
  node.innerHTML = `
    <strong>${escapeHtml(gatewayText)} / ${escapeHtml(plugText)}</strong>
    <span>命令：${escapeHtml(payload.command_url || "-")}</span>
    <span>插座：${escapeHtml(plug.ip || smartPlugIp())} → ${escapeHtml(plug.tcp_endpoint || plugTcpEndpoint())}</span>
    ${detail ? `<span>状态：${escapeHtml(detail)}</span>` : ""}
  `;
}

async function refreshSprayGatewayStatus(quiet = false) {
  if (!$("#sprayGatewayStatus")) return null;
  if (!quiet) {
    renderSprayGatewayStatus({
      gateway_reachable: false,
      command_url: `${sprayGatewayUrl()}/api/command`,
      smart_plug: { ip: smartPlugIp(), tcp_endpoint: plugTcpEndpoint(), connected: false },
    }, "检测中");
  }
  try {
    const params = new URLSearchParams({
      url: sprayGatewayUrl(),
      smart_plug_ip: smartPlugIp(),
      plug_tcp_endpoint: plugTcpEndpoint(),
      timeout: "2",
    });
    const payload = await fetchJson(`/api/agent/gateway-health?${params.toString()}`);
    renderSprayGatewayStatus(payload);
    return payload;
  } catch (error) {
    const payload = {
      gateway_reachable: false,
      command_url: `${sprayGatewayUrl().replace(/\/$/, "")}/api/command`,
      smart_plug: { ip: smartPlugIp(), tcp_endpoint: plugTcpEndpoint(), connected: false },
      error: error.message,
    };
    renderSprayGatewayStatus(payload, error.message);
    return payload;
  }
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2600);
}

function setStatus(node, text, mode = "muted") {
  if (!node) return;
  node.textContent = text;
  node.className = `status-pill ${mode}`;
}

function setResult(target, badge, payload, status = "ok") {
  target.textContent = JSON.stringify(scrubForDisplay(payload), null, 2);
  badge.textContent = status;
  badge.className = `mini-badge ${statusClass(status)}`;
}

function markBusy(isBusy) {
  state.busy = isBusy;
  $$("button").forEach((button) => {
    if (button.id !== "refreshButton") button.disabled = isBusy;
  });
}

function installLabTemplates() {
  const inputPage = $("#inputLabPage");
  const outputPage = $("#outputLabPage");
  if (inputPage) {
    inputPage.className = "page lab-shell tri-lab";
    inputPage.innerHTML = `
      <section class="lab-panel registry-panel">
        <div class="panel-head">
          <div>
            <p>Input registry</p>
            <h2>候选语义</h2>
          </div>
          <span id="inputRegistryCount" class="mini-badge">0</span>
        </div>
        <div class="lab-body">
          <div class="filter-row">
            <select id="inputLayerFilter" class="select-input" aria-label="semantic layer"></select>
          </div>
          <div id="inputPresetList" class="preset-list"></div>
          <div id="inputRegistryList" class="registry-list"></div>
        </div>
      </section>
      <section class="lab-panel assembly-panel">
        <div class="panel-head">
          <div>
            <p>World state assembly</p>
            <h2>组装测试输入</h2>
          </div>
          <span id="inputAssemblyCount" class="mini-badge">0</span>
        </div>
        <div class="lab-body">
          <div id="inputAssemblyList" class="assembly-list"></div>
          <label class="field-label" for="inputCustomText">补充语义</label>
          <textarea id="inputCustomText" spellcheck="false" rows="3" placeholder="可选：补充现场语义或合作者给出的自然语言描述"></textarea>
          <div class="input-actions">
            <button id="previewAssemblyButton" type="button">只组装预览</button>
            <button id="sendAssemblyButton" type="button" class="primary">送入中枢 Agent</button>
          </div>
          <button id="clearInputAssemblyButton" type="button" class="ghost-wide">清空组装队列</button>
          <div id="inputAssemblyPreview" class="summary-card"></div>
        </div>
      </section>
      <section class="lab-panel result-panel">
        <div class="panel-head">
          <div>
            <p>Result</p>
            <h2>输入响应</h2>
          </div>
          <span id="inputResultBadge" class="mini-badge">idle</span>
        </div>
        <div class="lab-body result-body">
          <div id="inputResultChain" class="chain-list"></div>
          <details class="json-drawer compact-json">
            <summary>详细 JSON</summary>
            <pre id="inputResult" class="result-json">{}</pre>
          </details>
        </div>
      </section>
    `;
  }
  if (outputPage) {
    outputPage.className = "page lab-shell tri-lab output-lab";
    outputPage.innerHTML = `
      <section class="lab-panel registry-panel">
        <div class="panel-head">
          <div>
            <p>Output registry</p>
            <h2>工具动作</h2>
          </div>
          <span id="outputRegistryCount" class="mini-badge">0</span>
        </div>
        <div class="lab-body">
          <div class="filter-row">
            <select id="outputCategoryFilter" class="select-input" aria-label="tool category"></select>
          </div>
          <div id="outputPresetList" class="preset-list"></div>
          <div id="outputRegistryList" class="registry-list"></div>
        </div>
      </section>
      <section class="lab-panel assembly-panel">
        <div class="panel-head">
          <div>
            <p>DeviceCommand assembly</p>
            <h2>输出链测试</h2>
          </div>
          <span id="outputAssemblyCount" class="mini-badge">0</span>
        </div>
        <div class="lab-body">
          <div class="gateway-card">
            <label class="field-label" for="sprayUrl">喷雾 HTTP 网关地址</label>
            <input id="sprayUrl" class="text-input" value="${DEFAULT_SPRAY_GATEWAY_URL}" spellcheck="false">
            <div class="device-map">
              <label>
                <span>智能插座 IP</span>
                <input id="smartPlugIp" class="text-input compact-input" value="${DEFAULT_SMART_PLUG_IP}" spellcheck="false">
              </label>
              <label>
                <span>插座接入端</span>
                <input id="plugTcpEndpoint" class="text-input compact-input" value="${DEFAULT_PLUG_TCP_ENDPOINT}" spellcheck="false">
              </label>
            </div>
            <button id="checkSprayGatewayButton" type="button" class="ghost-wide">检测喷雾链路</button>
            <div id="sprayGatewayStatus" class="gateway-status muted">等待检测：中控 → 喷雾网关 → 智能插座</div>
          </div>
          <label class="field-label" for="robotUrl">G1 测试端地址</label>
          <input id="robotUrl" class="text-input" value="${DEFAULT_ROBOT_BASE_URL}" spellcheck="false">
          <div id="outputAssemblyList" class="assembly-list"></div>
          <div class="input-actions">
            <button id="sendOutputSequenceButton" type="button" class="primary">发送选中动作链</button>
            <button id="clearOutputAssemblyButton" type="button">清空动作链</button>
          </div>
          <label class="checkline output-check">
            <input id="autoAckOutput" type="checkbox">
            <span>用模拟 ACK 补齐未直连设备</span>
          </label>
          <label class="field-label" for="outputText">自然语言动作测试</label>
          <textarea id="outputText" spellcheck="false" rows="3">让 G1 完成安全检查，导航到冰水点，取一杯冰水，递给热感明显的访客，并播报“清凉补给已送达”。</textarea>
          <button id="sendOutputTextButton" type="button" class="ghost-wide">让 Agent 生成动作链</button>
        </div>
      </section>
      <section class="lab-panel result-panel">
        <div class="panel-head">
          <div>
            <p>Result</p>
            <h2>输出响应</h2>
          </div>
          <span id="outputResultBadge" class="mini-badge">idle</span>
        </div>
        <div class="lab-body result-body">
          <div id="outputResultChain" class="chain-list"></div>
          <details class="json-drawer compact-json">
            <summary>详细 JSON</summary>
            <pre id="outputResult" class="result-json">{}</pre>
          </details>
        </div>
      </section>
    `;
  }
}

function registryInputItems() {
  return state.ioRegistry?.input_semantics?.items || [];
}

function registryInputAssemblies() {
  return state.ioRegistry?.input_semantics?.assemblies || [];
}

function registryOutputActions() {
  return state.ioRegistry?.output_tools?.actions || [];
}

function registryOutputPresets() {
  return state.ioRegistry?.output_tools?.presets || [];
}

function inputItemById(id) {
  return registryInputItems().find((item) => item.id === id);
}

function outputActionById(id) {
  return registryOutputActions().find((item) => item.id === id);
}

async function loadIoRegistry() {
  try {
    state.ioRegistry = await fetchJson("/api/agent/io-registry");
    renderInputLab();
    renderOutputLab();
  } catch (error) {
    showToast(`注册表加载失败: ${error.message}`);
  }
}

function renderInputLab() {
  if (!$("#inputRegistryList")) return;
  const layers = state.ioRegistry?.input_semantics?.semantic_layers || [];
  const items = registryInputItems();
  const filter = $("#inputLayerFilter");
  if (filter) {
    const options = [`<option value="all">全部层级</option>`]
      .concat(layers.map((layer) => `<option value="${escapeHtml(layer.id)}">${escapeHtml(layer.label || layer.id)}</option>`));
    filter.innerHTML = options.join("");
    filter.value = state.inputLayerFilter;
  }
  const filtered = state.inputLayerFilter === "all" ? items : items.filter((item) => item.layer === state.inputLayerFilter);
  $("#inputRegistryCount").textContent = `${filtered.length}`;
  $("#inputRegistryList").innerHTML = filtered.map((item) => `
    <button class="candidate-card" type="button" data-input-id="${escapeHtml(item.id)}">
      <span class="candidate-meta">${escapeHtml(item.layer || "-")} / ${escapeHtml(item.source_id || "-")}</span>
      <strong>${escapeHtml(item.label || item.id)}</strong>
      <p>${escapeHtml(item.summary || "")}</p>
      <span class="candidate-tags">${(item.tags || []).slice(0, 4).map((tag) => `<i>${escapeHtml(tag)}</i>`).join("")}</span>
    </button>
  `).join("") || `<div class="empty">没有匹配的语义块</div>`;
  $("#inputPresetList").innerHTML = registryInputAssemblies().map((preset) => `
    <button class="preset-chip" type="button" data-input-preset="${escapeHtml(preset.id)}">
      ${escapeHtml(preset.label || preset.id)}
    </button>
  `).join("");
  renderInputAssembly();
}

function renderInputAssembly() {
  if (!$("#inputAssemblyList")) return;
  $("#inputAssemblyCount").textContent = `${state.inputSelection.length}`;
  $("#inputAssemblyList").innerHTML = state.inputSelection.map((id, index) => {
    const item = inputItemById(id);
    return `
      <article class="assembly-item">
        <span class="assembly-index">${index + 1}</span>
        <div>
          <strong>${escapeHtml(item?.label || id)}</strong>
          <p>${escapeHtml(item?.summary || "")}</p>
          <small>${escapeHtml(item?.layer || "-")} / ${escapeHtml(item?.source_id || "-")}</small>
        </div>
        <button type="button" class="icon-remove" data-remove-input-index="${index}">移除</button>
      </article>
    `;
  }).join("") || `<div class="empty">从左侧选择语义块，按顺序组装 world state</div>`;
  const selected = state.inputSelection.map(inputItemById).filter(Boolean);
  const tags = Array.from(new Set(selected.flatMap((item) => item.tags || []))).slice(0, 8);
  const summary = selected.map((item) => item.summary).filter(Boolean).join(" / ");
  $("#inputAssemblyPreview").innerHTML = selected.length ? `
    <span>预览</span>
    <strong>${escapeHtml(selected.at(-1)?.situation_id || inferScenarioLabel(tags))}</strong>
    <p>${escapeHtml(clip(summary, 220))}</p>
    <div class="terminal-chips">${tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>
  ` : `<span>预览</span><p>尚未选择语义块。</p>`;
}

function inferScenarioLabel(tags) {
  const text = (tags || []).join(" ");
  if (/sound|music|cocktail|projection/.test(text)) return "music_cocktail_loop";
  if (/heat|hot|cooling|human_hot/.test(text)) return "heat_cooling_loop";
  return "observe_only";
}

function renderOutputLab() {
  if (!$("#outputRegistryList")) return;
  const categories = state.ioRegistry?.output_tools?.categories || [];
  const actions = registryOutputActions();
  const filter = $("#outputCategoryFilter");
  if (filter) {
    const options = [`<option value="all">全部工具</option>`]
      .concat(categories.map((category) => `<option value="${escapeHtml(category.id)}">${escapeHtml(category.label || category.id)}</option>`));
    filter.innerHTML = options.join("");
    filter.value = state.outputCategoryFilter;
  }
  const filtered = state.outputCategoryFilter === "all" ? actions : actions.filter((action) => action.category === state.outputCategoryFilter);
  $("#outputRegistryCount").textContent = `${filtered.length}`;
  $("#outputRegistryList").innerHTML = filtered.map((action) => {
    const commandTypeText = action.command?.type || "g1.unitree_sdk_sequence.step";
    return `
      <button class="candidate-card" type="button" data-output-id="${escapeHtml(action.id)}">
        <span class="candidate-meta">${escapeHtml(action.category || "-")} / ${escapeHtml(action.target_type || "-")}</span>
        <strong>${escapeHtml(action.label || action.id)}</strong>
        <p>${escapeHtml(action.description || "")}</p>
        <span class="candidate-tags"><i>${escapeHtml(commandTypeText)}</i></span>
      </button>
    `;
  }).join("") || `<div class="empty">没有匹配的输出动作</div>`;
  $("#outputPresetList").innerHTML = registryOutputPresets().map((preset) => `
    <button class="preset-chip" type="button" data-output-preset="${escapeHtml(preset.id)}">
      ${escapeHtml(preset.label || preset.id)}
    </button>
  `).join("");
  renderOutputAssembly();
}

function renderOutputAssembly() {
  if (!$("#outputAssemblyList")) return;
  $("#outputAssemblyCount").textContent = `${state.outputSelection.length}`;
  $("#outputAssemblyList").innerHTML = state.outputSelection.map((id, index) => {
    const action = outputActionById(id);
    const commandTypeText = action?.command?.type || "g1.unitree_sdk_sequence.step";
    return `
      <article class="assembly-item">
        <span class="assembly-index">${index + 1}</span>
        <div>
          <strong>${escapeHtml(action?.label || id)}</strong>
          <p>${escapeHtml(commandTypeText)}</p>
          <small>${escapeHtml(action?.category || "-")} / ${escapeHtml(action?.target_type || "-")}</small>
        </div>
        <button type="button" class="icon-remove" data-remove-output-index="${index}">移除</button>
      </article>
    `;
  }).join("") || `<div class="empty">从左侧选择动作，按顺序组装 DeviceCommand 链</div>`;
}

function renderLabResult(kind, payload, status = "ok") {
  const chainTarget = kind === "input" ? $("#inputResultChain") : $("#outputResultChain");
  const jsonTarget = kind === "input" ? $("#inputResult") : $("#outputResult");
  const badge = kind === "input" ? $("#inputResultBadge") : $("#outputResultBadge");
  if (jsonTarget) jsonTarget.innerHTML = pretty(payload);
  if (badge) {
    badge.textContent = status;
    badge.className = `mini-badge ${statusClass(status)}`;
  }
  if (chainTarget) chainTarget.innerHTML = labChainItems(payload).map(renderChainItem).join("") || `<div class="empty">暂无链条</div>`;
}

function labChainItems(payload) {
  const result = payload?.result || payload || {};
  const items = [];
  if (payload?.preview) {
    items.push({
      badge: "INPUT",
      title: "World state assembled",
      summary: payload.preview.summary,
      meta: `${payload.preview.space_id || "-"} / ${payload.preview.situation_id || "-"} / ${payload.preview.semantic_tags?.length || 0} tags`,
    });
  }
  if (Array.isArray(payload?.chain)) {
    payload.chain.forEach((item) => items.push({
      badge: String(item.phase || "STEP").toUpperCase(),
      title: item.title || item.phase || "step",
      summary: item.summary || "",
      meta: item.message_id || "",
    }));
  }
  const steps = result.hermes_turn?.steps || result.agent_run?.hermes_turn?.steps || [];
  steps.slice(-12).forEach((step) => {
    const view = stepView(step);
    items.push({
      badge: view.badge,
      title: view.title,
      summary: view.summary,
      meta: step.tool_name || step.stage || "",
      status: step.status,
    });
  });
  const commands = result.commands || payload?.commands || [];
  commands.forEach((command) => items.push({
    badge: "CMD",
    title: `${command.target_id || "-"} / ${commandType(command)}`,
    summary: command.command?.params?.content_id || command.command?.params?.scene_id || command.command?.params?.task_id || "",
    meta: command.message_id || "",
    status: "sent",
  }));
  const dispatches = [
    ...(result.dispatch_results || payload?.dispatch_results || []),
    ...(payload?.dispatch_result ? [payload.dispatch_result] : []),
  ];
  dispatches.forEach((dispatch) => items.push({
    badge: "ACK",
    title: dispatch.transport || "dispatch",
    summary: [dispatch.status || dispatch.reason || "", dispatch.response?.stage || dispatch.device_response?.stage || dispatch.error || ""]
      .filter(Boolean)
      .join(" / "),
    meta: dispatch.url || dispatch.message_id || "",
    status: dispatch.status,
  }));
  const ackRecords = [
    ...(result.direct_ack_records || payload?.direct_ack_records || []),
    ...(payload?.direct_ack_record ? [payload.direct_ack_record] : []),
  ].filter(Boolean);
  ackRecords.forEach((record) => {
    const ack = record.ack || {};
    items.push({
      badge: "DEV",
      title: `${ack.target_id || "-"} / ${ack.status || "-"}`,
      summary: [ack.stage, ack.error].filter(Boolean).join(" / "),
      meta: ack.message_id || "",
      status: ack.status,
    });
  });
  return items;
}

function renderChainItem(item) {
  return `
    <article class="chain-item">
      <span class="chain-badge">${escapeHtml(item.badge || "STEP")}</span>
      <div>
        <strong>${escapeHtml(item.title || "")}</strong>
        <p>${escapeHtml(clip(item.summary || "", 180))}</p>
        <small>${escapeHtml(item.meta || "")}</small>
      </div>
      <span class="step-status ${statusClass(item.status || "completed")}">${escapeHtml(item.status || "done")}</span>
    </article>
  `;
}

async function simulateAck(command, stage = "console_auto_ack") {
  const endpoint = command.target_type === "robot" ? "/api/robot/ack" : "/api/device/ack";
  return fetchJson(endpoint, {
    method: "POST",
    body: JSON.stringify({
      message_id: command.message_id,
      task_id: taskIdFor(command),
      target_id: command.target_id,
      target_type: command.target_type,
      status: "ok",
      stage,
      progress: 1,
      executed_steps: ["validate_schema", commandType(command), "report_ready"],
      device_time: cstNow(),
      telemetry: {
        executor: "zhichang_agent_console",
        scenario_id: command.scenario_id,
        space_id: command.space_id,
      },
      simulated: true,
    }),
  });
}

async function simulateDeviceAcks(commands) {
  for (const command of commands || []) {
    if (command.target_type !== "robot") {
      await simulateAck(command);
    }
  }
}

async function simulateAllAcks(commands) {
  for (const command of commands || []) {
    await simulateAck(command, "output_test_auto_ack");
  }
}

async function sendFrame(frame) {
  const payload = clone(frame);
  if (payload.scene?.situation_id === "heat_cooling_loop") {
    payload.robot_url = robotBaseUrl();
  }
  const result = await fetchJson("/api/scene/semantic/ingest", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  await simulateDeviceAcks(result.commands || []);
  return result;
}

function buildOperatorGoalFrame(text) {
  const worldState = latestWorldState();
  const lower = text.toLowerCase();
  const tags = ["operator_goal", "human_intent"];
  if (/活跃|兴奋|热闹|active|lively|energy|氛围/.test(lower)) tags.push("atmosphere_more_active");
  if (/安静|舒缓|calm|quiet/.test(lower)) tags.push("atmosphere_more_calm");
  if (/凉|冷|降温|cool|ice|water/.test(lower)) tags.push("cooling_preference");
  if (/音乐|声音|投影|music|sound|projection/.test(lower)) tags.push("soundscape_preference");
  const inferredScene = tags.includes("cooling_preference")
    ? "heat_cooling_loop"
    : (tags.includes("soundscape_preference") || tags.includes("atmosphere_more_active") || tags.includes("atmosphere_more_calm"))
      ? "music_cocktail_loop"
      : null;
  const activeScene = inferredScene || (worldState?.active_scene_id && worldState.active_scene_id !== "observe_only"
    ? worldState.active_scene_id
    : "operator_goal_setting");
  const inferredSpace = activeScene === "music_cocktail_loop"
    ? "sound_cocktail_zone_01"
    : activeScene === "heat_cooling_loop"
      ? "cooling_zone_01"
      : "operator_control_zone";
  return {
    ...baseFrame("operator_goal"),
    source_id: "operator.goal_console",
    space_id: inferredScene ? inferredSpace : (worldState?.space_id || inferredSpace),
    scene: {
      situation_id: activeScene,
      summary: `控制者目标：${text}`,
      intent_hint: "operator_goal",
      tags,
    },
    semantics: {
      operator_goal: {
        label: text,
        level: "goal",
        source: "main_monitor",
        tags,
      },
    },
    events: [{ type: "operator_goal_updated", confidence: 0.86 }],
    affordances: [{ action: "adapt_scene_toward_goal" }],
    safety: { level: "normal" },
    raw_refs: [{ terminal_id: "operator_console", modality: "human_goal" }],
    semantic_tags: tags,
    confidence: 0.86,
    priority: 0.7,
  };
}

async function submitOperatorGoal() {
  if (state.busy) return;
  const input = $("#operatorGoalText");
  const status = $("#goalStatus");
  const text = input?.value?.trim() || "";
  if (!text) {
    showToast("请先输入一个场景目标");
    return;
  }
  markBusy(true);
  if (status) status.textContent = "sending";
  try {
    const frame = buildOperatorGoalFrame(text);
    const result = await sendFrame(frame);
    if (status) status.textContent = result.status || "ok";
    showToast(`目标已进入中枢 / ${result.command_count || 0} commands`);
    await delayedRefresh();
  } catch (error) {
    if (status) status.textContent = "failed";
    showToast(`目标注入失败: ${error.message}`);
  } finally {
    markBusy(false);
  }
}

async function sendCurrentText() {
  if (state.busy) return;
  markBusy(true);
  try {
    const frame = buildFrame(state.activeFrame);
    const text = $("#semanticText").value.trim();
    if (text) {
      frame.scene.summary = text;
      frame.semantics.operator_note = { label: text, role: "input_lab" };
    }
    const result = await sendFrame(frame);
    setResult($("#inputResult"), $("#inputResultBadge"), result, result.status || "processed");
    showToast(`${result.planner_decision?.scenario_id || "observe"} / ${result.command_count || 0} commands`);
    await delayedRefresh();
  } catch (error) {
    setResult($("#inputResult"), $("#inputResultBadge"), { error: error.message }, "failed");
    showToast(`输入测试失败: ${error.message}`);
  } finally {
    markBusy(false);
  }
}

async function sendCurrentJson() {
  if (state.busy) return;
  markBusy(true);
  try {
    const frame = JSON.parse($("#semanticJson").value);
    const result = await sendFrame(frame);
    setResult($("#inputResult"), $("#inputResultBadge"), result, result.status || "processed");
    showToast(`${result.planner_decision?.scenario_id || "observe"} / ${result.command_count || 0} commands`);
    await delayedRefresh();
  } catch (error) {
    setResult($("#inputResult"), $("#inputResultBadge"), { error: error.message }, "failed");
    showToast(`JSON 注入失败: ${error.message}`);
  } finally {
    markBusy(false);
  }
}

async function sendInputAssembly(runAgent = true) {
  if (state.busy) return;
  if (!state.inputSelection.length) {
    showToast("请先从左侧选择语义块");
    return;
  }
  markBusy(true);
  try {
    const result = await fetchJson("/api/agent/input-test/assemble", {
      method: "POST",
      body: JSON.stringify({
        selected_ids: state.inputSelection,
        custom_text: $("#inputCustomText")?.value?.trim() || "",
        run_agent: runAgent,
        robot_url: robotBaseUrl(),
      }),
    });
    const commands = result.result?.commands || [];
    if (runAgent) await simulateDeviceAcks(commands);
    renderLabResult("input", result, result.status || "processed");
    showToast(runAgent ? `Agent 响应 ${commands.length} 条命令` : "World state 已组装预览");
    await delayedRefresh();
  } catch (error) {
    renderLabResult("input", { error: error.message }, "failed");
    showToast(`输入组装失败: ${error.message}`);
  } finally {
    markBusy(false);
  }
}

async function runLoop() {
  if (state.busy) return;
  markBusy(true);
  const results = [];
  try {
    for (const name of ["heat", "heat-feedback", "music", "music-feedback"]) {
      setActiveFrame(name);
      const result = await sendFrame(buildFrame(name));
      results.push({ frame: name, scenario_id: result.planner_decision?.scenario_id, command_count: result.command_count });
      await sleep(500);
      await refreshAll();
    }
    setResult($("#inputResult"), $("#inputResultBadge"), { loop: results }, "completed");
    showToast("两场景闭环完成");
  } catch (error) {
    setResult($("#inputResult"), $("#inputResultBadge"), { loop: results, error: error.message }, "failed");
    showToast(`闭环失败: ${error.message}`);
  } finally {
    markBusy(false);
    await refreshAll();
  }
}

async function sendOutputSequence() {
  if (state.busy) return;
  if (!state.outputSelection.length) {
    showToast("请先从左侧选择输出动作");
    return;
  }
  markBusy(true);
  try {
    const result = await fetchJson("/api/agent/output-test/sequence", {
      method: "POST",
      body: JSON.stringify({
        action_ids: state.outputSelection,
        robot_url: robotBaseUrl(),
        routing_overrides: outputRoutingOverrides(),
        execute: true,
      }),
    });
    if ($("#autoAckOutput")?.checked) {
      const directAcked = new Set((result.direct_ack_records || []).map((record) => record?.ack?.message_id).filter(Boolean));
      await simulateAllAcks((result.commands || []).filter((command) => !directAcked.has(command.message_id)));
    }
    renderLabResult("output", result, result.status || "sent");
    if ((result.commands || []).some((command) => command.target_type === "spray_gateway")) {
      await refreshSprayGatewayStatus(true);
    }
    showToast(`输出链已发送 ${result.commands?.length || 0} 条命令`);
    await delayedRefresh();
  } catch (error) {
    renderLabResult("output", { error: error.message }, "failed");
    showToast(`输出链发送失败: ${error.message}`);
  } finally {
    markBusy(false);
  }
}

function outputCommandTemplate(kind) {
  const taskId = `output_test_${kind}_${Date.now()}`;
  if (kind === "spray") {
    return {
      target_id: "spray_gateway",
      target_type: "spray_gateway",
      command: { type: "spray.scene", params: { task_id: taskId, op: "mist", zone: "cooling_zone_01", duration_sec: 20, intensity: 0.45 } },
      ack_required: true,
      timeout_ms: 15000,
    };
  }
  if (kind === "speaker") {
    return {
      target_id: "speaker_gateway",
      target_type: "speaker_gateway",
      command: { type: "speaker.play", params: { task_id: taskId, op: "play", content_id: "music_cocktail_loop", volume: 0.62, loop: false } },
      ack_required: true,
      timeout_ms: 15000,
    };
  }
  if (kind === "projection") {
    return {
      target_id: "projection_gateway",
      target_type: "projection_gateway",
      command: { type: "projection.play", params: { task_id: taskId, op: "play", content_id: "sound_wave_visual", loop: false } },
      ack_required: true,
      timeout_ms: 15000,
    };
  }
  return {
    target_id: "unitree_g1",
    target_type: "robot",
    command: {
      type: "g1.unitree_sdk_sequence",
      params: {
        task_id: taskId,
        scene_id: "output_test_robot_sequence",
        speech_cn: "清凉补给已送达。",
        safety: { dry_run: true, speed_limit_mps: 0.25, min_human_distance_m: 0.8 },
        sdk_sequence: [
          { step: 1, action: "SafetyGuard.CheckPreconditions" },
          { step: 2, action: "G1.NavigateTo", args: { waypoint: "ice_water_station" } },
          { step: 3, action: "G1.PickObject", args: { object_id: "ice_water_cup" } },
          { step: 4, action: "G1.NavigateTo", args: { waypoint: "cooling_handoff_01" } },
          { step: 5, action: "G1.DeliverObject", args: { object_id: "ice_water_cup" } },
          { step: 6, action: "G1.Speak", args: { text: "清凉补给已送达。" } },
          { step: 7, action: "FeedbackAdapter.ReportReady" },
        ],
      },
    },
    ack_required: true,
    timeout_ms: 60000,
  };
}

async function sendOutputCommand(kind) {
  if (state.busy) return;
  markBusy(true);
  try {
    const command = outputCommandTemplate(kind);
    const result = await fetchJson("/api/agent/output-test/command", {
      method: "POST",
      body: JSON.stringify({
        command,
        scenario_id: "output_test",
        space_id: kind === "speaker" || kind === "projection" ? "sound_cocktail_zone_01" : "cooling_zone_01",
        robot_url: robotBaseUrl(),
        routing_overrides: outputRoutingOverrides(),
      }),
    });
    if ($("#autoAckOutput").checked && !result.direct_ack_record) await simulateAck(result.command, "output_test_manual_command");
    renderLabResult("output", result, result.status || "sent");
    if (kind === "spray") await refreshSprayGatewayStatus(true);
    showToast(`${commandType(result.command)} 已发送`);
    await delayedRefresh();
  } catch (error) {
    renderLabResult("output", { error: error.message }, "failed");
    showToast(`输出测试失败: ${error.message}`);
  } finally {
    markBusy(false);
  }
}

async function sendOutputNaturalLanguage() {
  if (state.busy) return;
  markBusy(true);
  try {
    const text = $("#outputText").value.trim();
    const result = await fetchJson("/api/hermes/message", {
      method: "POST",
      body: JSON.stringify({
        text,
        mode: "output_tool_test",
        robot_url: robotBaseUrl(),
        routing_overrides: outputRoutingOverrides(),
      }),
    });
    const commands = result.result?.commands || [];
    if ($("#autoAckOutput").checked) {
      const directAcked = new Set((result.result?.direct_ack_records || []).map((record) => record?.ack?.message_id).filter(Boolean));
      await simulateAllAcks(commands.filter((command) => !directAcked.has(command.message_id)));
    }
    renderLabResult("output", result, result.status || "processed");
    if (commands.some((command) => command.target_type === "spray_gateway")) {
      await refreshSprayGatewayStatus(true);
    }
    showToast(`Agent 输出 ${commands.length} 条命令`);
    await delayedRefresh();
  } catch (error) {
    renderLabResult("output", { error: error.message }, "failed");
    showToast(`动作链生成失败: ${error.message}`);
  } finally {
    markBusy(false);
  }
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function delayedRefresh() {
  await refreshAll();
  await sleep(500);
  await refreshAll();
  await sleep(1000);
  await refreshAll();
}

async function refreshAll() {
  try {
    const [health, runtime, turns, conversation, worldStates] = await Promise.all([
      fetchJson("/api/health"),
      fetchJson("/api/hermes/status"),
      fetchJson("/api/hermes/turns/latest?limit=30"),
      fetchJson("/api/hermes/conversation?limit=160"),
      fetchJson("/api/agent/world-state"),
    ]);
    state.turns = turns.turns || [];
    state.conversation = conversation.messages || [];
    state.worldStates = worldStates.world_states || {};

    const provider = (runtime.candidate_providers || []).find((item) => item.configured) || (runtime.candidate_providers || [])[0] || {};
    const latestTurn = last(state.turns);
    const latestMode = latestTurn?.agent_mode || latestTurn?.planner_decision?.provider || {};
    const llmStatus = latestTurn?.planner_decision?.provider?.llm_status;
    const thinking = latestTurn?.agent_mode?.thinking?.type || runtime.runtime_policy?.default_thinking || "disabled";

    setStatus($("#hubStatus"), health.status === "ok" ? "中枢在线" : "中枢异常", health.status === "ok" ? "ok" : "warn");
    setStatus($("#modelStatus"), provider.model ? `${provider.provider} / ${provider.model}` : "模型未配置", provider.api_key_configured ? "ok" : "bad");
    setStatus($("#policyStatus"), `${latestMode.mode || "fast_planner"} · thinking ${thinking}${llmStatus ? ` · ${llmStatus}` : ""}`, thinking === "enabled" ? "warn" : "ok");

    renderConversation();
    renderWorldState();
    renderTrajectory();
    renderInspector();
    if (state.page === "output") {
      refreshSprayGatewayStatus(true);
    }
  } catch (error) {
    setStatus($("#hubStatus"), "中枢离线", "bad");
    showToast(`刷新失败: ${error.message}`);
  }
}

function protocolMessages() {
  return state.conversation.filter((message) => {
    const kind = message.kind || "";
    return ["scene_semantic_frame", "robot_ack", "device_ack"].includes(kind);
  });
}

function terminalLabel(message) {
  const kind = message.kind || "";
  const frame = message.frame || {};
  const ack = message.ack || {};
  const source = frame.source_id || ack.target_id || "";
  const text = `${source} ${message.content || ""}`.toLowerCase();
  if (kind === "robot_ack") return "G1 自身 ACK / 执行感知";
  if (kind === "device_ack") return "设备网关 ACK";
  if (text.includes("sound") || text.includes("music") || text.includes("声音")) return "场地声学感知组";
  if (text.includes("thermal") || text.includes("heat") || text.includes("cooling") || text.includes("热")) return "场地热环境感知组";
  return "场地语义融合端";
}

function protocolName(message) {
  if (message.kind === "robot_ack") return "RobotACK";
  if (message.kind === "device_ack") return "DeviceACK";
  return "SceneSemanticFrame";
}

function renderConversation() {
  const messages = protocolMessages();
  $("#streamCount").textContent = `${messages.length}`;
  const container = $("#streamList");
  if (!messages.length) {
    container.innerHTML = `<div class="empty">等待感知终端回传</div>`;
    return;
  }
  container.innerHTML = messages.slice(-32).map((message) => {
    const frame = message.frame || {};
    const ack = message.ack || {};
    const chips = [protocolName(message)];
    if (frame.source_id) chips.push(frame.source_id);
    if (frame.space_id) chips.push(frame.space_id);
    if (Array.isArray(frame.semantic_tags)) chips.push(...frame.semantic_tags.slice(0, 3));
    if (ack.status) chips.push(ack.status);
    if (ack.stage) chips.push(ack.stage);
    const content = frame.scene?.summary || message.content || ack.stage || "";
    return `
      <article class="stream-item ${escapeHtml(message.kind || "message")}">
        <div class="stream-meta">
          <span>${escapeHtml(protocolName(message))}</span>
          <time>${escapeHtml(timeOnly(message.timestamp || ack.device_time))}</time>
        </div>
        <strong class="terminal-name">${escapeHtml(terminalLabel(message))}</strong>
        <p class="terminal-text">${escapeHtml(clip(content, 144))}</p>
        <div class="terminal-chips">${chips.map((chip) => `<span>${escapeHtml(chip)}</span>`).join("")}</div>
      </article>
    `;
  }).join("");
  container.scrollTop = container.scrollHeight;
}

function renderWorldState() {
  const worldState = latestWorldState();
  if (!worldState) {
    $("#worldStateTitle").textContent = "等待场景状态";
    $("#worldStateBody").innerHTML = `<div class="empty compact">等待场景语义进入中枢</div>`;
    return;
  }
  $("#worldStateTitle").textContent = `${worldState.active_scene_id || "observe_only"} / ${worldState.scene_phase || "-"}`;
  const tags = (worldState.semantic_tags || []).slice(0, 6);
  $("#worldStateBody").innerHTML = `
    <div class="world-summary-line">${escapeHtml(worldState.summary || "当前场景稳定运行中")}</div>
    <div class="world-metrics">
      <span>${escapeHtml(worldState.space_id || "-")}</span>
      <span>priority ${escapeHtml(String(worldState.priority ?? "-"))}</span>
      <span>confidence ${escapeHtml(String(worldState.confidence ?? "-"))}</span>
    </div>
    <div class="world-tags">
      ${tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}
    </div>
  `;
}

function latestWorldState() {
  const states = Object.values(state.worldStates || {});
  return states.sort((a, b) => String(a.updated_at || "").localeCompare(String(b.updated_at || ""))).at(-1) || null;
}

function stepView(step) {
  const tool = step.tool_name || "";
  const stage = step.stage || "";
  const title = scrubForDisplay(step.title || stage || "step");
  if (tool.includes("observe_scene")) return { layer: "l1", badge: "L1 采样", title: "多源采样进入中枢", summary: step.summary || "场地与机器人感知语义进入当前回合。" };
  if (tool.includes("retrieve_context")) return { layer: "l2", badge: "L2 上下文", title: "检索短期状态与长期记忆", summary: step.summary || "读取 world state、近期命令、ACK 与记忆卡。" };
  if (tool.includes("select_scene_policy")) return { layer: "l3", badge: "L3 推理", title: "意图生成与场景策略", summary: step.summary || "选择热感清凉或声音鸡尾酒策略。" };
  if (stage.includes("runtime.llm")) return { layer: "l3", badge: "L3 模型", title: "V4 Flash 模型回合", summary: step.summary || "模型在工具约束下推进推理。" };
  if (stage.includes("runtime.fast_layer")) return { layer: "l2", badge: "快层", title: "快层处理反馈帧", summary: step.summary || "反馈或低优先级输入不等待模型回合。" };
  if (stage.includes("runtime.tool")) return { layer: "l3", badge: "L3 工具", title: title || "模型调用工具", summary: step.summary || "注册工具被模型调用并返回结果。" };
  if (tool.includes("plan_device_commands")) return { layer: "l3", badge: "L3 工具", title: "编排设备工具", summary: step.summary || "把策略翻译为标准 DeviceCommand。" };
  if (tool.includes("emit_device_command")) return { layer: "l3", badge: "L3 执行", title: "联动输出", summary: step.summary || "喷雾、音乐、投影或机器人动作进入设备协议。" };
  if (stage.includes("dispatch")) return { layer: "l3", badge: "L3 下发", title: "DeviceCommand 下发", summary: step.summary || "通过 HTTP/轮询/网关路由到设备。" };
  if (tool.includes("record_physical_feedback") || stage.includes("ack")) return { layer: "l4", badge: "L4 评估", title: "反馈评估", summary: step.summary || "机器人或设备 ACK 回到中枢。" };
  if (stage.includes("public_trace")) return { layer: "l3", badge: "轨迹", title: "公开轨迹抽取", summary: step.summary || "抽取可展示的推理/执行链。" };
  return { layer: "l3", badge: "RUN", title, summary: step.summary || "" };
}

function renderTrajectory() {
  const turn = last(state.turns);
  const container = $("#trajectoryList");
  if (!turn) {
    $("#runSummary").innerHTML = `<span>Waiting for run</span>`;
    container.innerHTML = `<div class="empty">暂无 Agent 轨迹</div>`;
    return;
  }
  const steps = turn.steps || [];
  if (!state.selectedStepId || !steps.some((step) => step.step_id === state.selectedStepId)) {
    state.selectedStepId = steps[steps.length - 1]?.step_id || null;
  }
  const toolCount = steps.filter((step) => String(step.stage || "").includes("tool.complete")).length;
  const commandCount = (turn.commands || []).length;
  const llmStatus = turn.planner_decision?.provider?.llm_status || "-";
  const thinking = turn.agent_mode?.thinking?.type || turn.planner_decision?.provider?.thinking?.type || "disabled";
  $("#runSummary").innerHTML = `
    <span>${escapeHtml(turn.run_id || "run")}</span>
    <b>${escapeHtml(turn.scenario_id || "observe_only")} · ${commandCount} commands · ${toolCount} tool steps</b>
    <small>${escapeHtml(turn.status || "running")} / ${escapeHtml(turn.space_id || "-")} / ${escapeHtml(llmStatus)} / thinking ${escapeHtml(thinking)}</small>
  `;
  container.innerHTML = steps.map((step) => renderStep(step)).join("");
}

function renderStep(step) {
  const view = stepView(step);
  const selected = step.step_id === state.selectedStepId ? " selected" : "";
  return `
    <article class="step ${escapeHtml(view.layer)}${selected}" data-step-id="${escapeHtml(step.step_id)}">
      <button class="step-main" type="button" data-step-id="${escapeHtml(step.step_id)}">
        <span class="step-icon">${escapeHtml(view.badge)}</span>
        <span class="step-copy">
          <span class="step-title">${escapeHtml(view.title)}</span>
          <span class="step-summary">${escapeHtml(view.summary)}</span>
          <span class="step-raw">${escapeHtml(String(step.tool_name || step.stage || "").replaceAll("hermes", "runtime"))}</span>
        </span>
        <span class="step-status ${statusClass(step.status)}">${escapeHtml(step.status || "done")}</span>
      </button>
    </article>
  `;
}

function renderInspector() {
  const turn = last(state.turns);
  const steps = turn?.steps || [];
  const step = steps.find((item) => item.step_id === state.selectedStepId) || last(steps);
  if (!step) {
    $("#inspectorTitle").textContent = "未选中步骤";
    $("#inspectorBadge").textContent = "idle";
    $("#inspectorBody").innerHTML = `<div class="empty">点击轨迹步骤查看细节</div>`;
    return;
  }
  const view = stepView(step);
  $("#inspectorTitle").textContent = view.title;
  $("#inspectorBadge").textContent = view.badge;
  $("#inspectorBody").innerHTML = `
    <dl class="detail-list">
      <div><dt>layer</dt><dd>${escapeHtml(view.badge)}</dd></div>
      <div><dt>chain</dt><dd>${escapeHtml(step.chain || "-")}</dd></div>
      <div><dt>tool</dt><dd>${escapeHtml(step.tool_name || "-")}</dd></div>
      <div><dt>time</dt><dd>${escapeHtml(step.timestamp || "-")}</dd></div>
    </dl>
    <pre class="detail-json">${pretty(step)}</pre>
  `;
}

function timeOnly(value) {
  if (!value) return "";
  const text = String(value);
  const match = text.match(/T(\d\d:\d\d:\d\d)/);
  return match ? match[1] : text.slice(11, 19);
}

function bindEvents() {
  const bind = (selector, eventName, handler) => {
    const node = $(selector);
    if (node) node.addEventListener(eventName, handler);
  };
  $$(".nav-link").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      setPage(link.dataset.page, true);
      refreshAll();
    });
  });
  window.addEventListener("popstate", () => setPage(routeToPage(), false));
  $$(".preset").forEach((button) => {
    button.addEventListener("click", () => setActiveFrame(button.dataset.frame));
  });
  bind("#refreshButton", "click", () => {
    loadIoRegistry();
    refreshAll();
  });
  bind("#sendTextButton", "click", sendCurrentText);
  bind("#sendFrameButton", "click", sendCurrentJson);
  bind("#sendGoalButton", "click", submitOperatorGoal);
  bind("#runLoopButton", "click", runLoop);
  bind("#sendOutputTextButton", "click", sendOutputNaturalLanguage);
  bind("#checkSprayGatewayButton", "click", async () => {
    const payload = await refreshSprayGatewayStatus(false);
    if (payload?.gateway_reachable && payload?.smart_plug?.connected) {
      showToast("喷雾链路在线");
    } else if (payload?.gateway_reachable) {
      showToast("喷雾网关在线，智能插座未接入");
    } else {
      showToast("喷雾网关不可达");
    }
  });
  bind("#previewAssemblyButton", "click", () => sendInputAssembly(false));
  bind("#sendAssemblyButton", "click", () => sendInputAssembly(true));
  bind("#clearInputAssemblyButton", "click", () => {
    state.inputSelection = [];
    renderInputAssembly();
  });
  bind("#sendOutputSequenceButton", "click", sendOutputSequence);
  bind("#clearOutputAssemblyButton", "click", () => {
    state.outputSelection = [];
    renderOutputAssembly();
  });
  bind("#inputLayerFilter", "change", (event) => {
    state.inputLayerFilter = event.target.value;
    renderInputLab();
  });
  bind("#outputCategoryFilter", "change", (event) => {
    state.outputCategoryFilter = event.target.value;
    renderOutputLab();
  });
  bind("#inputRegistryList", "click", (event) => {
    const button = event.target.closest("[data-input-id]");
    if (!button) return;
    state.inputSelection.push(button.dataset.inputId);
    renderInputAssembly();
  });
  bind("#inputPresetList", "click", (event) => {
    const button = event.target.closest("[data-input-preset]");
    if (!button) return;
    const preset = registryInputAssemblies().find((item) => item.id === button.dataset.inputPreset);
    state.inputSelection = [...(preset?.item_ids || [])];
    renderInputAssembly();
  });
  bind("#inputAssemblyList", "click", (event) => {
    const button = event.target.closest("[data-remove-input-index]");
    if (!button) return;
    state.inputSelection.splice(Number(button.dataset.removeInputIndex), 1);
    renderInputAssembly();
  });
  bind("#outputRegistryList", "click", (event) => {
    const button = event.target.closest("[data-output-id]");
    if (!button) return;
    state.outputSelection.push(button.dataset.outputId);
    renderOutputAssembly();
  });
  bind("#outputPresetList", "click", (event) => {
    const button = event.target.closest("[data-output-preset]");
    if (!button) return;
    const preset = registryOutputPresets().find((item) => item.id === button.dataset.outputPreset);
    state.outputSelection = [...(preset?.action_ids || [])];
    renderOutputAssembly();
  });
  bind("#outputAssemblyList", "click", (event) => {
    const button = event.target.closest("[data-remove-output-index]");
    if (!button) return;
    state.outputSelection.splice(Number(button.dataset.removeOutputIndex), 1);
    renderOutputAssembly();
  });
  $$(".command-grid button").forEach((button) => {
    button.addEventListener("click", () => sendOutputCommand(button.dataset.command));
  });
  bind("#trajectoryList", "click", (event) => {
    const button = event.target.closest("[data-step-id]");
    if (!button) return;
    state.selectedStepId = button.dataset.stepId;
    renderTrajectory();
    renderInspector();
  });
}

installLabTemplates();
bindEvents();
setPage(routeToPage(), false);
setActiveFrame("heat");
loadIoRegistry();
refreshAll();
window.setInterval(() => {
  if (!state.busy) refreshAll();
}, 3500);
