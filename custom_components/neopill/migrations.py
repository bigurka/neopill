"""One-time cleanup for entity registry entries orphaned by past key renames.

NeoPill computes unique_id and entity_id from a small "key" per entity (e.g.
"stock", "take_dose"). Whenever that key vocabulary changes - such as the
Italian-to-English rename in v0.5.0 - entities built from the new keys get
fresh unique_ids and register as brand new entities, while the registry
entries keyed by the *old* unique_id are never automatically removed: they
would otherwise linger forever as permanently "unavailable" ghost entities.
This module removes registry entries matching known-retired unique_id
suffixes, for every platform except button (time-slot buttons run their own,
ongoing version of this same cleanup in button.TimeSlotButtonManager, since
their set of valid keys changes routinely, not just at this one-time rename).
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

# Pre-v0.5.0 Italian per-medication and per-patient entity keys, replaced by
# English equivalents (see sensor.py/binary_sensor.py/button.py/calendar.py).
_LEGACY_UNIQUE_ID_SUFFIXES = (
    "_scorta",
    "_giorni_rimanenti",
    "_prossima_assunzione",
    "_da_assumere",
    "_scorta_in_esaurimento",
    "_assumi_ora",
    "_segna_non_assunta",
    "_rifornisci_confezione",
    "_farmaci_da_rifornire",
)


def async_cleanup_legacy_entities(hass: HomeAssistant, entry_id: str) -> None:
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry_id):
        if reg_entry.unique_id and reg_entry.unique_id.endswith(_LEGACY_UNIQUE_ID_SUFFIXES):
            registry.async_remove(reg_entry.entity_id)
