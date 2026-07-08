"""Button platform for NeoPill.

Two kinds of buttons:
- per-medication quick actions (take dose / mark missed / restock 1 package)
- per-patient, per-time-slot group actions: one "take all" / "mark all missed"
  pair for every distinct fixed dose time in use by that patient's
  medications, letting a single press act on every medication scheduled at that
  exact time. Dynamically created/removed as medications are added/edited/removed.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .actions import async_mark_missed, async_restock, async_take_dose
from .const import (
    SCHEDULE_TYPE_FIXED_TIMES,
    SCHEDULE_TYPE_WEEKLY,
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
    slot_manager.async_cleanup_orphans(entry.entry_id)
    slot_manager.async_recompute()
    for signal in (SIGNAL_MEDICATION_ADDED, SIGNAL_MEDICATION_UPDATED, SIGNAL_MEDICATION_REMOVED):
        entry.async_on_unload(async_dispatcher_connect(hass, signal, slot_manager.async_recompute))


class TakeDoseButton(NeoPillMedicationEntity, ButtonEntity):
    """Records one dose (the medication's configured amount) taken right now."""

    _attr_translation_key = "take_dose"
    _attr_icon = "mdi:pill"

    def __init__(self, store: NeoPillStore, medication_id: str, scheduler) -> None:
        super().__init__(store, medication_id, "take_dose", "button")
        self._scheduler = scheduler

    async def async_press(self) -> None:
        await async_take_dose(self._store, self._scheduler, self._medication_id)


class MarkMissedButton(NeoPillMedicationEntity, ButtonEntity):
    """Explicitly declares the currently due dose as not taken."""

    _attr_translation_key = "mark_missed"
    _attr_icon = "mdi:pill-off"

    def __init__(self, store: NeoPillStore, medication_id: str, scheduler) -> None:
        super().__init__(store, medication_id, "mark_missed", "button")
        self._scheduler = scheduler

    async def async_press(self) -> None:
        await async_mark_missed(self._store, self._scheduler, self._medication_id)


class RestockPackageButton(NeoPillMedicationEntity, ButtonEntity):
    """Adds one full package (the medication's configured package_size) to the stock.

    Only available for medications that have a package_size configured - otherwise
    there is nothing to compute "one package" from.
    """

    _attr_translation_key = "restock_package"
    _attr_icon = "mdi:package-variant-plus"

    def __init__(self, store: NeoPillStore, medication_id: str) -> None:
        super().__init__(store, medication_id, "restock_package", "button")

    @property
    def available(self) -> bool:
        medication = self.medication
        return medication is not None and bool(medication.package_size)

    async def async_press(self) -> None:
        await async_restock(self._store, self._medication_id, packages=1)


def _medication_uses_time(medication: Medication, time_str: str) -> bool:
    """True if this medication has `time_str` configured, fixed-daily or weekly."""
    schedule = medication.dose_schedule
    if schedule.schedule_type == SCHEDULE_TYPE_FIXED_TIMES:
        return time_str in schedule.fixed_times
    if schedule.schedule_type == SCHEDULE_TYPE_WEEKLY:
        return any(time_str in times for times in schedule.weekly_times.values())
    return False


class _TimeSlotButtonBase(ButtonEntity):
    """Shared plumbing for the per-patient, per-time-slot group action buttons."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, store: NeoPillStore, patient_id: str, time_str: str, key: str, translation_key: str
    ) -> None:
        self._store = store
        self._patient_id = patient_id
        self._time_str = time_str
        self._attr_unique_id = f"{patient_id}_{time_str}_{key}"
        self._attr_translation_key = translation_key
        self._attr_translation_placeholders = {"time": time_str}
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
            if _medication_uses_time(medication, self._time_str)
        ]


class TimeSlotTakeButton(_TimeSlotButtonBase):
    """Logs an intake for every fixed-time medication sharing this time slot."""

    _attr_icon = "mdi:pill-multiple"

    def __init__(self, store: NeoPillStore, scheduler, patient_id: str, time_str: str) -> None:
        super().__init__(store, patient_id, time_str, "take_all", "take_all")
        self._scheduler = scheduler

    async def async_press(self) -> None:
        for medication in self._medications():
            await async_take_dose(self._store, self._scheduler, medication.id)


class TimeSlotMissedButton(_TimeSlotButtonBase):
    """Declares every fixed-time medication sharing this time slot as not taken."""

    _attr_icon = "mdi:pill-off"

    def __init__(self, store: NeoPillStore, scheduler, patient_id: str, time_str: str) -> None:
        super().__init__(store, patient_id, time_str, "mark_all_missed", "mark_all_missed")
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

    # Recognizes both the current (English) and legacy pre-v0.5.0 (Italian)
    # unique_id suffixes, so renaming these keys doesn't leave the old ones as
    # permanent ghosts - the wanted-set diff below removes anything not current.
    _KNOWN_SUFFIXES = (
        "_take_all",
        "_mark_all_missed",
        "_assumi_tutti",
        "_segna_tutti_non_assunti",
    )

    def async_cleanup_orphans(self, entry_id: str) -> None:
        """One-time startup sweep for ghost registry entries from before this
        manager properly deregistered obsolete time-slot buttons (fixed
        prospectively in async_recompute/_async_fully_remove) - without this,
        those entries linger forever as permanently "unavailable" entities."""
        wanted_unique_ids: set[str] = set()
        for patient_id, time_str in self._current_groups():
            wanted_unique_ids.add(f"{patient_id}_{time_str}_take_all")
            wanted_unique_ids.add(f"{patient_id}_{time_str}_mark_all_missed")

        registry = er.async_get(self._hass)
        for reg_entry in er.async_entries_for_config_entry(registry, entry_id):
            if reg_entry.domain != "button" or not reg_entry.unique_id:
                continue
            if not reg_entry.unique_id.endswith(self._KNOWN_SUFFIXES):
                continue
            if reg_entry.unique_id not in wanted_unique_ids:
                registry.async_remove(reg_entry.entity_id)

    def _current_groups(self) -> set[tuple[str, str]]:
        groups: set[tuple[str, str]] = set()
        for medication in self._store.list_medications():
            schedule = medication.dose_schedule
            if schedule.schedule_type == SCHEDULE_TYPE_FIXED_TIMES:
                for time_str in schedule.fixed_times:
                    groups.add((medication.patient_id, time_str))
            elif schedule.schedule_type == SCHEDULE_TYPE_WEEKLY:
                for times in schedule.weekly_times.values():
                    for time_str in times:
                        groups.add((medication.patient_id, time_str))
        return groups

    @callback
    def async_recompute(self, *_args) -> None:
        wanted = self._current_groups()
        existing = set(self._entities.keys())

        for key in existing - wanted:
            for entity in self._entities.pop(key):
                self._hass.async_create_task(self._async_fully_remove(entity))

        new_entities: list[ButtonEntity] = []
        for key in wanted - existing:
            patient_id, time_str = key
            take = TimeSlotTakeButton(self._store, self._scheduler, patient_id, time_str)
            missed = TimeSlotMissedButton(self._store, self._scheduler, patient_id, time_str)
            self._entities[key] = [take, missed]
            new_entities.extend([take, missed])
        if new_entities:
            self._async_add_entities(new_entities)

    async def _async_fully_remove(self, entity: ButtonEntity) -> None:
        """Remove the entity's live state *and* its entity_registry entry.

        entity.async_remove() alone only detaches it from hass.states - the
        registry entry is a separate record that otherwise lingers forever,
        showing up as a permanently "unavailable" ghost entity.
        """
        entity_id = entity.entity_id
        await entity.async_remove(force_remove=True)
        if entity_id:
            registry = er.async_get(self._hass)
            if registry.async_get(entity_id) is not None:
                registry.async_remove(entity_id)
