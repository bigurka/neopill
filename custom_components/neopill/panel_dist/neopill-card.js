// NeoPill patient summary Lovelace card: doses due now, next dose, low-stock/restock
// warnings, with one-tap take/missed actions. Plain web component, no build step -
// served as-is from the same versioned static path as the full panel.
import { api } from "./api.js";
import { resolveLang, translate } from "./i18n.js";

const CARD_TAG = "neopill-patient-card";
const EDITOR_TAG = "neopill-patient-card-editor";
const REFRESH_MS = 15000;

function fmtNextDose(iso, lang) {
  if (!iso) return "-";
  const date = new Date(iso);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) {
    return date.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleString(lang, {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

class NeoPillPatientCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement(EDITOR_TAG);
  }

  static getStubConfig() {
    return { patient_id: "" };
  }

  setConfig(config) {
    if (!config || !config.patient_id) {
      throw new Error("neopill-patient-card: patient_id is required");
    }
    this._config = config;
    this._patientId = config.patient_id;
    this._patientName = config.title || null;
    this._medications = null;
    this._error = null;
    this._render();
  }

  set hass(hass) {
    const firstTime = !this._hass;
    this._hass = hass;
    if (firstTime) {
      this._fetch();
      this._scheduleRefresh();
    }
  }

  getCardSize() {
    return 3;
  }

  connectedCallback() {
    this._scheduleRefresh();
  }

  disconnectedCallback() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  }

  _scheduleRefresh() {
    if (this._timer) clearInterval(this._timer);
    this._timer = setInterval(() => this._fetch(), REFRESH_MS);
  }

  async _fetch() {
    if (!this._hass || !this._patientId || this._fetching) return;
    this._fetching = true;
    try {
      const needsName = !this._config.title;
      const [patients, medications] = await Promise.all([
        needsName ? api.listPatients(this._hass) : Promise.resolve(null),
        api.listMedications(this._hass, this._patientId),
      ]);
      if (patients) {
        const patient = patients.find((p) => p.id === this._patientId);
        this._patientName = patient ? patient.name : this._patientId;
      }
      this._medications = medications;
      this._error = null;
    } catch (err) {
      this._error = (err && err.message) || String(err);
    } finally {
      this._fetching = false;
      this._render();
    }
  }

  async _handleAction(action, medicationId) {
    if (!this._hass) return;
    try {
      if (action === "take") {
        await api.takeDose(this._hass, medicationId);
      } else if (action === "missed") {
        await api.markMissed(this._hass, medicationId);
      } else if (action === "take-all" || action === "missed-all") {
        const due = (this._medications || []).filter((m) => m.is_due);
        const fn = action === "take-all" ? api.takeDose : api.markMissed;
        for (const m of due) {
          await fn(this._hass, m.id);
        }
      }
    } finally {
      this._fetch();
    }
  }

  _lang() {
    return resolveLang(this._hass);
  }

  _t(key, vars) {
    return translate(this._lang(), key, vars);
  }

  _render() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-action]");
        if (!btn) return;
        this._handleAction(btn.dataset.action, btn.dataset.id);
      });
    }
    const title = this._config && this._config.title ? this._config.title : this._patientName || "";

    let body;
    if (this._error) {
      body = `<div class="msg error">${this._t("card_error", { error: this._error })}</div>`;
    } else if (this._medications === null) {
      body = `<div class="msg">${this._t("loading")}</div>`;
    } else {
      body = this._renderBody();
    }

    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <ha-card header="${title}">
        <div class="content">${body}</div>
      </ha-card>
    `;
  }

  _renderBody() {
    const lang = this._lang();
    const meds = this._medications || [];
    const due = meds.filter((m) => m.is_due);
    const upcoming = meds
      .filter((m) => !m.is_due && m.next_dose_at)
      .sort((a, b) => new Date(a.next_dose_at) - new Date(b.next_dose_at));
    const lowStock = meds.filter((m) => m.is_low_stock);

    const sections = [];

    if (due.length) {
      const rows = due
        .map(
          (m) => `
        <div class="row due-row">
          <span class="name">${m.display_name || m.name}</span>
          <span class="actions">
            <button class="iconbtn take" data-action="take" data-id="${m.id}" title="${this._t(
            "take_dose"
          )}">✓</button>
            <button class="iconbtn missed" data-action="missed" data-id="${m.id}" title="${this._t(
            "mark_missed"
          )}">✕</button>
          </span>
        </div>`
        )
        .join("");
      sections.push(`
        <section>
          <div class="section-head">
            <h4>${this._t("card_due_now")}</h4>
            <span class="actions">
              <button class="iconbtn take" data-action="take-all" title="${this._t(
                "card_take_all_title"
              )}">✓</button>
              <button class="iconbtn missed" data-action="missed-all" title="${this._t(
                "card_mark_all_missed_title"
              )}">✕</button>
            </span>
          </div>
          ${rows}
        </section>
      `);
    }

    if (upcoming.length) {
      const rows = upcoming
        .slice(0, 4)
        .map(
          (m) => `
        <div class="row">
          <span class="name">${m.display_name || m.name}</span>
          <span class="when">${fmtNextDose(m.next_dose_at, lang)}</span>
        </div>`
        )
        .join("");
      sections.push(`
        <section>
          <h4>${this._t("card_next_dose")}</h4>
          ${rows}
        </section>
      `);
    }

    if (lowStock.length) {
      const chips = lowStock
        .map((m) => `<span class="chip warn">${m.display_name || m.name}</span>`)
        .join("");
      sections.push(`
        <section>
          <h4>${this._t("card_low_stock")}</h4>
          <div class="chips">${chips}</div>
        </section>
      `);
    }

    if (!sections.length) {
      sections.push(`<div class="msg ok">${this._t("card_all_ok")}</div>`);
    }

    sections.push(`
      <a class="open-panel" href="/neopill">${this._t("card_open_panel")} →</a>
    `);

    return sections.join("");
  }

  _styles() {
    return `
      ha-card { display: flex; flex-direction: column; }
      .content { padding: 0 16px 16px; }
      .msg { opacity: 0.7; font-size: 14px; padding: 4px 0; }
      .msg.error { color: var(--error-color, #db4437); opacity: 1; }
      .msg.ok { color: var(--success-color, #43a047); }
      section { margin-bottom: 12px; }
      section:last-of-type { margin-bottom: 4px; }
      h4 {
        margin: 0 0 6px 0;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        opacity: 0.6;
        font-weight: 600;
      }
      .section-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 6px;
      }
      .section-head h4 { margin: 0; }
      .row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 6px 0;
        border-bottom: 1px solid var(--divider-color, rgba(127, 127, 127, 0.2));
        font-size: 14px;
      }
      .row:last-child { border-bottom: none; }
      .row .name { flex: 1; }
      .row .when { opacity: 0.75; font-size: 13px; }
      .actions { display: flex; gap: 6px; }
      button.iconbtn {
        border: none;
        border-radius: 6px;
        width: 30px;
        height: 30px;
        font-size: 15px;
        font-weight: 700;
        cursor: pointer;
        line-height: 1;
      }
      button.iconbtn.take { background: rgba(67, 160, 71, 0.18); color: var(--success-color, #43a047); }
      button.iconbtn.missed { background: rgba(219, 68, 55, 0.14); color: var(--error-color, #db4437); }
      button.iconbtn:hover { filter: brightness(1.15); }
      .chips { display: flex; flex-wrap: wrap; gap: 6px; }
      .chip {
        font-size: 12px;
        padding: 3px 10px;
        border-radius: 999px;
      }
      .chip.warn { background: rgba(255, 176, 32, 0.18); color: var(--warning-color, #ffb020); }
      .open-panel {
        display: inline-block;
        margin-top: 4px;
        font-size: 12.5px;
        color: var(--primary-color, #03a9f4);
        text-decoration: none;
      }
      .open-panel:hover { text-decoration: underline; }
    `;
  }
}

class NeoPillPatientCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    const firstTime = !this._hass;
    this._hass = hass;
    if (firstTime) this._loadPatients();
  }

  async _loadPatients() {
    try {
      this._patients = await api.listPatients(this._hass);
    } catch (err) {
      this._patients = [];
    }
    this._render();
  }

  _lang() {
    return resolveLang(this._hass);
  }

  _t(key, vars) {
    return translate(this._lang(), key, vars);
  }

  _emitChange(patch) {
    this._config = { ...this._config, ...patch };
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: this._config },
        bubbles: true,
        composed: true,
      })
    );
  }

  _render() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("change", (e) => {
        const el = e.target.closest("[data-field]");
        if (!el) return;
        this._emitChange({ [el.dataset.field]: el.value });
      });
    }
    const patients = this._patients || [];
    const options = patients
      .map(
        (p) =>
          `<option value="${p.id}" ${p.id === this._config.patient_id ? "selected" : ""}>${p.name}</option>`
      )
      .join("");

    this.shadowRoot.innerHTML = `
      <style>
        .field { margin-bottom: 12px; display: flex; flex-direction: column; gap: 4px; }
        label { font-size: 12px; opacity: 0.75; }
        select, input {
          padding: 8px;
          border-radius: 6px;
          border: 1px solid var(--divider-color, #3a3f4d);
          background: var(--card-background-color, transparent);
          color: inherit;
          font: inherit;
        }
        .hint { font-size: 12px; opacity: 0.6; }
      </style>
      <div class="field">
        <label>${this._t("editor_patient_label")}</label>
        ${
          patients.length
            ? `<select data-field="patient_id"><option value="">-</option>${options}</select>`
            : `<span class="hint">${this._t("editor_no_patients")}</span>`
        }
      </div>
      <div class="field">
        <label>${this._t("editor_title_label")}</label>
        <input type="text" data-field="title" value="${this._config.title || ""}" />
      </div>
    `;
  }
}

const STOCK_CARD_TAG = "neopill-stock-card";

// All-patients stock overview: one mini-table per patient, medications sorted by
// urgency (days remaining ascending) within each. No config required - meant to be
// dropped in as-is, and is what the dashboard strategy auto-generates a dedicated
// "Stock" view around.
class NeoPillStockCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    this._config = config || {};
    this._groups = null;
    this._error = null;
    this._render();
  }

  set hass(hass) {
    const firstTime = !this._hass;
    this._hass = hass;
    if (firstTime) {
      this._fetch();
      this._scheduleRefresh();
    }
  }

  getCardSize() {
    return 4;
  }

  connectedCallback() {
    this._scheduleRefresh();
  }

  disconnectedCallback() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  }

  _scheduleRefresh() {
    if (this._timer) clearInterval(this._timer);
    this._timer = setInterval(() => this._fetch(), REFRESH_MS);
  }

  async _fetch() {
    if (!this._hass || this._fetching) return;
    this._fetching = true;
    try {
      const [patients, medications] = await Promise.all([
        api.listPatients(this._hass),
        api.listMedications(this._hass),
      ]);
      const byPatient = new Map(patients.map((p) => [p.id, []]));
      for (const m of medications) {
        const rows = byPatient.get(m.patient_id);
        if (!rows) continue;
        rows.push({
          name: m.display_name || m.name,
          daysRemaining: m.days_remaining,
          stock: m.stock_quantity,
          isLowStock: m.is_low_stock,
        });
      }
      const byUrgency = (a, b) => {
        const da = a.daysRemaining === null || a.daysRemaining === undefined ? Infinity : a.daysRemaining;
        const db = b.daysRemaining === null || b.daysRemaining === undefined ? Infinity : b.daysRemaining;
        return da - db;
      };
      this._groups = patients
        .map((p) => ({ patientName: p.name, rows: (byPatient.get(p.id) || []).sort(byUrgency) }))
        .filter((g) => g.rows.length);
      this._error = null;
    } catch (err) {
      this._error = (err && err.message) || String(err);
    } finally {
      this._fetching = false;
      this._render();
    }
  }

  _lang() {
    return resolveLang(this._hass);
  }

  _t(key, vars) {
    return translate(this._lang(), key, vars);
  }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const title = this._config && this._config.title ? this._config.title : this._t("stock_card_title");

    let body;
    if (this._error) {
      body = `<div class="msg error">${this._t("card_error", { error: this._error })}</div>`;
    } else if (this._groups === null) {
      body = `<div class="msg">${this._t("loading")}</div>`;
    } else if (!this._groups.length) {
      body = `<div class="msg">${this._t("stock_empty")}</div>`;
    } else {
      body = this._groups
        .map((group) => {
          const rows = group.rows
            .map((r) => {
              const cls = r.isLowStock ? "warn" : "";
              const days =
                r.daysRemaining === null || r.daysRemaining === undefined
                  ? "-"
                  : Math.round(r.daysRemaining * 10) / 10;
              return `
            <tr class="${cls}">
              <td>${r.name}</td>
              <td class="num">${days}</td>
              <td class="num">${r.stock}</td>
            </tr>`;
            })
            .join("");
          return `
        <section>
          <h4>${group.patientName}</h4>
          <table>
            <thead>
              <tr>
                <th>${this._t("stock_col_medication")}</th>
                <th class="num">${this._t("stock_col_days")}</th>
                <th class="num">${this._t("stock_col_stock")}</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </section>`;
        })
        .join("");
    }

    this.shadowRoot.innerHTML = `
      <style>
        ha-card { display: flex; flex-direction: column; }
        .content { padding: 0 16px 16px; }
        .msg { opacity: 0.7; font-size: 14px; padding: 4px 0; }
        .msg.error { color: var(--error-color, #db4437); opacity: 1; }
        section { margin-bottom: 14px; }
        section:last-of-type { margin-bottom: 4px; }
        h4 {
          margin: 0 0 6px 0;
          font-size: 12px;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          opacity: 0.6;
          font-weight: 600;
        }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(127, 127, 127, 0.2)); }
        th.num, td.num { text-align: right; }
        tr.warn td { color: var(--warning-color, #ffb020); }
      </style>
      <ha-card header="${title}">
        <div class="content">${body}</div>
      </ha-card>
    `;
  }
}

if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, NeoPillPatientCard);
}
if (!customElements.get(EDITOR_TAG)) {
  customElements.define(EDITOR_TAG, NeoPillPatientCardEditor);
}
if (!customElements.get(STOCK_CARD_TAG)) {
  customElements.define(STOCK_CARD_TAG, NeoPillStockCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === CARD_TAG)) {
  window.customCards.push({
    type: CARD_TAG,
    name: "NeoPill - Riepilogo paziente",
    description: "Farmaci da assumere ora, prossima dose e avvisi scorte per un paziente NeoPill.",
    preview: false,
  });
}
if (!window.customCards.some((c) => c.type === STOCK_CARD_TAG)) {
  window.customCards.push({
    type: STOCK_CARD_TAG,
    name: "NeoPill - Situazione scorte",
    description: "Tabella di tutti i farmaci di tutti i pazienti, ordinata per urgenza di rifornimento.",
    preview: false,
  });
}
