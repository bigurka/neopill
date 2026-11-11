"""Per-day dose agenda: every scheduled dose of a patient's day, with what happened to it.

Feeds the per-patient "today's doses" sensor, which lets a dashboard built only from
native HA cards show what was already taken (so an elderly patient can see a dose is
done and doesn't take it twice) and what is still to come.

Interval schedules have no fixed wall-clock slots, so they're left out of the agenda.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import homeassistant.util.dt as dt_util

from .const import (
    INTAKE_STATUS_MISSED,
    INTAKE_STATUS_TAKEN,
    SCHEDULE_TYPE_FIXED_TIMES,
    SCHEDULE_TYPE_WEEKLY,
    WEEKDAY_KEYS,
)
from .models import IntakeEvent, Medication
from .storage import NeoPillStore

STATUS_TAKEN = "taken"
STATUS_MISSED = "missed"
STATUS_UNANSWERED = "unanswered"
STATUS_DUE = "due"
STATUS_LATER = "later"
STATUS_NOT_RECORDED = "not_recorded"

# An intake logged without a scheduled slot (e.g. taken a bit early, before the dose
# became due) is credited to the nearest open slot of that day within this distance.
_LOOSE_MATCH_WINDOW = timedelta(hours=3)


def _slot_times(medication: Medication, day: date) -> list[str]:
    schedule = medication.dose_schedule
    if schedule.schedule_type == SCHEDULE_TYPE_FIXED_TIMES:
        times = schedule.fixed_times
    elif schedule.schedule_type == SCHEDULE_TYPE_WEEKLY:
        times = schedule.weekly_times.get(WEEKDAY_KEYS[day.weekday()], [])
    else:
        return []
    return sorted(set(times))


def _slot_datetime(day: date, time_str: str) -> datetime | None:
    try:
        hour, minute = (int(part) for part in time_str.split(":")[:2])
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt_util.get_default_time_zone())
    except (ValueError, TypeError):
        return None


def _status_of(event: IntakeEvent) -> str:
    if event.status == INTAKE_STATUS_TAKEN:
        return STATUS_TAKEN
    if event.status == INTAKE_STATUS_MISSED:
        return STATUS_MISSED
    return STATUS_UNANSWERED


def doses_for_day(store: NeoPillStore, scheduler, patient_id: str, day: date) -> list[dict[str, Any]]:
    """Every scheduled dose of `day` for this patient, time-sorted, with its status."""
    now = dt_util.now()
    day_start = _slot_datetime(day, "00:00")
    day_end = day_start + timedelta(days=1)
    doses: list[dict[str, Any]] = []
    for medication in store.list_medications(patient_id=patient_id):
        slots = [(t, at) for t in _slot_times(medication, day) if (at := _slot_datetime(day, t))]
        if not slots:
            continue
        events = [
            e
            for e in store.intake_events
            if e.medication_id == medication.id
            and (
                (e.scheduled_for is not None and day_start <= e.scheduled_for < day_end)
                or (e.scheduled_for is None and day_start <= e.timestamp < day_end)
            )
        ]
        matched: dict[str, IntakeEvent] = {}
        for event in events:
            if event.scheduled_for is None:
                continue
            local = dt_util.as_local(event.scheduled_for).strftime("%H:%M")
            if any(t == local for t, _ in slots):
                matched.setdefault(local, event)
        for event in sorted((e for e in events if e.scheduled_for is None), key=lambda e: e.timestamp):
            open_slots = [(t, at) for t, at in slots if t not in matched]
            if not open_slots:
                break
            time_str, at = min(open_slots, key=lambda s: abs(s[1] - event.timestamp))
            if abs(at - event.timestamp) <= _LOOSE_MATCH_WINDOW:
                matched[time_str] = event

        due_for = scheduler.due_scheduled_for(medication.id)
        for time_str, at in slots:
            event = matched.get(time_str)
            if event is not None:
                status = _status_of(event)
                recorded_at = dt_util.as_local(event.timestamp).strftime("%H:%M")
            else:
                recorded_at = None
                if due_for is not None and dt_util.as_local(due_for) == at:
                    status = STATUS_DUE
                elif at > now:
                    status = STATUS_LATER
                else:
                    status = STATUS_NOT_RECORDED
            doses.append(
                {
                    "time": time_str,
                    "medication_id": medication.id,
                    "name": medication.name,
                    "display_name": medication.display_name(),
                    "amount": medication.dose_amount,
                    "status": status,
                    "recorded_at": recorded_at,
                }
            )
    doses.sort(key=lambda d: (d["time"], d["name"].lower()))
    return doses


def last_taken_at(store: NeoPillStore, patient_id: str) -> datetime | None:
    medication_ids = {m.id for m in store.list_medications(patient_id=patient_id)}
    taken = [
        e.timestamp
        for e in store.intake_events
        if e.medication_id in medication_ids and e.status == INTAKE_STATUS_TAKEN
    ]
    return max(taken) if taken else None
