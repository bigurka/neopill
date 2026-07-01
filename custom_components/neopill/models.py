"""Data models for the NeoPill integration.

All models are plain dataclasses with as_dict()/from_dict() so they can be persisted
as-is inside a homeassistant.helpers.storage.Store JSON blob.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .const import (
    DEFAULT_LOW_STOCK_DAYS_THRESHOLD,
    INTAKE_STATUS_TAKEN,
    SCHEDULE_TYPE_FIXED_TIMES,
    SCHEDULE_TYPE_INTERVAL,
)


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class DoseSchedule:
    schedule_type: str = SCHEDULE_TYPE_FIXED_TIMES
    fixed_times: list[str] = field(default_factory=list)
    interval_hours: float | None = None

    def daily_doses_count(self) -> float:
        """Doses per day implied by this schedule, used for consumption-rate estimates."""
        if self.schedule_type == SCHEDULE_TYPE_FIXED_TIMES:
            return float(len(self.fixed_times))
        if self.schedule_type == SCHEDULE_TYPE_INTERVAL and self.interval_hours:
            return 24.0 / self.interval_hours
        return 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "schedule_type": self.schedule_type,
            "fixed_times": list(self.fixed_times),
            "interval_hours": self.interval_hours,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DoseSchedule:
        return cls(
            schedule_type=data.get("schedule_type", SCHEDULE_TYPE_FIXED_TIMES),
            fixed_times=list(data.get("fixed_times", [])),
            interval_hours=data.get("interval_hours"),
        )


@dataclass
class Patient:
    name: str
    id: str = field(default_factory=new_id)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Patient:
        return cls(id=data["id"], name=data["name"])


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
    id: str = field(default_factory=new_id)

    def daily_consumption(self) -> float:
        return self.dose_schedule.daily_doses_count() * self.dose_amount

    def days_remaining(self) -> float | None:
        consumption = self.daily_consumption()
        if consumption <= 0:
            return None
        return self.stock_quantity / consumption

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
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Medication:
        return cls(
            id=data["id"],
            patient_id=data["patient_id"],
            name=data["name"],
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
