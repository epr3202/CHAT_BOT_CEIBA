import {
  labels, label, formatDate, summaryContent, formatCOP, bogotaDateTimeToISO,
  bookingBlockersText, backendErrorText,
} from "./labels.mjs";

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
  paymentEvidenceRequest: 0,
  staffNotificationsRequest: 0,
  agents: [],
  plans: [],
  planWrites: new Set(),
  reservations: [],
  reservationDetail: null,
  reservationListRequest: 0,
  reservationDetailRequest: 0,
  manualPlansRequest: 0,
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

function localizeControls() {
  $$('[data-label-kind]').forEach((node) => {
    node.replaceChildren(label(node.dataset.labelKind, node.dataset.labelValue));
  });
  const selects = [
    ["#conversationStateFilter", "conversationState"],
    ["#agentCreateRole", "role", ["AGENT", "ADMIN"]],
    ["#agentEditRole", "role", ["AGENT", "ADMIN"]],
    ["#catalogEventType", "eventType"],
    ["#catalogSendMode", "sendMode", ["ON_REQUEST", "PROACTIVE"]],
    ["#reservationStatusFilter", "reservationStatus"],
  ];
  for (const [selector, kind, values = Object.keys(labels[kind])] of selects) {
    for (const value of values) $(selector).add(new Option(labels[kind][value], value));
  }
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
      || (button.dataset.agentOnly === "true" && state.agent?.role !== "AGENT")
      || (button.dataset.view === "simulator" && !simulationVisible());
  });
  const manualContainer = state.agent?.role === "AGENT" ? $("#manualReservations") : $("#reservations");
  if ($("#manualReservationPanel").parentElement !== manualContainer) {
    manualContainer.prepend($("#manualReservationPanel"));
  }
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
  if (view === "staffNotifications") loadStaffNotifications();
  if (view === "plans") loadPlans();
  if (view === "reservations") { loadReservations(); loadManualPlans(); }
  if (view === "manualReservations") loadManualPlans();
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
    if (path.startsWith("/api/admin/reservations") || path.startsWith("/api/admin/payment-evidence")) {
      detail = backendErrorText(detail);
    } else {
      if (Array.isArray(detail)) detail = detail.map(item => item.msg || JSON.stringify(item)).join("; ");
      if (detail && typeof detail === "object") detail = JSON.stringify(detail);
    }
    if (response.status === 401) {
      clearSession();
      applyAuthState();
    }
    const error = new Error(detail || `Error de solicitud (${response.status})`);
    error.status = response.status;
    error.retryAfter = response.headers.get("Retry-After");
    throw error;
  }
  return payload;
}

async function loadPaymentEvidence() {
  const container = $("#paymentEvidenceList");
  if (state.agent?.role !== "ADMIN") {
    setEmpty(container, "Inicia sesión como administrador para revisar comprobantes.");
    return;
  }
  const request = ++state.paymentEvidenceRequest;
  const token = state.sessionToken;
  const refresh = $("#refreshPaymentEvidence");
  refresh.disabled = true;
  refresh.textContent = "Cargando…";
  setEmpty(container, "Cargando comprobantes…");
  try {
    const evidences = await managementRequest("/api/admin/payment-evidence");
    if (request !== state.paymentEvidenceRequest || token !== state.sessionToken) return;
    state.paymentEvidence = evidences;
    renderPaymentEvidence();
  } catch (error) {
    if (request === state.paymentEvidenceRequest && token === state.sessionToken) {
      managementFeedback("paymentEvidenceFeedback", `No se pudieron cargar los comprobantes: ${error.message}`, true);
      setEmpty(container, "No se pudo cargar la lista. Usa Actualizar para reintentar.");
    }
  } finally {
    if (request === state.paymentEvidenceRequest) {
      refresh.disabled = false;
      refresh.textContent = "Actualizar";
    }
  }
}

function reservationLink(id) {
  return actionButton("Ver reserva", async () => {
    if (state.agent?.role !== "ADMIN") return;
    selectView("reservations");
    await openReservationDetail(id);
  });
}

function renderPaymentEvidence() {
  const container = $("#paymentEvidenceList");
  container.replaceChildren();
  if (!state.paymentEvidence.length) {
    setEmpty(container, "No hay comprobantes pendientes de revisión.");
    return;
  }
  for (const evidence of state.paymentEvidence) {
    const card = createEvidenceCard(evidence, "paymentEvidenceFeedback",
      (decision, note, amount, button, scope) => reviewPaymentEvidence(evidence.id, decision, note, amount, button, scope));
    const title = document.createElement("strong");
    title.textContent = evidence.customer_name || evidence.customer_phone || "Sin nombre";
    const meta = document.createElement("span");
    meta.textContent = evidence.mime_type || "";
    const status = document.createElement("span");
    status.append(label("downloadStatus", evidence.download_status));
    $(".paymentEvidenceDetails", card).prepend(title, meta, status);
    if (evidence.reservation_id) $(".actions", card).append(reservationLink(evidence.reservation_id));
    container.append(card);
  }
}

async function reviewPaymentEvidence(evidenceId, decision, note, amount, button, card) {
  if (state.agent?.role !== "ADMIN") return;
  const body = evidenceReviewBody(decision, note, amount, "paymentEvidenceFeedback", card);
  if (!body) return;
  if (decision === "accept" && card.dataset.reviewId) body.review_id = card.dataset.reviewId;
  await managementAction(button, card, decision === "accept" ? "Aceptando…" : "Rechazando…", "paymentEvidenceFeedback",
    async current => {
      const result = await managementRequest(`/api/admin/payment-evidence/${evidenceId}/${decision}`, {
        method: "POST", body: JSON.stringify(body),
      });
      if (!current()) return;
      await loadPaymentEvidence();
      if (!current()) return;
      managementFeedback("paymentEvidenceFeedback", settlementMessage(result));
      const actions = $("#paymentEvidenceResultActions");
      actions.replaceChildren();
      if (result.reservation?.reservation_id) actions.append(reservationLink(result.reservation.reservation_id));
    }, "No se pudo revisar el comprobante");
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
    title.replaceChildren(category.event_type ? label("eventType", category.event_type) : "Sin asignaciones");
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

const catalogSendModeHelp = {
  ON_REQUEST: "solo si el cliente pide el catálogo",
  PROACTIVE: "se envía solo al detectar el evento",
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
  status.replaceChildren(label("active", catalog.active));
  heading.append(name, status);

  const summary = document.createElement("ul");
  summary.className = "catalogMappingSummary";
  for (const mapping of catalog.event_type_mappings) {
    const item = document.createElement("li");
    item.append(label("eventType", mapping.event_type), " · ", label("sendMode", mapping.send_mode));
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
    for (const [value, explanation] of Object.entries(catalogSendModeHelp)) {
      modeSelect.add(new Option(`${label("sendMode", value)} (${explanation})`, value));
    }
    modeSelect.value = mapping.send_mode;
    const help = document.createElement("small");
    help.className = "catalogModeHelp";
    help.textContent = catalogSendModeHelp[mapping.send_mode] || "Selecciona un modo de envío.";
    modeSelect.addEventListener("change", () => {
      mapping.send_mode = modeSelect.value;
      help.textContent = catalogSendModeHelp[mapping.send_mode];
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
    $("#agentRoleState").replaceChildren(label("role", state.agent.role));
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
    $("#agentRoleState").replaceChildren(label("role", state.agent.role));
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
  state.paymentEvidenceRequest += 1;
  state.staffNotificationsRequest += 1;
  $("#notificationRecipientList").replaceChildren();
  $("#staffNotificationList").replaceChildren();
  resetRecipientForm();
  managementFeedback("staffNotificationFeedback", "");
  state.catalogCategories = [];
  state.unassignedCatalogs = [];
  state.catalogEditor = null;
  state.agents = [];
  state.plans = [];
  state.planWrites = new Set();
  state.reservations = [];
  state.reservationDetail = null;
  state.reservationListRequest += 1;
  state.reservationDetailRequest += 1;
  state.manualPlansRequest += 1;
  $("#planRows").replaceChildren();
  $("#reservationRows").replaceChildren();
  $("#reservationDetails").replaceChildren();
  $("#reservationEvidences").replaceChildren();
  $("#paymentEvidenceResultActions").replaceChildren();
  $("#reservationScheduleForm").reset();
  $("#reservationDetail").hidden = true;
  $("#reservationCancelForm").reset();
  $("#manualReservationForm").reset();
  $("#manualReservationPlan").replaceChildren();
  $("#refreshPlans").disabled = false;
  for (const id of ["plansFeedback", "reservationsFeedback", "reservationDetailFeedback", "manualReservationFeedback", "paymentEvidenceFeedback"]) {
    managementFeedback(id, "");
  }
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
    logEvent(`No se pudo cerrar la sesión: ${error.message}`);
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
    logEvent(`Falló la comprobación de la API: ${error.message}`);
  }
}

function logEvent(...parts) {
  const list = $("#eventLog");
  const item = document.createElement("li");
  const message = parts.map(part => typeof part === "string" ? part : part.textContent).join("");
  item.append(`${formatDate(new Date())} · `, ...parts);
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
    const detail = error.message === "META_APP_SECRET y texto son obligatorios"
      ? "Configura el secreto de simulación y escribe un mensaje."
      : error.message;
    logEvent(`Falló la simulación: ${detail}`);
  }
}

async function loadHandoffs(status = state.currentStatus) {
  state.currentStatus = status;
  persistViewState();
  $$(".segment").forEach((button) => button.classList.toggle("active", button.dataset.status === status));

  const list = $("#handoffList");
  setEmpty(list, "Cargando casos...");

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
    reason: handoff.reason,
    reasonKind: "handoffReason",
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
    reason: conversation.handoff_reason || conversation.last_intent,
    reasonKind: conversation.handoff_reason ? "handoffReason" : "intent",
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
      item.reason ? labels[item.reasonKind]?.[item.reason] : "Sin clasificar",
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
    status.replaceChildren(statusLabel(item.handoffStatus, item.status));
    $(".caseAssignment", row).textContent = assignmentText(item);
    $(".caseReason", row).replaceChildren(reasonLabel(item));
    $(".caseActivity", row).replaceChildren(activityText(item));
    const actions = $(".caseActions", row);
    if (directTakeEligibleStates.has(item.status)) {
      actions.append(actionButton("Tomar conversación", () => takeConversation(item.conversationId), "primary"));
    } else if (item.status === "WAITING_FOR_HUMAN" && item.handoffStatus === "PENDING" && item.id !== null) {
      actions.append(actionButton("Tomar caso", () => takeHandoff(item.id), "primary"));
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
  if (status === "SIN_HANDOFF") {
    return conversationState ? label("conversationState", conversationState) : "Sin caso humano";
  }
  return label("handoffStatus", status);
}

function reasonLabel(item) {
  return item.reason ? label(item.reasonKind, item.reason) : "Sin clasificar";
}

function activityText(item) {
  const timestamp = item.resolvedAt || item.takenAt || item.createdAt;
  if (!timestamp) return "Sin fecha";
  const action = item.lastMessageDirection ? label("direction", item.lastMessageDirection)
    : item.resolvedAt ? label("handoffStatus", "RETURNED")
    : item.takenAt ? label("handoffStatus", "TAKEN") : "Creado";
  const content = document.createDocumentFragment();
  content.append(action, ` · ${formatDate(timestamp)}`);
  return content;
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
  $("#summaryModalDetails").replaceChildren(
    "Estado: ", label("conversationState", item.status),
    `\nAsignación: ${item.assignedTo}\nMotivo: `, reasonLabel(item),
    "\nActividad: ", activityText(item),
  );
  if (item.handoffStatus && item.handoffStatus !== "SIN_HANDOFF") {
    $("#summaryModalDetails").append("\nEstado del caso: ", label("handoffStatus", item.handoffStatus));
  }
  $("#summaryModalBody").replaceChildren(summaryContent(item.summary));
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
      return `${event.actor} tomó el caso`;
    });
    $("#summaryModalDetails").append(`\nHistorial: ${lines.join(" · ") || "Sin eventos"}`);
  } catch (error) {
    $("#summaryModalDetails").append("\nHistorial: no disponible");
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
    setEmpty(list, "No hay casos en este estado.");
    return;
  }

  const template = $("#handoffTemplate");
  for (const handoff of handoffs) {
    const node = template.content.firstElementChild.cloneNode(true);
    node.dataset.handoffId = String(handoff.id);
    $(".handoffTitle", node).textContent = `Conversación ${handoff.conversation_id}`;
    $(".handoffMeta", node).replaceChildren(`Caso ${handoff.id} · `,
      label("handoffReason", handoff.reason), " · ", label("handoffStatus", handoff.status));
    const priority = $(".priority", node);
    priority.className = `priority ${priorityClass(handoff.priority)}`;
    priority.replaceChildren(label("priority", handoff.priority));
    $(".summary", node).replaceChildren(summaryContent(handoff.summary));
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
    logEvent("Inicia sesión para tomar casos.");
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
    logEvent(`Caso ${handoffId} tomado.`);
    await refreshAll();
    await loadHandoffs("TAKEN");
  } catch (error) {
    logEvent(`No se pudo tomar el caso: ${error.message}`);
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
    meta.replaceChildren(chatMetaText(message));
    bubble.append(meta);

    thread.append(bubble);
  }

  if (wasNearBottom) {
    thread.scrollTop = thread.scrollHeight;
  }
}

function chatMetaText(message) {
  const content = document.createDocumentFragment();
  content.append(label("direction", message.direction), ` · ${formatDate(message.created_at)}`);
  if (message.message_type) content.append(" · ", label("messageType", message.message_type));
  if (message.status) content.append(" · ", label("outboxStatus", message.status));
  if (message.status === "SUPPRESSED") {
    content.append(" · Motivo: ", message.delivery_reason
      ? label("deliveryReason", message.delivery_reason) : "Sin motivo registrado");
  }
  return content;
}

async function returnHandoff(handoffId) {
  const resolution = "Cliente atendido y devuelto al bot.";
  try {
    await requestJson(`/api/admin/handoffs/${handoffId}/return`, {
      method: "POST",
      headers: operationHeaders(),
      body: JSON.stringify({ resolution }),
    });
    logEvent(`Caso ${handoffId} devuelto al bot.`);
    await refreshAll();
  } catch (error) {
    logEvent(`No se pudo devolver el caso: ${error.message}`);
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
    if (state.currentView === "plans") await loadPlans();
    if (state.currentView === "staffNotifications") await loadStaffNotifications();
    if (state.currentView === "reservations") await Promise.all([loadReservations(), loadManualPlans()]);
  }
  if (state.currentView === "manualReservations") await loadManualPlans();
}

function feedback(id, message, error = false) {
  const node = document.getElementById(id);
  node.textContent = message;
  node.classList.toggle("formError", error);
}

function managementFeedback(id, message, error = false) {
  const node = document.getElementById(id);
  node.textContent = message;
  node.hidden = !message;
  node.classList.toggle("formError", error);
  node.setAttribute("role", error ? "alert" : "status");
}

async function managementRequest(path, options = {}) {
  try {
    return await requestJson(path, { ...options, headers: sessionHeaders() });
  } catch (error) {
    if (error.status) {
      error.message = backendErrorText(error.message);
      throw error;
    }
    throw new Error("No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.");
  }
}

function emptyTable(body, columns, message) {
  body.replaceChildren();
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = columns;
  cell.textContent = message;
  row.append(cell);
  body.append(row);
}

// Reuse the same loading/error behavior for every reservation form.
async function managementAction(button, scope, busyText, feedbackId, operation, failureText) {
  if (!state.sessionToken || button.disabled || scope.dataset.busy === "true") return;
  const token = state.sessionToken;
  const controls = $$("input, select, textarea, button", scope);
  const disabled = controls.map(control => control.disabled);
  const caption = button.textContent;
  scope.dataset.busy = "true";
  scope.setAttribute("aria-busy", "true");
  controls.forEach(control => { control.disabled = true; });
  button.textContent = busyText;
  managementFeedback(feedbackId, "");
  try {
    await operation(() => token === state.sessionToken);
  } catch (error) {
    if (token === state.sessionToken) managementFeedback(feedbackId, `${failureText}: ${error.message}`, true);
  } finally {
    controls.forEach((control, index) => { control.disabled = disabled[index]; });
    button.textContent = caption;
    scope.dataset.busy = "false";
    scope.setAttribute("aria-busy", "false");
  }
}

async function loadManualPlans() {
  if (!state.agent || $("#manualReservationForm").dataset.busy === "true") return;
  const request = ++state.manualPlansRequest;
  const token = state.sessionToken;
  const select = $("#manualReservationPlan");
  const previous = select.value;
  select.disabled = true;
  managementFeedback("manualReservationFeedback", "Cargando planes…");
  try {
    const plans = await managementRequest("/api/admin/plans");
    if (request !== state.manualPlansRequest || token !== state.sessionToken) return;
    select.replaceChildren(new Option("Selecciona un plan", ""));
    for (const plan of plans.filter(plan => plan.active)) select.append(new Option(plan.name, plan.plan_id));
    if (plans.some(plan => plan.active && plan.plan_id === previous)) select.value = previous;
    managementFeedback("manualReservationFeedback", plans.some(plan => plan.active) ? "" : "No hay planes activos.");
  } catch (error) {
    if (request === state.manualPlansRequest && token === state.sessionToken) {
      managementFeedback("manualReservationFeedback", `No se pudieron cargar los planes: ${error.message}`, true);
    }
  } finally {
    if (request === state.manualPlansRequest) select.disabled = false;
  }
}

function manualReservationData() {
  const form = $("#manualReservationForm");
  if (!form.reportValidity()) return null;
  const name = $("#manualReservationName").value.trim();
  return {
    phone: $("#manualReservationPhone").value.trim(), ...(name ? { full_name: name } : {}),
    plan_id: $("#manualReservationPlan").value,
    starts_at: bogotaDateTimeToISO($("#manualReservationDate").value, $("#manualReservationTime").value),
  };
}

async function verifyManualReservation() {
  let data;
  try { data = manualReservationData(); }
  catch (error) { managementFeedback("manualReservationFeedback", error.message, true); return; }
  if (!data) return;
  await managementAction($("#verifyManualReservation"), $("#manualReservationForm"), "Verificando…",
    "manualReservationFeedback", async current => {
      const params = new URLSearchParams({ plan_id: data.plan_id, starts_at: data.starts_at });
      const result = await managementRequest(`/api/admin/reservations/availability?${params}`);
      if (!current()) return;
      const message = result.available ? `Disponible. Anticipo: ${formatCOP(result.deposit_amount_cop)}.`
        : [labels.bookingWindow[result.window?.reason], bookingBlockersText(result.blockers),
          `Anticipo: ${formatCOP(result.deposit_amount_cop)}.`].filter(Boolean).join("\n");
      managementFeedback("manualReservationFeedback", message, !result.available);
    }, "No se pudo verificar la disponibilidad");
}

async function createManualReservation(event) {
  event.preventDefault();
  let data;
  try { data = manualReservationData(); }
  catch (error) { managementFeedback("manualReservationFeedback", error.message, true); return; }
  if (!data) return;
  await managementAction($("#createManualReservation"), $("#manualReservationForm"), "Creando…",
    "manualReservationFeedback", async current => {
      const result = await managementRequest("/api/admin/reservations", { method: "POST", body: JSON.stringify(data) });
      if (!current()) return;
      managementFeedback("manualReservationFeedback", `Reserva creada. Anticipo: ${formatCOP(result.deposit_amount_cop)}. La fecha se confirma al validar el pago.`);
      if (state.agent?.role === "ADMIN") await loadReservations();
    }, "No se pudo crear la reserva");
}

async function loadPlans() {
  if (state.agent?.role !== "ADMIN" || state.planWrites.size) return;
  const token = state.sessionToken;
  managementFeedback("plansFeedback", "Cargando planes…");
  try {
    const plans = await managementRequest("/api/admin/plans");
    if (token !== state.sessionToken) return;
    state.plans = plans;
    renderPlans();
    managementFeedback("plansFeedback", "");
  } catch (error) {
    if (token === state.sessionToken) {
      managementFeedback("plansFeedback", `No se pudieron cargar los planes: ${error.message}`, true);
    }
  }
}

function renderPlans() {
  const body = $("#planRows");
  body.replaceChildren();
  if (!state.plans.length) {
    emptyTable(body, 9, "No hay planes disponibles.");
    return;
  }
  const fields = [
    ["name", "Nombre", "text"], ["price_cop", "Precio (COP)", "number"],
    ["duration_minutes", "Duración (minutos)", "number"], ["exclusive", "Exclusivo", "checkbox"],
    ["weekend_only", "Solo fines de semana", "checkbox"], ["active", "Activo", "checkbox"],
    ["sort_order", "Orden", "number"],
  ];
  for (const plan of state.plans) {
    const row = document.createElement("tr");
    const controls = {};
    for (const [field, title, type] of fields) {
      const cell = document.createElement("td");
      const input = document.createElement("input");
      input.type = type;
      input.setAttribute("aria-label", title);
      if (type === "checkbox") input.checked = plan[field];
      else {
        input.value = plan[field];
        input.required = true;
        if (type === "number") {
          input.step = "1";
          input.min = field === "sort_order" ? "-2147483648" : "1";
          input.max = "2147483647";
        } else input.maxLength = 180;
      }
      controls[field] = input;
      cell.append(input);
      row.append(cell);
      if (field === "name") {
        const eventCell = document.createElement("td");
        eventCell.append(label("eventType", plan.event_type));
        row.append(eventCell);
      }
    }
    const actions = document.createElement("td");
    actions.append(actionButton("Guardar", (event) => savePlan(plan, controls, event.currentTarget)));
    row.append(actions);
    body.append(row);
  }
}

async function savePlan(plan, controls, button) {
  if (state.agent?.role !== "ADMIN" || button.disabled) return;
  if (Object.values(controls).some((input) => !input.reportValidity())) return;
  const changes = {};
  for (const [field, input] of Object.entries(controls)) {
    changes[field] = input.type === "checkbox" ? input.checked
      : input.type === "number" ? Number(input.value) : input.value.trim();
  }
  const writes = state.planWrites;
  const token = state.sessionToken;
  writes.add(plan.plan_id);
  button.disabled = true;
  button.textContent = "Guardando…";
  Object.values(controls).forEach((input) => { input.disabled = true; });
  $("#refreshPlans").disabled = true;
  managementFeedback("plansFeedback", "");
  try {
    const updated = await managementRequest(`/api/admin/plans/${plan.plan_id}`, {
      method: "PATCH", body: JSON.stringify(changes),
    });
    if (token !== state.sessionToken) return;
    Object.assign(plan, updated);
    for (const [field, input] of Object.entries(controls)) {
      if (input.type === "checkbox") input.checked = updated[field];
      else input.value = updated[field];
    }
    managementFeedback("plansFeedback", "Plan guardado.");
  } catch (error) {
    if (token === state.sessionToken) {
      managementFeedback("plansFeedback", `No se pudo guardar el plan: ${error.message}`, true);
    }
  } finally {
    writes.delete(plan.plan_id);
    button.disabled = false;
    button.textContent = "Guardar";
    Object.values(controls).forEach((input) => { input.disabled = false; });
    if (writes === state.planWrites) $("#refreshPlans").disabled = writes.size > 0;
  }
}

async function loadReservations() {
  if (state.agent?.role !== "ADMIN") return;
  const request = ++state.reservationListRequest;
  const params = new URLSearchParams();
  const status = $("#reservationStatusFilter").value;
  if (status) params.set("status", status);
  const balanceStatus = $("#reservationBalanceFilter").value;
  if (balanceStatus) params.set("balance_status", balanceStatus);
  try {
    if ($("#reservationFromFilter").value) params.set("from", bogotaDateTimeToISO($("#reservationFromFilter").value, "00:00"));
    if ($("#reservationToFilter").value) {
      const finalMinute = new Date(bogotaDateTimeToISO($("#reservationToFilter").value, "23:59"));
      params.set("to", new Date(finalMinute.getTime() + 59999).toISOString());
    }
  } catch (error) { managementFeedback("reservationsFeedback", error.message, true); return; }
  managementFeedback("reservationsFeedback", "Cargando reservas…");
  try {
    const reservations = await managementRequest(`/api/admin/reservations?${params}`);
    if (request !== state.reservationListRequest) return;
    state.reservations = reservations;
    renderReservations();
    managementFeedback("reservationsFeedback", "");
  } catch (error) {
    if (request === state.reservationListRequest) {
      managementFeedback("reservationsFeedback", `No se pudieron cargar las reservas: ${error.message}`, true);
    }
  }
}

function renderReservations() {
  const body = $("#reservationRows");
  body.replaceChildren();
  if (!state.reservations.length) {
    emptyTable(body, 7, "No hay reservas con este filtro.");
    return;
  }
  for (const reservation of state.reservations) {
    const row = document.createElement("tr");
    for (const value of [reservation.customer_name || reservation.customer_phone || "Sin nombre", reservation.plan_name || "Sin plan",
      formatDate(reservation.starts_at), label("reservationStatus", reservation.status),
      `${formatCOP(reservation.amount_paid_cop)} / ${formatCOP(reservation.missing_cop)}`,
      label("calendarStatus", reservation.calendar_status)]) {
      const cell = document.createElement("td");
      cell.append(value);
      row.append(cell);
    }
    if (reservation.conversation_id === null) {
      const badge = document.createElement("span");
      badge.className = "pill neutral manualBadge";
      badge.textContent = "Manual";
      row.firstElementChild.append(badge);
    }
    if (reservation.status === "RESERVED" && reservation.amount_paid_cop < reservation.price_cop) {
      const badge = document.createElement("span");
      badge.className = "pill neutral";
      badge.textContent = reservation.balance_overdue_at ? "Saldo vencido" : "Saldo pendiente";
      row.children[3].append(badge);
    }
    const actions = document.createElement("td");
    actions.append(actionButton("Ver detalle", () => openReservationDetail(reservation.reservation_id)));
    row.append(actions);
    body.append(row);
  }
}

async function openReservationDetail(id) {
  if (state.agent?.role !== "ADMIN") return;
  const request = ++state.reservationDetailRequest;
  state.reservationDetail = null;
  $("#reservationDetail").hidden = false;
  $("#reservationDetails").replaceChildren();
  $("#reservationEvidences").replaceChildren();
  $("#reservationCustomerNotifications").replaceChildren();
  $("#reservationScheduleForm").hidden = true;
  $("#retryReservationCalendar").hidden = true;
  $("#reservationCancelForm").hidden = true;
  managementFeedback("reservationDetailFeedback", "Cargando detalle…");
  try {
    const reservation = await managementRequest(`/api/admin/reservations/${id}`);
    if (request !== state.reservationDetailRequest) return;
    renderReservationDetail(reservation);
    managementFeedback("reservationDetailFeedback", "");
  } catch (error) {
    if (request === state.reservationDetailRequest) {
      managementFeedback("reservationDetailFeedback", `No se pudo cargar el detalle: ${error.message}`, true);
    }
  }
}

function renderReservationDetail(reservation) {
  state.reservationDetail = reservation;
  const details = $("#reservationDetails");
  const cop = new Intl.NumberFormat("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });
  details.replaceChildren();
  for (const [title, value] of [
    ["Cliente", reservation.customer_name || reservation.customer_phone || "Sin nombre"], ["Plan", reservation.plan_name || "Sin plan"],
    ["Origen", reservation.conversation_id === null ? "Manual" : "Conversación"],
    ["Estado", label("reservationStatus", reservation.status)], ["Inicio", formatDate(reservation.starts_at)],
    ["Fin", formatDate(reservation.ends_at)], ["Precio", cop.format(reservation.price_cop)],
    ["Pagado", cop.format(reservation.amount_paid_cop)],
    ["Saldo pendiente", formatCOP(Math.max(0, reservation.price_cop - reservation.amount_paid_cop))],
    ["Anticipo", formatCOP(reservation.deposit_amount_cop)],
    ["Faltante para el anticipo", formatCOP(reservation.missing_cop)],
    ["Calendario", label("calendarStatus", reservation.calendar_status)],
    ["Modalidad de pago", reservation.payment_kind ? label("paymentKind", reservation.payment_kind) : "Sin modalidad"],
    ["Vencimiento del saldo", formatDate(reservation.balance_due_at)],
    ["Saldo vencido desde", formatDate(reservation.balance_overdue_at)],
  ]) {
    const term = document.createElement("dt");
    term.textContent = title;
    const description = document.createElement("dd");
    description.append(value);
    details.append(term, description);
  }
  const reminders = $("#reservationCustomerNotifications");
  reminders.replaceChildren();
  if (!reservation.customer_notifications?.length) setEmpty(reminders, "No hay recordatorios registrados.");
  for (const reminder of reservation.customer_notifications || []) {
    const item = document.createElement("p");
    item.textContent = `${label("customerNotificationKind", reminder.kind)} · ${label("staffNotificationStatus", reminder.status)} · ${formatDate(reminder.sent_at || reminder.created_at)}`;
    reminders.append(item);
  }
  const form = $("#reservationCancelForm");
  form.reset();
  const writable = state.agent?.role === "ADMIN" && ["PAYMENT_PENDING", "PAYMENT_REVIEW", "RESERVED"].includes(reservation.status);
  form.hidden = !writable;
  const schedule = $("#reservationScheduleForm");
  schedule.hidden = !writable;
  if (writable) {
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/Bogota", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    }).formatToParts(new Date(reservation.starts_at)).map(p => [p.type, p.value]));
    $("#reservationScheduleDate").value = `${parts.year}-${parts.month}-${parts.day}`;
    $("#reservationScheduleTime").value = `${parts.hour}:${parts.minute}`;
  }
  $("#retryReservationCalendar").hidden = state.agent?.role !== "ADMIN" || reservation.status !== "RESERVED" || reservation.calendar_status !== "NONE";
  const evidences = $("#reservationEvidences");
  evidences.replaceChildren();
  if (!reservation.evidences?.length) setEmpty(evidences, "Esta reserva no tiene comprobantes.");
  for (const evidence of reservation.evidences || []) {
    evidences.append(createEvidenceCard({ ...evidence, reservation_id: reservation.reservation_id }, "reservationDetailFeedback",
      (decision, note, amount, button, card) => settleReservationEvidence(reservation.reservation_id, evidence.id, decision, note, amount, button, card)));
  }
}

function createEvidenceCard(evidence, feedbackId, review) {
  const card = document.createElement("article");
  card.className = "paymentEvidenceCard";
  card.dataset.unlinked = String(!evidence.reservation_id);
  const details = document.createElement("div");
  details.className = "paymentEvidenceDetails";
  const title = document.createElement("strong");
  title.textContent = `Comprobante #${evidence.id}`;
  const status = document.createElement("span");
  status.append(label("reviewStatus", evidence.status || evidence.review_status));
  const amount = document.createElement("span");
  amount.textContent = `Monto: ${formatCOP(evidence.amount_cop)}`;
  const date = document.createElement("span");
  date.textContent = formatDate(evidence.created_at);
  details.append(title, status, amount, date);
  card.append(details);
  if (evidence.review) card.append(createPrereviewBlock(evidence.review));
  const actions = document.createElement("div");
  actions.className = "actions";
  if (evidence.download_status === "DOWNLOADED") {
    actions.append(actionButton("Descargar", event => downloadEvidence(evidence.id, event.currentTarget, card, feedbackId)));
  }
  if ((evidence.status || evidence.review_status) === "PENDING_REVIEW" && state.agent?.role === "ADMIN") {
    const failedDownload = evidence.download_status === "FAILED_PERMANENT";
    const amountLabel = document.createElement("label");
    amountLabel.textContent = "Monto verificado (COP)";
    const input = document.createElement("input");
    input.type = "number"; input.min = "1"; input.max = "2147483647"; input.step = "1"; input.inputMode = "numeric";
    amountLabel.append(input);
    const noteLabel = document.createElement("label");
    noteLabel.textContent = "Nota interna";
    const note = document.createElement("textarea");
    note.maxLength = 255; note.rows = 2;
    note.placeholder = "Opcional al aceptar; obligatoria al rechazar";
    noteLabel.append(note);
    card.append(amountLabel, noteLabel);
    if (!evidence.reservation_id) {
      const reasonLabel = document.createElement("label");
      reasonLabel.textContent = "Motivo visible para el cliente";
      const reason = document.createElement("textarea");
      reason.className = "customerReason"; reason.maxLength = 200; reason.rows = 2;
      reason.placeholder = "Obligatorio al rechazar; sin enlaces";
      reasonLabel.append(reason);
      card.append(reasonLabel);
    }
    if (failedDownload) {
      note.value = "No se pudo descargar el comprobante. Envía una nueva imagen.";
      const notice = document.createElement("p");
      notice.textContent = "No se pudo descargar el comprobante. Solicita una nueva imagen antes de aceptar el pago.";
      card.append(notice);
    } else if (evidence.review?.status === "COMPLETED") {
      if (evidence.review.suggestion === "REJECT") {
        const failed = evidence.review.checks?.find(check =>
          ["ACCOUNT", "REFERENCE"].includes(check.code) && check.result === "FAIL");
        note.value = failed?.code === "ACCOUNT" ? "Cuenta destino no coincide" : "Referencia ya usada";
      } else if (Number.isInteger(evidence.review.suggested_amount_cop) && evidence.review.suggested_amount_cop > 0) {
        actions.append(actionButton("Aceptar propuesta", () => {
          input.value = evidence.review.suggested_amount_cop;
          card.dataset.reviewId = evidence.review.review_id;
          input.focus();
          managementFeedback(feedbackId, "Monto propuesto cargado. Verifica el comprobante y pulsa Aceptar para confirmar.");
        }));
      }
    }
    if (evidence.download_status === "DOWNLOADED") {
      actions.append(actionButton(evidence.review ? "Reintentar pre-revisión" : "Solicitar pre-revisión",
        event => retryEvidencePrereview(evidence, event.currentTarget, card, feedbackId)));
    }
    const accept = actionButton("Aceptar", event => review("accept", note.value, input.value, event.currentTarget, card), "primary");
    accept.disabled = failedDownload;
    actions.append(
      accept,
      actionButton("Rechazar", event => review("reject", note.value, input.value, event.currentTarget, card), "danger"),
    );
  }
  card.append(actions);
  return card;
}

function createPrereviewBlock(review) {
  const block = document.createElement("section");
  block.className = "receiptPrereview";
  const heading = document.createElement("strong");
  heading.textContent = "Pre-revisión";
  block.append(heading);
  const message = document.createElement("p");
  if (review.status !== "COMPLETED") {
    message.textContent = review.status === "FAILED"
      ? "No se pudo leer el comprobante. Puedes reintentar o revisarlo manualmente."
      : "Este comprobante requiere revisión manual.";
    block.append(message);
    return block;
  }
  message.textContent = ({ ACCEPT: "Sugerencia: aceptar", REVIEW: "Sugerencia: revisar", REJECT: "Sugerencia: rechazar" })[review.suggestion]
    || "Sugerencia: revisar";
  block.append(message);
  const names = { amount_cop: "Monto", currency: "Moneda", transaction_date: "Fecha de transacción",
    transaction_time: "Hora", reference: "Referencia", bank: "Banco", destination_account_last4: "Cuenta destino (últimos 4)",
    sender_name: "Iniciales del remitente", confidence: "Confianza de lectura", notes: "Observaciones" };
  const fields = document.createElement("dl");
  for (const [key, name] of Object.entries(names)) {
    const term = document.createElement("dt"); term.textContent = name;
    const value = document.createElement("dd");
    const raw = review.extracted?.[key];
    value.textContent = raw == null ? "No leído" : key === "amount_cop" ? formatCOP(raw)
      : key === "confidence" ? `${Math.round(raw * 100)} %` : String(raw);
    fields.append(term, value);
  }
  block.append(fields);
  const checks = document.createElement("ul");
  const codes = { AMOUNT: "Monto", CURRENCY: "Moneda", ACCOUNT: "Cuenta destino", DATE: "Fecha", REFERENCE: "Referencia", CONFIDENCE: "Confianza" };
  const results = { OK: "✓ Correcto", WARN: "⚠ Atención", FAIL: "✕ No coincide", UNKNOWN: "? Sin datos" };
  for (const check of review.checks || []) {
    const item = document.createElement("li");
    item.textContent = `${codes[check.code] || "Verificación"}: ${results[check.result] || "Sin datos"}. ${check.detail || ""}`;
    checks.append(item);
  }
  const notice = document.createElement("p");
  notice.textContent = "La lectura no detecta falsificaciones. La confirmación del pago requiere revisión humana.";
  block.append(checks, notice);
  return block;
}

async function retryEvidencePrereview(evidence, button, card, feedbackId) {
  const reservationId = feedbackId === "reservationDetailFeedback" ? state.reservationDetail?.reservation_id : null;
  const request = state.reservationDetailRequest;
  await managementAction(button, card, "Leyendo comprobante…", feedbackId, async current => {
    const result = await managementRequest(`/api/admin/payment-evidence/${evidence.id}/prereview`, { method: "POST" });
    if (!current() || reservationId && request !== state.reservationDetailRequest) return;
    if (reservationId) await openReservationDetail(reservationId);
    else await loadPaymentEvidence();
    if (!current()) return;
    managementFeedback(feedbackId, result.review?.status === "COMPLETED" ? "Pre-revisión completada."
      : "No se pudo leer el comprobante. Revisa el archivo manualmente.", result.review?.status === "FAILED");
  }, "No se pudo completar la pre-revisión");
}

function evidenceReviewBody(decision, note, amount, feedbackId, card = null) {
  const body = {};
  if (note.trim()) body.note = note.trim();
  if (decision === "reject" && !body.note) {
    managementFeedback(feedbackId, "Escribe la nota interna del rechazo.", true);
    return null;
  }
  if (decision === "reject" && card?.dataset.unlinked === "true") {
    const reason = $(".customerReason", card).value.trim().replace(/\s+/g, " ");
    if (!reason) {
      managementFeedback(feedbackId, "Escribe el motivo que verá el cliente", true);
      return null;
    }
    if (/http|www/i.test(reason)) {
      managementFeedback(feedbackId, "No incluyas enlaces en el motivo", true);
      return null;
    }
    body.customer_reason = reason.slice(0, 200);
  }
  if (decision === "accept") {
    const value = Number(amount);
    if (!Number.isInteger(value) || value <= 0 || value > 2147483647) {
      managementFeedback(feedbackId, "Escribe un monto verificado en pesos, mayor que cero y sin decimales.", true);
      return null;
    }
    body.amount_cop = value;
  }
  return body;
}

function settlementMessage(result) {
  if (result.result === "PARTIAL") return `Abono registrado, faltan ${formatCOP(result.missing_cop)}.`;
  if (result.result === "RESERVED") return result.calendar_synced === false
    ? `Confirmada; falta sincronizar calendario. ${result.detail || ""}`.trim()
    : "Reserva confirmada. Calendario sincronizado.";
  return labels.settlementResult[result.result] || "Comprobante revisado.";
}

async function settleReservationEvidence(id, evidenceId, decision, note, amount, button, card) {
  if (state.agent?.role !== "ADMIN") return;
  const body = evidenceReviewBody(decision, note, amount, "reservationDetailFeedback");
  if (!body) return;
  if (decision === "accept" && card.dataset.reviewId) body.review_id = card.dataset.reviewId;
  const request = state.reservationDetailRequest;
  await managementAction(button, card, decision === "accept" ? "Aceptando…" : "Rechazando…", "reservationDetailFeedback",
    async current => {
      const result = await managementRequest(`/api/admin/payment-evidence/${evidenceId}/${decision}`, { method: "POST", body: JSON.stringify(body) });
      if (!current() || request !== state.reservationDetailRequest) return;
      await reloadReservationAfterMutation(id, result.reservation, current, request);
      if (!current() || request !== state.reservationDetailRequest) return;
      managementFeedback("reservationDetailFeedback", settlementMessage(result));
      await loadReservations();
    }, "No se pudo revisar el comprobante");
}

async function reloadReservationAfterMutation(id, updated, current, request) {
  if (updated) renderReservationDetail({ ...state.reservationDetail, ...updated });
  try {
    const fresh = await managementRequest(`/api/admin/reservations/${id}`);
    if (current() && request === state.reservationDetailRequest) renderReservationDetail(fresh);
  } catch (error) {
    // The mutation succeeded; preserve its result even when a later read fails.
    if (current() && request === state.reservationDetailRequest) logEvent(`La operación se completó; no se pudo actualizar el detalle: ${error.message}`);
  }
}

async function scheduleReservation(event) {
  event.preventDefault();
  if (state.agent?.role !== "ADMIN" || !state.reservationDetail) return;
  const reservation = state.reservationDetail;
  const form = $("#reservationScheduleForm");
  if (!form.reportValidity()) return;
  let starts_at;
  try { starts_at = bogotaDateTimeToISO($("#reservationScheduleDate").value, $("#reservationScheduleTime").value); }
  catch (error) { managementFeedback("reservationDetailFeedback", error.message, true); return; }
  const request = state.reservationDetailRequest;
  await managementAction($("#scheduleReservation"), form, "Reprogramando…", "reservationDetailFeedback", async current => {
    const result = await managementRequest(`/api/admin/reservations/${reservation.reservation_id}/schedule`, { method: "PATCH", body: JSON.stringify({ starts_at }) });
    if (!current() || request !== state.reservationDetailRequest) return;
    await reloadReservationAfterMutation(reservation.reservation_id, result, current, request);
    if (!current() || request !== state.reservationDetailRequest) return;
    managementFeedback("reservationDetailFeedback", result.calendar_synced === false
      ? `Reserva reprogramada. Confirmada; falta sincronizar calendario. ${result.detail || ""}` : "Reserva reprogramada.");
    await loadReservations();
  }, "No se pudo reprogramar la reserva");
}

async function retryReservationCalendar(event) {
  if (state.agent?.role !== "ADMIN" || !state.reservationDetail) return;
  const reservation = state.reservationDetail;
  const request = state.reservationDetailRequest;
  await managementAction(event.currentTarget, $("#reservationCalendarActions"), "Sincronizando…", "reservationDetailFeedback", async current => {
    const result = await managementRequest(`/api/admin/reservations/${reservation.reservation_id}/sync-calendar`, { method: "POST" });
    if (!current() || request !== state.reservationDetailRequest) return;
    await reloadReservationAfterMutation(reservation.reservation_id, result, current, request);
    if (!current() || request !== state.reservationDetailRequest) return;
    managementFeedback("reservationDetailFeedback", result.calendar_synced === false
      ? `Confirmada; falta sincronizar calendario. ${result.detail || ""}` : "Calendario sincronizado.", result.calendar_synced === false);
    await loadReservations();
  }, "No se pudo sincronizar el calendario");
}

async function downloadEvidence(id, button, card, feedbackId) {
  await managementAction(button, card, "Descargando…", feedbackId, async current => {
    const response = await fetch(`/api/admin/payment-evidence/${id}/download`, { headers: sessionHeaders() });
    if (!response.ok) {
      const payload = (response.headers.get("content-type") || "").includes("application/json") ? await response.json() : await response.text();
      throw new Error(backendErrorText(payload?.detail || payload));
    }
    const blob = await response.blob();
    if (!current()) return;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = `comprobante-${id}`;
    link.click();
    URL.revokeObjectURL(url);
  }, "No se pudo descargar el comprobante");
}

async function cancelReservation(event) {
  event.preventDefault();
  const button = $("#cancelReservation");
  const reservation = state.reservationDetail;
  if (state.agent?.role !== "ADMIN" || button.disabled || !reservation) return;
  const note = $("#reservationCancelNote").value.trim();
  if (!note) {
    managementFeedback("reservationDetailFeedback", "Escribe el motivo de la cancelación.", true);
    return;
  }
  const request = state.reservationDetailRequest;
  button.disabled = true;
  button.textContent = "Guardando…";
  $("#reservationCancelNote").disabled = true;
  managementFeedback("reservationDetailFeedback", "");
  try {
    const updated = await managementRequest(`/api/admin/reservations/${reservation.reservation_id}/cancel`, {
      method: "POST", body: JSON.stringify({ note }),
    });
    if (request !== state.reservationDetailRequest) return;
    renderReservationDetail(updated);
    managementFeedback("reservationDetailFeedback", updated.calendar_synced === false
      ? "Reserva cancelada; falta retirar el evento del calendario."
      : "Reserva cancelada.", updated.calendar_synced === false);
    await loadReservations();
  } catch (error) {
    if (request === state.reservationDetailRequest) {
      managementFeedback("reservationDetailFeedback", `No se pudo cancelar la reserva: ${error.message}`, true);
    }
  } finally {
    button.disabled = false;
    button.textContent = "Cancelar reserva";
    $("#reservationCancelNote").disabled = false;
  }
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
    for (const value of [agent.name, label("role", agent.role),
      agent.has_credentials ? agent.document_id : "sin credenciales",
      label("active", agent.active), formatDate(agent.created_at)]) {
      const cell = document.createElement("td");
      cell.append(value);
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
  setText("resetRequestId", `ID de solicitud: ${summary.request_id}`);
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
  $("#refreshPlans").addEventListener("click", loadPlans);
  $("#refreshStaffNotifications").addEventListener("click", loadStaffNotifications);
  $("#notificationRecipientForm").addEventListener("submit", saveNotificationRecipient);
  $("#cancelRecipientEdit").addEventListener("click", resetRecipientForm);
  $("#refreshReservations").addEventListener("click", loadReservations);
  $("#manualReservationForm").addEventListener("submit", createManualReservation);
  $("#verifyManualReservation").addEventListener("click", verifyManualReservation);
  $("#reloadManualPlans").addEventListener("click", loadManualPlans);
  $("#manualReservationForm").addEventListener("input", () => managementFeedback("manualReservationFeedback", ""));
  for (const selector of ["#reservationStatusFilter", "#reservationBalanceFilter"]) $(selector).addEventListener("change", () => {
    state.reservationDetailRequest += 1;
    $("#reservationDetail").hidden = true;
    loadReservations();
  });
  for (const selector of ["#reservationFromFilter", "#reservationToFilter"]) $(selector).addEventListener("change", () => {
    state.reservationDetailRequest += 1;
    $("#reservationDetail").hidden = true;
    loadReservations();
  });
  $("#reservationScheduleForm").addEventListener("submit", scheduleReservation);
  $("#retryReservationCalendar").addEventListener("click", retryReservationCalendar);
  $("#reservationCancelForm").addEventListener("submit", cancelReservation);
  $("#closeReservationDetail").addEventListener("click", () => {
    state.reservationDetailRequest += 1;
    $("#reservationDetail").hidden = true;
  });
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

localizeControls();
applyConfigToForm();
bindUi();
applyAuthState();
refreshAll();
setInterval(refreshVisibleHandoffMessages, state.chatPollIntervalMs);

function resetRecipientForm() {
  const form = $("#notificationRecipientForm");
  form.reset();
  delete form.dataset.recipientId;
  form.elements.phone_number.disabled = false;
}

function editNotificationRecipient(recipient) {
  const form = $("#notificationRecipientForm");
  form.dataset.recipientId = recipient.id;
  form.elements.display_name.value = recipient.display_name;
  form.elements.phone_number.value = recipient.phone_number;
  form.elements.phone_number.disabled = true;
  for (const field of ["notify_on_evidence", "notify_on_payment_pending", "active"]) {
    form.elements[field].checked = recipient[field];
  }
  form.elements.display_name.focus();
}

function staffTable(headings) {
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const tr = document.createElement("tr");
  for (const title of headings) {
    const th = document.createElement("th"); th.textContent = title; tr.append(th);
  }
  head.append(tr);
  const body = document.createElement("tbody");
  table.append(head, body);
  return { table, body };
}

function staffRow(body, values) {
  const row = document.createElement("tr");
  for (const value of values) {
    const cell = document.createElement("td"); cell.textContent = value || "—"; row.append(cell);
  }
  body.append(row);
  return row;
}

async function loadStaffNotifications() {
  if (state.agent?.role !== "ADMIN") return;
  const token = state.sessionToken;
  const request = ++state.staffNotificationsRequest;
  setEmpty($("#notificationRecipientList"), "Cargando destinatarios…");
  setEmpty($("#staffNotificationList"), "Cargando avisos…");
  try {
    const [recipients, notifications] = await Promise.all([
      managementRequest("/api/admin/notification-recipients"),
      managementRequest("/api/admin/staff-notifications?limit=50"),
    ]);
    if (token !== state.sessionToken || request !== state.staffNotificationsRequest || state.agent?.role !== "ADMIN") return;
    const targets = staffTable(["Nombre", "Teléfono", "Comprobantes", "Solicitudes", "Activo", "Ventana abierta hasta", "Acciones"]);
    for (const recipient of recipients) {
      const row = staffRow(targets.body, [recipient.display_name, recipient.phone_number,
        recipient.notify_on_evidence ? "Sí" : "No", recipient.notify_on_payment_pending ? "Sí" : "No",
        recipient.active ? "Sí" : "No", recipient.ventana_abierta_hasta ? formatDate(recipient.ventana_abierta_hasta) : "Cerrada"]);
      const actions = document.createElement("td");
      actions.append(actionButton("Editar", () => editNotificationRecipient(recipient)),
        actionButton("Enviar prueba", event => sendStaffTest(recipient.id, event.currentTarget, row)));
      row.append(actions);
    }
    $("#notificationRecipientList").replaceChildren(targets.table);
    if (!recipients.length) setEmpty($("#notificationRecipientList"), "Aún no hay destinatarios.");
    const latest = staffTable(["Destinatario", "Teléfono", "Aviso", "Estado", "Canal", "Fecha"]);
    for (const notification of notifications) {
      staffRow(latest.body, [notification.display_name, notification.phone_number,
        labels.staffEventKind[notification.event_kind], labels.staffNotificationStatus[notification.status],
        labels.staffMessageKind[notification.message_kind] || "Por decidir", formatDate(notification.created_at)]);
    }
    $("#staffNotificationList").replaceChildren(latest.table);
    if (!notifications.length) setEmpty($("#staffNotificationList"), "Aún no hay avisos.");
  } catch (error) {
    if (token !== state.sessionToken || request !== state.staffNotificationsRequest) return;
    managementFeedback("staffNotificationFeedback", `No se pudieron cargar los avisos: ${error.message}`, true);
    setEmpty($("#notificationRecipientList"), "No se pudieron cargar los destinatarios.");
    setEmpty($("#staffNotificationList"), "No se pudieron cargar los avisos.");
  }
}

async function saveNotificationRecipient(event) {
  event.preventDefault();
  if (state.agent?.role !== "ADMIN") return;
  const form = event.currentTarget;
  const displayName = form.elements.display_name.value.trim();
  const phone = form.elements.phone_number.value.trim();
  if (!displayName || displayName.length > 120 || !phone) {
    managementFeedback("staffNotificationFeedback", "Escribe un nombre y un teléfono, por ejemplo +57 300 123 4567.", true);
    return;
  }
  const body = { display_name: displayName };
  for (const field of ["notify_on_evidence", "notify_on_payment_pending", "active"]) body[field] = form.elements[field].checked;
  const id = form.dataset.recipientId;
  if (!id) body.phone_number = phone;
  await managementAction($("button[type=submit]", form), form, "Guardando…", "staffNotificationFeedback", async current => {
    const saved = await managementRequest(`/api/admin/notification-recipients${id ? `/${id}` : ""}`, {
      method: id ? "PATCH" : "POST", body: JSON.stringify(body),
    });
    if (!current()) return;
    resetRecipientForm();
    await loadStaffNotifications();
    if (current()) managementFeedback("staffNotificationFeedback", saved.warning || "Destinatario guardado.");
  }, "No se pudo guardar el destinatario");
}

async function sendStaffTest(id, button, scope) {
  if (state.agent?.role !== "ADMIN") return;
  const token = state.sessionToken;
  await managementAction(button, scope, "Encolando…", "staffNotificationFeedback", async current => {
    await managementRequest(`/api/admin/notification-recipients/${id}/test`, { method: "POST" });
    if (!current()) return;
    await loadStaffNotifications();
    // The refreshed row replaces scope; session/role still own this acknowledgement.
    if (token === state.sessionToken && state.agent?.role === "ADMIN") managementFeedback("staffNotificationFeedback", "Prueba encolada.");
  }, "No se pudo encolar la prueba");
}
