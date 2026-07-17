// NeoPill sidebar panel - plain Web Component, no build step, no external dependencies.
// Talks to the backend exclusively through the neopill/* websocket commands (api.js).

import { api } from "./api.js";
import { styles } from "./styles.js";
import { resolveLang, translate } from "./i18n.js";

const EVENT_TYPE_KEYS = {
  assunta: "event_taken",
  non_assunta: "event_missed",
  nessuna_risposta: "event_unanswered",
  rifornimento: "event_restock",
  scorta_esaurita: "event_depleted",
};

const WEEK_DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

// Soft, low-opacity tints assigned to each distinct dose time-of-day (e.g. "06:00"),
// reused both for the toolbar legend chips and for tinting matching history rows.
const TIME_SLOT_COLORS = [
  [139, 127, 255], // violet
  [255, 177, 102], // amber
  [94, 199, 182], // teal
  [255, 140, 189], // pink
  [126, 178, 255], // blue
  [158, 214, 130], // green
];
const TIME_SLOT_MATCH_TOLERANCE_MINUTES = 90;
const DOSE_EVENT_TYPES = new Set(["assunta", "non_assunta", "nessuna_risposta"]);

function timeStrToMinutes(timeStr) {
  const [h, m] = timeStr.split(":").map(Number);
  return h * 60 + m;
}

// Finds the patient's time slot closest to an event's actual local time, within
// TIME_SLOT_MATCH_TOLERANCE_MINUTES (wraparound-aware, so 23:50 is "close" to 00:10).
// Returns -1 if nothing is close enough - e.g. an ad-hoc dose taken well outside any
// of the patient's usual times, which is deliberately left untinted.
function closestTimeSlotIndex(isoTimestamp, slots) {
  if (!slots.length) return -1;
  const d = new Date(isoTimestamp);
  const minutes = d.getHours() * 60 + d.getMinutes();
  let bestIndex = -1;
  let bestDiff = Infinity;
  slots.forEach((slot, i) => {
    const diffRaw = Math.abs(minutes - timeStrToMinutes(slot));
    const diff = Math.min(diffRaw, 1440 - diffRaw);
    if (diff <= TIME_SLOT_MATCH_TOLERANCE_MINUTES && diff < bestDiff) {
      bestDiff = diff;
      bestIndex = i;
    }
  });
  return bestIndex;
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

function timeRowHtml(value, removeAction, removeTitle) {
  return `<div class="time-row">
    <input type="time" data-role="${removeAction === "remove-time-row" ? "fixed-time-value" : "weekly-time-value"}" value="${esc(value)}" required>
    <button type="button" class="iconbtn" data-action="${removeAction}" title="${esc(removeTitle)}">&#10005;</button>
  </div>`;
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

  get _lang() {
    return resolveLang(this._hass);
  }

  t(key, vars) {
    return translate(this._lang, key, vars);
  }

  _fmtDateTime(iso) {
    if (!iso) return "-";
    try {
      const locale = this._lang === "it" ? "it-IT" : "en-GB";
      return new Date(iso).toLocaleString(locale, { dateStyle: "short", timeStyle: "short" });
    } catch (err) {
      return iso;
    }
  }

  _fmtDate(iso) {
    if (!iso) return "-";
    try {
      const locale = this._lang === "it" ? "it-IT" : "en-GB";
      return new Date(iso).toLocaleDateString(locale, { dateStyle: "short" });
    } catch (err) {
      return iso;
    }
  }

  _weekDays() {
    return WEEK_DAY_KEYS.map((key) => [key, this.t(`day_${key}`)]);
  }

  _weeklyScheduleText(weeklyTimes) {
    const entries = Object.entries(weeklyTimes || {}).filter(([, times]) => times && times.length);
    if (!entries.length) return this.t("no_days_set");
    return entries
      .map(([day, times]) => `${this.t(`day_short_${day}`)} ${times.join(",")}`)
      .join(" · ");
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
      </div>
      <div id="toolbar"></div>
      <div class="main" id="main"></div>
      <dialog id="patientDialog"></dialog>
      <dialog id="medDialog"></dialog>
    `;

    this.shadowRoot.addEventListener("click", (e) => this._handleClick(e));
    this.shadowRoot.addEventListener("submit", (e) => this._handleSubmit(e));
    this.shadowRoot.addEventListener("change", (e) => this._handleChange(e));
    this.shadowRoot.addEventListener("focusout", (e) => this._handleBlur(e));
    this.shadowRoot.addEventListener("input", (e) => this._handleThresholdInput(e));

    await this._reloadPatients();
  }

  // ---- Data loading ----

  async _reloadPatients() {
    this._loadingPatients = true;
    this._renderToolbar();
    try {
      this._patients = await api.listPatients(this._hass);
      this._error = null;
    } catch (err) {
      this._error = this.t("error_loading_patients", { error: err.message || err });
    }
    this._loadingPatients = false;
    if (this._selectedPatientId && !this._patients.some((p) => p.id === this._selectedPatientId)) {
      this._selectedPatientId = null;
      this._medications = [];
      this._history = [];
    }
    // A native <select> always shows *some* option as chosen even when we never
    // set one - keep our state in sync with that default (the first patient)
    // instead of showing a "select a patient" placeholder next to an apparently
    // already-selected dropdown.
    if (!this._selectedPatientId && this._patients.length) {
      await this._selectPatient(this._patients[0].id);
      return;
    }
    this._renderToolbar();
    this._renderMain();
  }

  async _selectPatient(patientId) {
    this._selectedPatientId = patientId || null;
    this._renderToolbar();
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
      this._error = this.t("error_loading_medications", { error: err.message || err });
    }
    this._loadingMedications = false;
    this._renderMain();
  }

  // ---- Rendering: toolbar ----

  _renderToolbar() {
    const toolbar = this.shadowRoot.getElementById("toolbar");
    if (!toolbar) return;

    if (this._loadingPatients) {
      toolbar.innerHTML = `<div class="patient-toolbar"><span class="empty-state">${this.t("loading")}</span></div>`;
      return;
    }

    const patient = this._patients.find((p) => p.id === this._selectedPatientId) || null;
    const options = this._patients
      .map((p) => `<option value="${p.id}" ${p.id === this._selectedPatientId ? "selected" : ""}>${esc(p.name)}</option>`)
      .join("");

    toolbar.innerHTML = `
      <div class="patient-toolbar">
        ${
          this._isAdmin
            ? `<button class="iconbtn icon-badge" data-action="new-patient" title="${this.t("add_patient")}">
                 <span class="icon-base">&#128100;</span><span class="icon-plus">+</span>
               </button>`
            : ""
        }
        <select data-role="patient-select" ${this._patients.length ? "" : "disabled"}>
          ${this._patients.length ? options : `<option>${this.t("no_patients_option")}</option>`}
        </select>
        ${
          patient && this._isAdmin
            ? `<button class="iconbtn" data-action="edit-patient" data-id="${patient.id}" title="${this.t("rename_patient_action")}">&#9998;</button>`
            : ""
        }
        ${
          patient
            ? `
          <span class="toolbar-sep"></span>
          <div class="threshold-stack">
            <label class="threshold-field">
              ${this.t("min_days")}
              <input type="number" min="0" step="1" data-role="threshold-min" value="${patient.restock_window_min_days}">
            </label>
            <label class="threshold-field">
              ${this.t("max_days")}
              <input type="number" min="0" step="1" data-role="threshold-max" value="${patient.restock_window_max_days}">
            </label>
          </div>
          ${
            this._isAdmin
              ? `
            <span class="toolbar-sep"></span>
            <button class="iconbtn icon-badge" data-action="new-medication" title="${this.t("add_medication")}">
              <span class="icon-base">&#128138;</span><span class="icon-plus">+</span>
            </button>
            <button class="iconbtn danger" data-action="delete-patient" data-id="${patient.id}" title="${this.t("delete_patient")}">&#128465;</button>
          `
              : ""
          }`
            : ""
        }
        <span class="toolbar-spacer"></span>
        <button class="iconbtn" data-action="refresh" title="${this.t("refresh")}">&#x21bb;</button>
      </div>
    `;
  }

  // ---- Rendering: main ----

  _renderMain() {
    const main = this.shadowRoot.getElementById("main");
    if (!main) return;

    const errorBanner = this._error ? `<div class="error-banner">${esc(this._error)}</div>` : "";

    if (!this._selectedPatientId) {
      main.innerHTML = `${errorBanner}<div class="empty-state">${this.t("select_patient_prompt")}</div>`;
      return;
    }

    if (this._loadingMedications) {
      main.innerHTML = `${errorBanner}<div class="empty-state">${this.t("loading")}</div>`;
      return;
    }

    const cards = this._medications.map((m) => this._renderMedicationCard(m)).join("");

    const timeSlots = this._computeTimeSlots();
    const legend = timeSlots.length
      ? `<div class="time-slot-legend">
          <span class="time-slot-legend-label">${this.t("time_slots_label")}</span>
          ${timeSlots
            .map((t, i) => {
              const [r, g, b] = TIME_SLOT_COLORS[i % TIME_SLOT_COLORS.length];
              return `<span class="time-slot-chip" style="--slot-rgb:${r},${g},${b}">${esc(t)}</span>`;
            })
            .join("")}
        </div>`
      : "";

    const historyRows = [...this._history]
      .reverse()
      .slice(0, 50)
      .map((e) => {
        const typeKey = EVENT_TYPE_KEYS[e.type];
        const label = typeKey ? this.t(typeKey) : e.type;
        const slotIndex = DOSE_EVENT_TYPES.has(e.type) ? closestTimeSlotIndex(e.timestamp, timeSlots) : -1;
        const rowStyle =
          slotIndex >= 0
            ? ` style="background:rgba(${TIME_SLOT_COLORS[slotIndex % TIME_SLOT_COLORS.length].join(",")},0.13)"`
            : "";
        return `<tr${rowStyle}>
          <td>${this._fmtDateTime(e.timestamp)}</td>
          <td>${esc(label)}</td>
          <td>${esc(e.medication_name)}</td>
          <td>${e.amount !== undefined ? e.amount : e.amount_added !== undefined ? "+" + e.amount_added : ""}</td>
        </tr>`;
      })
      .join("");

    main.innerHTML = `
      ${errorBanner}
      ${legend}
      ${cards ? `<div class="med-grid">${cards}</div>` : `<div class="empty-state">${this.t("no_medications")}</div>`}
      <section class="history">
        <h3>${this.t("history_title")}</h3>
        ${
          historyRows
            ? `<table class="history"><thead><tr><th>${this.t("col_when")}</th><th>${this.t("col_event")}</th><th>${this.t("col_medication")}</th><th>${this.t("col_qty")}</th></tr></thead><tbody>${historyRows}</tbody></table>`
            : `<div class="empty-state">${this.t("no_history")}</div>`
        }
      </section>
    `;
  }

  _computeTimeSlots() {
    const times = new Set();
    for (const m of this._medications) {
      const schedule = m.dose_schedule;
      if (!schedule) continue;
      (schedule.fixed_times || []).forEach((t) => times.add(t));
      Object.values(schedule.weekly_times || {}).forEach((list) => (list || []).forEach((t) => times.add(t)));
    }
    return [...times].sort();
  }

  // ---- Pill glyph (matches the NeoPill brand mark) used inside icon-action buttons ----

  _pillGlyph() {
    return `<svg viewBox="0 0 26 26" class="pill-icon" aria-hidden="true">
      <g transform="rotate(-40 13 13)">
        <rect x="3" y="9" width="20" height="8" rx="4" fill="#1de9ff"/>
        <rect x="13" y="9" width="10" height="8" rx="4" fill="#ff5b5b"/>
      </g>
    </svg>`;
  }

  _doublePillGlyph() {
    return `<svg viewBox="0 0 34 26" class="pill-icon pill-icon-double" aria-hidden="true">
      <g transform="rotate(-40 10 13)" opacity="0.85">
        <rect x="-3" y="8" width="20" height="8" rx="4" fill="#1de9ff"/>
        <rect x="11" y="8" width="10" height="8" rx="4" fill="#ff5b5b"/>
      </g>
      <g transform="rotate(-40 22 15)">
        <rect x="11" y="10" width="20" height="8" rx="4" fill="#1de9ff"/>
        <rect x="25" y="10" width="10" height="8" rx="4" fill="#ff5b5b"/>
      </g>
    </svg>`;
  }

  _pillActionButton(action, id, badgeClass, badgeGlyph, label, double) {
    return `<button class="pillbtn" data-action="${action}" data-id="${id}" title="${label}" aria-label="${label}">
      ${double ? this._doublePillGlyph() : this._pillGlyph()}
      <span class="pillbtn-badge ${badgeClass}">${badgeGlyph}</span>
    </button>`;
  }

  _renderMedicationCard(m) {
    const badges = [
      m.is_due ? `<span class="badge due">${this.t("badge_due")}</span>` : "",
      m.is_low_stock ? `<span class="badge low-stock">${this.t("badge_low_stock")}</span>` : "",
    ].join("");

    const scheduleText =
      m.dose_schedule.schedule_type === "fixed_times"
        ? this.t("schedule_fixed_times_text", { times: m.dose_schedule.fixed_times.join(", ") || "-" })
        : m.dose_schedule.schedule_type === "weekly"
        ? this._weeklyScheduleText(m.dose_schedule.weekly_times)
        : this.t("schedule_interval_text", { hours: m.dose_schedule.interval_hours ?? "-" });

    const adminActions = this._isAdmin
      ? `${this._pillActionButton("edit-medication", m.id, "accent", "&#9998;", this.t("edit"))}
         <button class="iconbtn danger" data-action="delete-medication" data-id="${m.id}" title="${this.t(
          "delete"
        )}" aria-label="${this.t("delete")}">&#128465;&#65039;</button>`
      : "";

    return `
      <div class="med-card" data-medication-id="${m.id}">
        <div class="title-row">
          <span class="name">${esc(m.name)}</span>
          ${badges}
        </div>
        <div class="meta">
          <span>${this.t("stock_label")} <b>${m.stock_quantity}</b> ${this.t("unit_label")}</span>
          <span>${this.t("dose_label")} <b>${m.dose_amount}</b></span>
          ${m.package_size ? `<span>${this.t("package_content_label")} <b>${m.package_size}</b></span>` : ""}
          <span>${esc(scheduleText)}</span>
          <span>${this.t("days_remaining_label")} <b>${m.days_remaining !== null ? Math.floor(m.days_remaining) : "-"}</b></span>
          <span>${this.t("next_dose_label")} <b>${this._fmtDateTime(m.next_dose_at)}</b></span>
          ${m.next_depletion_date ? `<span>${this.t("depletion_date_label")} <b>${this._fmtDate(m.next_depletion_date)}</b></span>` : ""}
        </div>
        <div class="action-row">
          ${this._pillActionButton("take-dose", m.id, "success", "&#10003;", this.t("take_dose"))}
          ${this._pillActionButton("mark-missed", m.id, "danger", "&#10005;", this.t("mark_missed"))}
          <span class="restock-form">
            <input type="number" step="0.25" min="0" placeholder="${this.t("placeholder_units")}" data-role="restock-amount">
            <span>${this.t("or")}</span>
            <input type="number" step="1" min="0" placeholder="${this.t("placeholder_packages")}" data-role="restock-packages">
            ${this._pillActionButton("do-restock", m.id, "accent", "&#8592;", this.t("restock"), true)}
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
        <h2>${patient ? this.t("rename_patient_title") : this.t("new_patient_title")}</h2>
        <div class="field">
          <label>${this.t("name_label")}</label>
          <input name="name" required value="${esc(this._patientDraft.name)}" autofocus>
        </div>
        <div class="dialog-actions">
          <button type="button" data-action="close-patient-dialog">${this.t("cancel")}</button>
          <button type="submit" class="primary">${this.t("save")}</button>
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
          full_name: medication.full_name || "",
          dose_amount: medication.dose_amount,
          stock_quantity: medication.stock_quantity,
          package_size: medication.package_size ?? "",
          low_stock_days_threshold: medication.low_stock_days_threshold,
          schedule_type: medication.dose_schedule.schedule_type,
          fixed_times: medication.dose_schedule.fixed_times.length
            ? [...medication.dose_schedule.fixed_times]
            : ["08:00"],
          interval_hours: medication.dose_schedule.interval_hours ?? "",
          weekly_times: medication.dose_schedule.weekly_times || {},
          notes: medication.notes || "",
        }
      : {
          id: null,
          name: "",
          full_name: "",
          dose_amount: 1,
          stock_quantity: 0,
          package_size: "",
          low_stock_days_threshold: 7,
          schedule_type: "fixed_times",
          fixed_times: ["08:00", "20:00"],
          interval_hours: "",
          weekly_times: {},
          notes: "",
        };
    const d = this._medDraft;
    const dialog = this.shadowRoot.getElementById("medDialog");
    const removeTitle = this.t("remove");
    dialog.innerHTML = `
      <form method="dialog" class="dialog-body" data-form="medication">
        <h2>${medication ? this.t("edit_medication_title") : this.t("new_medication_title")}</h2>
        <div class="field">
          <label>${this.t("name_label")}</label>
          <input name="name" required value="${esc(d.name)}" autofocus>
        </div>
        <div class="field">
          <label>${this.t("full_name_label")}</label>
          <input name="full_name" value="${esc(d.full_name)}" placeholder="${this.t("full_name_placeholder")}">
        </div>
        <div class="field-row">
          <div class="field">
            <label>${this.t("dose_per_intake")}</label>
            <input name="dose_amount" type="number" step="0.25" min="0" value="${d.dose_amount}" required>
          </div>
          <div class="field">
            <label>${this.t("current_stock")}</label>
            <input name="stock_quantity" type="number" step="0.25" min="0" value="${d.stock_quantity}" required>
          </div>
        </div>
        <div class="field-row">
          <div class="field">
            <label>${this.t("package_size_label")}</label>
            <input name="package_size" type="number" step="1" min="0" value="${d.package_size}">
          </div>
          <div class="field">
            <label>${this.t("low_stock_threshold_label")}</label>
            <input name="low_stock_days_threshold" type="number" step="1" min="1" value="${d.low_stock_days_threshold}" required>
          </div>
        </div>
        <div class="field">
          <label>${this.t("schedule_type_label")}</label>
          <select name="schedule_type" data-role="schedule-type">
            <option value="fixed_times" ${d.schedule_type === "fixed_times" ? "selected" : ""}>${this.t("schedule_type_fixed")}</option>
            <option value="weekly" ${d.schedule_type === "weekly" ? "selected" : ""}>${this.t("schedule_type_weekly")}</option>
            <option value="interval" ${d.schedule_type === "interval" ? "selected" : ""}>${this.t("schedule_type_interval")}</option>
          </select>
        </div>
        <div class="field" data-role="fixed-times-field" style="${d.schedule_type === "fixed_times" ? "" : "display:none"}">
          <label>${this.t("times_label")}</label>
          <div data-role="fixed-times-list">
            ${d.fixed_times.map((t) => timeRowHtml(t, "remove-time-row", removeTitle)).join("")}
          </div>
          <button type="button" class="small" data-action="add-time-row">${this.t("add_time")}</button>
        </div>
        <div class="field" data-role="interval-field" style="${d.schedule_type === "interval" ? "" : "display:none"}">
          <label>${this.t("interval_hours_label")}</label>
          <input name="interval_hours" type="number" step="0.5" min="0.5" value="${d.interval_hours}">
        </div>
        <div class="field" data-role="weekly-field" style="${d.schedule_type === "weekly" ? "" : "display:none"}">
          <label>${this.t("days_and_times_label")}</label>
          ${this._weekDays().map(([key, label]) => {
            const times = d.weekly_times[key] || [];
            const enabled = times.length > 0;
            return `
            <div class="weekly-day" data-day="${key}">
              <label class="weekly-day-toggle">
                <input type="checkbox" data-role="weekly-day-enabled" ${enabled ? "checked" : ""}>
                ${label}
              </label>
              <div data-role="weekly-day-times" style="${enabled ? "" : "display:none"}">
                ${times.map((t) => timeRowHtml(t, "remove-weekly-time-row", removeTitle)).join("")}
                <button type="button" class="small" data-action="add-weekly-time-row">${this.t("add_time")}</button>
              </div>
            </div>`;
          }).join("")}
        </div>
        <div class="field">
          <label>${this.t("notes_label")}</label>
          <textarea name="notes" rows="2">${esc(d.notes)}</textarea>
        </div>
        <div class="dialog-actions">
          <button type="button" data-action="close-med-dialog">${this.t("cancel")}</button>
          <button type="submit" class="primary">${this.t("save")}</button>
        </div>
      </form>
    `;
    dialog.showModal();
  }

  // ---- Event handling ----

  _handleChange(e) {
    if (e.target.matches('[data-role="patient-select"]')) {
      this._selectPatient(e.target.value);
    }
    if (e.target.matches('[data-role="schedule-type"]')) {
      const dialog = this.shadowRoot.getElementById("medDialog");
      const type = e.target.value;
      dialog.querySelector('[data-role="fixed-times-field"]').style.display = type === "fixed_times" ? "" : "none";
      dialog.querySelector('[data-role="interval-field"]').style.display = type === "interval" ? "" : "none";
      dialog.querySelector('[data-role="weekly-field"]').style.display = type === "weekly" ? "" : "none";
    }
    if (e.target.matches('[data-role="weekly-day-enabled"]')) {
      const dayBlock = e.target.closest(".weekly-day");
      const timesDiv = dayBlock.querySelector('[data-role="weekly-day-times"]');
      timesDiv.style.display = e.target.checked ? "" : "none";
      if (e.target.checked && !timesDiv.querySelector('[data-role="weekly-time-value"]')) {
        const addBtn = timesDiv.querySelector('[data-action="add-weekly-time-row"]');
        addBtn.insertAdjacentHTML("beforebegin", timeRowHtml("08:00", "remove-weekly-time-row", this.t("remove")));
      }
    }
  }

  _handleThresholdInput(e) {
    if (!e.target.matches('[data-role="threshold-min"], [data-role="threshold-max"]')) return;
    const toolbar = e.target.closest(".patient-toolbar");
    const minInput = toolbar.querySelector('[data-role="threshold-min"]');
    const maxInput = toolbar.querySelector('[data-role="threshold-max"]');
    const min = Number(minInput.value);
    const max = Number(maxInput.value);
    const valid = Number.isFinite(min) && Number.isFinite(max) && min >= 0 && max >= 0 && min < max;
    minInput.classList.toggle("invalid", !valid);
    maxInput.classList.toggle("invalid", !valid);
  }

  async _handleBlur(e) {
    if (!e.target.matches('[data-role="threshold-min"], [data-role="threshold-max"]')) return;
    const toolbar = e.target.closest(".patient-toolbar");
    const minInput = toolbar.querySelector('[data-role="threshold-min"]');
    const maxInput = toolbar.querySelector('[data-role="threshold-max"]');
    const min = Number(minInput.value);
    const max = Number(maxInput.value);
    const patient = this._patients.find((p) => p.id === this._selectedPatientId);
    if (!patient) return;

    if (!Number.isFinite(min) || !Number.isFinite(max) || min < 0 || max < 0 || min >= max) {
      this._error = this.t("threshold_validation_error");
      minInput.value = patient.restock_window_min_days;
      maxInput.value = patient.restock_window_max_days;
      minInput.classList.remove("invalid");
      maxInput.classList.remove("invalid");
      this._renderMain();
      return;
    }
    if (min === patient.restock_window_min_days && max === patient.restock_window_max_days) return;

    try {
      await api.updatePatient(this._hass, patient.id, {
        restock_window_min_days: min,
        restock_window_max_days: max,
      });
      patient.restock_window_min_days = min;
      patient.restock_window_max_days = max;
      this._error = null;
    } catch (err) {
      this._error = err.message || String(err);
      minInput.value = patient.restock_window_min_days;
      maxInput.value = patient.restock_window_max_days;
      minInput.classList.remove("invalid");
      maxInput.classList.remove("invalid");
      this._renderMain();
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
          if (confirm(this.t("confirm_delete_patient"))) {
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
          if (confirm(this.t("confirm_delete_medication"))) {
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
          list.insertAdjacentHTML("beforeend", timeRowHtml("08:00", "remove-time-row", this.t("remove")));
          break;
        }
        case "remove-time-row":
          el.closest(".time-row").remove();
          break;
        case "add-weekly-time-row":
          el.insertAdjacentHTML("beforebegin", timeRowHtml("08:00", "remove-weekly-time-row", this.t("remove")));
          break;
        case "remove-weekly-time-row":
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
            alert(this.t("restock_amount_required"));
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
          await api.updatePatient(this._hass, this._patientDraft.id, { name });
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
          full_name: data.get("full_name").trim(),
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
            weekly_times:
              scheduleType === "weekly"
                ? Array.from(form.querySelectorAll(".weekly-day")).reduce((acc, dayBlock) => {
                    const enabled = dayBlock.querySelector('[data-role="weekly-day-enabled"]').checked;
                    if (!enabled) return acc;
                    const times = Array.from(
                      dayBlock.querySelectorAll('[data-role="weekly-time-value"]')
                    )
                      .map((input) => input.value)
                      .filter(Boolean);
                    if (times.length) acc[dayBlock.dataset.day] = times;
                    return acc;
                  }, {})
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
