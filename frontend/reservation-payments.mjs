import {formatCOP, formatDate} from "./labels.mjs";

const byId = id => document.getElementById(id);
export const balance = reservation => Math.max(0, reservation.price_cop - reservation.amount_paid_cop);

export function renderAccount(reservation) {
  const closed = ["CANCELLED", "EXPIRED"].includes(reservation.status);
  const money = byId("reservationMoney");
  money.replaceChildren();
  for (const [title, amount] of [
    ["Precio total", reservation.price_cop], ["Pagado", reservation.amount_paid_cop],
    [closed ? "Importe sin abonar al cierre" : "Saldo pendiente", balance(reservation)],
  ]) {
    const group = document.createElement("div"), term = document.createElement("dt"), value = document.createElement("dd");
    term.textContent = title; value.textContent = formatCOP(amount);
    group.append(term, value); money.append(group);
  }
  const ledger = byId("manualPaymentHistory");
  ledger.replaceChildren();
  const entries = reservation.manual_payments || [];
  if (!entries.length) ledger.textContent = "Aún no hay abonos manuales registrados.";
  const methods = byId("manualPaymentMethod").options;
  for (const payment of entries) {
    const entry = document.createElement("article"), method = document.createElement("strong");
    const value = document.createElement("b"), meta = document.createElement("small");
    method.textContent = Array.from(methods).find(o => o.value === payment.method)?.textContent || payment.method;
    value.textContent = formatCOP(payment.amount_cop);
    meta.textContent = [formatDate(payment.created_at), payment.recorded_by].join(" · ");
    entry.append(method, value, meta);
    if (payment.note) {
      const note = document.createElement("p"); note.textContent = payment.note; entry.append(note);
    }
    ledger.append(entry);
  }
  byId("openManualPayment").hidden = !["PAYMENT_PENDING","PAYMENT_REVIEW","RESERVED"].includes(reservation.status) || balance(reservation) <= 0;
}

export function bindManualPayment({selected, api, refresh, onApplied}) {
  const dialog = byId("manualPaymentDialog"), form = byId("manualPaymentForm"), amount = byId("manualPaymentAmount");
  const submit = byId("submitManualPayment"), close = byId("closeManualPayment"), feedback = byId("manualPaymentFeedback");
  const reload = byId("refreshManualPayment");
  let draft = null, busy = false;
  function project() {
    if (!draft) return;
    const value = amount.valueAsNumber, limit = balance(draft.row);
    const valid = Number.isSafeInteger(value) && value > 0 && value <= limit;
    submit.disabled = busy || !valid;
    byId("manualPaymentRemaining").textContent = amount.value && !valid ? "Revisa el monto" : formatCOP(limit - (valid ? value : 0));
  }
  function toggleBusy(active) {
    busy = active;
    for (const control of [amount, byId("manualPaymentMethod"), byId("manualPaymentNote"), close]) control.disabled = active;
    submit.textContent = active ? "Registrando…" : "Confirmar abono";
    form.setAttribute("aria-busy", String(active));
    project();
  }
  byId("openManualPayment").onclick = () => {
    const row = selected();
    if (!row || !balance(row)) return;
    draft = {id: crypto.randomUUID(), row};
    form.reset(); feedback.hidden = true; reload.hidden = true;
    byId("manualPaymentFor").textContent = [row.customer_name || row.customer_phone, row.plan_name].filter(Boolean).join(" · ");
    amount.max = String(balance(row));
    toggleBusy(false);
    dialog.showModal(); amount.focus();
  };
  reload.onclick = () => {
    if (draft && !busy) {
      const id = draft.row.reservation_id;
      dialog.close();
      refresh(id);
    }
  };
  close.onclick = () => { if (!busy) dialog.close(); };
  dialog.addEventListener("cancel", event => { if (busy) event.preventDefault(); });
  dialog.addEventListener("close", () => { draft = null; });
  amount.oninput = project;
  form.onsubmit = async event => {
    event.preventDefault(); project();
    if (!draft || submit.disabled || busy || !form.reportValidity()) return;
    const attempt = draft, row = attempt.row;
    toggleBusy(true); feedback.hidden = true;
    try {
      const result = await api(`/api/admin/reservations/${row.reservation_id}/payments`, {
        method: "POST", body: JSON.stringify({payment_id: attempt.id, method: byId("manualPaymentMethod").value,
          amount_cop: amount.valueAsNumber, expected_paid_cop: row.amount_paid_cop, note: byId("manualPaymentNote").value.trim() || null}),
      });
      if (draft === attempt && selected()?.reservation_id === row.reservation_id && dialog.open) {
        dialog.close();
        await onApplied(result);
      }
    } catch (error) {
      if (draft === attempt && dialog.open) {
        reload.hidden = error.status !== 409;
        feedback.textContent = error.message;
        feedback.hidden = false;
      }
    } finally {
      if (draft === attempt) toggleBusy(false);
    }
  };
}
