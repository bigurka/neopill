"""Button platform for NeoPill.

Two kinds of buttons:
- per-medication quick actions (assumi ora / segna non assunta / rifornisci 1 confezione)
- per-patient, per-time-slot group actions: one "assumi tutti" / "segna tutti non
  assunti" pair for every distinct fixed dose time in use by that patient's
  medications, letting a single press act on every medication scheduled at that
  exact time. Dynamically created/removed as medications are added/edited/removed.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .actions import async_mark_missed, async_restock, async_take_dose
from .const import (
    SCHEDULE_TYPE_FIXED_TIMES,
    SIGNAL_MEDICATION_ADDED,
    SIGNAL_MEDICATION_REMOVED,
    SIGNAL_MEDICATION_UPDATED,
)
from .entity import NeoPillMedicationEntity, patient_hub_device_info
from .models import Medication
from .storage import NeoPillStore


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    store: NeoPillStore = entry.runtime_data.store
    scheduler = entry.runtime_data.scheduler

    @callback
    def _add_for_medication(medication: Medication) -> None:
        async_add_entities(
            [
                TakeDoseButton(store, medication.id, scheduler),
                MarkMissedButton(store, medication.id, scheduler),
                RestockPackageButton(store, medication.id),
            ]
        )

    for medication in store.list_medications():
        _add_for_medication(medication)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_MEDICATION_ADDED, _add_for_medication)
    )

    slot_manager = TimeSlotButtonManager(hass, store, scheduler, async_add_entities)
    slot_manager.async_recompute()
    for signal in (SIGNAL_MEDICATION_ADDED, SIGNAL_MEDICATION_UPDATED, SIGNAL_MEDICATION_REMOVED):
        entry.async_on_unload(async_dispatcher_connect(hass, signal, slot_manager.async_recompute))


class TakeDoseButton(NeoPillMedicationEntity, ButtonEntity):
    """Records one dose (the medication's configured amount) taken right now."""

    _attr_name = "Assumi ora"
    _attr_icon = "mdi:pill"

    def __init__(self, store: NeoPillStore, medication_id: str, scheduler) -> None:
        super().__init__(store, medication_id, "assumi_ora", "button")
        self._scheduler = scheduler

    async def async_press(self) -> None:
        await async_take_dose(self._store, self._scheduler, self._medication_id)


class MarkMissedButton(NeoPillMedicationEntity, ButtonEntity):
    """Explicitly declares the currently due dose as not taken."""

    _attr_name = "Segna come non assunta"
    _attr_icon = "mdi:pill-off"

    def __init__(self, store: NeoPillStore, medication_id: str, scheduler) -> None:
        super().__init__(store, medication_id, "segna_non_assunta", "button")
        self._scheduler = scheduler

    async def async_press(self) -> None:
        await async_mark_missed(self._store, self._scheduler, self._medication_id)


class RestockPackageButton(NeoPillMedicationEntity, ButtonEntity):
    """Adds one full package (the medication's configured package_size) to the stock.

    Only available for medications that have a package_size configured - otherwise
    there is nothing to compute "one package" from.
    """

    _attr_name = "Rifornisci (1 confezione)"
    _attr_icon = "mdi:package-variant-plus"

    def __init__(self, store: NeoPillStore, medication_id: str) -> None:
        super().__init__(store, medication_id, "rifornisci_confezione", "button")

    @property
    def available(self) -> bool:
        medication = self.medication
        return medication is not None and bool(medication.package_size)

    async def async_press(self) -> None:
        await async_restock(self._store, self._medication_id, packages=1)


class _TimeSlotButtonBase(ButtonEntity):
    """Shared plumbing for the per-patient, per-time-slot group action buttons."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, store: NeoPillStore, patient_id: str, time_str: str, key: str, name_prefix: str
    ) -> None:
        self._store = store
        self._patient_id = patient_id
        self._time_str = time_str
        self._attr_unique_id = f"{patient_id}_{time_str}_{key}"
        self._attr_name = f"{name_prefix} ore {time_str}"
        patient = store.patients.get(patient_id)
        slug = patient.slug if patient else "pz"
        self.entity_id = f"button.{slug}_{key}_{time_str.replace(':', '')}"

    @property
    def available(self) -> bool:
        return self._patient_id in self._store.patients

    @property
    def device_info(self) -> DeviceInfo | None:
        patient = self._store.patients.get(self._patient_id)
        return patient_hub_device_info(patient) if patient else None

    def _medications(self) -> list[Medication]:
        return [
            medication
            for medication in self._store.list_medications(patient_id=self._patient_id)
            if medication.dose_schedule.schedule_type == SCHEDULE_TYPE_FIXED_TIMES
            and self._time_str in medication.dose_schedule.fixed_times
        ]


class TimeSlotTakeButton(_TimeSlotButtonBase):
    """Logs an intake for every fixed-time medication sharing this time slot."""

    _attr_icon = "mdi:pill-multiple"

    def __init__(self, store: NeoPillStore, scheduler, patient_id: str, time_str: str) -> None:
        super().__init__(store, patient_id, time_str, "assumi_tutti", "Assumi tutti")
        self._scheduler = scheduler

    async def async_press(self) -> None:
        for medication in self._medications():
            await async_take_dose(self._store, self._scheduler, medication.id)


class TimeSlotMissedButton(_TimeSlotButtonBase):
    """Declares every fixed-time medication sharing this time slot as not taken."""

    _attr_icon = "mdi:pill-off"

    def __init__(self, store: NeoPillStore, scheduler, patient_id: str, time_str: str) -> None:
        super().__init__(store, patient_id, time_str, "segna_tutti_non_assunti", "Segna tutti non assunti")
        self._scheduler = scheduler

    async def async_press(self) -> None:
        for medication in self._medications():
            await async_mark_missed(self._store, self._scheduler, medication.id)


class TimeSlotButtonManager:
    """Keeps the set of per-(patient, time) group buttons in sync with the store.

    A pair of buttons exists for every distinct (patient, fixed-dose-time)
    combination currently in use. Recomputed on every medication add/edit/removal;
    entries no longer needed are removed individually (patient-wide cleanup, when
    a whole patient is deleted, instead happens for free via the patient hub
    device removal cascade).
    """

    def __init__(self, hass: HomeAssistant, store: NeoPillStore, scheduler, async_add_entities) -> None:
        self._hass = hass
        self._store = store
        self._scheduler = scheduler
        self._async_add_entities = async_add_entities
        self._entities: dict[tuple[str, str], list[ButtonEntity]] = {}

    def _current_groups(self) -> set[tuple[str, str]]:
        groups: set[tuple[str, str]] = set()
        for medication in self._store.list_medications():
            if medication.dose_schedule.schedule_type != SCHEDULE_TYPE_FIXED_TIMES:
                continue
            for time_str in medication.dose_schedule.fixed_times:
                groups.add((medication.patient_id, time_str))
        return groups

    @callback
    def async_recompute(self, *_args) -> None:
        wanted = self._current_groups()
        existing = set(self._entities.keys())

        for key in existing - wanted:
            for entity in self._entities.pop(key):
                self._hass.async_create_task(entity.async_remove(force_remove=True))

        new_entities: list[ButtonEntity] = []
        for key in wanted - existing:
            patient_id, time_str = key
            take = TimeSlotTakeButton(self._store, self._scheduler, patient_id, time_str)
            missed = TimeSlotMissedButton(self._store, self._scheduler, patient_id, time_str)
            self._entities[key] = [take, missed]
            new_entities.extend([take, missed])
        if new_entities:
            self._async_add_entities(new_entities)
