// The operator's drafts live only in the authenticated page session.
export function createInbox({
  api,
  getAgent,
  meta,
  updateCount,
  onClose,
  refreshCases,
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
  let active = null,
    generation = 0,
    fetching = false,
    marking = false,
    snapshot = "";
  const isCurrent = (version) => active && generation === version;
  const owner = () =>
    active?.handoffStatus === "TAKEN" && active.ownerId === getAgent()?.id;
  function compose() {
    $("#replyForm").hidden = !owner();
    input.readOnly = sending.has(active?.conversationId);
    send.disabled = input.readOnly || !input.value.trim();
    send.textContent = input.readOnly ? "Enviando…" : "Enviar";
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
    $("#chatContext").textContent = [item.phone, item.assignedTo]
      .filter(Boolean)
      .join(" · ");
    $("#replyRestriction").textContent = owner()
      ? ""
      : "Para responder, el caso debe estar asignado a ti.";
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
      if (viewing()) $("#replyStatus").textContent = error.message;
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
  $("#chatTake").onclick = async () => {
    if (!active) return;
    const item = active,
      version = generation,
      btn = $("#chatTake");
    btn.disabled = true;
    try {
      const url =
        item.handoffStatus === "PENDING"
          ? `/api/admin/handoffs/${item.id}/take`
          : `/api/admin/conversations/${item.conversationId}/take`;
      const handoff = await api(url, { method: "POST" });
      if (isCurrent(version)) {
        open({
          ...item,
          id: handoff.id,
          status: "HUMAN_ACTIVE",
          handoffStatus: handoff.status,
          ownerId: handoff.assigned_agent?.id,
          assignedTo: handoff.assigned_to,
        });
        btn.hidden = true;
        $("#replyStatus").textContent = "Caso asignado a ti.";
        await refreshCases();
      }
    } catch (error) {
      if (isCurrent(version)) $("#replyStatus").textContent = error.message;
    } finally {
      btn.disabled = false;
    }
  };
  history.addEventListener("scroll", markVisible);
  window.addEventListener("resize", markVisible);
  document.addEventListener("visibilitychange", load);
  return {
    open(item, canTake) {
      open(item);
      $("#chatTake").hidden = !canTake;
    },
    close,
    load,
    selected: () => active?.conversationId,
    reset() {
      close(false);
      drafts.clear();
      sending.clear();
    },
  };
}
