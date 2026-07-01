"""Persistent storage layer for NeoPill (patients, medications, intake/restock history).

Single JSON blob via homeassistant.helpers.storage.Store - no external database.
All mutating methods keep the in-memory dicts/lists and the on-disk copy in sync and
fire a dispatcher signal so entity platforms and the scheduler can react.
"""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
import homeassistant.util.dt as dt_util

from .const import (
    CALENDAR_EVENT_DEPLETED,
    CALENDAR_EVENT_MISSED,
    CALENDAR_EVENT_RESTOCK,
    CALENDAR_EVENT_TAKEN,
    DEFAULT_LOW_STOCK_DAYS_THRESHOLD,
    INTAKE_STATUS_MISSED,
    INTAKE_STATUS_TAKEN,
    SIGNAL_INTAKE_RECORDED,
    SIGNAL_MEDICATION_ADDED,
    SIGNAL_MEDICATION_REMOVED,
    SIGNAL_MEDICATION_UPDATED,
    SIGNAL_PATIENT_ADDED,
    SIGNAL_PATIENT_REMOVED,
    SIGNAL_RESTOCK_RECORDED,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .models import DoseSchedule, IntakeEvent, Medication, Patient, RestockEvent

_LOGGER = logging.getLogger(__name__)

_SAVE_DELAY = 5


class PatientNotFoundError(KeyError):
    """Raised when a patient id does not exist."""


class MedicationNotFoundError(KeyError):
    """Raised when a medication id does not exist."""


class NeoPillStore:
    """Wraps a single Store instance holding all NeoPill data for one config entry."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.patients: dict[str, Patient] = {}
        self.medications: dict[str, Medication] = {}
        self.intake_events: list[IntakeEvent] = []
        self.restock_events: list[RestockEvent] = []

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.patients = {
            pid: Patient.from_dict(pdata) for pid, pdata in data.get("patients", {}).items()
        }
        self.medications = {
            mid: Medication.from_dict(mdata)
            for mid, mdata in data.get("medications", {}).items()
        }
        self.intake_events = [IntakeEvent.from_dict(e) for e in data.get("intake_events", [])]
        self.restock_events = [RestockEvent.from_dict(e) for e in data.get("restock_events", [])]

    def _as_storage_dict(self) -> dict[str, Any]:
        return {
            "patients": {pid: p.as_dict() for pid, p in self.patients.items()},
            "medications": {mid: m.as_dict() for mid, m in self.medications.items()},
            "intake_events": [e.as_dict() for e in self.intake_events],
            "restock_events": [e.as_dict() for e in self.restock_events],
        }

    async def _async_save(self) -> None:
        await self._store.async_save(self._as_storage_dict())

    def _async_delay_save(self) -> None:
        self._store.async_delay_save(self._as_storage_dict, _SAVE_DELAY)

    # ---- Patients ----

    def list_patients(self) -> list[Patient]:
        return list(self.patients.values())

    def get_patient(self, patient_id: str) -> Patient:
        try:
            return self.patients[patient_id]
        except KeyError as err:
            raise PatientNotFoundError(patient_id) from err

    async def async_add_patient(self, name: str) -> Patient:
        patient = Patient(name=name)
        self.patients[patient.id] = patient
        await self._async_save()
        async_dispatcher_send(self._hass, SIGNAL_PATIENT_ADDED, patient)
        return patient

    async def async_update_patient(self, patient_id: str, name: str) -> Patient:
        patient = self.get_patient(patient_id)
        patient.name = name
        await self._async_save()
        return patient

    async def async_delete_patient(self, patient_id: str) -> None:
        self.get_patient(patient_id)
        for medication in self.list_medications(patient_id=patient_id):
            await self.async_delete_medication(medication.id)
        del self.patients[patient_id]
        await self._async_save()
        async_dispatcher_send(self._hass, SIGNAL_PATIENT_REMOVED, patient_id)

    # ---- Medications ----

    def list_medications(self, patient_id: str | None = None) -> list[Medication]:
        medications = list(self.medications.values())
        if patient_id is not None:
            medications = [m for m in medications if m.patient_id == patient_id]
        return medications

    def get_medication(self, medication_id: str) -> Medication:
        try:
            return self.medications[medication_id]
        except KeyError as err:
            raise MedicationNotFoundError(medication_id) from err

    async def async_add_medication(
        self,
        patient_id: str,
        name: str,
        *,
        dose_amount: float = 1.0,
        stock_quantity: float = 0.0,
        package_size: float | None = None,
        low_stock_days_threshold: int | None = None,
        dose_schedule: DoseSchedule | None = None,
        notes: str = "",
    ) -> Medication:
        self.get_patient(patient_id)  # raises PatientNotFoundError if unknown
        medication = Medication(
            patient_id=patient_id,
            name=name,
            dose_amount=dose_amount,
            stock_quantity=stock_quantity,
            package_size=package_size,
            low_stock_days_threshold=(
                low_stock_days_threshold
                if low_stock_days_threshold is not None
                else DEFAULT_LOW_STOCK_DAYS_THRESHOLD
            ),
            dose_schedule=dose_schedule or DoseSchedule(),
            notes=notes,
        )
        self.medications[medication.id] = medication
        await self._async_save()
        async_dispatcher_send(self._hass, SIGNAL_MEDICATION_ADDED, medication)
        return medication

    async def async_update_medication(self, medication_id: str, **fields: Any) -> Medication:
        medication = self.get_medication(medication_id)
        schedule = fields.pop("dose_schedule", None)
        if schedule is not None:
            medication.dose_schedule = (
                schedule if isinstance(schedule, DoseSchedule) else DoseSchedule.from_dict(schedule)
            )
        for key, value in fields.items():
            if value is not None and hasattr(medication, key):
                setattr(medication, key, value)
        await self._async_save()
        async_dispatcher_send(self._hass, SIGNAL_MEDICATION_UPDATED, medication)
        return medication

    async def async_delete_medication(self, medication_id: str) -> None:
        self.get_medication(medication_id)
        del self.medications[medication_id]
        self.intake_events = [e for e in self.intake_events if e.medication_id != medication_id]
        self.restock_events = [e for e in self.restock_events if e.medication_id != medication_id]
        await self._async_save()
        async_dispatcher_send(self._hass, SIGNAL_MEDICATION_REMOVED, medication_id)

    # ---- Intake / missed / restock actions ----

    def last_taken_intake(self, medication_id: str) -> IntakeEvent | None:
        taken = [
            e
            for e in self.intake_events
            if e.medication_id == medication_id and e.status == INTAKE_STATUS_TAKEN
        ]
        if not taken:
            return None
        return max(taken, key=lambda e: e.timestamp)

    def last_intake_event(self, medication_id: str) -> IntakeEvent | None:
        """Most recent intake event (taken or missed) - used as scheduling anchor on restart."""
        events = [e for e in self.intake_events if e.medication_id == medication_id]
        if not events:
            return None
        return max(events, key=lambda e: e.timestamp)

    async def async_record_intake(
        self,
        medication_id: str,
        *,
        amount: float | None = None,
        scheduled_for: datetime | None = None,
    ) -> IntakeEvent:
        medication = self.get_medication(medication_id)
        actual_amount = amount if amount is not None else medication.dose_amount
        medication.stock_quantity = max(0.0, medication.stock_quantity - actual_amount)
        event = IntakeEvent(
            medication_id=medication_id,
            timestamp=dt_util.utcnow(),
            amount=actual_amount,
            status=INTAKE_STATUS_TAKEN,
            scheduled_for=scheduled_for,
            depleted=medication.stock_quantity <= 0,
        )
        self.intake_events.append(event)
        self._async_delay_save()
        async_dispatcher_send(self._hass, SIGNAL_INTAKE_RECORDED, event)
        return event

    async def async_record_missed(
        self, medication_id: str, *, scheduled_for: datetime | None = None
    ) -> IntakeEvent:
        self.get_medication(medication_id)
        event = IntakeEvent(
            medication_id=medication_id,
            timestamp=dt_util.utcnow(),
            amount=0.0,
            status=INTAKE_STATUS_MISSED,
            scheduled_for=scheduled_for,
        )
        self.intake_events.append(event)
        await self._async_save()
        async_dispatcher_send(self._hass, SIGNAL_INTAKE_RECORDED, event)
        return event

    async def async_record_restock(
        self,
        medication_id: str,
        *,
        amount: float | None = None,
        packages: float | None = None,
    ) -> RestockEvent:
        medication = self.get_medication(medication_id)
        if packages is not None:
            if not medication.package_size:
                raise ValueError(f"Medication {medication_id} has no package_size configured")
            amount_added = packages * medication.package_size
        elif amount is not None:
            amount_added = amount
        else:
            raise ValueError("Either amount or packages must be provided")
        medication.stock_quantity += amount_added
        event = RestockEvent(
            medication_id=medication_id,
            timestamp=dt_util.utcnow(),
            amount_added=amount_added,
            new_total=medication.stock_quantity,
            packages=packages,
        )
        self.restock_events.append(event)
        await self._async_save()
        async_dispatcher_send(self._hass, SIGNAL_RESTOCK_RECORDED, event)
        return event

    # ---- History / calendar queries ----

    def events_in_range(
        self, medication_ids: set[str], start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """Return a flat, time-sorted list of calendar-ready event dicts within [start, end)."""
        results: list[dict[str, Any]] = []

        for intake in self.intake_events:
            if intake.medication_id not in medication_ids:
                continue
            if not start <= intake.timestamp < end:
                continue
            medication = self.medications.get(intake.medication_id)
            med_name = medication.name if medication else intake.medication_id
            if intake.status == INTAKE_STATUS_TAKEN:
                results.append(
                    {
                        "type": CALENDAR_EVENT_TAKEN,
                        "medication_id": intake.medication_id,
                        "medication_name": med_name,
                        "timestamp": intake.timestamp,
                        "amount": intake.amount,
                    }
                )
                if intake.depleted:
                    results.append(
                        {
                            "type": CALENDAR_EVENT_DEPLETED,
                            "medication_id": intake.medication_id,
                            "medication_name": med_name,
                            "timestamp": intake.timestamp,
                        }
                    )
            else:
                results.append(
                    {
                        "type": CALENDAR_EVENT_MISSED,
                        "medication_id": intake.medication_id,
                        "medication_name": med_name,
                        "timestamp": intake.timestamp,
                    }
                )

        for restock in self.restock_events:
            if restock.medication_id not in medication_ids:
                continue
            if not start <= restock.timestamp < end:
                continue
            medication = self.medications.get(restock.medication_id)
            med_name = medication.name if medication else restock.medication_id
            results.append(
                {
                    "type": CALENDAR_EVENT_RESTOCK,
                    "medication_id": restock.medication_id,
                    "medication_name": med_name,
                    "timestamp": restock.timestamp,
                    "amount_added": restock.amount_added,
                }
            )

        results.sort(key=lambda e: e["timestamp"])
        return results
