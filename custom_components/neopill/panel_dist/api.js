// Thin wrapper around the Home Assistant websocket connection for all neopill/* commands.
// Plain ES module, no build step - served as-is by the integration's static path.

function send(hass, msg) {
  return hass.connection.sendMessagePromise(msg);
}

export const api = {
  listPatients: (hass) => send(hass, { type: "neopill/patients/list" }).then((r) => r.patients),
  addPatient: (hass, name) =>
    send(hass, { type: "neopill/patients/add", name }).then((r) => r.patient),
  updatePatient: (hass, patient_id, name) =>
    send(hass, { type: "neopill/patients/update", patient_id, name }).then((r) => r.patient),
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
};
