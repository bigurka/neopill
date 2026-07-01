"""Button platform for NeoPill: quick actions on a medication device."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .actions import async_mark_missed, async_restock, async_take_dose
from .const import SIGNAL_MEDICATION_ADDED
from .entity import NeoPillMedicationEntity
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


class TakeDoseButton(NeoPillMedicationEntity, ButtonEntity):
    """Records one dose (the medication's configured amount) taken right now."""

    _attr_name = "Assumi ora"
    _attr_icon = "mdi:pill"

    def __init__(self, store: NeoPillStore, medication_id: str, scheduler) -> None:
        super().__init__(store, medication_id, "assumi_ora")
        self._scheduler = scheduler

    async def async_press(self) -> None:
        await async_take_dose(self._store, self._scheduler, self._medication_id)


class MarkMissedButton(NeoPillMedicationEntity, ButtonEntity):
    """Explicitly declares the currently due dose as not taken."""

    _attr_name = "Segna come non assunta"
    _attr_icon = "mdi:pill-off"

    def __init__(self, store: NeoPillStore, medication_id: str, scheduler) -> None:
        super().__init__(store, medication_id, "segna_non_assunta")
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
        super().__init__(store, medication_id, "rifornisci_confezione")

    @property
    def available(self) -> bool:
        medication = self.medication
        return medication is not None and bool(medication.package_size)

    async def async_press(self) -> None:
        await async_restock(self._store, self._medication_id, packages=1)
