// NeoPill dashboard strategy: auto-generates one view per patient, each containing
// the neopill-patient-card summary card - zero manual card placement required.
// Usage in a dashboard's raw config:
//   strategy:
//     type: custom:neopill
import { api } from "./api.js";
import { resolveLang, translate } from "./i18n.js";

const STRATEGY_TAG = "ll-strategy-dashboard-neopill";

function slug(name, fallback) {
  const s = (name || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return s || fallback;
}

async function buildViews(hass) {
  const patients = await api.listPatients(hass);
  const lang = resolveLang(hass);
  if (!patients.length) {
    return [
      {
        title: "NeoPill",
        path: "neopill",
        cards: [
          {
            type: "markdown",
            content: translate(lang, "strategy_no_patients"),
          },
        ],
      },
    ];
  }
  const patientViews = patients.map((patient, index) => ({
    title: patient.name,
    path: slug(patient.name, `paziente-${index}`),
    icon: "mdi:account",
    cards: [
      {
        type: "custom:neopill-patient-card",
        patient_id: patient.id,
        title: patient.name,
      },
    ],
  }));
  const stockView = {
    title: translate(lang, "stock_view_title"),
    path: "scorte",
    icon: "mdi:package-variant",
    cards: [{ type: "custom:neopill-stock-card" }],
  };
  return [...patientViews, stockView];
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

if (!customElements.get(STRATEGY_TAG)) {
  customElements.define(STRATEGY_TAG, NeoPillDashboardStrategy);
}
