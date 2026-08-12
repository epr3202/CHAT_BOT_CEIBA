const adminTokenStorageKey = "ceiba.adminToken";
const agentTokenStorageKey = "ceiba.agentToken";
const agentDocumentIdStorageKey = "ceiba.agentDocumentId";
const directTakeEligibleStates = new Set([
  "BOT_ACTIVE",
  "ANSWERING_INFORMATION",
  "COLLECTING_EVENT_DATA",
  "WAITING_FOR_APPOINTMENT_DATE",
  "WAITING_FOR_APPOINTMENT_SELECTION",
  "APPOINTMENT_PENDING_CONFIRMATION",
  "APPOINTMENT_CONFIRMED",
  "RESOLVED",
]);

function loadAdminToken() {
  const sessionToken = sessionStorage.getItem(adminTokenStorageKey);
  if (sessionToken !== null) {
    return sessionToken;
  }
  const legacyToken = localStorage.getItem(adminTokenStorageKey);
  if (legacyToken !== null) {
    sessionStorage.setItem(adminTokenStorageKey, legacyToken);
    localStorage.removeItem(adminTokenStorageKey);
    return legacyToken;
  }
  return "";
}

function loadAgentDocumentId() {
  const persistentDocumentId = localStorage.getItem(agentDocumentIdStorageKey);
  if (persistentDocumentId !== null) {
    return persistentDocumentId;
  }
  const legacyToken = sessionStorage.getItem(agentTokenStorageKey);
  if (legacyToken !== null) {
    localStorage.setItem(agentDocumentIdStorageKey, legacyToken);
    sessionStorage.removeItem(agentTokenStorageKey);
    return legacyToken;
  }
  return "";
}

const state = {
  adminToken: loadAdminToken(),
  agentDocumentId: loadAgentDocumentId(),
  agent: null,
  metaSecret: sessionStorage.getItem("ceiba.metaSecret") || "",
  currentStatus: "PENDING",
  caseStatus: "ALL",
  conversationState: "",
  assignedToMe: false,
  adminCases: [],
  visibleConversationIds: new Set(),
  chatPollIntervalMs: 3000,
  lastWebhook: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function agentHeaders() {
  return state.agentDocumentId ? { Authorization: `Bearer ${state.agentDocumentId}` } : {};
}

function adminHeaders() {
  return state.adminToken ? { Authorization: `Bearer ${state.adminToken}` } : {};
}

function operationHeaders() {
  return state.agentDocumentId ? agentHeaders() : adminHeaders();
}

function hasOperationToken() {
  return Boolean(state.agentDocumentId || state.adminToken);
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
    container.innerHTML = `<div class="emptyState">Configura y guarda un token para cargar conversaciones.</div>`;
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
  $("#agentDocumentId").value = state.agentDocumentId;
  $("#metaSecret").value = state.metaSecret;
}

function saveConfig() {
  state.adminToken = $("#adminToken").value.trim();
  state.agentDocumentId = $("#agentDocumentId").value.trim();
  state.metaSecret = $("#metaSecret").value;
  sessionStorage.setItem(adminTokenStorageKey, state.adminToken);
  localStorage.setItem(agentDocumentIdStorageKey, state.agentDocumentId);
  sessionStorage.removeItem(agentTokenStorageKey);
  localStorage.removeItem(adminTokenStorageKey);
  localStorage.removeItem("ceiba.agentName");
  sessionStorage.setItem("ceiba.metaSecret", state.metaSecret);
  logEvent("Configuración guardada para esta estación.");
}

async function resolveAgentIdentity() {
  if (!state.agentDocumentId) {
    state.agent = null;
    setText("agentState", "Sin asesor");
    return;
  }
  try {
    state.agent = await requestJson("/api/admin/me", { headers: agentHeaders() });
    setText("agentState", `Asesor: ${state.agent.name}`);
  } catch (error) {
    state.agent = null;
    setText("agentState", "Cédula no registrada");
    logEvent(`Identidad de asesor falló: ${error.message}`);
  }
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
    const hint = error.message === "META_APP_SECRET y texto son obligatorios"
      ? " Exporta META_APP_SECRET antes de arrancar node frontend/server.mjs."
      : "";
    logEvent(`Webhook falló: ${error.message}.${hint}`);
  }
}

async function loadHandoffs(status = state.currentStatus) {
  state.currentStatus = status;
  $$(".segment").forEach((button) => button.classList.toggle("active", button.dataset.status === status));

  const list = $("#handoffList");
  list.innerHTML = `<div class="emptyState">Cargando ${status.toLowerCase()}...</div>`;

  try {
    const handoffs = await requestJson(`/api/admin/handoffs?status=${encodeURIComponent(status)}`, {
      headers: operationHeaders(),
    });
    renderHandoffs(handoffs);
    await refreshVisibleHandoffMessages();
    if (status === "PENDING") setText("metricPending", String(handoffs.length));
    if (status === "TAKEN") setText("metricTaken", String(handoffs.length));
    return handoffs;
  } catch (error) {
    list.innerHTML = `<div class="emptyState">No se pudo cargar la bandeja: ${error.message}</div>`;
    return [];
  }
}

async function loadAllAdminCases() {
  if (!hasOperationToken()) {
    renderAdminTokenRequired();
    return;
  }

  try {
    const params = new URLSearchParams({ limit: "200", offset: "0" });
    if (state.conversationState) params.set("state", state.conversationState);
    if (state.assignedToMe) params.set("assigned_to_me", "true");
    const conversations = await requestJson(`/api/admin/conversations?${params.toString()}`, {
      headers: operationHeaders(),
    });
    state.adminCases = conversations.map(caseFromConversation);
    setText("metricPending", String(state.adminCases.filter((item) => item.handoffStatus === "PENDING").length));
    setText("metricTaken", String(state.adminCases.filter((item) => item.handoffStatus === "TAKEN").length));
    setText("metricReturned", String(state.adminCases.filter((item) => item.handoffStatus === "RETURNED").length));
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

function caseFromHandoff(handoff) {
  const parsed = parseSummary(handoff.summary || "");
  return {
    id: handoff.id,
    conversationId: handoff.conversation_id,
    status: handoff.status,
    priority: handoff.priority,
    reason: parsed.motivo || handoff.reason,
    customerName: handoff.customer_name || parsed.cliente || "Cliente sin nombre confirmado",
    phone: handoff.customer_phone || parsed.telefono || "Teléfono no disponible",
    assignedTo: handoff.assigned_to || "Sin asignar",
    createdAt: handoff.created_at,
    takenAt: handoff.taken_at,
    resolvedAt: handoff.resolved_at,
    summary: handoff.summary || "",
  };
}

function caseFromConversation(conversation) {
  const handoffStatus = conversation.handoff_status || "SIN_HANDOFF";
  const assignedAgent = conversation.assigned_agent?.name || conversation.assigned_to;
  return {
    id: conversation.handoff_id,
    conversationId: conversation.id || conversation.conversation_id,
    status: conversation.state,
    handoffStatus,
    priority: conversation.handoff_priority || "NORMAL",
    reason: conversation.handoff_reason || conversation.last_intent || "Sin clasificar",
    customerName: conversation.customer_name || "Cliente sin nombre confirmado",
    phone: conversation.customer_phone || "Teléfono no disponible",
    assignedTo: assignedAgent || (conversation.bot_enabled ? "Bot activo" : "Sin asignar"),
    createdAt: conversation.last_message_at,
    takenAt: null,
    resolvedAt: null,
    summary: conversation.last_message_preview || conversation.last_message_body || "",
    lastMessageDirection: conversation.last_message_direction,
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
    const statusMatches = state.caseStatus === "ALL" || item.handoffStatus === state.caseStatus;
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
    status.className = `caseStatus pill ${statusClass(item.handoffStatus)}`;
    status.textContent = statusLabel(item.handoffStatus, item.status);
    $(".caseAssignment", row).textContent = item.assignedTo;
    $(".caseReason", row).textContent = item.reason;
    $(".caseActivity", row).textContent = activityText(item);
    const actions = $(".caseActions", row);
    if (directTakeEligibleStates.has(item.status)) {
      actions.append(actionButton("Tomar conversación", () => takeConversation(item.conversationId), "primary"));
    } else if (item.status === "WAITING_FOR_HUMAN" && item.handoffStatus === "PENDING" && item.id !== null) {
      actions.append(actionButton("Tomar handoff", () => takeHandoff(item.id), "primary"));
    }
    if (item.handoffStatus === "TAKEN" && item.id !== null) {
      actions.append(actionButton("Responder", () => openHandoffAndFocus(item.id)));
      actions.append(actionButton("Devolver", () => returnHandoff(item.id), "danger"));
    } else if (item.id !== null) {
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

function statusLabel(status, conversationState = null) {
  return {
    PENDING: "Pendiente",
    TAKEN: "Asignado",
    RETURNED: "Devuelto",
    RESOLVED: "Resuelto",
    SIN_HANDOFF: conversationState || "Sin handoff",
  }[status] || status;
}

function activityText(item) {
  const timestamp = item.resolvedAt || item.takenAt || item.createdAt;
  if (!timestamp) return "Sin fecha";
  const label = item.resolvedAt ? "Devuelto" : item.takenAt ? "Tomado" : "Creado";
  if (item.lastMessageDirection) {
    return `${item.lastMessageDirection} · ${new Date(timestamp).toLocaleString("es-CO", { hour12: false })}`;
  }
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
  logEvent(item.summary ? `Resumen conversación ${item.conversationId}: ${item.summary}` : "Sin resumen disponible.");
}

function priorityClass(priority) {
  if (priority === "CRITICAL") return "bad";
  if (priority === "URGENT") return "warn";
  return "neutral";
}

function renderHandoffs(handoffs) {
  const list = $("#handoffList");
  list.innerHTML = "";
  state.visibleConversationIds = new Set(handoffs.map((handoff) => handoff.conversation_id));
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
    $(".chatThread", node).dataset.conversationId = String(handoff.conversation_id);
    $(".chatThread", node).innerHTML = `<div class="chatEmpty">Cargando conversación...</div>`;

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
  if (!state.agentDocumentId && !state.adminToken) {
    logEvent("Configura un token para tomar handoffs.");
    return;
  }
  try {
    const options = {
      method: "POST",
      headers: operationHeaders(),
    };
    if (!state.agentDocumentId && state.adminToken) {
      options.body = JSON.stringify({ agent: "ADMIN" });
    }
    await requestJson(`/api/admin/handoffs/${handoffId}/take`, {
      ...options,
    });
    logEvent(`Handoff ${handoffId} tomado.`);
    await refreshAll();
    await loadHandoffs("TAKEN");
  } catch (error) {
    logEvent(`No se pudo tomar el handoff: ${error.message}`);
  }
}

async function takeConversation(conversationId) {
  saveConfig();
  if (!state.agentDocumentId) {
    logEvent("La toma directa requiere cédula de agente.");
    return;
  }
  try {
    const handoff = await requestJson(`/api/admin/conversations/${conversationId}/take`, {
      method: "POST",
      headers: agentHeaders(),
    });
    logEvent(`Conversación ${conversationId} tomada por ${state.agent?.name || "asesor"}.`);
    await refreshAll();
    await loadHandoffs("TAKEN");
    openHandoffAndFocus(handoff.id);
  } catch (error) {
    logEvent(`No se pudo tomar la conversación: ${error.message}`);
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
      headers: operationHeaders(),
      body: JSON.stringify({ text }),
    });
    logEvent(`Respuesta encolada para conversación ${conversationId}.`);
    await refreshAll();
    await refreshConversationMessages(conversationId);
  } catch (error) {
    logEvent(`No se pudo enviar la respuesta: ${error.message}`);
  }
}

async function refreshVisibleHandoffMessages() {
  if (!hasOperationToken() || state.visibleConversationIds.size === 0) return;
  await Promise.all(
    Array.from(state.visibleConversationIds).map((conversationId) =>
      refreshConversationMessages(conversationId)
    )
  );
}

async function refreshConversationMessages(conversationId) {
  const threads = $$(`.chatThread[data-conversation-id="${conversationId}"]`);
  if (!threads.length) return;

  try {
    const messages = await requestJson(`/api/admin/conversations/${conversationId}/messages`, {
      headers: operationHeaders(),
    });
    for (const thread of threads) {
      renderChatThread(thread, messages);
    }
  } catch (error) {
    for (const thread of threads) {
      thread.innerHTML = `<div class="chatEmpty">No se pudo cargar el chat: ${error.message}</div>`;
    }
  }
}

function renderChatThread(thread, messages) {
  const wasNearBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 40;
  thread.innerHTML = "";
  if (!messages.length) {
    thread.innerHTML = `<div class="chatEmpty">Sin mensajes en esta conversación.</div>`;
    return;
  }

  for (const message of messages) {
    const bubble = document.createElement("div");
    bubble.className = `chatBubble ${message.direction === "OUTBOUND" ? "outbound" : "inbound"}`;

    const body = document.createElement("div");
    body.className = "chatBody";
    body.textContent = message.body;
    bubble.append(body);

    const meta = document.createElement("div");
    meta.className = "chatMeta";
    meta.textContent = chatMetaText(message);
    bubble.append(meta);

    thread.append(bubble);
  }

  if (wasNearBottom) {
    thread.scrollTop = thread.scrollHeight;
  }
}

function chatMetaText(message) {
  const timestamp = message.created_at
    ? new Date(message.created_at).toLocaleTimeString("es-CO", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "";
  const status = message.status ? ` · ${message.status.toLowerCase()}` : "";
  return `${timestamp}${status}`;
}

async function returnHandoff(handoffId) {
  const resolution = "Cliente atendido y devuelto al bot.";
  try {
    await requestJson(`/api/admin/handoffs/${handoffId}/return`, {
      method: "POST",
      headers: operationHeaders(),
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
  await resolveAgentIdentity();
  if (!hasOperationToken()) {
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
  $("#conversationStateFilter").addEventListener("change", (event) => {
    state.conversationState = event.target.value;
    loadAllAdminCases();
  });
  $("#assignedToMeFilter").addEventListener("change", (event) => {
    state.assignedToMe = event.target.checked;
    loadAllAdminCases();
  });
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
setInterval(refreshVisibleHandoffMessages, state.chatPollIntervalMs);
