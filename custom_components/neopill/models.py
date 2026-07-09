"""Data models for the NeoPill integration.

All models are plain dataclasses with as_dict()/from_dict() so they can be persisted
as-is inside a homeassistant.helpers.storage.Store JSON blob.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import homeassistant.util.dt as dt_util

from .const import (
    DEFAULT_LOW_STOCK_DAYS_THRESHOLD,
    DEFAULT_RESTOCK_WINDOW_MAX_DAYS,
    DEFAULT_RESTOCK_WINDOW_MIN_DAYS,
    INTAKE_STATUS_TAKEN,
    SCHEDULE_TYPE_FIXED_TIMES,
    SCHEDULE_TYPE_INTERVAL,
    SCHEDULE_TYPE_WEEKLY,
)


def new_id() -> str:
    return uuid.uuid4().hex


_VOWELS = set("aeiouàèéìòùáéíóúäëïöü")


def consonant_prefix(name: str, length: int = 3) -> str:
    """Compact deterministic tag from a name: first `length` consonants, lowercase.

    Falls back to plain letters (then a fixed placeholder) for names with too few
    consonants, so it always returns something usable as an entity_id fragment.
    """
    letters = [c.lower() for c in name if c.isalpha()]
    consonants = [c for c in letters if c not in _VOWELS]
    base = "".join(consonants[:length]) or "".join(letters[:length])
    return base or "pz"


def generate_patient_slug(name: str, existing_slugs: set[str]) -> str:
    """Stable, human-readable patient tag used to prefix that patient's entity_ids.

    Computed once when the patient is created and never recomputed on rename, so
    renaming a patient later doesn't retroactively change existing entity_ids and
    break automations/dashboards built on them.
    """
    base = consonant_prefix(name, 3)
    if base not in existing_slugs:
        return base
    suffix = 2
    while f"{base}{suffix}" in existing_slugs:
        suffix += 1
    return f"{base}{suffix}"


@dataclass
class DoseSchedule:
    schedule_type: str = SCHEDULE_TYPE_FIXED_TIMES
    fixed_times: list[str] = field(default_factory=list)
    interval_hours: float | None = None
    # schedule_type == "weekly": e.g. {"tue": ["08:00", "20:00"], "fri": ["09:00"]}
    weekly_times: dict[str, list[str]] = field(default_factory=dict)

    def daily_doses_count(self) -> float:
        """Doses per day implied by this schedule, used for consumption-rate estimates."""
        if self.schedule_type == SCHEDULE_TYPE_FIXED_TIMES:
            return float(len(self.fixed_times))
        if self.schedule_type == SCHEDULE_TYPE_INTERVAL and self.interval_hours:
            return 24.0 / self.interval_hours
        if self.schedule_type == SCHEDULE_TYPE_WEEKLY and self.weekly_times:
            total = sum(len(times) for times in self.weekly_times.values())
            return total / 7.0
        return 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "schedule_type": self.schedule_type,
            "fixed_times": list(self.fixed_times),
            "interval_hours": self.interval_hours,
            "weekly_times": {day: list(times) for day, times in self.weekly_times.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DoseSchedule:
        return cls(
            schedule_type=data.get("schedule_type", SCHEDULE_TYPE_FIXED_TIMES),
            fixed_times=list(data.get("fixed_times", [])),
            interval_hours=data.get("interval_hours"),
            weekly_times={
                day: list(times) for day, times in data.get("weekly_times", {}).items()
            },
        )


@dataclass
class Patient:
    name: str
    slug: str
    id: str = field(default_factory=new_id)
    # "Ideal reorder window": a medication surfaces in the restock-reminder sensor
    # once its estimated days remaining falls between these two bounds - min is
    # the "don't leave it any later" cutoff, max is the "don't order too early"
    # cutoff. min must stay < max (enforced in storage.async_update_patient).
    restock_window_min_days: int = DEFAULT_RESTOCK_WINDOW_MIN_DAYS
    restock_window_max_days: int = DEFAULT_RESTOCK_WINDOW_MAX_DAYS

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "restock_window_min_days": self.restock_window_min_days,
            "restock_window_max_days": self.restock_window_max_days,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Patient:
        return cls(
            id=data["id"],
            name=data["name"],
            slug=data.get("slug") or consonant_prefix(data["name"]),
            restock_window_min_days=data.get(
                "restock_window_min_days", DEFAULT_RESTOCK_WINDOW_MIN_DAYS
            ),
            restock_window_max_days=data.get(
                "restock_window_max_days", DEFAULT_RESTOCK_WINDOW_MAX_DAYS
            ),
        )


@dataclass
class Medication:
    patient_id: str
    name: str
    dose_amount: float = 1.0
    stock_quantity: float = 0.0
    package_size: float | None = None
    low_stock_days_threshold: int = DEFAULT_LOW_STOCK_DAYS_THRESHOLD
    dose_schedule: DoseSchedule = field(default_factory=DoseSchedule)
    notes: str = ""
    # Full commercial/prescription name (e.g. "Olmesartan e Idroclorotiazide
    # 40/12,5mg"), distinct from the short `name` used for the device/entities
    # (e.g. "Olmesartan"). Optional - falls back to `name` where used.
    full_name: str = ""
    id: str = field(default_factory=new_id)

    def display_name(self) -> str:
        """Full name if set, otherwise the short name - for outbound text/email."""
        return self.full_name or self.name

    def daily_consumption(self) -> float:
        return self.dose_schedule.daily_doses_count() * self.dose_amount

    def days_remaining(self) -> float | None:
        consumption = self.daily_consumption()
        if consumption <= 0:
            return None
        return self.stock_quantity / consumption

    def next_depletion_date(self) -> datetime | None:
        """Predicted date/time the stock reaches zero, at the current consumption rate."""
        remaining = self.days_remaining()
        if remaining is None:
            return None
        return dt_util.now() + timedelta(days=remaining)

    def is_low_stock(self) -> bool:
        remaining = self.days_remaining()
        if remaining is None:
            return False
        return remaining <= self.low_stock_days_threshold

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "name": self.name,
            "dose_amount": self.dose_amount,
            "stock_quantity": self.stock_quantity,
            "package_size": self.package_size,
            "low_stock_days_threshold": self.low_stock_days_threshold,
            "dose_schedule": self.dose_schedule.as_dict(),
            "notes": self.notes,
            "full_name": self.full_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Medication:
        return cls(
            id=data["id"],
            patient_id=data["patient_id"],
            name=data["name"],
            full_name=data.get("full_name", ""),
            dose_amount=data.get("dose_amount", 1.0),
            stock_quantity=data.get("stock_quantity", 0.0),
            package_size=data.get("package_size"),
            low_stock_days_threshold=data.get(
                "low_stock_days_threshold", DEFAULT_LOW_STOCK_DAYS_THRESHOLD
            ),
            dose_schedule=DoseSchedule.from_dict(data.get("dose_schedule", {})),
            notes=data.get("notes", ""),
        )


@dataclass
class IntakeEvent:
    medication_id: str
    timestamp: datetime
    amount: float
    status: str = INTAKE_STATUS_TAKEN
    scheduled_for: datetime | None = None
    depleted: bool = False
    id: str = field(default_factory=new_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "medication_id": self.medication_id,
            "timestamp": self.timestamp.isoformat(),
            "amount": self.amount,
            "status": self.status,
            "scheduled_for": self.scheduled_for.isoformat() if self.scheduled_for else None,
            "depleted": self.depleted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntakeEvent:
        scheduled_for = data.get("scheduled_for")
        return cls(
            id=data["id"],
            medication_id=data["medication_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            amount=data.get("amount", 0.0),
            status=data.get("status", INTAKE_STATUS_TAKEN),
            scheduled_for=datetime.fromisoformat(scheduled_for) if scheduled_for else None,
            depleted=data.get("depleted", False),
        )


@dataclass
class RestockEvent:
    medication_id: str
    timestamp: datetime
    amount_added: float
    new_total: float
    packages: float | None = None
    id: str = field(default_factory=new_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "medication_id": self.medication_id,
            "timestamp": self.timestamp.isoformat(),
            "amount_added": self.amount_added,
            "new_total": self.new_total,
            "packages": self.packages,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RestockEvent:
        return cls(
            id=data["id"],
            medication_id=data["medication_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            amount_added=data.get("amount_added", 0.0),
            new_total=data.get("new_total", 0.0),
            packages=data.get("packages"),
        )
