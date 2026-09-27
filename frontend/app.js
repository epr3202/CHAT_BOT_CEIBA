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
  currentView: localStorage.getItem("ceiba.currentView") || "admin",
  environment: null,
  metaSecret: sessionStorage.getItem("ceiba.metaSecret") || "",
  currentStatus: localStorage.getItem(currentStatusStorageKey) || "PENDING",
  caseStatus: localStorage.getItem(caseStatusStorageKey) || "ALL",
  conversationState: localStorage.getItem(conversationStateStorageKey) || "",
  assignedToMe: localStorage.getItem(assignedToMeStorageKey) === "true",
  adminCases: [],
  catalogCategories: [],
  unassignedCatalogs: [],
  catalogEditor: null,
  paymentEvidence: [],
  agents: [],
  resetPreview: null,
  resetBusy: false,
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

function simulationVisible() {
  return ["development", "testing"].includes(state.environment);
}

function applyAuthState() {
  try {
    renderAuthState();
    const banner = $("#authError");
    if (banner) banner.hidden = true;
  } catch (error) {
    let banner = $("#authError");
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "authError";
      banner.className = "panel formError";
      banner.setAttribute("role", "alert");
      document.body.prepend(banner);
    }
    banner.textContent = `No se pudo mostrar el panel: ${error.message || String(error)}`;
    banner.hidden = false;
    console.error("No se pudo mostrar el panel", error);
  }
}

function renderAuthState() {
  const authenticated = Boolean(state.sessionToken && state.agent);
  document.body.classList.toggle("loggedOut", !authenticated);
  $(".nav").hidden = !authenticated;
  $(".topbar").hidden = !authenticated;
  $$(".navItem").forEach((button) => {
    button.hidden = !authenticated
      || (button.dataset.adminOnly === "true" && state.agent?.role !== "ADMIN")
      || (button.dataset.view === "simulator" && !simulationVisible());
  });
  const selected = $$(".navItem").find((button) =>
    button.dataset.view === state.currentView && !button.hidden
  );
  if (authenticated && !selected) state.currentView = "admin";
  $$(".view").forEach((view) => {
    const visible = authenticated ? view.id === state.currentView : view.id === "loginView";
    view.hidden = !visible;
    view.classList.toggle("active", visible);
  });
  $$(".navItem").forEach((button) =>
    button.classList.toggle("active", authenticated && button.dataset.view === state.currentView)
  );
}

function selectView(view) {
  const button = $$(".navItem").find((item) => item.dataset.view === view);
  if (!state.agent || !state.sessionToken || !button || button.hidden) return;
  state.currentView = view;
  localStorage.setItem("ceiba.currentView", view);
  applyAuthState();
  if (view === "catalogsModule") loadCatalogCategories();
  if (view === "paymentEvidence") loadPaymentEvidence();
  if (view === "agents") loadAgents();
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
    let detail = typeof payload === "object" && payload !== null ? payload.detail || JSON.stringify(payload) : payload;
    if (Array.isArray(detail)) detail = detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
    if (detail && typeof detail === "object") detail = JSON.stringify(detail);
    if (response.status === 401) {
      clearSession();
      applyAuthState();
    }
    const error = new Error(detail || `HTTP ${response.status}`);
    error.status = response.status;
    error.retryAfter = response.headers.get("Retry-After");
    throw error;
  }
  return payload;
}

async function loadPaymentEvidence() {
  const container = $("#paymentEvidenceList");
  if (state.agent?.role !== "ADMIN") {
    setEmpty(container, "Inicia sesion como administrador para revisar comprobantes.");
    return;
  }
  setEmpty(container, "Cargando comprobantes...");
  try {
    state.paymentEvidence = await requestJson("/api/admin/payment-evidence", {
      headers: sessionHeaders(),
    });
    renderPaymentEvidence();
  } catch (error) {
    setEmpty(container, `No se pudieron cargar los comprobantes: ${error.message}`);
  }
}

function renderPaymentEvidence() {
  const container = $("#paymentEvidenceList");
  container.replaceChildren();
  if (!state.paymentEvidence.length) {
    setEmpty(container, "No hay comprobantes pendientes de revision.");
    return;
  }
  for (const evidence of state.paymentEvidence) {
    const card = document.createElement("article");
    card.className = "paymentEvidenceCard";
    const details = document.createElement("div");
    details.className = "paymentEvidenceDetails";
    const title = document.createElement("strong");
    title.textContent = evidence.customer_name || evidence.customer_phone;
    const meta = document.createElement("span");
    meta.textContent = `Evidencia #${evidence.id} · Conversacion ${evidence.conversation_id} · ${evidence.mime_type}`;
    const downloadStatus = document.createElement("span");
    downloadStatus.className = "pill neutral";
    downloadStatus.textContent = evidence.download_status;
    details.append(title, meta, downloadStatus);

    const note = document.createElement("textarea");
    note.rows = 2;
    note.maxLength = 500;
    note.placeholder = "Nota de revision para auditoria";
    const actions = document.createElement("div");
    actions.className = "actions";
    if (evidence.download_status === "DOWNLOADED") {
      actions.append(actionButton("Descargar", () => downloadPaymentEvidence(evidence.id)));
    }
    actions.append(
      actionButton("Aceptar", () => reviewPaymentEvidence(evidence.id, "accept", note.value), "primary"),
      actionButton("Rechazar", () => reviewPaymentEvidence(evidence.id, "reject", note.value), "danger"),
    );
    card.append(details, note, actions);
    container.append(card);
  }
}

async function downloadPaymentEvidence(evidenceId) {
  try {
    const response = await fetch(`/api/admin/payment-evidence/${evidenceId}/download`, {
      headers: sessionHeaders(),
    });
    if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
    const blobUrl = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = `comprobante-${evidenceId}`;
    link.click();
    URL.revokeObjectURL(blobUrl);
  } catch (error) {
    logEvent(`No se pudo descargar el comprobante: ${error.message}`);
  }
}

async function reviewPaymentEvidence(evidenceId, decision, note) {
  if (!note.trim()) {
    logEvent("Escribe una nota antes de revisar el comprobante.");
    return;
  }
  try {
    const result = await requestJson(`/api/admin/payment-evidence/${evidenceId}/${decision}`, {
      method: "POST",
      headers: sessionHeaders(),
      body: JSON.stringify({ note: note.trim() }),
    });
    const notification = result.customer_notification === "ENQUEUED"
      ? "mensaje al cliente encolado"
      : "notificacion al cliente diferida";
    logEvent(`Evidencia #${evidenceId} revisada: ${notification}.`);
    await loadPaymentEvidence();
  } catch (error) {
    logEvent(`No se pudo revisar el comprobante: ${error.message}`);
  }
}

async function loadCatalogCategories() {
  const container = $("#catalogCategoryList");
  if (!hasOperationToken()) {
    setEmpty(container, "Inicia sesión como administrador para gestionar catálogos.");
    return;
  }
  setEmpty(container, "Cargando cobertura de catálogos...");
  try {
    const [categories, catalogs] = await Promise.all([
      requestJson("/api/admin/catalogs/categories", { headers: sessionHeaders() }),
      requestJson("/api/admin/catalogs", { headers: sessionHeaders() }),
    ]);
    state.catalogCategories = categories;
    state.unassignedCatalogs = catalogs.filter((catalog) => !catalog.event_type_mappings.length);
    renderCatalogCategories();
  } catch (error) {
    setEmpty(container, `No se pudo cargar la cobertura: ${error.message}`);
  }
}

function renderCatalogCategories() {
  const container = $("#catalogCategoryList");
  container.replaceChildren();
  const categories = [...state.catalogCategories];
  if (state.unassignedCatalogs.length) {
    categories.push({ event_type: null, catalogs: state.unassignedCatalogs });
  }
  for (const category of categories) {
    const card = document.createElement("article");
    card.className = `catalogCategory ${category.covered ? "covered" : "uncovered"}`;

    const header = document.createElement("div");
    header.className = "catalogCategoryHeader";
    const title = document.createElement("strong");
    title.textContent = category.event_type ? catalogEventTypeLabel(category.event_type) : "Sin asignaciones";
    const coverage = document.createElement("span");
    coverage.className = `pill ${category.covered ? "ok" : "bad"}`;
    coverage.textContent = category.covered ? "Con cobertura" : "Sin cobertura";
    header.append(title);
    if (category.event_type) header.append(coverage);
    card.append(header);

    if (category.event_type && !category.covered) {
      const note = document.createElement("p");
      note.className = "catalogManualNote";
      note.textContent = "Atención manual para solicitudes sin PDF activo.";
      card.append(note);
    }

    const assets = document.createElement("div");
    assets.className = "catalogAssets";
    for (const catalog of category.catalogs) {
      assets.append(renderCatalogAsset(catalog, category.event_type));
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

function catalogEventTypeLabel(eventType) {
  return Array.from($("#catalogEventType").options).find((option) => option.value === eventType)?.label
    || "Tipo de evento no reconocido";
}

const catalogSendModes = {
  ON_REQUEST: { label: "A solicitud", explanation: "solo si el cliente pide el catálogo" },
  PROACTIVE: { label: "Proactivo", explanation: "se envía solo al detectar el evento" },
};

function renderCatalogAsset(catalog, category) {
  const row = document.createElement("div");
  row.className = "catalogAsset";
  row.dataset.catalogId = catalog.catalog_asset_id;
  const heading = document.createElement("div");
  heading.className = "catalogAssetHeading";
  const name = document.createElement("strong");
  name.textContent = catalog.name;
  const status = document.createElement("span");
  status.className = `pill ${catalog.active ? "ok" : "neutral"}`;
  status.textContent = catalog.active ? "Activo" : "Inactivo";
  heading.append(name, status);

  const summary = document.createElement("ul");
  summary.className = "catalogMappingSummary";
  for (const mapping of catalog.event_type_mappings) {
    const item = document.createElement("li");
    item.textContent = `${catalogEventTypeLabel(mapping.event_type)} · ${catalogSendModes[mapping.send_mode]?.label || "Modo no reconocido"}`;
    summary.append(item);
  }
  if (!catalog.event_type_mappings.length) {
    const empty = document.createElement("li");
    empty.textContent = "Sin asignaciones";
    summary.append(empty);
  }
  const actions = document.createElement("div");
  actions.className = "catalogAssetActions";
  const key = `${category || "unassigned"}:${catalog.catalog_asset_id}`;
  const editing = state.catalogEditor?.key === key;
  const edit = actionButton("Editar asignaciones", () => {
    state.catalogEditor = {
      key, catalogAssetId: catalog.catalog_asset_id,
      mappings: catalog.event_type_mappings.map((mapping) => ({ ...mapping })),
      saving: false, error: "",
    };
    renderCatalogCategories();
    $(".catalogMappingEditor select")?.focus();
  });
  edit.setAttribute("aria-expanded", String(editing));
  edit.disabled = Boolean(state.catalogEditor);
  const toggle = actionButton(
    catalog.active ? "Desactivar" : "Activar",
    () => setCatalogActive(catalog.catalog_asset_id, !catalog.active),
    catalog.active ? "danger" : ""
  );
  toggle.disabled = Boolean(state.catalogEditor?.saving);
  actions.append(edit, toggle);
  row.append(heading, summary, actions);
  if (editing) row.append(renderCatalogMappingEditor(catalog));
  return row;
}

function renderCatalogMappingEditor(catalog) {
  const editor = state.catalogEditor;
  const form = document.createElement("form");
  form.className = "catalogMappingEditor";
  form.setAttribute("aria-label", `Asignaciones de ${catalog.name}`);
  form.addEventListener("submit", saveCatalogMappings);
  const fields = document.createElement("fieldset");
  fields.disabled = editor.saving;
  const legend = document.createElement("legend");
  legend.textContent = "Asignaciones del catálogo";
  fields.append(legend);
  const eventOptions = Array.from($("#catalogEventType").options);
  editor.mappings.forEach((mapping, index) => {
    const row = document.createElement("div");
    row.className = "catalogMappingRow";
    const eventLabel = document.createElement("label");
    eventLabel.textContent = "Tipo de evento";
    const eventSelect = document.createElement("select");
    eventSelect.setAttribute("aria-label", "Tipo de evento");
    eventSelect.required = true;
    eventOptions.forEach((option) => eventSelect.add(new Option(option.label, option.value)));
    eventSelect.value = mapping.event_type;
    eventSelect.addEventListener("change", () => { mapping.event_type = eventSelect.value; });
    eventLabel.append(eventSelect);
    const remove = actionButton("Quitar fila", () => {
      editor.mappings.splice(index, 1);
      renderCatalogCategories();
      $(".catalogMappingEditor select")?.focus();
    });
    const modeLabel = document.createElement("label");
    modeLabel.className = "catalogMappingMode";
    modeLabel.textContent = "Modo de envío";
    const modeSelect = document.createElement("select");
    modeSelect.setAttribute("aria-label", "Modo de envío");
    for (const [value, mode] of Object.entries(catalogSendModes)) {
      modeSelect.add(new Option(`${mode.label} (${mode.explanation})`, value));
    }
    modeSelect.value = mapping.send_mode;
    const help = document.createElement("small");
    help.className = "catalogModeHelp";
    help.textContent = catalogSendModes[mapping.send_mode]?.explanation || "Selecciona un modo de envío.";
    modeSelect.addEventListener("change", () => {
      mapping.send_mode = modeSelect.value;
      help.textContent = catalogSendModes[mapping.send_mode].explanation;
    });
    modeLabel.append(modeSelect);
    row.append(eventLabel, remove, modeLabel, help);
    fields.append(row);
  });
  if (!editor.mappings.length) {
    const empty = document.createElement("p");
    empty.className = "catalogEmpty";
    empty.textContent = "Sin asignaciones. Añade una fila para elegir el tipo de evento.";
    fields.append(empty);
  }
  const add = actionButton("Añadir fila", () => {
    const available = eventOptions.find((option) => !editor.mappings.some((mapping) => mapping.event_type === option.value));
    if (!available) return;
    editor.mappings.push({ event_type: available.value, send_mode: "ON_REQUEST" });
    renderCatalogCategories();
    $$(".catalogMappingEditor .catalogMappingRow").at(-1)?.querySelector("select")?.focus();
  });
  add.disabled = editor.mappings.length >= eventOptions.length;
  const error = document.createElement("p");
  error.className = "formError";
  error.setAttribute("role", "alert");
  error.textContent = editor.error;
  error.hidden = !editor.error;
  const actions = document.createElement("div");
  actions.className = "catalogAssetActions";
  const save = document.createElement("button");
  save.type = "submit";
  save.className = "primary";
  save.textContent = editor.saving ? "Guardando…" : "Guardar";
  const cancel = actionButton("Cancelar", () => {
    state.catalogEditor = null;
    renderCatalogCategories();
  });
  actions.append(save, cancel);
  fields.append(add, error, actions);
  form.append(fields);
  return form;
}

async function saveCatalogMappings(event) {
  event.preventDefault();
  const editor = state.catalogEditor;
  if (!editor || editor.saving) return;
  editor.error = "";
  if (new Set(editor.mappings.map((mapping) => mapping.event_type)).size !== editor.mappings.length) {
    editor.error = "Cada tipo de evento solo puede asignarse una vez.";
    renderCatalogCategories();
    return;
  }
  editor.saving = true;
  renderCatalogCategories();
  try {
    await requestJson(`/api/admin/catalogs/${editor.catalogAssetId}/event-types`, {
      method: "PUT", headers: sessionHeaders(),
      body: JSON.stringify({ event_types: editor.mappings }),
    });
    if (state.catalogEditor !== editor) return;
    state.catalogEditor = null;
    await loadCatalogCategories();
    logEvent("Asignaciones del catálogo guardadas.");
  } catch (error) {
    if (state.catalogEditor !== editor) return;
    editor.saving = false;
    editor.error = error.message;
    renderCatalogCategories();
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
    clearSession();
    setText("agentState", "Sesión inválida");
    setText("agentRoleState", "Sesión requerida");
    applyAuthState();
    logEvent(`Sesión falló: ${error.message}`);
  }
}

async function login() {
  saveLocalConfig();
  const pin = $("#pin").value;
  if (!state.documentId || !pin) {
    setText("loginError", "Documento y PIN son obligatorios.");
    return;
  }
  $("#login").disabled = true;
  setText("loginError", "");
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
    applyAuthState();
    logEvent(`Sesión iniciada para ${state.agent.name}.`);
    await refreshAll();
  } catch (error) {
    const seconds = Number(error.retryAfter);
    const retry = error.status === 429
      ? (seconds > 0 ? ` Reintenta en ${Math.ceil(seconds / 60)} min.` : " Reintenta más tarde.")
      : "";
    setText("loginError", `${error.message}${retry}`);
  } finally {
    $("#login").disabled = false;
  }
}

function clearSession() {
  state.sessionToken = "";
  state.agent = null;
  sessionStorage.removeItem(sessionTokenStorageKey);
  state.adminCases = [];
  state.paymentEvidence = [];
  state.catalogCategories = [];
  state.unassignedCatalogs = [];
  state.catalogEditor = null;
  state.agents = [];
  $("#agentRows").replaceChildren();
  $("#agentEditForm").hidden = true;
  $("#agentCredentialsForm").hidden = true;
  $("#agentCredentialsForm").reset();
  $("#resetExecuteForm").reset();
  invalidateResetPreview();
  state.visibleConversationIds.clear();
  $("#pin").value = "";
  closeSummaryModal();
  for (const id of ["caseList", "handoffList", "paymentEvidenceList", "catalogCategoryList"]) {
    document.getElementById(id)?.replaceChildren();
  }
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
    applyAuthState();
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
    state.environment = data.environment || null;
    applyAuthState();
    setApiState("ok", data.status === "ok" ? "API ok" : "API responde");
  } catch (error) {
    state.environment = null;
    applyAuthState();
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
  applyAuthState();
  if (!hasOperationToken()) {
    renderAdminTokenRequired();
    return;
  }
  await loadAllAdminCases();
  await loadHandoffs(state.currentStatus);
  if (state.agent?.role === "ADMIN") {
    await Promise.all([loadCatalogCategories(), loadPaymentEvidence()]);
    if (state.currentView === "agents") await loadAgents();
  }
}

function feedback(id, message, error = false) {
  const node = document.getElementById(id);
  node.textContent = message;
  node.classList.toggle("formError", error);
}

async function loadAgents() {
  if (state.agent?.role !== "ADMIN") return;
  try {
    state.agents = await requestJson("/api/admin/agents", { headers: sessionHeaders() });
    renderAgents();
  } catch (error) {
    feedback("agentsFeedback", error.message, true);
  }
}

function renderAgents() {
  const body = $("#agentRows");
  body.replaceChildren();
  const filter = $("#agentStatusFilter").value;
  const agents = state.agents.filter((agent) =>
    filter === "all" || agent.active === (filter === "active")
  );
  for (const agent of agents) {
    const row = document.createElement("tr");
    row.dataset.agentId = agent.id;
    for (const value of [agent.name, agent.role,
      agent.has_credentials ? agent.document_id : "sin credenciales",
      agent.active ? "Activo" : "Inactivo", new Date(agent.created_at).toLocaleString("es-CO")]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const cell = document.createElement("td");
    const actions = document.createElement("div");
    actions.className = "actions";
    actions.append(
      actionButton("Editar", () => editAgent(agent)),
      actionButton("Credenciales", () => editAgentCredentials(agent)),
      actionButton(agent.active ? "Desactivar" : "Activar", (event) =>
        toggleAgentActive(agent, event.currentTarget), agent.active ? "danger" : ""),
    );
    cell.append(actions);
    row.append(cell);
    body.append(row);
  }
  if (!agents.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.textContent = "No hay agentes con este filtro.";
    row.append(cell);
    body.append(row);
  }
}

async function createAgent(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('[type="submit"]');
  if (button.disabled) return;
  button.disabled = true;
  try {
    const agent = await requestJson("/api/admin/agents", {
      method: "POST", headers: sessionHeaders(),
      body: JSON.stringify({ name: $("#agentCreateName").value.trim(), role: $("#agentCreateRole").value }),
    });
    form.reset();
    $("#agentStatusFilter").value = "active";
    await loadAgents();
    feedback("agentsFeedback", `Agente ${agent.name} creado. Asigna sus credenciales para permitir el ingreso.`);
  } catch (error) {
    feedback("agentsFeedback", error.message, true);
  } finally {
    button.disabled = false;
  }
}

function editAgent(agent) {
  const form = $("#agentEditForm");
  form.dataset.agentId = agent.id;
  $("#agentEditName").value = agent.name;
  $("#agentEditRole").value = agent.role;
  setText("agentEditTitle", `Editar: ${agent.name}`);
  form.hidden = false;
  $("#agentCredentialsForm").hidden = true;
  form.scrollIntoView({ block: "center" });
  $("#agentEditName").focus();
}

async function saveAgent(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('[type="submit"]');
  if (button.disabled) return;
  button.disabled = true;
  try {
    const agent = await requestJson(`/api/admin/agents/${form.dataset.agentId}`, {
      method: "PATCH", headers: sessionHeaders(),
      body: JSON.stringify({ name: $("#agentEditName").value.trim(), role: $("#agentEditRole").value }),
    });
    form.hidden = true;
    await resolveAgentIdentity();
    applyAuthState();
    await loadAgents();
    feedback("agentsFeedback", `Agente ${agent.name} actualizado.`);
  } catch (error) {
    feedback("agentsFeedback", error.message, true);
  } finally {
    button.disabled = false;
  }
}

function editAgentCredentials(agent) {
  const form = $("#agentCredentialsForm");
  form.reset();
  form.dataset.agentId = agent.id;
  $("#agentDocument").value = agent.document_id || "";
  setText("agentCredentialsTitle", `Credenciales: ${agent.name}`);
  form.hidden = false;
  $("#agentEditForm").hidden = true;
  form.scrollIntoView({ block: "center" });
  $("#agentDocument").focus();
}

async function saveAgentCredentials(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('[type="submit"]');
  if (button.disabled) return;
  if (!confirm("¿Guardar las credenciales? Esto cierra las sesiones del agente.")) return;
  button.disabled = true;
  try {
    await requestJson(`/api/admin/agents/${form.dataset.agentId}/credentials`, {
      method: "POST", headers: sessionHeaders(),
      body: JSON.stringify({ document_id: $("#agentDocument").value.trim(), pin: $("#agentPin").value }),
    });
    form.reset();
    form.hidden = true;
    await resolveAgentIdentity();
    applyAuthState();
    await loadAgents();
    feedback("agentsFeedback", "Credenciales guardadas; las sesiones anteriores se cerraron.");
  } catch (error) {
    feedback("agentsFeedback", error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function toggleAgentActive(agent, button) {
  if (button.disabled) return;
  const action = agent.active ? "deactivate" : "activate";
  if (!confirm(`¿${agent.active ? "Desactivar" : "Activar"} a ${agent.name}?`)) return;
  button.disabled = true;
  try {
    await requestJson(`/api/admin/agents/${agent.id}/${action}`, { method: "POST", headers: sessionHeaders() });
    await resolveAgentIdentity();
    applyAuthState();
    await loadAgents();
    feedback("agentsFeedback", `${agent.name}: ${agent.active ? "desactivado" : "activado"}.`);
  } catch (error) {
    feedback("agentsFeedback", error.message, true);
  } finally {
    button.disabled = false;
  }
}

function updateResetAvailability() {
  const preview = state.resetPreview;
  $("#executeReset").disabled = state.resetBusy || !preview
    || $("#resetPhone").value.trim() !== preview.input
    || !$("#resetReason").value.trim()
    || $("#resetConfirmPhone").value.trim() !== preview.phone_number;
}

function invalidateResetPreview() {
  state.resetPreview = null;
  $("#resetSummary").replaceChildren();
  setText("resetRequestId", "");
  setText("resetFeedback", "");
  $("#resetConfirmPhone").value = "";
  updateResetAvailability();
}

function renderResetSummary(summary) {
  const container = $("#resetSummary");
  container.replaceChildren();
  const title = document.createElement("p");
  title.textContent = `${summary.dry_run ? "Previsualización" : "Reinicio completado"}: ${summary.phone_number}`;
  const list = document.createElement("dl");
  list.className = "resetCounts";
  const fields = {
    conversations_found: "Conversaciones encontradas",
    conversations_closed: summary.dry_run ? "Conversaciones por cerrar" : "Conversaciones cerradas",
    handoffs_resolved: summary.dry_run ? "Casos por resolver" : "Casos resueltos",
    inbox_jobs_completed: summary.dry_run ? "Tareas de entrada por retirar" : "Tareas de entrada retiradas",
    pending_outbox_suppressed: "Salidas pendientes sujetas al bloqueo",
    customer_name_cleared: summary.dry_run ? "Se limpiará el nombre" : "Nombre limpiado",
  };
  for (const [key, label] of Object.entries(fields)) {
    const term = document.createElement("dt"); term.textContent = label;
    const value = document.createElement("dd");
    value.textContent = typeof summary[key] === "boolean" ? (summary[key] ? "Sí" : "No") : summary[key];
    list.append(term, value);
  }
  container.append(title, list);
  setText("resetRequestId", `request_id: ${summary.request_id}`);
}

async function previewReset(event) {
  event.preventDefault();
  if (state.resetBusy) return;
  invalidateResetPreview();
  state.resetBusy = true;
  $("#previewReset").disabled = true;
  const input = $("#resetPhone").value.trim();
  try {
    const summary = await requestJson("/api/admin/conversations/reset", {
      method: "POST", headers: sessionHeaders(), body: JSON.stringify({ phone_number: input, dry_run: true }),
    });
    if ($("#resetPhone").value.trim() !== input || state.agent?.role !== "ADMIN") return;
    state.resetPreview = { ...summary, input };
    renderResetSummary(summary);
    feedback("resetFeedback", summary.customer_id === null ? "No existe un cliente con ese teléfono." : "Revisa los conteos, escribe el motivo y confirma el teléfono.");
  } catch (error) {
    feedback("resetFeedback", error.message, true);
  } finally {
    state.resetBusy = false;
    $("#previewReset").disabled = false;
    updateResetAvailability();
  }
}

async function executeReset(event) {
  event.preventDefault();
  updateResetAvailability();
  if ($("#executeReset").disabled) return;
  const phone = state.resetPreview.phone_number;
  state.resetBusy = true;
  $("#previewReset").disabled = true;
  updateResetAvailability();
  try {
    const summary = await requestJson("/api/admin/conversations/reset", {
      method: "POST", headers: sessionHeaders(),
      body: JSON.stringify({ phone_number: phone, dry_run: false, reason: $("#resetReason").value.trim() }),
    });
    state.resetPreview = null;
    renderResetSummary(summary);
    feedback("resetFeedback", "Reinicio completado. El historial se conserva.");
  } catch (error) {
    feedback("resetFeedback", error.message, true);
  } finally {
    state.resetBusy = false;
    $("#previewReset").disabled = false;
    updateResetAvailability();
  }
}

function bindUi() {
  $$(".navItem").forEach((button) => {
    button.addEventListener("click", () => selectView(button.dataset.view));
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

  $("#loginForm").addEventListener("submit", (event) => {
    event.preventDefault();
    login();
  });
  $("#refreshAgents").addEventListener("click", loadAgents);
  $("#agentStatusFilter").addEventListener("change", renderAgents);
  $("#agentCreateForm").addEventListener("submit", createAgent);
  $("#agentEditForm").addEventListener("submit", saveAgent);
  $("#agentCredentialsForm").addEventListener("submit", saveAgentCredentials);
  $("#cancelAgentEdit").addEventListener("click", () => { $("#agentEditForm").hidden = true; });
  $("#cancelAgentCredentials").addEventListener("click", () => {
    $("#agentCredentialsForm").hidden = true;
    $("#agentCredentialsForm").reset();
  });
  $("#resetPreviewForm").addEventListener("submit", previewReset);
  $("#resetExecuteForm").addEventListener("submit", executeReset);
  $("#resetPhone").addEventListener("input", invalidateResetPreview);
  $("#resetReason").addEventListener("input", updateResetAvailability);
  $("#resetConfirmPhone").addEventListener("input", updateResetAvailability);
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
  $("#refreshPaymentEvidence").addEventListener("click", loadPaymentEvidence);
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
applyAuthState();
refreshAll();
setInterval(refreshVisibleHandoffMessages, state.chatPollIntervalMs);
