// Thin wrapper around the Home Assistant websocket connection for all neopill/* commands.
// Plain ES module, no build step - served as-is by the integration's static path.

function send(hass, msg) {
  return hass.connection.sendMessagePromise(msg);
}

// Per (user, patient) roles - mirror of const.py. Each patient from listPatients()
// carries the viewer's own role in `role` ("admin" for HA administrators).
export const ASSIGNABLE_ROLES = ["assisted", "patient", "caregiver", "doctor"];
export const canAct = (role) => ["patient", "caregiver", "doctor", "admin"].includes(role);
export const canEdit = (role) => ["doctor", "admin"].includes(role);

export const api = {
  listPatients: (hass) => send(hass, { type: "neopill/patients/list" }).then((r) => r.patients),
  addPatient: (hass, name) =>
    send(hass, { type: "neopill/patients/add", name }).then((r) => r.patient),
  updatePatient: (hass, patient_id, data) =>
    send(hass, { type: "neopill/patients/update", patient_id, ...data }).then((r) => r.patient),
  deletePatient: (hass, patient_id) => send(hass, { type: "neopill/patients/delete", patient_id }),

  listMedications: (hass, patient_id) =>
    send(hass, {
      type: "neopill/medications/list",
      ...(patient_id ? { patient_id } : {}),
    }).then((r) => r.medications),
  addMedication: (hass, data) =>
    send(hass, { type: "neopill/medications/add", ...data }).then((r) => r.medication),
  updateMedication: (hass, medication_id, data) =>
    send(hass, { type: "neopill/medications/update", medication_id, ...data }).then(
      (r) => r.medication
    ),
  deleteMedication: (hass, medication_id) =>
    send(hass, { type: "neopill/medications/delete", medication_id }),

  takeDose: (hass, medication_id, amount) =>
    send(hass, {
      type: "neopill/intake/take",
      medication_id,
      ...(amount !== undefined && amount !== null && amount !== "" ? { amount: Number(amount) } : {}),
    }),
  markMissed: (hass, medication_id) => send(hass, { type: "neopill/intake/mark_missed", medication_id }),
  restock: (hass, medication_id, amount, packages) =>
    send(hass, {
      type: "neopill/restock",
      medication_id,
      ...(amount !== undefined && amount !== null && amount !== "" ? { amount: Number(amount) } : {}),
      ...(packages !== undefined && packages !== null && packages !== ""
        ? { packages: Number(packages) }
        : {}),
    }),

  listEvents: (hass, start, end, patient_id) =>
    send(hass, {
      type: "neopill/events/list",
      start,
      end,
      ...(patient_id ? { patient_id } : {}),
    }).then((r) => r.events),

  me: (hass) => send(hass, { type: "neopill/me" }),
  listUsers: (hass) => send(hass, { type: "neopill/users/list" }).then((r) => r.users),
  importUsers: (hass) => send(hass, { type: "neopill/users/import" }).then((r) => r.patients),
  setAccess: (hass, patient_id, user_id, role) =>
    send(hass, { type: "neopill/access/set", patient_id, user_id, role }).then((r) => r.patient),
  linkUser: (hass, patient_id, user_id) =>
    send(hass, { type: "neopill/patients/link_user", patient_id, user_id }).then((r) => r.patient),
  updateSettings: (hass, settings) =>
    send(hass, { type: "neopill/settings/update", ...settings }).then((r) => r.settings),
};
