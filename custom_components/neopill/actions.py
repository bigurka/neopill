"""Shared action logic reused by button.py, services.py and websocket_api.py.

Keeping this in one place guarantees the button entities, the neopill.* services and
the websocket API used by the panel all produce identical results for the same action.
"""
from __future__ import annotations

from .coordinator import DoseScheduler
from .models import IntakeEvent, RestockEvent
from .storage import NeoPillStore


async def async_take_dose(
    store: NeoPillStore, scheduler: DoseScheduler, medication_id: str, amount: float | None = None
) -> IntakeEvent:
    """Record that a dose was taken now, clearing any pending due reminder."""
    scheduled_for = scheduler.due_scheduled_for(medication_id)
    return await store.async_record_intake(medication_id, amount=amount, scheduled_for=scheduled_for)


async def async_mark_missed(
    store: NeoPillStore, scheduler: DoseScheduler, medication_id: str
) -> IntakeEvent:
    """Explicitly declare that a due dose was not taken."""
    scheduled_for = scheduler.due_scheduled_for(medication_id)
    return await store.async_record_missed(medication_id, scheduled_for=scheduled_for)


async def async_restock(
    store: NeoPillStore,
    medication_id: str,
    amount: float | None = None,
    packages: float | None = None,
) -> RestockEvent:
    """Record a restock, either as a direct quantity or as a number of packages."""
    return await store.async_record_restock(medication_id, amount=amount, packages=packages)
