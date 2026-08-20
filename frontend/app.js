const sessionTokenStorageKey = "ceiba.sessionToken";
const legacyAdminTokenStorageKey = "ceiba.adminToken";
const legacyAgentDocumentIdStorageKey = "ceiba.agentDocumentId";
const legacyAgentTokenStorageKey = "ceiba.agentToken";
const currentStatusStorageKey = "ceiba.currentStatus";
const caseStatusStorageKey = "ceiba.caseStatus";
const conversationStateStorageKey = "ceiba.conversationState";
const assignedToMeStorageKey = "ceiba.assignedToMe";
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

function cleanupLegacyAuthStorage() {
  localStorage.removeItem(legacyAgentDocumentIdStorageKey);
  localStorage.removeItem(legacyAdminTokenStorageKey);
  localStorage.removeItem("ceiba.agentName");
  sessionStorage.removeItem(legacyAgentTokenStorageKey);
}

cleanupLegacyAuthStorage();

const state = {
  sessionToken: sessionStorage.getItem(sessionTokenStorageKey) || "",
  documentId: "",
  agent: null,
  metaSecret: sessionStorage.getItem("ceiba.metaSecret") || "",
  currentStatus: localStorage.getItem(currentStatusStorageKey) || "PENDING",
  caseStatus: localStorage.getItem(caseStatusStorageKey) || "ALL",
  conversationState: localStorage.getItem(conversationStateStorageKey) || "",
  assignedToMe: localStorage.getItem(assignedToMeStorageKey) === "true",
  adminCases: [],
  catalogCategories: [],
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

function setEmpty(container, text, className = "emptyState") {
  if (!container) return;
  container.replaceChildren();
  const node = document.createElement("div");
  node.className = className;
  node.textContent = text;
  container.append(node);
}

function sessionHeaders() {
  return state.sessionToken ? { Authorization: `Bearer ${state.sessionToken}` } : {};
}

function operationHeaders() {
  return sessionHeaders();
}

function hasOperationToken() {
  return Boolean(state.sessionToken);
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
  setEmpty(container, "Ingresa con cédula y PIN para cargar conversaciones.");
}

async function requestJson(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "object" && payload !== null ? payload.detail || JSON.stringify(payload) : payload;
    if (response.status === 401 && path !== "/api/admin/login") {
      clearSession();
    }
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return payload;
}

async function loadCatalogCategories() {
  const container = $("#catalogCategoryList");
  if (!hasOperationToken()) {
    setEmpty(container, "Inicia sesión como administrador para gestionar catálogos.");
    return;
  }
  setEmpty(container, "Cargando cobertura de catálogos...");
  try {
    state.catalogCategories = await requestJson("/api/admin/catalogs/categories", {
      headers: sessionHeaders(),
    });
    renderCatalogCategories();
  } catch (error) {
    setEmpty(container, `No se pudo cargar la cobertura: ${error.message}`);
  }
}

function renderCatalogCategories() {
  const container = $("#catalogCategoryList");
  container.replaceChildren();
  for (const category of state.catalogCategories) {
    const card = document.createElement("article");
    card.className = `catalogCategory ${category.covered ? "covered" : "uncovered"}`;

    const header = document.createElement("div");
    header.className = "catalogCategoryHeader";
    const title = document.createElement("strong");
    title.textContent = category.event_type;
    const coverage = document.createElement("span");
    coverage.className = `pill ${category.covered ? "ok" : "bad"}`;
    coverage.textContent = category.covered ? "Con cobertura" : "Sin cobertura";
    header.append(title, coverage);
    card.append(header);

    if (!category.covered) {
      const note = document.createElement("p");
      note.className = "catalogManualNote";
      note.textContent = "Atención manual para solicitudes sin PDF activo.";
      card.append(note);
    }

    const assets = document.createElement("div");
    assets.className = "catalogAssets";
    for (const catalog of category.catalogs) {
      const row = document.createElement("div");
      row.className = "catalogAsset";
      const label = document.createElement("span");
      label.textContent = `${catalog.name} · ${catalog.active ? "Activo" : "Inactivo"}`;
      const toggle = actionButton(
        catalog.active ? "Desactivar" : "Activar",
        () => setCatalogActive(catalog.catalog_asset_id, !catalog.active),
        catalog.active ? "danger" : ""
      );
      row.append(label, toggle);
      assets.append(row);
    }
    if (!category.catalogs.length) {
      const empty = document.createElement("span");
      empty.className = "catalogEmpty";
      empty.textContent = "Sin PDFs mapeados";
      assets.append(empty);
    }
    card.append(assets);
    container.append(card);
  }
}

async function uploadCatalog(event) {
  event.preventDefault();
  const file = $("#catalogFile").files[0];
  if (!file) {
    logEvent("Selecciona un PDF para cargar.");
    return;
  }
  const form = new FormData();
  form.append("name", $("#catalogName").value.trim());
  form.append("event_type", $("#catalogEventType").value);
  form.append("send_mode", $("#catalogSendMode").value);
  form.append("file", file, file.name);
  try {
    await requestJson("/api/admin/catalogs/upload", {
      method: "POST",
      headers: sessionHeaders(),
      body: form,
    });
    $("#catalogUploadForm").reset();
    logEvent("Catálogo cargado y mapeado.");
    await loadCatalogCategories();
  } catch (error) {
    logEvent(`No se pudo subir el catálogo: ${error.message}`);
  }
}

async function setCatalogActive(catalogAssetId, active) {
  try {
    await requestJson(`/api/admin/catalogs/${catalogAssetId}`, {
      method: "PATCH",
      headers: sessionHeaders(),
      body: JSON.stringify({ active }),
    });
    await loadCatalogCategories();
  } catch (error) {
    logEvent(`No se pudo actualizar el catálogo: ${error.message}`);
  }
}

function applyConfigToForm() {
  $("#documentId").value = state.documentId;
  $("#pin").value = "";
  $("#metaSecret").value = state.metaSecret;
  $("#conversationStateFilter").value = state.conversationState;
  $("#assignedToMeFilter").checked = state.assignedToMe;
  $$(".segment").forEach((button) =>
    button.classList.toggle("active", button.dataset.status === state.currentStatus)
  );
  $$(".caseFilter").forEach((button) =>
    button.classList.toggle("active", button.dataset.caseStatus === state.caseStatus)
  );
}

function saveLocalConfig() {
  state.documentId = $("#documentId").value.trim();
  state.metaSecret = $("#metaSecret").value;
  sessionStorage.setItem("ceiba.metaSecret", state.metaSecret);
}

async function resolveAgentIdentity() {
  if (!state.sessionToken) {
    state.agent = null;
    setText("agentState", "Sin asesor");
    setText("agentRoleState", "Sesión requerida");
    return;
  }
  try {
    state.agent = await requestJson("/api/admin/me", { headers: sessionHeaders() });
    setText("agentState", `${state.agent.name}`);
    setText("agentRoleState", state.agent.role);
  } catch (error) {
    state.agent = null;
    setText("agentState", "Sesión inválida");
    setText("agentRoleState", "Sesión requerida");
    logEvent(`Sesión falló: ${error.message}`);
  }
}

async function login() {
  saveLocalConfig();
  const pin = $("#pin").value;
  if (!state.documentId || !pin) {
    logEvent("Cédula y PIN son obligatorios.");
    return;
  }
  try {
    const payload = await requestJson("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({ document_id: state.documentId, pin }),
    });
    state.sessionToken = payload.token;
    state.agent = payload.agent;
    sessionStorage.setItem(sessionTokenStorageKey, state.sessionToken);
    $("#pin").value = "";
    setText("agentState", state.agent.name);
    setText("agentRoleState", state.agent.role);
    logEvent(`Sesión iniciada para ${state.agent.name}.`);
    await refreshAll();
  } catch (error) {
    logEvent(`Login falló: ${error.message}`);
  }
}

function clearSession() {
  state.sessionToken = "";
  state.agent = null;
  sessionStorage.removeItem(sessionTokenStorageKey);
  setText("agentState", "Sin asesor");
  setText("agentRoleState", "Sesión requerida");
}

async function logout() {
  try {
    if (state.sessionToken) {
      await requestJson("/api/admin/logout", { method: "POST", headers: sessionHeaders() });
    }
  } catch (error) {
    logEvent(`Logout falló: ${error.message}`);
  } finally {
    clearSession();
    renderAdminTokenRequired();
  }
}

function persistViewState() {
  localStorage.setItem(currentStatusStorageKey, state.currentStatus);
  localStorage.setItem(caseStatusStorageKey, state.caseStatus);
  localStorage.setItem(conversationStateStorageKey, state.conversationState);
  localStorage.setItem(assignedToMeStorageKey, String(state.assignedToMe));
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
  saveLocalConfig();
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
  persistViewState();
  $$(".segment").forEach((button) => button.classList.toggle("active", button.dataset.status === status));

  const list = $("#handoffList");
  setEmpty(list, `Cargando ${status.toLowerCase()}...`);

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
    setEmpty(list, `No se pudo cargar la bandeja: ${error.message}`);
    return [];
  }
}

async function loadAllAdminCases() {
  if (!hasOperationToken()) {
    renderAdminTokenRequired();
    return;
  }

  try {
    if (state.sessionToken && !state.agent) {
      await resolveAgentIdentity();
    }
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
    setEmpty(container, `No se pudo cargar clientes: ${error.message}`);
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
    assignmentHistory: [],
    createdAt: conversation.last_message_at,
    takenAt: null,
    resolvedAt: null,
    summary: conversation.handoff_summary || conversation.last_message_preview || conversation.last_message_body || "",
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

  container.replaceChildren();
  if (!cases.length) {
    setEmpty(container, "No hay clientes para este filtro con la API actual.");
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
    $(".caseAssignment", row).textContent = assignmentText(item);
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

function assignmentText(item) {
  const history = item.assignmentHistory || [];
  if (!history.length) {
    return item.assignedTo;
  }
  const trail = history
    .map((event) => {
      if (event.action === "HANDOFF_RETURNED") return `${event.actor} devolvió`;
      return `${event.actor} tomó`;
    })
    .join(" · ");
  return `${item.assignedTo}\n${trail}`;
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
  $("#summaryModalTitle").textContent = item.customerName;
  $("#summaryModalMeta").textContent = `${item.phone} · conversación ${item.conversationId}`;
  $("#summaryModalDetails").textContent = [
    `Estado: ${statusLabel(item.handoffStatus, item.status)}`,
    `Asignación: ${item.assignedTo}`,
    `Motivo: ${item.reason}`,
    `Actividad: ${activityText(item)}`,
  ].join("\n");
  $("#summaryModalBody").textContent = item.summary || "Sin resumen disponible.";
  $("#summaryModal").hidden = false;
  loadAssignmentHistory(item.conversationId);
}

async function loadAssignmentHistory(conversationId) {
  try {
    const history = await requestJson(`/api/admin/conversations/${conversationId}/history`, {
      headers: operationHeaders(),
    });
    const lines = history.map((event) => {
      if (event.action === "HANDOFF_RETURNED") return `${event.actor} devolvió`;
      if (event.action === "CONVERSATION_MANUAL_TAKEOVER") return `${event.actor} tomó conversación`;
      return `${event.actor} tomó handoff`;
    });
    $("#summaryModalDetails").textContent += `\nHistorial: ${lines.join(" · ") || "Sin eventos"}`;
  } catch (error) {
    $("#summaryModalDetails").textContent += `\nHistorial: no disponible`;
    logEvent(`Historial falló: ${error.message}`);
  }
}

function closeSummaryModal() {
  $("#summaryModal").hidden = true;
}

function priorityClass(priority) {
  if (priority === "CRITICAL") return "bad";
  if (priority === "URGENT") return "warn";
  return "neutral";
}

function renderHandoffs(handoffs) {
  const list = $("#handoffList");
  list.replaceChildren();
  state.visibleConversationIds = new Set(handoffs.map((handoff) => handoff.conversation_id));
  if (!handoffs.length) {
    setEmpty(list, "No hay handoffs en este estado.");
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
    setEmpty($(".chatThread", node), "Cargando conversación...", "chatEmpty");

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
  saveLocalConfig();
  if (!state.sessionToken) {
    logEvent("Inicia sesión para tomar handoffs.");
    return;
  }
  try {
    const options = {
      method: "POST",
      headers: operationHeaders(),
    };
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
  saveLocalConfig();
  if (!state.sessionToken) {
    logEvent("La toma directa requiere sesión activa.");
    return;
  }
  if (!state.agent) {
    await resolveAgentIdentity();
  }
  if (!state.agent) {
    logEvent("Inicia sesión antes de tomar la conversación.");
    return;
  }
  try {
    const options = {
      method: "POST",
      headers: sessionHeaders(),
    };
    const handoff = await requestJson(`/api/admin/conversations/${conversationId}/take`, {
      ...options,
    });
    logEvent(`Conversación ${conversationId} tomada por ${state.agent.name}.`);
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
      setEmpty(thread, `No se pudo cargar el chat: ${error.message}`, "chatEmpty");
    }
  }
}

function renderChatThread(thread, messages) {
  const wasNearBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 40;
  thread.replaceChildren();
  if (!messages.length) {
    setEmpty(thread, "Sin mensajes en esta conversación.", "chatEmpty");
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
  if (state.agent?.role === "ADMIN") await loadCatalogCategories();
}

function bindUi() {
  $$(".navItem").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".navItem").forEach((item) => item.classList.remove("active"));
      $$(".view").forEach((view) => view.classList.remove("active"));
      button.classList.add("active");
      $(`#${button.dataset.view}`).classList.add("active");
      if (button.dataset.view === "catalogsModule") loadCatalogCategories();
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
      persistViewState();
      $$(".caseFilter").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      renderAdminCases();
    });
  });

  $("#login").addEventListener("click", login);
  $("#logout").addEventListener("click", logout);
  $("#checkHealth").addEventListener("click", checkHealth);
  $("#refreshCases").addEventListener("click", loadAllAdminCases);
  $("#caseSearch").addEventListener("input", renderAdminCases);
  $("#conversationStateFilter").addEventListener("change", (event) => {
    state.conversationState = event.target.value;
    persistViewState();
    loadAllAdminCases();
  });
  $("#assignedToMeFilter").addEventListener("change", (event) => {
    state.assignedToMe = event.target.checked;
    persistViewState();
    loadAllAdminCases();
  });
  $("#refreshAll").addEventListener("click", refreshAll);
  $("#refreshCatalogs").addEventListener("click", loadCatalogCategories);
  $("#catalogUploadForm").addEventListener("submit", uploadCatalog);
  $("#closeSummaryModal").addEventListener("click", closeSummaryModal);
  $("#summaryModal").addEventListener("click", (event) => {
    if (event.target.id === "summaryModal") closeSummaryModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#summaryModal").hidden) closeSummaryModal();
  });
  $("#clearLog").addEventListener("click", () => {
    $("#eventLog").replaceChildren();
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
