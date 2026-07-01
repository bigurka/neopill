"""Shared entity helpers for NeoPill medication devices."""
from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN, SIGNAL_MEDICATION_UPDATED
from .models import Medication
from .storage import NeoPillStore


def medication_device_info(medication: Medication) -> DeviceInfo:
    """Build the HA DeviceInfo for a medication's device."""
    return DeviceInfo(
        identifiers={(DOMAIN, medication.id)},
        name=medication.name,
        manufacturer="NeoPill",
        model="Farmaco",
    )


class NeoPillMedicationEntity(Entity):
    """Base class for entities that belong to a single medication device.

    Reads the medication live from the store (rather than caching a copy) so edits
    made from the panel are reflected without extra plumbing.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, store: NeoPillStore, medication_id: str, key: str) -> None:
        self._store = store
        self._medication_id = medication_id
        self._attr_unique_id = f"{medication_id}_{key}"

    @property
    def medication(self) -> Medication | None:
        return self._store.medications.get(self._medication_id)

    @property
    def device_info(self) -> DeviceInfo | None:
        medication = self.medication
        return medication_device_info(medication) if medication else None

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
