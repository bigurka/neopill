"""WebSocket API for the NeoPill panel.

Read/action commands (list, record intake/missed/restock) are open to any
authenticated user. Commands that create/edit/delete patients or medications
require admin, matching the access-control decision for this integration.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.websocket_api.const import ERR_INVALID_FORMAT, ERR_NOT_FOUND
from homeassistant.core import HomeAssistant

from .actions import async_mark_missed, async_restock, async_take_dose
from .models import DoseSchedule, Medication
from .runtime import get_runtime_data
from .storage import MedicationNotFoundError, PatientNotFoundError

DOMAIN_PREFIX = "neopill"

_TIME_STR_RE = r"^([01]\d|2[0-3]):[0-5]\d$"

_DOSE_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("schedule_type"): vol.In(["fixed_times", "interval"]),
        vol.Optional("fixed_times", default=list): [vol.Match(_TIME_STR_RE)],
        vol.Optional("interval_hours"): vol.Coerce(float),
    }
)


def async_setup_websocket_api(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_list_patients)
    websocket_api.async_register_command(hass, ws_add_patient)
    websocket_api.async_register_command(hass, ws_update_patient)
    websocket_api.async_register_command(hass, ws_delete_patient)
    websocket_api.async_register_command(hass, ws_list_medications)
    websocket_api.async_register_command(hass, ws_add_medication)
    websocket_api.async_register_command(hass, ws_update_medication)
    websocket_api.async_register_command(hass, ws_delete_medication)
    websocket_api.async_register_command(hass, ws_take_dose)
    websocket_api.async_register_command(hass, ws_mark_missed)
    websocket_api.async_register_command(hass, ws_restock)
    websocket_api.async_register_command(hass, ws_list_events)


def _medication_payload(runtime, medication: Medication) -> dict[str, Any]:
    """Medication dict plus the computed fields the panel needs (no client-side duplication)."""
    due_at = runtime.scheduler.next_dose_at(medication.id)
    return {
        **medication.as_dict(),
        "is_due": runtime.scheduler.is_due(medication.id),
        "next_dose_at": due_at.isoformat() if due_at else None,
        "days_remaining": medication.days_remaining(),
        "is_low_stock": medication.is_low_stock(),
    }


def _error(connection: websocket_api.ActiveConnection, msg_id: int, err: Exception) -> None:
    if isinstance(err, (PatientNotFoundError, MedicationNotFoundError)):
        connection.send_error(msg_id, ERR_NOT_FOUND, str(err))
    else:
        connection.send_error(msg_id, ERR_INVALID_FORMAT, str(err))


# ---- Patients ----


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN_PREFIX}/patients/list"})
@websocket_api.async_response
async def ws_list_patients(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    connection.send_result(msg["id"], {"patients": [p.as_dict() for p in runtime.store.list_patients()]})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN_PREFIX}/patients/add", vol.Required("name"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_add_patient(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    patient = await runtime.store.async_add_patient(msg["name"])
    connection.send_result(msg["id"], {"patient": patient.as_dict()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN_PREFIX}/patients/update",
        vol.Required("patient_id"): str,
        vol.Required("name"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_update_patient(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    try:
        patient = await runtime.store.async_update_patient(msg["patient_id"], msg["name"])
    except PatientNotFoundError as err:
        _error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], {"patient": patient.as_dict()})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN_PREFIX}/patients/delete", vol.Required("patient_id"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete_patient(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    try:
        await runtime.store.async_delete_patient(msg["patient_id"])
    except PatientNotFoundError as err:
        _error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"])


# ---- Medications ----


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN_PREFIX}/medications/list",
        vol.Optional("patient_id"): str,
    }
)
@websocket_api.async_response
async def ws_list_medications(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    medications = runtime.store.list_medications(patient_id=msg.get("patient_id"))
    connection.send_result(
        msg["id"], {"medications": [_medication_payload(runtime, m) for m in medications]}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN_PREFIX}/medications/add",
        vol.Required("patient_id"): str,
        vol.Required("name"): str,
        vol.Optional("dose_amount", default=1.0): vol.Coerce(float),
        vol.Optional("stock_quantity", default=0.0): vol.Coerce(float),
        vol.Optional("package_size"): vol.Coerce(float),
        vol.Optional("low_stock_days_threshold"): vol.Coerce(int),
        vol.Optional("dose_schedule"): _DOSE_SCHEDULE_SCHEMA,
        vol.Optional("notes", default=""): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_add_medication(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    schedule = msg.get("dose_schedule")
    try:
        medication = await runtime.store.async_add_medication(
            msg["patient_id"],
            msg["name"],
            dose_amount=msg["dose_amount"],
            stock_quantity=msg["stock_quantity"],
            package_size=msg.get("package_size"),
            low_stock_days_threshold=msg.get("low_stock_days_threshold"),
            dose_schedule=DoseSchedule.from_dict(schedule) if schedule else None,
            notes=msg["notes"],
        )
    except PatientNotFoundError as err:
        _error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], {"medication": _medication_payload(runtime, medication)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN_PREFIX}/medications/update",
        vol.Required("medication_id"): str,
        vol.Optional("name"): str,
        vol.Optional("dose_amount"): vol.Coerce(float),
        vol.Optional("stock_quantity"): vol.Coerce(float),
        vol.Optional("package_size"): vol.Coerce(float),
        vol.Optional("low_stock_days_threshold"): vol.Coerce(int),
        vol.Optional("dose_schedule"): _DOSE_SCHEDULE_SCHEMA,
        vol.Optional("notes"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_update_medication(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    fields = {k: v for k, v in msg.items() if k not in ("type", "id", "medication_id")}
    try:
        medication = await runtime.store.async_update_medication(msg["medication_id"], **fields)
    except MedicationNotFoundError as err:
        _error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], {"medication": _medication_payload(runtime, medication)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN_PREFIX}/medications/delete",
        vol.Required("medication_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete_medication(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    try:
        await runtime.store.async_delete_medication(msg["medication_id"])
    except MedicationNotFoundError as err:
        _error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"])


# ---- Actions (open to any authenticated user) ----


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN_PREFIX}/intake/take",
        vol.Required("medication_id"): str,
        vol.Optional("amount"): vol.Coerce(float),
    }
)
@websocket_api.async_response
async def ws_take_dose(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    try:
        event = await async_take_dose(
            runtime.store, runtime.scheduler, msg["medication_id"], msg.get("amount")
        )
    except MedicationNotFoundError as err:
        _error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], {"event": event.as_dict()})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN_PREFIX}/intake/mark_missed", vol.Required("medication_id"): str}
)
@websocket_api.async_response
async def ws_mark_missed(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    try:
        event = await async_mark_missed(runtime.store, runtime.scheduler, msg["medication_id"])
    except MedicationNotFoundError as err:
        _error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], {"event": event.as_dict()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN_PREFIX}/restock",
        vol.Required("medication_id"): str,
        vol.Optional("amount"): vol.Coerce(float),
        vol.Optional("packages"): vol.Coerce(float),
    }
)
@websocket_api.async_response
async def ws_restock(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    try:
        event = await async_restock(
            runtime.store, msg["medication_id"], amount=msg.get("amount"), packages=msg.get("packages")
        )
    except (MedicationNotFoundError, ValueError) as err:
        _error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], {"event": event.as_dict()})


# ---- History ----


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN_PREFIX}/events/list",
        vol.Required("start"): str,
        vol.Required("end"): str,
        vol.Optional("patient_id"): str,
        vol.Optional("medication_id"): str,
    }
)
@websocket_api.async_response
async def ws_list_events(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    start = datetime.fromisoformat(msg["start"])
    end = datetime.fromisoformat(msg["end"])
    if msg.get("medication_id"):
        medication_ids = {msg["medication_id"]}
    elif msg.get("patient_id"):
        medication_ids = {m.id for m in runtime.store.list_medications(patient_id=msg["patient_id"])}
    else:
        medication_ids = set(runtime.store.medications.keys())
    events = runtime.store.events_in_range(medication_ids, start, end)
    connection.send_result(
        msg["id"],
        {
            "events": [
                {**e, "timestamp": e["timestamp"].isoformat()} for e in events
            ]
        },
    )
