"""Sensor platform for NeoPill: per-medication stock, next dose and days-remaining,
plus one per-patient restock-reminder summary sensor.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_change

from .const import (
    SIGNAL_DOSE_DUE_CHANGED,
    SIGNAL_INTAKE_RECORDED,
    SIGNAL_MEDICATION_ADDED,
    SIGNAL_MEDICATION_REMOVED,
    SIGNAL_MEDICATION_UPDATED,
    SIGNAL_PATIENT_ADDED,
    SIGNAL_PATIENT_UPDATED,
    SIGNAL_RESTOCK_NOTIFY_CHANGED,
    SIGNAL_RESTOCK_RECORDED,
)
from .entity import NeoPillMedicationEntity, patient_hub_device_info
from .models import IntakeEvent, Medication, Patient, RestockEvent
from .storage import NeoPillStore


# Everything is computed locally from NeoPill's own store: no limit needed.
PARALLEL_UPDATES = 0

async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    store: NeoPillStore = entry.runtime_data.store
    scheduler = entry.runtime_data.scheduler

    @callback
    def _add_for_patient(patient: Patient) -> None:
        async_add_entities([RestockReminderSensor(store, patient.id)])

    for patient in store.list_patients():
        _add_for_patient(patient)

    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_PATIENT_ADDED, _add_for_patient))

    @callback
    def _add_for_medication(medication: Medication) -> None:
        async_add_entities(
            [
                StockSensor(store, medication.id),
                DaysRemainingSensor(store, medication.id),
                NextDoseSensor(store, medication.id, scheduler),
            ]
        )

    for medication in store.list_medications():
        _add_for_medication(medication)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_MEDICATION_ADDED, _add_for_medication)
    )


class StockSensor(NeoPillMedicationEntity, SensorEntity):
    """Current stock quantity for a medication."""

    _attr_translation_key = "stock"
    _attr_native_unit_of_measurement = "unità"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:pill"

    def __init__(self, store: NeoPillStore, medication_id: str) -> None:
        super().__init__(store, medication_id, "stock", "sensor")

    @property
    def native_value(self) -> float | None:
        medication = self.medication
        return medication.stock_quantity if medication else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_INTAKE_RECORDED, self._handle_event)
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_RESTOCK_RECORDED, self._handle_event)
        )

    @callback
    def _handle_event(self, event: IntakeEvent | RestockEvent) -> None:
        if event.medication_id == self._medication_id:
            self.async_write_ha_state()


class DaysRemainingSensor(NeoPillMedicationEntity, SensorEntity):
    """Estimated days of stock remaining, based on the dose schedule's consumption rate."""

    _attr_translation_key = "days_remaining"
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, store: NeoPillStore, medication_id: str) -> None:
        super().__init__(store, medication_id, "days_remaining", "sensor")

    @property
    def native_value(self) -> float | None:
        medication = self.medication
        if medication is None:
            return None
        remaining = medication.days_remaining()
        return round(remaining, 1) if remaining is not None else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_INTAKE_RECORDED, self._handle_event)
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_RESTOCK_RECORDED, self._handle_event)
        )

    @callback
    def _handle_event(self, event: IntakeEvent | RestockEvent) -> None:
        if event.medication_id == self._medication_id:
            self.async_write_ha_state()


class NextDoseSensor(NeoPillMedicationEntity, SensorEntity):
    """Timestamp of the next (or currently due) dose."""

    _attr_translation_key = "next_dose"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-alert-outline"

    def __init__(self, store: NeoPillStore, medication_id: str, scheduler) -> None:
        super().__init__(store, medication_id, "next_dose", "sensor")
        self._scheduler = scheduler

    @property
    def native_value(self):
        return self._scheduler.next_dose_at(self._medication_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_DOSE_DUE_CHANGED, self._handle_due_changed)
        )

    @callback
    def _handle_due_changed(self, medication_id: str) -> None:
        if medication_id == self._medication_id:
            self.async_write_ha_state()


class RestockReminderSensor(SensorEntity):
    """Per-patient summary of that patient's medications ready to batch into one order.

    Lives on the patient's "<Nome> NeoPill" hub device (cleaned up automatically
    when that device is removed on patient deletion). A medication is a *candidate*
    once its estimated days-remaining falls at or below that patient's own "ideal
    reorder window" max (Patient.restock_window_max_days, editable from the panel) -
    no lower bound, so a medication doesn't drop out of consideration just because
    it's now more overdue than the window's min. The sensor only reports something
    once at least one candidate has reached the window's min (the "don't wait any
    longer" cutoff) - at that point *every* current candidate is included, not just
    the one that triggered it, so as many medications as possible get batched into
    the same pharmacy trip. Recomputed on every relevant change (intake, restock,
    medication add/edit/removal, patient window edit) plus a midnight/restart safety
    sweep, so it never sits stale. The "testo" attribute is a ready-to-send summary
    for a notify.* automation.

    The "already notified" bookkeeping lives per medication (see
    Medication.restock_notify_pending), not on this sensor: whenever a medication
    newly joins the batch, its own flag is raised; it's only lowered again by an
    automation (via the neopill.segna_rifornimento_notificato service) or by the
    medication leaving the batch. This sensor's own "da_notificare" attribute is
    just the OR of its currently-decided medications' flags, so a partial restock
    (acknowledging one medication while another stays pending) behaves correctly.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "restock_reminder"
    _attr_icon = "mdi:pill-multiple"
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, store: NeoPillStore, patient_id: str) -> None:
        self._store = store
        self._patient_id = patient_id
        self._attr_unique_id = f"{patient_id}_restock_reminder"
        self._decided_ids: set[str] = set()
        patient = store.patients.get(patient_id)
        if patient is not None:
            self.entity_id = f"sensor.{patient.slug}_restock_reminder"

    @property
    def available(self) -> bool:
        return self._patient_id in self._store.patients

    @property
    def device_info(self) -> DeviceInfo | None:
        patient = self._store.patients.get(self._patient_id)
        return patient_hub_device_info(patient) if patient else None

    def _candidate_medications(self) -> dict[str, float]:
        """Medications at or below the reorder window's max, mapped to days-remaining.

        No lower bound: a medication that's more overdue than the window's min is
        still a candidate (and still swept into the batch), it just no longer needs
        to be the one that *triggers* the report.
        """
        patient = self._store.patients.get(self._patient_id)
        if patient is None:
            return {}
        candidates: dict[str, float] = {}
        for medication in self._store.list_medications(patient_id=self._patient_id):
            remaining = medication.days_remaining()
            if remaining is not None and remaining <= patient.restock_window_max_days:
                candidates[medication.id] = remaining
        return candidates

    @callback
    def _async_recompute_decision(self) -> None:
        """Decide whether to report, which medications to include, and raise/clear
        each one's own restock_notify_pending flag on the transitions.

        Nothing is reported until at least one candidate reaches the window's min
        (the "don't wait any longer" cutoff) - at that point every current candidate
        is included, not just the one that triggered it, to batch as many medications
        as possible into the same pharmacy trip. A medication *newly* entering this
        batch (compared to Patient.restock_previous_decided_ids, persisted so a
        restart doesn't look like a fresh entry) has its notify flag raised; one
        newly *leaving* it has the flag cleared, ready for a future fresh occurrence.
        A medication that stays in the batch across recomputes is left untouched, so
        an automation's acknowledgement (clearing the flag) isn't undone the moment
        anything else changes while it's still pending.
        """
        patient = self._store.patients.get(self._patient_id)
        candidates = self._candidate_medications()
        triggered = patient is not None and any(
            remaining <= patient.restock_window_min_days for remaining in candidates.values()
        )
        self._decided_ids = set(candidates) if triggered else set()

        if patient is None:
            return
        previous_decided = set(patient.restock_previous_decided_ids)
        for medication_id in self._decided_ids - previous_decided:
            self.hass.async_create_task(self._store.async_set_restock_notify_pending(medication_id, True))
        for medication_id in previous_decided - self._decided_ids:
            self.hass.async_create_task(self._store.async_set_restock_notify_pending(medication_id, False))
        if self._decided_ids != previous_decided:
            self.hass.async_create_task(
                self._store.async_set_restock_previous_decided(patient.id, sorted(self._decided_ids))
            )

    def _decided_medications(self) -> list[Medication]:
        return [
            medication
            for medication_id in self._decided_ids
            if (medication := self._store.medications.get(medication_id)) is not None
        ]

    @property
    def native_value(self) -> int:
        return len(self._decided_ids)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        patient = self._store.patients.get(self._patient_id)
        medications = self._decided_medications()
        items = []
        lines = []
        for medication in medications:
            remaining = round(medication.days_remaining(), 1)
            depletion_date = medication.next_depletion_date()
            display_name = medication.display_name()
            items.append(
                {
                    "medication_id": medication.id,
                    "name": medication.name,
                    "display_name": display_name,
                    "days_remaining": remaining,
                    "stock_quantity": medication.stock_quantity,
                    "data_esaurimento_prevista": depletion_date.isoformat() if depletion_date else None,
                }
            )
            lines.append(f"- {display_name}: {remaining} giorni rimanenti")
        window_min = patient.restock_window_min_days if patient else "-"
        window_max = patient.restock_window_max_days if patient else "-"
        testo = (
            "\n".join(lines)
            if lines
            else f"Nessun farmaco da rifornire nella finestra {window_min}-{window_max} giorni."
        )
        da_notificare = any(m.restock_notify_pending for m in medications)
        return {
            "farmaci": items,
            "testo": testo,
            "patient_id": self._patient_id,
            "da_notificare": da_notificare,
        }

    async def async_added_to_hass(self) -> None:
        self._async_recompute_decision()
        for signal in (
            SIGNAL_INTAKE_RECORDED,
            SIGNAL_RESTOCK_RECORDED,
            SIGNAL_MEDICATION_ADDED,
            SIGNAL_MEDICATION_UPDATED,
            SIGNAL_MEDICATION_REMOVED,
        ):
            self.async_on_remove(async_dispatcher_connect(self.hass, signal, self._handle_recompute))
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_PATIENT_UPDATED, self._handle_patient_updated)
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_RESTOCK_NOTIFY_CHANGED, self._handle_notify_changed)
        )
        self.async_on_remove(
            async_track_time_change(self.hass, self._handle_midnight, hour=0, minute=0, second=30)
        )

    @callback
    def _handle_recompute(self, *_args) -> None:
        """Any change to stock, doses or medications can change who's a candidate
        or who triggers the report, so recompute on every one of these signals
        instead of only at midnight - keeps the sensor from ever sitting stale."""
        self._async_recompute_decision()
        self.async_write_ha_state()

    @callback
    def _handle_patient_updated(self, patient: Patient) -> None:
        if patient.id == self._patient_id:
            self._async_recompute_decision()
            self.async_write_ha_state()

    @callback
    def _handle_notify_changed(self, medication_id: str) -> None:
        """A medication's restock_notify_pending flag changed (raised by our own
        recompute, or cleared by an automation via the service) - refresh the
        aggregate "da_notificare" attribute, which is just the OR of all our
        currently-decided medications' flags."""
        if medication_id in self._decided_ids:
            self.async_write_ha_state()

    @callback
    def _handle_midnight(self, _now) -> None:
        self._async_recompute_decision()
        self.async_write_ha_state()
