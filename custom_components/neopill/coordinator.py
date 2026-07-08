"""Dose reminder scheduling for NeoPill.

Deliberately NOT a DataUpdateCoordinator: there is no external data source to poll,
just an in-memory "when is the next dose due" computation over data already held by
NeoPillStore. Uses one-shot point-in-time callbacks (rescheduled after every relevant
change) plus a periodic safety sweep to recover from any callback lost across an HA
restart or an event-loop hiccup.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_time, async_track_time_interval
import homeassistant.util.dt as dt_util

from .const import (
    DEFAULT_SAFETY_SWEEP_INTERVAL_MINUTES,
    EVENT_DOSE_DUE,
    INTAKE_STATUS_TAKEN,
    SCHEDULE_TYPE_FIXED_TIMES,
    SCHEDULE_TYPE_INTERVAL,
    SCHEDULE_TYPE_WEEKLY,
    SIGNAL_DOSE_DUE_CHANGED,
    SIGNAL_INTAKE_RECORDED,
    SIGNAL_MEDICATION_ADDED,
    SIGNAL_MEDICATION_REMOVED,
    SIGNAL_MEDICATION_UPDATED,
    WEEKDAY_KEYS,
)
from .models import DoseSchedule, IntakeEvent, Medication
from .storage import NeoPillStore

_LOGGER = logging.getLogger(__name__)


def _parse_time_str(time_str: str) -> tuple[int, int] | None:
    """Parse "HH:MM" defensively - malformed stored data must never crash setup."""
    try:
        hour_str, minute_str = time_str.split(":")[:2]
        hour, minute = int(hour_str), int(minute_str)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, IndexError):
        _LOGGER.warning("Ignoring invalid dose time %r (expected HH:MM)", time_str)
        return None
    return hour, minute


def _next_occurrence(schedule: DoseSchedule, reference: datetime) -> datetime | None:
    """Pure function: first schedule occurrence strictly after `reference`."""
    if schedule.schedule_type == SCHEDULE_TYPE_FIXED_TIMES:
        if not schedule.fixed_times:
            return None
        candidates: list[datetime] = []
        for time_str in schedule.fixed_times:
            parsed = _parse_time_str(time_str)
            if parsed is None:
                continue
            hour, minute = parsed
            for day_offset in (0, 1):
                day = reference + timedelta(days=day_offset)
                candidate = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate > reference:
                    candidates.append(candidate)
        return min(candidates) if candidates else None
    if schedule.schedule_type == SCHEDULE_TYPE_INTERVAL:
        if not schedule.interval_hours:
            return None
        return reference + timedelta(hours=schedule.interval_hours)
    if schedule.schedule_type == SCHEDULE_TYPE_WEEKLY:
        if not schedule.weekly_times:
            return None
        candidates: list[datetime] = []
        for day_offset in range(0, 8):
            day = reference + timedelta(days=day_offset)
            times = schedule.weekly_times.get(WEEKDAY_KEYS[day.weekday()])
            if not times:
                continue
            for time_str in times:
                parsed = _parse_time_str(time_str)
                if parsed is None:
                    continue
                hour, minute = parsed
                candidate = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate > reference:
                    candidates.append(candidate)
        return min(candidates) if candidates else None
    return None


class DoseScheduler:
    """Tracks, per medication, when the next dose is due and fires reminders."""

    def __init__(self, hass: HomeAssistant, store: NeoPillStore) -> None:
        self._hass = hass
        self._store = store
        self._due_at: dict[str, datetime] = {}
        self._is_due: dict[str, bool] = {}
        self._cancel_timers: dict[str, Callable[[], None]] = {}
        self._unsub_signals: list[Callable[[], None]] = []
        self._unsub_sweep: Callable[[], None] | None = None

    async def async_setup(self) -> None:
        self._unsub_signals = [
            async_dispatcher_connect(self._hass, SIGNAL_MEDICATION_ADDED, self._on_medication_added),
            async_dispatcher_connect(self._hass, SIGNAL_MEDICATION_UPDATED, self._on_medication_updated),
            async_dispatcher_connect(self._hass, SIGNAL_MEDICATION_REMOVED, self._on_medication_removed),
            async_dispatcher_connect(self._hass, SIGNAL_INTAKE_RECORDED, self._on_intake_recorded),
        ]
        for medication in self._store.list_medications():
            self._recompute(medication, reference=self._startup_reference(medication.id))
        self._unsub_sweep = async_track_time_interval(
            self._hass,
            self._async_safety_sweep,
            timedelta(minutes=DEFAULT_SAFETY_SWEEP_INTERVAL_MINUTES),
        )

    async def async_unload(self) -> None:
        for unsub in self._unsub_signals:
            unsub()
        self._unsub_signals = []
        if self._unsub_sweep is not None:
            self._unsub_sweep()
            self._unsub_sweep = None
        for cancel in self._cancel_timers.values():
            cancel()
        self._cancel_timers = {}

    # ---- Public read API for entities ----

    def next_dose_at(self, medication_id: str) -> datetime | None:
        return self._due_at.get(medication_id)

    def is_due(self, medication_id: str) -> bool:
        return self._is_due.get(medication_id, False)

    def due_scheduled_for(self, medication_id: str) -> datetime | None:
        return self._due_at.get(medication_id) if self.is_due(medication_id) else None

    # ---- Internal: reference-time selection ----

    def _startup_reference(self, medication_id: str) -> datetime:
        last_event = self._store.last_intake_event(medication_id)
        return last_event.timestamp if last_event else dt_util.now()

    # ---- Signal handlers ----

    @callback
    def _on_medication_added(self, medication: Medication) -> None:
        self._recompute(medication, reference=dt_util.now())

    @callback
    def _on_medication_updated(self, medication: Medication) -> None:
        self._recompute(medication, reference=dt_util.now())

    @callback
    def _on_medication_removed(self, medication_id: str) -> None:
        cancel = self._cancel_timers.pop(medication_id, None)
        if cancel is not None:
            cancel()
        self._due_at.pop(medication_id, None)
        self._is_due.pop(medication_id, None)

    @callback
    def _on_intake_recorded(self, event: IntakeEvent) -> None:
        medication = self._store.medications.get(event.medication_id)
        if medication is None:
            return
        reference = event.timestamp if event.status == INTAKE_STATUS_TAKEN else dt_util.now()
        self._recompute(medication, reference=reference)

    # ---- Core scheduling logic ----

    def _recompute(self, medication: Medication, *, reference: datetime) -> None:
        cancel = self._cancel_timers.pop(medication.id, None)
        if cancel is not None:
            cancel()

        occurrence = _next_occurrence(medication.dose_schedule, reference)
        if occurrence is None:
            self._due_at.pop(medication.id, None)
            self._set_due(medication.id, False)
            return

        self._due_at[medication.id] = occurrence
        if occurrence <= dt_util.now():
            self._set_due(medication.id, True)
        else:
            self._set_due(medication.id, False)
            self._cancel_timers[medication.id] = async_track_point_in_time(
                self._hass, self._make_due_callback(medication.id), occurrence
            )

    def _make_due_callback(self, medication_id: str) -> Callable[[datetime], None]:
        @callback
        def _due_callback(_now: datetime) -> None:
            self._cancel_timers.pop(medication_id, None)
            self._set_due(medication_id, True)

        return _due_callback

    def _set_due(self, medication_id: str, is_due: bool) -> None:
        changed = self._is_due.get(medication_id) != is_due
        self._is_due[medication_id] = is_due
        if is_due and changed:
            medication = self._store.medications.get(medication_id)
            self._hass.bus.async_fire(
                EVENT_DOSE_DUE,
                {
                    "medication_id": medication_id,
                    "patient_id": medication.patient_id if medication else None,
                    "scheduled_for": self._due_at[medication_id].isoformat(),
                },
            )
        if changed:
            async_dispatcher_send(self._hass, SIGNAL_DOSE_DUE_CHANGED, medication_id)

    @callback
    def _async_safety_sweep(self, _now: datetime) -> None:
        """Backstop: catch any medication whose due time passed without its timer firing."""
        now = dt_util.now()
        for medication_id, due_at in list(self._due_at.items()):
            if not self._is_due.get(medication_id) and due_at <= now:
                _LOGGER.debug("Safety sweep found overdue dose for %s", medication_id)
                self._cancel_timers.pop(medication_id, lambda: None)()
                self._set_due(medication_id, True)
