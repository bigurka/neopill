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

from .const import (
    RESTOCK_REMINDER_MAX_DAYS,
    RESTOCK_REMINDER_MIN_DAYS,
    SIGNAL_DOSE_DUE_CHANGED,
    SIGNAL_INTAKE_RECORDED,
    SIGNAL_MEDICATION_ADDED,
    SIGNAL_MEDICATION_REMOVED,
    SIGNAL_MEDICATION_UPDATED,
    SIGNAL_PATIENT_ADDED,
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

    _attr_name = "Scorta"
    _attr_native_unit_of_measurement = "unità"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:pill"

    def __init__(self, store: NeoPillStore, medication_id: str) -> None:
        super().__init__(store, medication_id, "scorta", "sensor")

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

    _attr_name = "Giorni rimanenti"
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, store: NeoPillStore, medication_id: str) -> None:
        super().__init__(store, medication_id, "giorni_rimanenti", "sensor")

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

    _attr_name = "Prossima assunzione"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-alert-outline"

    def __init__(self, store: NeoPillStore, medication_id: str, scheduler) -> None:
        super().__init__(store, medication_id, "prossima_assunzione", "sensor")
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
    """Per-patient summary of that patient's medications running low soon.

    Lives on the patient's "<Nome> NeoPill" hub device (cleaned up automatically
    when that device is removed on patient deletion). State is the count of
    medications whose estimated days-remaining falls within
    [RESTOCK_REMINDER_MIN_DAYS, RESTOCK_REMINDER_MAX_DAYS]; the "testo" attribute
    is a ready-to-send summary for a notify.* automation.
    """

    _attr_has_entity_name = True
    _attr_name = "Farmaci da rifornire"
    _attr_icon = "mdi:pill-multiple"
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, store: NeoPillStore, patient_id: str) -> None:
        self._store = store
        self._patient_id = patient_id
        self._attr_unique_id = f"{patient_id}_farmaci_da_rifornire"
        patient = store.patients.get(patient_id)
        if patient is not None:
            self.entity_id = f"sensor.{patient.slug}_farmaci_da_rifornire"

    @property
    def available(self) -> bool:
        return self._patient_id in self._store.patients

    @property
    def device_info(self) -> DeviceInfo | None:
        patient = self._store.patients.get(self._patient_id)
        return patient_hub_device_info(patient) if patient else None

    def _matching_medications(self) -> list[Medication]:
        matches = []
        for medication in self._store.list_medications(patient_id=self._patient_id):
            remaining = medication.days_remaining()
            if remaining is not None and RESTOCK_REMINDER_MIN_DAYS <= remaining <= RESTOCK_REMINDER_MAX_DAYS:
                matches.append(medication)
        return matches

    @property
    def native_value(self) -> int:
        return len(self._matching_medications())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        medications = self._matching_medications()
        items = []
        lines = []
        for medication in medications:
            remaining = round(medication.days_remaining(), 1)
            items.append(
                {
                    "medication_id": medication.id,
                    "name": medication.name,
                    "days_remaining": remaining,
                    "stock_quantity": medication.stock_quantity,
                }
            )
            lines.append(
                f"- {medication.name}: {remaining} giorni rimanenti, "
                f"scorta {medication.stock_quantity} unità"
            )
        testo = (
            f"Farmaci da rifornire nei prossimi {RESTOCK_REMINDER_MIN_DAYS}-"
            f"{RESTOCK_REMINDER_MAX_DAYS} giorni:\n" + "\n".join(lines)
            if lines
            else f"Nessun farmaco da rifornire nei prossimi {RESTOCK_REMINDER_MIN_DAYS}-"
            f"{RESTOCK_REMINDER_MAX_DAYS} giorni."
        )
        return {"farmaci": items, "testo": testo}

    async def async_added_to_hass(self) -> None:
        for signal in (
            SIGNAL_INTAKE_RECORDED,
            SIGNAL_RESTOCK_RECORDED,
            SIGNAL_MEDICATION_ADDED,
            SIGNAL_MEDICATION_UPDATED,
            SIGNAL_MEDICATION_REMOVED,
        ):
            self.async_on_remove(async_dispatcher_connect(self.hass, signal, self._handle_refresh))

    @callback
    def _handle_refresh(self, *_args) -> None:
        self.async_write_ha_state()
