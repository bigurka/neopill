// NeoPill dashboard strategy: auto-generates a dashboard built only from native HA
// cards (sections view, heading, button, markdown) - no custom cards needed.
// Designed first for the patient (often elderly) and whoever assists them:
//   - one page per patient: big "take it now" buttons with a confirmation, the list
//     of today's doses with what was already taken (so a dose isn't taken twice),
//     and stock in plain words;
//   - a summary page for whoever assists several patients: doses due, what to
//     reorder, a restock button, and yesterday's missed doses.
// Usage in a dashboard's raw config:
//   strategy:
//     type: custom:neopill
import { canAct } from "./api.js";
import { resolveLang, translate } from "./i18n.js";
import { defineElement } from "./register.js";

const STRATEGY_TAG = "ll-strategy-dashboard-neopill";

const TEXT = {
  it: {
    now: "Da prendere adesso",
    nothing_due: "Nessuna pastiglia da prendere adesso.",
    take_slot: "Pastiglie delle {time}",
    confirm_one: "Hai preso {name}?",
    confirm_many: "Hai preso {names}?",
    confirm_missed: "Segnare {name} come NON presa?",
    confirm_restock: "È arrivata una confezione di {name}?",
    today: "Oggi",
    yesterday: "Ieri",
    stock: "Scorte",
    summary: "Riepilogo",
    to_reorder: "Da ordinare",
    restock: "Arrivata una confezione: {name}",
    skip: "Saltata: {name}",
    no_doses: "Nessuna pastiglia programmata.",
    nothing_missed: "Nessuna dose saltata.",
    st_taken: "✅ presa alle {at}",
    st_missed: "❌ saltata",
    st_unanswered: "❔ nessuna risposta",
    st_due: "⏰ da prendere",
    st_later: "più tardi",
    st_not_recorded: "– non segnata",
    days_left: "per {days} giorni",
    days_unknown: "durata non calcolabile",
    units_left: "{units} rimaste",
    due_now: "⏰ {count} da prendere adesso",
    all_done: "✅ niente da prendere adesso",
    last_taken: "Ultima presa: {when}",
    next_dose: "Prossima: {when}",
    never: "mai",
    today_word: "oggi",
    yesterday_word: "ieri",
    tomorrow_word: "domani",
    and: "e",
    col_dose: "Pastiglia",
    col_status: "Stato",
    col_med: "Farmaco",
    col_lasts: "Basta",
  },
  en: {
    now: "Take now",
    nothing_due: "Nothing to take right now.",
    take_slot: "{time} pills",
    confirm_one: "Did you take {name}?",
    confirm_many: "Did you take {names}?",
    confirm_missed: "Mark {name} as NOT taken?",
    confirm_restock: "Did a package of {name} arrive?",
    today: "Today",
    yesterday: "Yesterday",
    stock: "Stock",
    summary: "Summary",
    to_reorder: "To reorder",
    restock: "Package arrived: {name}",
    skip: "Skipped: {name}",
    no_doses: "No doses scheduled.",
    nothing_missed: "No missed doses.",
    st_taken: "✅ taken at {at}",
    st_missed: "❌ skipped",
    st_unanswered: "❔ no answer",
    st_due: "⏰ to take",
    st_later: "later",
    st_not_recorded: "– not recorded",
    days_left: "for {days} days",
    days_unknown: "duration unknown",
    units_left: "{units} left",
    due_now: "⏰ {count} to take now",
    all_done: "✅ nothing to take now",
    last_taken: "Last taken: {when}",
    next_dose: "Next: {when}",
    never: "never",
    today_word: "today",
    yesterday_word: "yesterday",
    tomorrow_word: "tomorrow",
    and: "and",
    col_dose: "Dose",
    col_status: "Status",
    col_med: "Medication",
    col_lasts: "Lasts",
  },
};

function t(lang, key, vars) {
  let str = (TEXT[lang] || TEXT.en)[key] ?? key;
  for (const [name, value] of Object.entries(vars || {})) str = str.replaceAll(`{${name}}`, value);
  return str;
}

function slug(name, fallback) {
  const s = (name || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return s || fallback;
}

// Jinja string literal for text that ends up inside a markdown template.
const jq = (s) => `'${String(s).replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`;

const isOn = (entity) => ({ condition: "state", entity, state: "on" });
const isOff = (entity) => ({ condition: "state", entity, state: "off" });

// "A, B e C" - reads more naturally than a bare comma list in a confirmation.
function joinNames(lang, names) {
  return names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} ${t(lang, "and")} ${names.at(-1)}`;
}

function pairs(items) {
  const out = [];
  for (let i = 0; i < items.length; i++)
    for (let j = i + 1; j < items.length; j++) out.push([items[i], items[j]]);
  return out;
}

function pressAction(entity, confirmText) {
  return {
    action: "perform-action",
    perform_action: "button.press",
    target: { entity_id: entity },
    confirmation: { text: confirmText },
  };
}

function bigButton(entity, name, icon, tapAction, visibility) {
  const card = {
    type: "button",
    entity,
    name,
    icon,
    show_name: true,
    show_icon: true,
    show_state: false,
    icon_height: "56px",
    tap_action: tapAction || { action: "none" },
    hold_action: { action: "none" },
    grid_options: { columns: "full", rows: 2 },
  };
  if (visibility) card.visibility = visibility;
  return card;
}

const heading = (text, icon) => ({ type: "heading", heading: text, icon, heading_style: "title" });

// Markdown helper templates shared by several cards.
function whenMacro(lang) {
  return (
    `{% macro when(iso) %}{% if not iso %}${t(lang, "never")}{% else %}` +
    `{% set d = as_local(as_datetime(iso)) %}{% set days = (now().date() - d.date()).days %}` +
    `{% if days == 0 %}${t(lang, "today_word")}{% elif days == 1 %}${t(lang, "yesterday_word")}` +
    `{% elif days == -1 %}${t(lang, "tomorrow_word")}` +
    `{% else %}{{ d.strftime('%d/%m') }}{% endif %} {{ d.strftime('%H:%M') }}{% endif %}{% endmacro %}`
  );
}

function statusMacro(lang) {
  const keys = ["taken", "missed", "unanswered", "due", "later", "not_recorded"];
  const branches = keys
    .map((k, i) => {
      const label = k === "taken" ? jq(t(lang, "st_taken")) + ".replace('{at}', d.recorded_at or '')" : jq(t(lang, `st_${k}`));
      return `{% ${i ? "elif" : "if"} d.status == '${k}' %}{{ ${label} }}`;
    })
    .join("");
  return `{% macro status(d) %}${branches}{% endif %}{% endmacro %}`;
}

function dosesTable(lang, sensor, attribute, emptyKey, onlyProblems = false) {
  const filter = onlyProblems
    ? " | selectattr('status', 'in', ['missed', 'unanswered', 'not_recorded']) | list"
    : "";
  return {
    type: "markdown",
    content:
      statusMacro(lang) +
      `{% set doses = (state_attr(${jq(sensor)}, '${attribute}') or [])${filter} %}` +
      `{% if doses %}| ${t(lang, "col_dose")} | ${t(lang, "col_status")} |\n|:--|--:|\n{% for d in doses %}| **{{ d.time }}** {{ d.name }} | {{ status(d) }} |\n{% endfor %}` +
      `{% else %}${t(lang, emptyKey)}{% endif %}`,
    grid_options: { columns: "full" },
  };
}

function stockMarkdown(lang, medications) {
  const rows = medications
    .filter((m) => m.entities.days_remaining)
    .map(
      (m) =>
        `{% set days = states(${jq(m.entities.days_remaining)}) %}` +
        `{% set low = is_state(${jq(m.entities.low_stock || "")}, 'on') %}` +
        `| **${m.name.replace(/\|/g, "/")}** | {{ '⚠️ ' if low }}` +
        `{% if days | is_number %}{{ ${jq(t(lang, "days_left"))}.replace('{days}', days | float | round(0) | int | string) }}` +
        `{% else %}${t(lang, "days_unknown")}{% endif %}` +
        (m.entities.stock
          ? ` · {{ ${jq(t(lang, "units_left"))}.replace('{units}', states(${jq(m.entities.stock)}) | float(0) | round(0) | int | string) }}`
          : "") +
        " |\n"
    )
    .join("");
  const header = `| ${t(lang, "col_med")} | ${t(lang, "col_lasts")} |\n|:--|--:|\n`;
  return { type: "markdown", content: header + rows, grid_options: { columns: "full" } };
}

function patientView(lang, patient, index) {
  const act = canAct(patient.role);
  const meds = patient.medications;
  const nowCards = [];

  for (const slot of patient.slots) {
    if (slot.medication_ids.length < 2 || !slot.take_all) continue;
    const slotMeds = meds.filter((m) => slot.medication_ids.includes(m.id) && m.entities.dose_due);
    if (slotMeds.length < 2) continue;
    const names = slotMeds.map((m) => m.name).join(", ");
    const spoken = joinNames(lang, slotMeds.map((m) => m.name));
    nowCards.push(
      bigButton(
        slot.take_all,
        `${t(lang, "take_slot", { time: slot.time })}: ${names}`,
        "mdi:pill-multiple",
        act ? pressAction(slot.take_all, t(lang, "confirm_many", { names: spoken })) : null,
        // At least two of this slot's medications due right now.
        [{ condition: "or", conditions: pairs(slotMeds).map(([a, b]) => ({ condition: "and", conditions: [isOn(a.entities.dose_due), isOn(b.entities.dose_due)] })) }]
      )
    );
  }
  for (const m of meds) {
    if (!m.entities.dose_due || !m.entities.take_dose) continue;
    const amount = m.dose_amount && m.dose_amount !== 1 ? ` ×${m.dose_amount}` : "";
    nowCards.push(
      bigButton(
        m.entities.take_dose,
        `${m.name}${amount}`,
        "mdi:pill",
        act ? pressAction(m.entities.take_dose, t(lang, "confirm_one", { name: m.name })) : null,
        [isOn(m.entities.dose_due)]
      )
    );
  }
  const dueSensors = meds.map((m) => m.entities.dose_due).filter(Boolean);
  nowCards.push({
    type: "markdown",
    content: `### ${t(lang, "nothing_due")}`,
    grid_options: { columns: "full" },
    visibility: dueSensors.map(isOff),
  });

  const sections = [{ type: "grid", cards: [heading(t(lang, "now"), "mdi:bell-ring"), ...nowCards] }];
  if (patient.entities.today_doses) {
    sections.push({
      type: "grid",
      cards: [heading(t(lang, "today"), "mdi:clipboard-check-outline"), dosesTable(lang, patient.entities.today_doses, "doses", "no_doses")],
    });
  }
  if (meds.length) {
    sections.push({ type: "grid", cards: [heading(t(lang, "stock"), "mdi:package-variant"), stockMarkdown(lang, meds)] });
  }
  return {
    title: patient.name,
    path: slug(patient.name, `paziente-${index}`),
    type: "sections",
    max_columns: 3,
    sections,
  };
}

function summaryView(lang, patients) {
  const sections = [];
  for (const patient of patients) {
    const sensor = patient.entities.today_doses;
    const act = canAct(patient.role);
    const cards = [heading(patient.name, "mdi:account")];
    if (sensor) {
      cards.push({
        type: "markdown",
        content:
          whenMacro(lang) +
          `{% set due = states(${jq(sensor)}) | int(0) %}` +
          `**{% if due > 0 %}{{ ${jq(t(lang, "due_now"))}.replace('{count}', due | string) }}{% else %}${t(lang, "all_done")}{% endif %}**\n\n` +
          `{{ ${jq(t(lang, "last_taken"))}.replace('{when}', when(state_attr(${jq(sensor)}, 'last_taken'))) }}\n\n` +
          `{% set nxt = state_attr(${jq(sensor)}, 'next_dose') %}{% if nxt %}{{ ${jq(t(lang, "next_dose"))}.replace('{when}', when(nxt)) }}{% endif %}`,
        grid_options: { columns: "full" },
      });
    }
    if (act) {
      for (const m of patient.medications) {
        if (!m.entities.dose_due || !m.entities.mark_missed) continue;
        cards.push({
          type: "tile",
          entity: m.entities.mark_missed,
          name: t(lang, "skip", { name: m.name }),
          icon: "mdi:pill-off",
          hide_state: true,
          tap_action: pressAction(m.entities.mark_missed, t(lang, "confirm_missed", { name: m.name })),
          hold_action: { action: "none" },
          icon_tap_action: { action: "none" },
          visibility: [isOn(m.entities.dose_due)],
        });
      }
    }
    const reminder = patient.entities.restock_reminder;
    if (reminder) {
      cards.push({
        type: "markdown",
        content: `**${t(lang, "to_reorder")}**\n\n{{ state_attr(${jq(reminder)}, 'testo') }}`,
        grid_options: { columns: "full" },
        visibility: [{ condition: "numeric_state", entity: reminder, above: 0 }],
      });
    }
    if (act) {
      for (const m of patient.medications) {
        if (!m.entities.restock_package || !m.entities.low_stock) continue;
        cards.push({
          type: "tile",
          entity: m.entities.restock_package,
          name: t(lang, "restock", { name: m.name }),
          icon: "mdi:package-variant-plus",
          hide_state: true,
          tap_action: pressAction(m.entities.restock_package, t(lang, "confirm_restock", { name: m.name })),
          hold_action: { action: "none" },
          icon_tap_action: { action: "none" },
          visibility: [isOn(m.entities.low_stock)],
        });
      }
    }
    if (sensor) {
      cards.push({ type: "heading", heading: t(lang, "yesterday"), heading_style: "subtitle" });
      cards.push(dosesTable(lang, sensor, "yesterday", "nothing_missed", true));
    }
    sections.push({ type: "grid", cards });
  }
  return {
    title: t(lang, "summary"),
    path: "riepilogo",
    type: "sections",
    max_columns: 3,
    sections,
  };
}

async function buildViews(hass) {
  const lang = resolveLang(hass);
  const { patients } = await hass.connection.sendMessagePromise({ type: "neopill/dashboard" });
  if (!patients.length) {
    return [
      {
        title: "NeoPill",
        path: "neopill",
        cards: [{ type: "markdown", content: translate(lang, "strategy_no_patients") }],
      },
    ];
  }
  const views = patients.map((patient, index) => patientView(lang, patient, index));
  // The summary is for whoever looks after someone else: more than one patient, or
  // a role beyond being the (assisted) patient themselves.
  const assists = patients.length > 1 || patients.some((p) => ["caregiver", "doctor", "admin"].includes(p.role));
  if (assists) views.push(summaryView(lang, patients));
  return views;
}

class NeoPillDashboardStrategy {
  static async generate(config, hass) {
    return { views: await buildViews(hass) };
  }

  // Pre-2024.x API name, kept for compatibility with older frontends.
  static async generateDashboard(info) {
    return { views: await buildViews(info.hass) };
  }
}

defineElement(STRATEGY_TAG, NeoPillDashboardStrategy);
