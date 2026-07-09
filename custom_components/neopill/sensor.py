"""Sensor platform for NeoPill: per-medication stock, next dose and days-remaining,
plus one per-patient restock-reminder summary sensor.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change

from .const import (
    SIGNAL_DOSE_DUE_CHANGED,
    SIGNAL_INTAKE_RECORDED,
    SIGNAL_MEDICATION_ADDED,
    SIGNAL_MEDICATION_REMOVED,
    SIGNAL_MEDICATION_UPDATED,
    SIGNAL_PATIENT_ADDED,
    SIGNAL_PATIENT_UPDATED,
    SIGNAL_RESTOCK_RECORDED,
)
from .entity import NeoPillMedicationEntity, patient_hub_device_info
from .models import IntakeEvent, Medication, Patient, RestockEvent
from .storage import NeoPillStore


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
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
    when that device is removed on patient deletion). A medication becomes a
    *candidate* once its estimated days-remaining falls within that patient's own
    "ideal reorder window" (Patient.restock_window_min_days/max_days, editable
    from the panel). The sensor's state is the count of medications being reported
    *today*: each candidate is reported once, either the moment it first enters the
    window (so you learn about it while there's still time to wait for others to
    join the same order) or - always - the moment it becomes the most urgent one
    (so nothing is ever silently missed), whichever comes first. A candidate that
    was already reported and isn't yet urgent again is not repeated in later
    batches, so a slow-to-restock medication doesn't reappear in every email while
    it waits alongside newer, more urgent ones. This decision is only recomputed
    at midnight and on HA restart (not on every live change), so the state stays
    stable for automations that check it once a day. The "testo" attribute is a
    ready-to-send summary for a notify.* automation.
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
        """Medications currently inside the reorder window, mapped to days-remaining."""
        patient = self._store.patients.get(self._patient_id)
        if patient is None:
            return {}
        candidates: dict[str, float] = {}
        for medication in self._store.list_medications(patient_id=self._patient_id):
            remaining = medication.days_remaining()
            if (
                remaining is not None
                and patient.restock_window_min_days <= remaining <= patient.restock_window_max_days
            ):
                candidates[medication.id] = remaining
        return candidates

    @callback
    def _async_recompute_decision(self) -> None:
        """Decide whether *today* is the day to report, and which medications to include.

        A medication is reported once: either the first time it enters the window (so
        you know about it while it's still safe to wait), or - always - once it becomes
        the urgent one forcing a report (so nothing is ever silently missed). Medications
        already reported earlier and still just waiting (not yet urgent again) are not
        repeated in every subsequent batch.
        """
        patient = self._store.patients.get(self._patient_id)
        candidates = self._candidate_medications()
        if not candidates or patient is None:
            self._decided_ids = set()
            if patient is not None and patient.restock_reported_ids:
                self.hass.async_create_task(
                    self._store.async_set_restock_reported_ids(patient.id, [])
                )
            return

        previously_reported = set(patient.restock_reported_ids) & set(candidates)
        new_ids = set(candidates) - previously_reported
        forced_ids = {
            medication_id
            for medication_id, remaining in candidates.items()
            if remaining <= patient.restock_window_min_days
        }
        self._decided_ids = new_ids | forced_ids

        updated_reported = previously_reported | self._decided_ids
        if updated_reported != set(patient.restock_reported_ids):
            self.hass.async_create_task(
                self._store.async_set_restock_reported_ids(patient.id, sorted(updated_reported))
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
        return {"farmaci": items, "testo": testo}

    async def async_added_to_hass(self) -> None:
        self._async_recompute_decision()
        for signal in (
            SIGNAL_INTAKE_RECORDED,
            SIGNAL_RESTOCK_RECORDED,
            SIGNAL_MEDICATION_ADDED,
            SIGNAL_MEDICATION_UPDATED,
        ):
            self.async_on_remove(async_dispatcher_connect(self.hass, signal, self._handle_refresh))
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_MEDICATION_REMOVED, self._handle_medication_removed)
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_PATIENT_UPDATED, self._handle_patient_updated)
        )
        self.async_on_remove(
            async_track_time_change(self.hass, self._handle_midnight, hour=0, minute=0, second=30)
        )

    @callback
    def _handle_refresh(self, *_args) -> None:
        """Live data (stock, days-remaining) for already-decided medications may change,
        but which medications are decided is only recomputed at midnight/restart."""
        self.async_write_ha_state()

    @callback
    def _handle_medication_removed(self, medication_id: str) -> None:
        self._decided_ids.discard(medication_id)
        self.async_write_ha_state()

    @callback
    def _handle_patient_updated(self, patient: Patient) -> None:
        if patient.id == self._patient_id:
            # The reorder window itself may have just changed - reflect that now
            # rather than waiting for the next midnight recompute.
            self._async_recompute_decision()
            self.async_write_ha_state()

    @callback
    def _handle_midnight(self, _now) -> None:
        self._async_recompute_decision()
        self.async_write_ha_state()
