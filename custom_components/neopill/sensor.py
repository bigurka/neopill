"""Sensor platform for NeoPill: per-medication stock, next dose and days-remaining."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTime
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
        super().__init__(store, medication_id, "scorta")

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
        super().__init__(store, medication_id, "giorni_rimanenti")

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
        super().__init__(store, medication_id, "prossima_assunzione")
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
