// NeoPill sidebar panel - plain Web Component, no build step, no external dependencies.
// Talks to the backend exclusively through the neopill/* websocket commands (api.js).

import { api } from "./api.js";
import { styles } from "./styles.js";

const EVENT_LABELS = {
  assunta: "Assunta",
  non_assunta: "Non assunta",
  rifornimento: "Rifornimento",
  scorta_esaurita: "Scorta esaurita",
};

function fmtDateTime(iso) {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" });
  } catch (err) {
    return iso;
  }
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

class NeoPillPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._patients = [];
    this._selectedPatientId = null;
    this._medications = [];
    this._history = [];
    this._loadingPatients = false;
    this._loadingMedications = false;
    this._error = null;
    this._patientDraft = null; // { id: null|string, name: "" }
    this._medDraft = null; // full medication draft
    this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._init();
    }
  }

  get hass() {
    return this._hass;
  }

  get _isAdmin() {
    return !!(this._hass && this._hass.user && this._hass.user.is_admin);
  }

  async _init() {
    this.shadowRoot.innerHTML = `
      <style>${styles}</style>
      <div class="header">
        <svg class="pill-logo" viewBox="0 0 256 256" xmlns="http://www.w3.org/2000/svg">
          <g transform="translate(128,128) rotate(-40)">
            <rect x="-84" y="-24" width="84" height="48" rx="24" fill="#1de9ff"/>
            <rect x="0" y="-24" width="84" height="48" rx="24" fill="#ff5b5b"/>
          </g>
        </svg>
        <h1>NeoPill</h1>
        <button class="icon" data-action="refresh" title="Aggiorna">&#x21bb;</button>
      </div>
      <div class="layout">
        <div class="sidebar" id="sidebar"></div>
        <div class="main" id="main"></div>
      </div>
      <dialog id="patientDialog"></dialog>
      <dialog id="medDialog"></dialog>
    `;

    this.shadowRoot.addEventListener("click", (e) => this._handleClick(e));
    this.shadowRoot.addEventListener("submit", (e) => this._handleSubmit(e));
    this.shadowRoot.addEventListener("change", (e) => this._handleChange(e));

    await this._reloadPatients();
  }

  // ---- Data loading ----

  async _reloadPatients() {
    this._loadingPatients = true;
    this._renderSidebar();
    try {
      this._patients = await api.listPatients(this._hass);
      this._error = null;
    } catch (err) {
      this._error = `Errore nel caricamento pazienti: ${err.message || err}`;
    }
    this._loadingPatients = false;
    if (this._selectedPatientId && !this._patients.some((p) => p.id === this._selectedPatientId)) {
      this._selectedPatientId = null;
      this._medications = [];
      this._history = [];
    }
    this._renderSidebar();
    this._renderMain();
  }

  async _selectPatient(patientId) {
    this._selectedPatientId = patientId;
    this._renderSidebar();
    await this._reloadMedications();
  }

  async _reloadMedications() {
    if (!this._selectedPatientId) {
      this._medications = [];
      this._history = [];
      this._renderMain();
      return;
    }
    this._loadingMedications = true;
    this._renderMain();
    try {
      this._medications = await api.listMedications(this._hass, this._selectedPatientId);
      const end = new Date();
      const start = new Date(end.getTime() - 30 * 24 * 60 * 60 * 1000);
      this._history = await api.listEvents(
        this._hass,
        start.toISOString(),
        end.toISOString(),
        this._selectedPatientId
      );
      this._error = null;
    } catch (err) {
      this._error = `Errore nel caricamento farmaci: ${err.message || err}`;
    }
    this._loadingMedications = false;
    this._renderMain();
  }

  // ---- Rendering: sidebar ----

  _renderSidebar() {
    const sidebar = this.shadowRoot.getElementById("sidebar");
    if (!sidebar) return;
    const rows = this._patients
      .map((p) => {
        const selected = p.id === this._selectedPatientId ? "selected" : "";
        const adminActions = this._isAdmin
          ? `<span class="actions">
              <button class="iconbtn" data-action="edit-patient" data-id="${p.id}" title="Rinomina">&#9998;</button>
              <button class="iconbtn" data-action="delete-patient" data-id="${p.id}" title="Elimina">&#128465;</button>
            </span>`
          : "";
        return `<div class="patient-row ${selected}" data-action="select-patient" data-id="${p.id}">
          <span class="name">${esc(p.name)}</span>
          ${adminActions}
        </div>`;
      })
      .join("");

    sidebar.innerHTML = `
      ${this._loadingPatients ? `<div class="empty-state">Caricamento...</div>` : rows || `<div class="empty-state">Nessun paziente</div>`}
      ${
        this._isAdmin
          ? `<div class="add-patient-row"><button data-action="new-patient">+ Paziente</button></div>`
          : ""
      }
    `;
  }

  // ---- Rendering: main ----

  _renderMain() {
    const main = this.shadowRoot.getElementById("main");
    if (!main) return;

    const errorBanner = this._error ? `<div class="error-banner">${esc(this._error)}</div>` : "";

    if (!this._selectedPatientId) {
      main.innerHTML = `${errorBanner}<div class="empty-state">Seleziona un paziente dalla lista, oppure aggiungine uno.</div>`;
      return;
    }

    if (this._loadingMedications) {
      main.innerHTML = `${errorBanner}<div class="empty-state">Caricamento...</div>`;
      return;
    }

    const cards = this._medications.map((m) => this._renderMedicationCard(m)).join("");
    const addButton = this._isAdmin
      ? `<button class="primary" data-action="new-medication">+ Farmaco</button>`
      : "";

    const historyRows = [...this._history]
      .reverse()
      .slice(0, 50)
      .map(
        (e) => `<tr>
          <td>${fmtDateTime(e.timestamp)}</td>
          <td>${esc(EVENT_LABELS[e.type] || e.type)}</td>
          <td>${esc(e.medication_name)}</td>
          <td>${e.amount !== undefined ? e.amount : e.amount_added !== undefined ? "+" + e.amount_added : ""}</td>
        </tr>`
      )
      .join("");

    main.innerHTML = `
      ${errorBanner}
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
        <div></div>
        ${addButton}
      </div>
      ${cards || `<div class="empty-state">Nessun farmaco per questo paziente.</div>`}
      <section class="history">
        <h3>Storico (ultimi 30 giorni)</h3>
        ${
          historyRows
            ? `<table class="history"><thead><tr><th>Quando</th><th>Evento</th><th>Farmaco</th><th>Qtà</th></tr></thead><tbody>${historyRows}</tbody></table>`
            : `<div class="empty-state">Nessun evento registrato.</div>`
        }
      </section>
    `;
  }

  _renderMedicationCard(m) {
    const badges = [
      m.is_due ? `<span class="badge due">Da assumere</span>` : "",
      m.is_low_stock ? `<span class="badge low-stock">Scorta in esaurimento</span>` : "",
    ].join("");

    const scheduleText =
      m.dose_schedule.schedule_type === "fixed_times"
        ? `Orari: ${m.dose_schedule.fixed_times.join(", ") || "-"}`
        : `Ogni ${m.dose_schedule.interval_hours ?? "-"} ore dall'ultima assunzione`;

    const adminActions = this._isAdmin
      ? `<button class="small" data-action="edit-medication" data-id="${m.id}">Modifica</button>
         <button class="small danger" data-action="delete-medication" data-id="${m.id}">Elimina</button>`
      : "";

    return `
      <div class="med-card" data-medication-id="${m.id}">
        <div class="title-row">
          <span class="name">${esc(m.name)}</span>
          ${badges}
        </div>
        <div class="meta">
          <span>Scorta: <b>${m.stock_quantity}</b> unità</span>
          <span>Dose: <b>${m.dose_amount}</b></span>
          <span>${esc(scheduleText)}</span>
          <span>Giorni rimanenti: <b>${m.days_remaining !== null ? Math.floor(m.days_remaining) : "-"}</b></span>
          <span>Prossima: <b>${fmtDateTime(m.next_dose_at)}</b></span>
        </div>
        <div class="action-row">
          <button data-action="take-dose" data-id="${m.id}">Assumi ora</button>
          <button data-action="mark-missed" data-id="${m.id}">Segna come non assunta</button>
          <span class="restock-form">
            <input type="number" step="0.25" min="0" placeholder="unità" data-role="restock-amount">
            <span>oppure</span>
            <input type="number" step="1" min="0" placeholder="confezioni" data-role="restock-packages">
            <button data-action="do-restock" data-id="${m.id}">Rifornisci</button>
          </span>
          ${adminActions}
        </div>
      </div>
    `;
  }

  // ---- Dialogs ----

  _openPatientDialog(patient) {
    this._patientDraft = patient ? { id: patient.id, name: patient.name } : { id: null, name: "" };
    const dialog = this.shadowRoot.getElementById("patientDialog");
    dialog.innerHTML = `
      <form method="dialog" class="dialog-body" data-form="patient">
        <h2>${patient ? "Rinomina paziente" : "Nuovo paziente"}</h2>
        <div class="field">
          <label>Nome</label>
          <input name="name" required value="${esc(this._patientDraft.name)}" autofocus>
        </div>
        <div class="dialog-actions">
          <button type="button" data-action="close-patient-dialog">Annulla</button>
          <button type="submit" class="primary">Salva</button>
        </div>
      </form>
    `;
    dialog.showModal();
  }

  _openMedicationDialog(medication) {
    this._medDraft = medication
      ? {
          id: medication.id,
          name: medication.name,
          dose_amount: medication.dose_amount,
          stock_quantity: medication.stock_quantity,
          package_size: medication.package_size ?? "",
          low_stock_days_threshold: medication.low_stock_days_threshold,
          schedule_type: medication.dose_schedule.schedule_type,
          fixed_times: medication.dose_schedule.fixed_times.length
            ? [...medication.dose_schedule.fixed_times]
            : ["08:00"],
          interval_hours: medication.dose_schedule.interval_hours ?? "",
          notes: medication.notes || "",
        }
      : {
          id: null,
          name: "",
          dose_amount: 1,
          stock_quantity: 0,
          package_size: "",
          low_stock_days_threshold: 7,
          schedule_type: "fixed_times",
          fixed_times: ["08:00", "20:00"],
          interval_hours: "",
          notes: "",
        };
    const d = this._medDraft;
    const dialog = this.shadowRoot.getElementById("medDialog");
    dialog.innerHTML = `
      <form method="dialog" class="dialog-body" data-form="medication">
        <h2>${medication ? "Modifica farmaco" : "Nuovo farmaco"}</h2>
        <div class="field">
          <label>Nome</label>
          <input name="name" required value="${esc(d.name)}" autofocus>
        </div>
        <div class="field-row">
          <div class="field">
            <label>Dose per assunzione</label>
            <input name="dose_amount" type="number" step="0.25" min="0" value="${d.dose_amount}" required>
          </div>
          <div class="field">
            <label>Scorta attuale</label>
            <input name="stock_quantity" type="number" step="0.25" min="0" value="${d.stock_quantity}" required>
          </div>
        </div>
        <div class="field-row">
          <div class="field">
            <label>Unità per confezione (opzionale)</label>
            <input name="package_size" type="number" step="1" min="0" value="${d.package_size}">
          </div>
          <div class="field">
            <label>Soglia scorta in esaurimento (giorni)</label>
            <input name="low_stock_days_threshold" type="number" step="1" min="1" value="${d.low_stock_days_threshold}" required>
          </div>
        </div>
        <div class="field">
          <label>Tipo di schema dose</label>
          <select name="schedule_type" data-role="schedule-type">
            <option value="fixed_times" ${d.schedule_type === "fixed_times" ? "selected" : ""}>Orari fissi al giorno</option>
            <option value="interval" ${d.schedule_type === "interval" ? "selected" : ""}>Intervallo dall'ultima assunzione</option>
          </select>
        </div>
        <div class="field" data-role="fixed-times-field" style="${d.schedule_type === "interval" ? "display:none" : ""}">
          <label>Orari</label>
          <div data-role="fixed-times-list">
            ${d.fixed_times
              .map(
                (t) => `
              <div class="time-row">
                <input type="time" data-role="fixed-time-value" value="${esc(t)}" required>
                <button type="button" class="iconbtn" data-action="remove-time-row" title="Rimuovi">&#10005;</button>
              </div>`
              )
              .join("")}
          </div>
          <button type="button" class="small" data-action="add-time-row">+ Aggiungi orario</button>
        </div>
        <div class="field" data-role="interval-field" style="${d.schedule_type === "fixed_times" ? "display:none" : ""}">
          <label>Intervallo (ore)</label>
          <input name="interval_hours" type="number" step="0.5" min="0.5" value="${d.interval_hours}">
        </div>
        <div class="field">
          <label>Note</label>
          <textarea name="notes" rows="2">${esc(d.notes)}</textarea>
        </div>
        <div class="dialog-actions">
          <button type="button" data-action="close-med-dialog">Annulla</button>
          <button type="submit" class="primary">Salva</button>
        </div>
      </form>
    `;
    dialog.showModal();
  }

  // ---- Event handling ----

  _handleChange(e) {
    if (e.target.matches('[data-role="schedule-type"]')) {
      const dialog = this.shadowRoot.getElementById("medDialog");
      const isInterval = e.target.value === "interval";
      dialog.querySelector('[data-role="fixed-times-field"]').style.display = isInterval ? "none" : "";
      dialog.querySelector('[data-role="interval-field"]').style.display = isInterval ? "" : "none";
    }
  }

  async _handleClick(e) {
    const el = e.target.closest("[data-action]");
    if (!el) return;
    const action = el.dataset.action;
    const id = el.dataset.id;

    try {
      switch (action) {
        case "refresh":
          await this._reloadPatients();
          if (this._selectedPatientId) await this._reloadMedications();
          break;
        case "select-patient":
          await this._selectPatient(id);
          break;
        case "new-patient":
          this._openPatientDialog(null);
          break;
        case "edit-patient":
          this._openPatientDialog(this._patients.find((p) => p.id === id));
          break;
        case "delete-patient":
          if (confirm("Eliminare questo paziente e tutti i suoi farmaci?")) {
            await api.deletePatient(this._hass, id);
            await this._reloadPatients();
          }
          break;
        case "close-patient-dialog":
          this.shadowRoot.getElementById("patientDialog").close();
          break;
        case "new-medication":
          this._openMedicationDialog(null);
          break;
        case "edit-medication":
          this._openMedicationDialog(this._medications.find((m) => m.id === id));
          break;
        case "delete-medication":
          if (confirm("Eliminare questo farmaco?")) {
            await api.deleteMedication(this._hass, id);
            await this._reloadMedications();
          }
          break;
        case "close-med-dialog":
          this.shadowRoot.getElementById("medDialog").close();
          break;
        case "add-time-row": {
          const list = this.shadowRoot
            .getElementById("medDialog")
            .querySelector('[data-role="fixed-times-list"]');
          list.insertAdjacentHTML(
            "beforeend",
            `<div class="time-row">
              <input type="time" data-role="fixed-time-value" value="08:00" required>
              <button type="button" class="iconbtn" data-action="remove-time-row" title="Rimuovi">&#10005;</button>
            </div>`
          );
          break;
        }
        case "remove-time-row":
          el.closest(".time-row").remove();
          break;
        case "take-dose":
          await api.takeDose(this._hass, id);
          await this._reloadMedications();
          break;
        case "mark-missed":
          await api.markMissed(this._hass, id);
          await this._reloadMedications();
          break;
        case "do-restock": {
          const card = el.closest(".med-card");
          const amount = card.querySelector('[data-role="restock-amount"]').value;
          const packages = card.querySelector('[data-role="restock-packages"]').value;
          if (!amount && !packages) {
            alert("Indica una quantità in unità oppure un numero di confezioni.");
            return;
          }
          await api.restock(this._hass, id, amount || undefined, packages || undefined);
          await this._reloadMedications();
          break;
        }
      }
    } catch (err) {
      this._error = err.message || String(err);
      this._renderMain();
    }
  }

  async _handleSubmit(e) {
    const form = e.target.closest("form[data-form]");
    if (!form) return;
    e.preventDefault();
    const formType = form.dataset.form;
    const data = new FormData(form);

    try {
      if (formType === "patient") {
        const name = data.get("name").trim();
        if (!name) return;
        if (this._patientDraft.id) {
          await api.updatePatient(this._hass, this._patientDraft.id, name);
        } else {
          await api.addPatient(this._hass, name);
        }
        this.shadowRoot.getElementById("patientDialog").close();
        await this._reloadPatients();
      } else if (formType === "medication") {
        const scheduleType = data.get("schedule_type");
        const payload = {
          ...(this._medDraft.id ? {} : { patient_id: this._selectedPatientId }),
          name: data.get("name").trim(),
          dose_amount: Number(data.get("dose_amount")),
          stock_quantity: Number(data.get("stock_quantity")),
          package_size: data.get("package_size") ? Number(data.get("package_size")) : undefined,
          low_stock_days_threshold: Number(data.get("low_stock_days_threshold")),
          dose_schedule: {
            schedule_type: scheduleType,
            fixed_times:
              scheduleType === "fixed_times"
                ? Array.from(form.querySelectorAll('[data-role="fixed-time-value"]'))
                    .map((input) => input.value)
                    .filter(Boolean)
                : [],
            interval_hours:
              scheduleType === "interval" && data.get("interval_hours")
                ? Number(data.get("interval_hours"))
                : undefined,
          },
          notes: data.get("notes") || "",
        };
        if (this._medDraft.id) {
          await api.updateMedication(this._hass, this._medDraft.id, payload);
        } else {
          await api.addMedication(this._hass, payload);
        }
        this.shadowRoot.getElementById("medDialog").close();
        await this._reloadMedications();
      }
    } catch (err) {
      this._error = err.message || String(err);
      this._renderMain();
    }
  }
}

customElements.define("neopill-panel", NeoPillPanel);
