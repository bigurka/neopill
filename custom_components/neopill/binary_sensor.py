"""Binary sensor platform for NeoPill: dose-due reminder and low-stock warning."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    SIGNAL_DOSE_DUE_CHANGED,
    SIGNAL_INTAKE_RECORDED,
    SIGNAL_MEDICATION_ADDED,
    SIGNAL_RESTOCK_RECORDED,
)
from .entity import NeoPillMedicationEntity
from .models import IntakeEvent, Medication, RestockEvent
from .storage import NeoPillStore


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    store: NeoPillStore = entry.runtime_data.store
    scheduler = entry.runtime_data.scheduler

    @callback
    def _add_for_medication(medication: Medication) -> None:
        async_add_entities(
            [
                DoseDueBinarySensor(store, medication.id, scheduler),
                LowStockBinarySensor(store, medication.id),
            ]
        )

    for medication in store.list_medications():
        _add_for_medication(medication)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_MEDICATION_ADDED, _add_for_medication)
    )


class DoseDueBinarySensor(NeoPillMedicationEntity, BinarySensorEntity):
    """On while a scheduled dose is due and has not been taken or declared missed."""

    _attr_translation_key = "dose_due"
    _attr_icon = "mdi:pill-multiple"

    def __init__(self, store: NeoPillStore, medication_id: str, scheduler) -> None:
        super().__init__(store, medication_id, "dose_due", "binary_sensor")
        self._scheduler = scheduler

    @property
    def is_on(self) -> bool:
        return self._scheduler.is_due(self._medication_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_DOSE_DUE_CHANGED, self._handle_due_changed)
        )

    @callback
    def _handle_due_changed(self, medication_id: str) -> None:
        if medication_id == self._medication_id:
            self.async_write_ha_state()


class LowStockBinarySensor(NeoPillMedicationEntity, BinarySensorEntity):
    """On when estimated days of stock remaining drop at or below the configured threshold."""

    _attr_translation_key = "low_stock"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:package-variant-closed-remove"

    def __init__(self, store: NeoPillStore, medication_id: str) -> None:
        super().__init__(store, medication_id, "low_stock", "binary_sensor")

    @property
    def is_on(self) -> bool:
        medication = self.medication
        return medication.is_low_stock() if medication else False

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
