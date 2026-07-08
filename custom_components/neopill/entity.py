"""Shared entity helpers for NeoPill medication and patient devices."""
from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.util import slugify

from .const import DOMAIN, SIGNAL_MEDICATION_UPDATED
from .models import Medication, Patient
from .storage import NeoPillStore


def patient_hub_identifier(patient_id: str) -> tuple[str, str]:
    return (DOMAIN, f"patient_{patient_id}")


def patient_hub_device_info(patient: Patient) -> DeviceInfo:
    """DeviceInfo for a patient's hub device.

    Owns the cross-medication entities (calendar, restock summary, per-time-slot
    group buttons) and is the via_device parent for that patient's medications.
    """
    return DeviceInfo(
        identifiers={patient_hub_identifier(patient.id)},
        name=f"{patient.name} NeoPill",
        manufacturer="NeoPill",
        model="Paziente",
    )


def medication_device_info(medication: Medication, patient: Patient | None) -> DeviceInfo:
    """DeviceInfo for a medication's device - name includes the patient to
    disambiguate same-named medications across different patients."""
    patient_name = patient.name if patient else "?"
    info = DeviceInfo(
        identifiers={(DOMAIN, medication.id)},
        name=f"{medication.name} ({patient_name})",
        manufacturer="NeoPill",
        model="Farmaco",
    )
    if patient is not None:
        info["via_device"] = patient_hub_identifier(patient.id)
    return info


def medication_entity_id(
    platform: str, patient: Patient | None, medication: Medication, key: str
) -> str:
    """Entity id carrying the patient's stable slug, so same-named medications
    across different patients never collide and stay easy to tell apart."""
    patient_slug = patient.slug if patient else "pz"
    med_slug = slugify(medication.name) or medication.id[:8]
    return f"{platform}.{patient_slug}_{med_slug}_{key}"


class NeoPillMedicationEntity(Entity):
    """Base class for entities that belong to a single medication device.

    Reads the medication live from the store (rather than caching a copy) so edits
    made from the panel are reflected without extra plumbing.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, store: NeoPillStore, medication_id: str, key: str, platform: str) -> None:
        self._store = store
        self._medication_id = medication_id
        self._attr_unique_id = f"{medication_id}_{key}"
        medication = store.medications.get(medication_id)
        if medication is not None:
            patient = store.patients.get(medication.patient_id)
            self.entity_id = medication_entity_id(platform, patient, medication, key)

    @property
    def medication(self) -> Medication | None:
        return self._store.medications.get(self._medication_id)

    @property
    def device_info(self) -> DeviceInfo | None:
        medication = self.medication
        if medication is None:
            return None
        patient = self._store.patients.get(medication.patient_id)
        return medication_device_info(medication, patient)

    @property
    def available(self) -> bool:
        return self.medication is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_MEDICATION_UPDATED, self._handle_medication_updated
            )
        )

    @callback
    def _handle_medication_updated(self, medication: Medication) -> None:
        if medication.id == self._medication_id:
            self.async_write_ha_state()
