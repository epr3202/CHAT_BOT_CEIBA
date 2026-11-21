// The operator's drafts live only in the authenticated page session.
export function createInbox({
  api,
  getAgent,
  ownedByMe,
  onTaken,
  onReturned,
  meta,
  updateCount,
  onClose,
  refreshCases,
  canTake,
  showSummary,
  openReassign,
}) {
  const box = document.querySelector("#activeChat");
  const $ = (selector) => box.querySelector(selector);
  const history = $("#activeHistory");
  const dayLabel = new Intl.DateTimeFormat("es-CO", {
    timeZone: "America/Bogota",
    dateStyle: "long",
  });
  const input = $("#replyText");
  const send = $("#replySend");
  const drafts = new Map();
  const sending = new Map();
  const assignments = new Map();
  let active = null,
    generation = 0,
    fetching = false,
    marking = false,
    snapshot = "";
  const isCurrent = (version) => active && generation === version;
  const owner = () => active && ownedByMe(active);
  function compose() {
    const mine = owner();
    const busy = assignments.has(active?.conversationId);
    $("#replyForm").hidden = !mine;
    $("#chatTake").hidden = !active || !canTake(active);
    $("#chatTake").disabled = busy;
    $("#chatTake").textContent = busy ? "Tomando…" : "Tomar para responder";
    $("#chatReturn").hidden = !mine;
    $("#chatReturn").disabled = busy || sending.has(active?.conversationId);
    $("#chatReassign").hidden = active?.handoffStatus !== "TAKEN" || getAgent()?.role !== "ADMIN";
    $("#chatReassign").disabled = busy || sending.has(active?.conversationId);
    $("#replyRestriction").textContent = mine ? ""
      : active?.handoffStatus === "TAKEN" ? (active.ownerId != null
        ? "Solo " + active.assignedTo + " puede responder en este chat." : "Actualiza la bandeja para consultar el responsable.")
      : active && canTake(active) ? "Toma esta conversación para habilitar tu respuesta."
      : "Esta conversación está disponible para consulta.";
    input.readOnly = busy || sending.has(active?.conversationId);
    send.disabled = input.readOnly || !input.value.trim();
    send.textContent = sending.has(active?.conversationId) ? "Enviando…" : "Enviar";
  }
  function close(notify = true) {
    generation++;
    active = null;
    fetching = false;
    marking = false;
    snapshot = "";
    box.hidden = true;
    history.replaceChildren();
    input.value = "";
    $("#replyStatus").textContent = "";
    document.querySelector("#admin").classList.remove("chatOpen");
    if (notify) onClose();
  }
  function open(item) {
    const change = item.conversationId !== active?.conversationId;
    if (change) close(false);
    active = item;
    box.hidden = false;
    document.querySelector("#admin").classList.add("chatOpen");
    $("#chatContact").textContent = item.customerName;
    $("#chatContext").textContent = [item.phone, owner() ? "Asignada a ti" : item.assignedTo]
      .filter(Boolean)
      .join(" · ");
    if (change) {
      history.textContent = "Cargando mensajes…";
      input.value = drafts.get(item.conversationId) || "";
      $("#chatContact").focus();
      load();
    }
    compose();
  }
  async function markVisible() {
    if (
      !active ||
      document.hidden ||
      marking ||
      box.closest("[hidden]") ||
      document.querySelector("dialog[open], #summaryModal:not([hidden])")
    )
      return;
    const viewport = history.getBoundingClientRect();
    const visible = Array.from(history.querySelectorAll("[data-unopened]"))
      .filter((row) => {
        const r = row.getBoundingClientRect();
        return (
          Math.min(viewport.bottom, r.bottom, innerHeight) -
            Math.max(0, r.top, viewport.top) >=
            Math.min(24, r.height) &&
          r.right > 0 &&
          r.left < innerWidth
        );
      })
      .slice(0, 200);
    if (!visible.length) return;
    const version = generation,
      id = active.conversationId;
    marking = true;
    try {
      await api(`/api/admin/conversations/${id}/messages/opened`, {
        method: "POST",
        body: JSON.stringify({
          message_ids: visible.map((row) => Number(row.dataset.unopened)),
        }),
      });
      if (!isCurrent(version)) return;
      for (const row of visible) {
        delete row.dataset.unopened;
        row.querySelector(".readState").textContent = "Abierto por ti";
      }
      updateCount(id, history.querySelectorAll("[data-unopened]").length);
    } catch {
      // Keep visible items unmarked. The next poll retries the same idempotent write.
    } finally {
      if (isCurrent(version)) marking = false;
    }
  }
  async function load() {
    if (
      !active ||
      fetching ||
      marking ||
      document.hidden ||
      box.closest("[hidden]")
    )
      return;
    const version = generation;
    fetching = true;
    try {
      const rows = await api(
        `/api/admin/conversations/${active.conversationId}/messages`,
      );
      if (!isCurrent(version)) return;
      const latest = JSON.stringify(rows);
      if (latest !== snapshot) {
        const nearEnd =
          !snapshot ||
          history.scrollHeight - history.scrollTop - history.clientHeight < 60;
        const offset = history.scrollTop;
        const fragment = document.createDocumentFragment();
        let previousDay = "";
        for (const message of rows) {
          const timestamp = new Date(message.created_at);
          const day = Number.isFinite(timestamp.getTime())
            ? dayLabel.format(timestamp)
            : "";
          if (day && day !== previousDay) {
            const separator = document.createElement("p");
            separator.className = "messageDay";
            separator.textContent = day;
            fragment.append(separator);
          }
          previousDay = day;
          const incoming = message.direction === "INBOUND";
          const bubble = document.createElement("article");
          bubble.className =
            "operatorMessage " + (incoming ? "incoming" : "outgoing");
          const heading = document.createElement("strong");
          heading.textContent = incoming
            ? active.customerName
            : "Equipo de La Ceiba";
          const body = document.createElement("p");
          body.textContent = message.body;
          const details = document.createElement("small");
          details.append(meta(message));
          const read = document.createElement("small");
          read.className = "readState";
          if (incoming) {
            read.textContent = message.opened_by_me
              ? "Abierto por ti"
              : "Sin abrir";
            if (!message.opened_by_me && /^message-\d+$/.test(message.id))
              bubble.dataset.unopened = message.id.slice(8);
          } else if (message.id.startsWith("message-")) {
            read.textContent = message.read_by_contact
              ? "Leído por el contacto"
              : "Sin confirmación de lectura";
          }
          bubble.append(heading, body, details, read);
          fragment.append(bubble);
        }
        if (!rows.length) fragment.append("Todavía no hay mensajes.");
        history.replaceChildren(fragment);
        updateCount(
          active.conversationId,
          history.querySelectorAll("[data-unopened]").length,
        );
        snapshot = latest;
        history.scrollTop = nearEnd ? history.scrollHeight : offset;
      }
      $("#historyStatus").textContent = "";
      await markVisible();
    } catch (error) {
      if (isCurrent(version)) {
        if (!snapshot) history.replaceChildren();
        $("#historyStatus").textContent =
          "No se pudo actualizar el historial. " + error.message;
      }
    } finally {
      if (isCurrent(version)) fetching = false;
    }
  }
  input.oninput = () => {
    if (active) drafts.set(active.conversationId, input.value);
    compose();
  };
  $("#replyForm").onsubmit = async (event) => {
    event.preventDefault();
    if (!owner() || send.disabled) return;
    const id = active.conversationId,
      request = Symbol();
    const currentUser = () => sending.get(id) === request;
    const viewing = () => currentUser() && active?.conversationId === id;
    const value = input.value.trim();
    sending.set(id, request);
    compose();
    $("#replyStatus").textContent = "Enviando…";
    try {
      await api(`/api/admin/conversations/${id}/messages`, {
        method: "POST",
        body: JSON.stringify({ text: value }),
      });
      if (!currentUser()) return;
      drafts.delete(id);
      if (viewing()) {
        input.value = "";
        $("#replyStatus").textContent = "Respuesta en cola de envío.";
        await load();
      }
    } catch (error) {
      if (viewing()) {
        $("#replyStatus").textContent = error.message;
        if (error.status === 403) open({ ...active, ownerId: null, assignedTo: "Asignación por verificar" });
        if (error.status === 403 || error.status === 409) await refreshCases();
      }
    } finally {
      if (currentUser()) {
        sending.delete(id);
        if (active?.conversationId === id) compose();
      }
    }
  };
  input.onkeydown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      $("#replyForm").requestSubmit();
    }
  };
  $("#chatBack").onclick = () => close();
  $("#chatRefresh").onclick = load;
  function applyAssignment(handoff) {
    if (!active || active.conversationId !== handoff.conversation_id) return;
    const returned = handoff.status === "RETURNED";
    open({
      ...active,
      id: handoff.id,
      status: returned ? "BOT_ACTIVE" : "HUMAN_ACTIVE",
      handoffStatus: handoff.status,
      ownerId: handoff.assigned_agent?.id,
      assignedTo: handoff.assigned_agent?.name || handoff.assigned_to || (returned ? "Bot activo" : "Sin asignar"),
      summary: handoff.summary ?? active.summary,
      priority: handoff.priority ?? active.priority,
      reason: handoff.reason ?? active.reason,
      reasonKind: handoff.reason ? "handoffReason" : active.reasonKind,
    });
  }
  async function changeAssignment(returning) {
    const item = active;
    if (!item || assignments.has(item.conversationId)) return;
    if (returning) {
      if (!owner() || sending.has(item.conversationId) || !window.confirm("¿Devolver este caso al bot?")) return;
    } else if (!canTake(item)) return;
    const id = item.conversationId, request = Symbol();
    const current = () => assignments.get(id) === request;
    assignments.set(id, request);
    compose();
    $("#replyStatus").textContent = returning ? "Devolviendo al bot…" : "Asignando conversación…";
    try {
      const url = returning ? `/api/admin/handoffs/${item.id}/return`
        : item.handoffStatus === "PENDING" ? `/api/admin/handoffs/${item.id}/take`
        : `/api/admin/conversations/${id}/take`;
      const options = { method: "POST" };
      if (returning) options.body = JSON.stringify({ resolution: "Cliente atendido y devuelto al bot." });
      const handoff = await api(url, options);
      if (!current()) return;
      applyAssignment(handoff);
      if (active?.conversationId === id) {
        $("#replyStatus").textContent = returning ? "Caso devuelto al bot." : "Caso asignado a ti.";
        if (returning) onReturned();
        else {
          onTaken();
          input.focus();
        }
      }
      await refreshCases(!returning && active?.conversationId === id ? id : null);
    } catch (error) {
      if (current() && active?.conversationId === id) {
        $("#replyStatus").textContent = error.message;
        if (error.status === 403 || error.status === 409) await refreshCases();
      }
    } finally {
      if (current()) {
        assignments.delete(id);
        if (active?.conversationId === id) compose();
      }
    }
  }
  $("#chatTake").onclick = () => changeAssignment(false);
  $("#chatReturn").onclick = () => changeAssignment(true);
  $("#chatReassign").onclick = () => { if (active) openReassign(active); };
  $("#chatSummary").onclick = () => { if (active) showSummary(active); };
  history.addEventListener("scroll", markVisible);
  window.addEventListener("resize", markVisible);
  document.addEventListener("visibilitychange", load);
  return {
    open,
    applyAssignment,
    close,
    load,
    selected: () => active?.conversationId,
    reset() {
      close(false);
      drafts.clear();
      sending.clear();
      assignments.clear();
    },
  };
}
