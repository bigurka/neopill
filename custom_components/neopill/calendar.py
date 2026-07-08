"""Calendar platform for NeoPill: one native HA calendar entity per patient.

CalendarEntity has no built-in storage - events are materialized on the fly from
NeoPillStore's intake/restock history (past) plus each medication's next scheduled
dose from the DoseScheduler (a single upcoming occurrence, not a projected series).

Lives on the patient's "<Nome> NeoPill" hub device; cleanup on patient deletion
happens for free via that device's removal cascade (see __init__.py), so this
platform only needs to react to patients being *added*.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CALENDAR_EVENT_DEPLETED,
    CALENDAR_EVENT_MISSED,
    CALENDAR_EVENT_RESTOCK,
    CALENDAR_EVENT_TAKEN,
    SIGNAL_INTAKE_RECORDED,
    SIGNAL_MEDICATION_ADDED,
    SIGNAL_MEDICATION_REMOVED,
    SIGNAL_PATIENT_ADDED,
    SIGNAL_RESTOCK_RECORDED,
)
from .entity import patient_hub_device_info
from .models import Patient
from .storage import NeoPillStore

_EVENT_LABELS = {
    CALENDAR_EVENT_TAKEN: "Assunta",
    CALENDAR_EVENT_MISSED: "Non assunta",
    CALENDAR_EVENT_RESTOCK: "Rifornimento",
    CALENDAR_EVENT_DEPLETED: "Scorta esaurita",
}

_UPCOMING_DURATION = timedelta(minutes=15)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    store: NeoPillStore = entry.runtime_data.store
    scheduler = entry.runtime_data.scheduler

    @callback
    def _add_for_patient(patient: Patient) -> None:
        async_add_entities([PatientCalendarEntity(store, scheduler, patient.id)])

    for patient in store.list_patients():
        _add_for_patient(patient)

    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_PATIENT_ADDED, _add_for_patient))


class PatientCalendarEntity(CalendarEntity):
    """Calendar of intakes/missed doses/restocks for a single patient."""

    _attr_has_entity_name = True
    _attr_translation_key = "calendar"
    _attr_should_poll = False
    _attr_icon = "mdi:calendar-heart"

    def __init__(self, store: NeoPillStore, scheduler, patient_id: str) -> None:
        self._store = store
        self._scheduler = scheduler
        self._patient_id = patient_id
        self._attr_unique_id = f"{patient_id}_calendar"
        patient = store.patients.get(patient_id)
        if patient is not None:
            self.entity_id = f"calendar.{patient.slug}_neopill"

    @property
    def available(self) -> bool:
        return self._patient_id in self._store.patients

    @property
    def device_info(self) -> DeviceInfo | None:
        patient = self._store.patients.get(self._patient_id)
        return patient_hub_device_info(patient) if patient else None

    def _medication_ids(self) -> set[str]:
        return {m.id for m in self._store.list_medications(patient_id=self._patient_id)}

    @property
    def event(self) -> CalendarEvent | None:
        """Next upcoming due dose across this patient's medications, if any."""
        upcoming: list[tuple[datetime, str]] = []
        for medication in self._store.list_medications(patient_id=self._patient_id):
            due_at = self._scheduler.next_dose_at(medication.id)
            if due_at is not None:
                upcoming.append((due_at, medication.name))
        if not upcoming:
            return None
        due_at, med_name = min(upcoming, key=lambda item: item[0])
        return CalendarEvent(start=due_at, end=due_at + _UPCOMING_DURATION, summary=f"Da assumere: {med_name}")

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        medication_ids = self._medication_ids()
        events = self._store.events_in_range(medication_ids, start_date, end_date)
        calendar_events = [
            CalendarEvent(
                start=e["timestamp"],
                end=e["timestamp"] + _UPCOMING_DURATION,
                summary=f"{_EVENT_LABELS.get(e['type'], e['type'])}: {e['medication_name']}",
            )
            for e in events
        ]
        for medication in self._store.list_medications(patient_id=self._patient_id):
            due_at = self._scheduler.next_dose_at(medication.id)
            if due_at is not None and start_date <= due_at < end_date:
                calendar_events.append(
                    CalendarEvent(
                        start=due_at,
                        end=due_at + _UPCOMING_DURATION,
                        summary=f"Da assumere: {medication.name}",
                    )
                )
        calendar_events.sort(key=lambda e: e.start)
        return calendar_events

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        for signal in (
            SIGNAL_INTAKE_RECORDED,
            SIGNAL_RESTOCK_RECORDED,
            SIGNAL_MEDICATION_ADDED,
            SIGNAL_MEDICATION_REMOVED,
        ):
            self.async_on_remove(async_dispatcher_connect(self.hass, signal, self._handle_refresh))

    @callback
    def _handle_refresh(self, *_args) -> None:
        self.async_write_ha_state()
