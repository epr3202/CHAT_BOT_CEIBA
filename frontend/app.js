const state = {
  adminToken: localStorage.getItem("ceiba.adminToken") || "",
  agentName: localStorage.getItem("ceiba.agentName") || "Asesor",
  metaSecret: sessionStorage.getItem("ceiba.metaSecret") || "",
  currentStatus: "PENDING",
  caseStatus: "ALL",
  adminCases: [],
  lastWebhook: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function headers() {
  return state.adminToken ? { Authorization: `Bearer ${state.adminToken}` } : {};
}

function resetAdminMetrics() {
  setText("metricPending", "--");
  setText("metricTaken", "--");
  setText("metricReturned", "--");
}

function renderAdminTokenRequired() {
  state.adminCases = [];
  resetAdminMetrics();
  const container = $("#caseList");
  if (container) {
    container.innerHTML = `<div class="emptyState">Configura y guarda el token admin para cargar clientes.</div>`;
  }
}

async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "object" && payload !== null ? payload.detail || JSON.stringify(payload) : payload;
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return payload;
}

function applyConfigToForm() {
  $("#adminToken").value = state.adminToken;
  $("#agentName").value = state.agentName;
  $("#metaSecret").value = state.metaSecret;
}

function saveConfig() {
  state.adminToken = $("#adminToken").value.trim();
  state.agentName = $("#agentName").value.trim() || "Asesor";
  state.metaSecret = $("#metaSecret").value;
  localStorage.setItem("ceiba.adminToken", state.adminToken);
  localStorage.setItem("ceiba.agentName", state.agentName);
  sessionStorage.setItem("ceiba.metaSecret", state.metaSecret);
  logEvent("Configuración guardada para esta estación.");
}

function setApiState(kind, text) {
  const node = $("#apiState");
  node.className = `pill ${kind}`;
  node.textContent = text;
  setText("metricApi", text);
}

async function checkHealth() {
  try {
    const data = await requestJson("/api/health");
    setApiState("ok", data.status === "ok" ? "API ok" : "API responde");
  } catch (error) {
    setApiState("bad", "API caída");
    logEvent(`Health falló: ${error.message}`);
  }
}

function logEvent(message) {
  const list = $("#eventLog");
  const item = document.createElement("li");
  item.textContent = `${new Date().toLocaleTimeString("es-CO", { hour12: false })} · ${message}`;
  list.prepend(item);
  setText("metricWebhook", message.slice(0, 22));
}

function messageId() {
  return `wamid.frontend.${Date.now()}.${crypto.randomUUID()}`;
}

async function sendWebhook({ duplicate = false } = {}) {
  saveConfig();
  const payload = duplicate && state.lastWebhook
    ? state.lastWebhook
    : {
        phone: $("#phone").value.trim(),
        text: $("#messageText").value.trim(),
        messageId: messageId(),
        metaSecret: state.metaSecret,
      };

  if (!payload.metaSecret) {
    logEvent("Falta META_APP_SECRET para firmar el webhook.");
    return;
  }
  if (!payload.text) {
    logEvent("El mensaje no puede estar vacío.");
    return;
  }

  try {
    await requestJson("/api/webhook/simulate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.lastWebhook = payload;
    logEvent(duplicate ? `Duplicado reenviado: ${payload.messageId}` : `Webhook aceptado: ${payload.text}`);
    await refreshAll();
  } catch (error) {
    logEvent(`Webhook falló: ${error.message}`);
  }
}

async function loadHandoffs(status = state.currentStatus) {
  state.currentStatus = status;
  $$(".segment").forEach((button) => button.classList.toggle("active", button.dataset.status === status));

  const list = $("#handoffList");
  list.innerHTML = `<div class="emptyState">Cargando ${status.toLowerCase()}...</div>`;

  try {
    const handoffs = await requestJson(`/api/admin/handoffs?status=${encodeURIComponent(status)}`, {
      headers: headers(),
    });
    renderHandoffs(handoffs);
    if (status === "PENDING") setText("metricPending", String(handoffs.length));
    if (status === "TAKEN") setText("metricTaken", String(handoffs.length));
    return handoffs;
  } catch (error) {
    list.innerHTML = `<div class="emptyState">No se pudo cargar la bandeja: ${error.message}</div>`;
    return [];
  }
}

async function loadAllAdminCases() {
  if (!state.adminToken) {
    renderAdminTokenRequired();
    return;
  }

  try {
    const results = await loadAllAdminCasesWithoutPartialData();
    state.adminCases = results.flat().map(caseFromHandoff);
    setText("metricPending", String(state.adminCases.filter((item) => item.status === "PENDING").length));
    setText("metricTaken", String(state.adminCases.filter((item) => item.status === "TAKEN").length));
    setText("metricReturned", String(state.adminCases.filter((item) => item.status === "RETURNED").length));
    renderAdminCases();
  } catch (error) {
    state.adminCases = [];
    resetAdminMetrics();
    const container = $("#caseList");
    if (container) {
      container.innerHTML = `<div class="emptyState">No se pudo cargar clientes: ${error.message}</div>`;
    }
    logEvent(`Clientes falló: ${error.message}`);
  }
}

async function loadAllAdminCasesWithoutPartialData() {
  const statuses = ["PENDING", "TAKEN", "RETURNED"];
  return Promise.all(
    statuses.map((status) =>
      requestJson(`/api/admin/handoffs?status=${encodeURIComponent(status)}`, {
        headers: headers(),
      })
    )
  );
}

function caseFromHandoff(handoff) {
  const parsed = parseSummary(handoff.summary || "");
  return {
    id: handoff.id,
    conversationId: handoff.conversation_id,
    status: handoff.status,
    priority: handoff.priority,
    reason: parsed.motivo || handoff.reason,
    customerName: parsed.cliente || "Cliente sin nombre confirmado",
    phone: parsed.telefono || "Teléfono no disponible",
    assignedTo: handoff.assigned_to || "Sin asignar",
    createdAt: handoff.created_at,
    takenAt: handoff.taken_at,
    resolvedAt: handoff.resolved_at,
    summary: handoff.summary || "",
  };
}

function parseSummary(summary) {
  const fields = {};
  for (const line of summary.split("\n")) {
    const [rawKey, ...rest] = line.split(":");
    if (!rawKey || rest.length === 0) continue;
    const key = rawKey.trim().toLowerCase();
    const value = rest.join(":").trim();
    if (key === "cliente") fields.cliente = value;
    if (key === "telefono") fields.telefono = value;
    if (key === "motivo") fields.motivo = value;
  }
  return fields;
}

function renderAdminCases() {
  const container = $("#caseList");
  if (!container) return;

  const query = ($("#caseSearch")?.value || "").trim().toLowerCase();
  const cases = state.adminCases.filter((item) => {
    const statusMatches = state.caseStatus === "ALL" || item.status === state.caseStatus;
    const text = [
      item.customerName,
      item.phone,
      item.reason,
      item.assignedTo,
      String(item.conversationId),
      String(item.id),
    ]
      .join(" ")
      .toLowerCase();
    return statusMatches && (!query || text.includes(query));
  });

  container.innerHTML = "";
  if (!cases.length) {
    container.innerHTML = `<div class="emptyState">No hay clientes para este filtro con la API actual.</div>`;
    return;
  }

  const template = $("#caseTemplate");
  for (const item of cases) {
    const row = template.content.firstElementChild.cloneNode(true);
    $(".caseClient", row).textContent = item.customerName;
    $(".casePhone", row).textContent = `${item.phone} · conversación ${item.conversationId}`;
    const status = $(".caseStatus", row);
    status.className = `caseStatus pill ${statusClass(item.status)}`;
    status.textContent = statusLabel(item.status);
    $(".caseAssignment", row).textContent = item.assignedTo;
    $(".caseReason", row).textContent = item.reason;
    $(".caseActivity", row).textContent = activityText(item);
    const actions = $(".caseActions", row);
    if (item.status === "PENDING") {
      actions.append(actionButton("Tomar", () => takeHandoff(item.id), "primary"));
    } else if (item.status === "TAKEN") {
      actions.append(actionButton("Responder", () => openHandoffAndFocus(item.id)));
      actions.append(actionButton("Devolver", () => returnHandoff(item.id), "danger"));
    } else {
      actions.append(actionButton("Ver resumen", () => showSummary(item)));
    }
    container.append(row);
  }
}

function statusClass(status) {
  if (status === "PENDING") return "warn";
  if (status === "TAKEN") return "ok";
  if (status === "RETURNED") return "neutral";
  return "neutral";
}

function statusLabel(status) {
  return {
    PENDING: "Pendiente",
    TAKEN: "Asignado",
    RETURNED: "Devuelto",
    RESOLVED: "Resuelto",
  }[status] || status;
}

function activityText(item) {
  const timestamp = item.resolvedAt || item.takenAt || item.createdAt;
  if (!timestamp) return "Sin fecha";
  const label = item.resolvedAt ? "Devuelto" : item.takenAt ? "Tomado" : "Creado";
  return `${label} · ${new Date(timestamp).toLocaleString("es-CO", { hour12: false })}`;
}

function openHandoffAndFocus(handoffId) {
  const nav = $(`.navItem[data-view="handoffs"]`);
  nav?.click();
  loadHandoffs("TAKEN").then(() => {
    const card = $(`[data-handoff-id="${handoffId}"]`);
    card?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
}

function showSummary(item) {
  alert(item.summary || "Sin resumen disponible");
}

function priorityClass(priority) {
  if (priority === "CRITICAL") return "bad";
  if (priority === "URGENT") return "warn";
  return "neutral";
}

function renderHandoffs(handoffs) {
  const list = $("#handoffList");
  list.innerHTML = "";
  if (!handoffs.length) {
    list.innerHTML = `<div class="emptyState">No hay handoffs en este estado.</div>`;
    return;
  }

  const template = $("#handoffTemplate");
  for (const handoff of handoffs) {
    const node = template.content.firstElementChild.cloneNode(true);
    node.dataset.handoffId = String(handoff.id);
    $(".handoffTitle", node).textContent = `Conversación ${handoff.conversation_id}`;
    $(".handoffMeta", node).textContent = `Handoff ${handoff.id} · ${handoff.reason} · ${handoff.status}`;
    const priority = $(".priority", node);
    priority.className = `priority ${priorityClass(handoff.priority)}`;
    priority.textContent = handoff.priority;
    $(".summary", node).textContent = handoff.summary || "Sin resumen disponible";

    const actions = $(".handoffActions", node);
    if (handoff.status === "PENDING") {
      actions.append(actionButton("Tomar", () => takeHandoff(handoff.id)));
    } else if (handoff.status === "TAKEN") {
      const textarea = document.createElement("textarea");
      textarea.placeholder = "Respuesta del asesor";
      textarea.value = "Hola, soy del equipo de La Ceiba. Ya reviso tu solicitud.";
      actions.append(textarea);
      actions.append(actionButton("Enviar", () => sendAgentMessage(handoff.conversation_id, textarea.value)));
      actions.append(actionButton("Devolver", () => returnHandoff(handoff.id), "danger"));
    } else {
      const button = actionButton("Ver pendientes", () => loadHandoffs("PENDING"));
      actions.append(button);
    }
    list.append(node);
  }
}

function actionButton(label, onClick, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  if (className) button.classList.add(className);
  button.addEventListener("click", onClick);
  return button;
}

async function takeHandoff(handoffId) {
  saveConfig();
  try {
    await requestJson(`/api/admin/handoffs/${handoffId}/take`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ agent: state.agentName }),
    });
    logEvent(`Handoff ${handoffId} tomado por ${state.agentName}.`);
    await refreshAll();
    await loadHandoffs("TAKEN");
  } catch (error) {
    logEvent(`No se pudo tomar el handoff: ${error.message}`);
  }
}

async function sendAgentMessage(conversationId, text) {
  if (!text.trim()) {
    logEvent("La respuesta humana no puede estar vacía.");
    return;
  }
  try {
    await requestJson(`/api/admin/conversations/${conversationId}/messages`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ text }),
    });
    logEvent(`Respuesta encolada para conversación ${conversationId}.`);
  } catch (error) {
    logEvent(`No se pudo enviar la respuesta: ${error.message}`);
  }
}

async function returnHandoff(handoffId) {
  const resolution = prompt("Resolución para devolver la conversación al bot:", "Cliente atendido y devuelto al bot.");
  if (!resolution) return;
  try {
    await requestJson(`/api/admin/handoffs/${handoffId}/return`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ resolution }),
    });
    logEvent(`Handoff ${handoffId} devuelto al bot.`);
    await refreshAll();
  } catch (error) {
    logEvent(`No se pudo devolver el handoff: ${error.message}`);
  }
}

async function refreshAll() {
  await checkHealth();
  if (!state.adminToken) {
    renderAdminTokenRequired();
    return;
  }
  await loadAllAdminCases();
  await loadHandoffs(state.currentStatus);
}

function bindUi() {
  $$(".navItem").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".navItem").forEach((item) => item.classList.remove("active"));
      $$(".view").forEach((view) => view.classList.remove("active"));
      button.classList.add("active");
      $(`#${button.dataset.view}`).classList.add("active");
    });
  });

  $$(".quickMessages button").forEach((button) => {
    button.addEventListener("click", () => {
      $("#messageText").value = button.dataset.message;
    });
  });

  $$(".segment").forEach((button) => {
    button.addEventListener("click", () => loadHandoffs(button.dataset.status));
  });
  $$(".caseFilter").forEach((button) => {
    button.addEventListener("click", () => {
      state.caseStatus = button.dataset.caseStatus;
      $$(".caseFilter").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      renderAdminCases();
    });
  });

  $("#saveConfig").addEventListener("click", saveConfig);
  $("#checkHealth").addEventListener("click", checkHealth);
  $("#refreshCases").addEventListener("click", loadAllAdminCases);
  $("#caseSearch").addEventListener("input", renderAdminCases);
  $("#refreshAll").addEventListener("click", refreshAll);
  $("#clearLog").addEventListener("click", () => {
    $("#eventLog").innerHTML = "";
    setText("metricWebhook", "--");
  });
  $("#duplicateLast").addEventListener("click", () => sendWebhook({ duplicate: true }));
  $("#messageForm").addEventListener("submit", (event) => {
    event.preventDefault();
    sendWebhook();
  });
}

applyConfigToForm();
bindUi();
refreshAll();
