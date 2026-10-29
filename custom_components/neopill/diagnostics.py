"""Diagnostics for NeoPill (Settings > Devices & services > NeoPill > Download diagnostics).

The download is meant to be attached to GitHub issues, so it carries no health
data or identities: no patient/medication names, notes, HA user ids or history
contents - only structure, counts, schedules and the integration's settings.
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import ASSIGNABLE_ROLES


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry) -> dict[str, Any]:
    store = entry.runtime_data.store
    scheduler = entry.runtime_data.scheduler
    patients = []
    for index, patient in enumerate(store.list_patients()):
        medications = store.list_medications(patient_id=patient.id)
        patients.append(
            {
                "patient": f"patient_{index}",
                "linked_to_ha_user": patient.ha_user_id is not None,
                "roles": {role: list(patient.access.values()).count(role) for role in ASSIGNABLE_ROLES},
                "restock_window_min_days": patient.restock_window_min_days,
                "restock_window_max_days": patient.restock_window_max_days,
                "medications": [
                    {
                        "schedule": medication.dose_schedule.as_dict(),
                        "dose_amount": medication.dose_amount,
                        "stock_quantity": medication.stock_quantity,
                        "package_size": medication.package_size,
                        "low_stock_days_threshold": medication.low_stock_days_threshold,
                        "days_remaining": medication.days_remaining(),
                        "is_due": scheduler.is_due(medication.id),
                        "restock_notify_pending": medication.restock_notify_pending,
                    }
                    for medication in medications
                ],
            }
        )
    return {
        "settings": dict(store.settings),
        "patients": patients,
        "intake_events": len(store.intake_events),
        "restock_events": len(store.restock_events),
    }
