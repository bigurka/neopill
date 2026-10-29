"""WebSocket API for the NeoPill panel, cards and dashboard strategy.

Every command is filtered by the caller's role on the patient involved (see
access.py): non-admin users only see the patients they were given access to,
record intakes/restocks with ROLE_PATIENT/ROLE_CAREGIVER and above, and edit
medications with ROLE_DOCTOR. Managing access, users and settings is admin-only.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.websocket_api.const import (
    ERR_INVALID_FORMAT,
    ERR_NOT_FOUND,
    ERR_UNAUTHORIZED,
)
from homeassistant.core import HomeAssistant

from .access import (
    async_import_ha_users,
    async_list_ha_users,
    can_act,
    can_create_patients,
    can_edit,
    can_view,
    role_for,
)
from .actions import async_mark_missed, async_restock, async_take_dose
from .const import ASSIGNABLE_ROLES, DEFAULT_OWN_ROLE, ROLE_DOCTOR, WEEKDAY_KEYS
from .models import DoseSchedule, Medication, Patient
from .panel import async_update_panel_visibility
from .runtime import get_runtime_data
from .storage import MedicationNotFoundError, PatientNotFoundError

DOMAIN_PREFIX = "neopill"

_TIME_STR_RE = r"^([01]\d|2[0-3]):[0-5]\d$"

_DOSE_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("schedule_type"): vol.In(["fixed_times", "interval", "weekly"]),
        vol.Optional("fixed_times", default=list): [vol.Match(_TIME_STR_RE)],
        vol.Optional("interval_hours"): vol.Coerce(float),
        vol.Optional("weekly_times", default=dict): {
            vol.In(WEEKDAY_KEYS): [vol.Match(_TIME_STR_RE)]
        },
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
    websocket_api.async_register_command(hass, ws_me)
    websocket_api.async_register_command(hass, ws_list_users)
    websocket_api.async_register_command(hass, ws_import_users)
    websocket_api.async_register_command(hass, ws_set_access)
    websocket_api.async_register_command(hass, ws_link_user)
    websocket_api.async_register_command(hass, ws_update_settings)


def _patient_payload(connection: websocket_api.ActiveConnection, patient: Patient) -> dict[str, Any]:
    """Patient dict plus the caller's role; who-else-has-access is admin-only."""
    payload = {**patient.as_dict(), "role": role_for(connection.user, patient)}
    if not connection.user.is_admin:
        payload.pop("access")
    return payload


def _check_patient(
    runtime,
    connection: websocket_api.ActiveConnection,
    msg_id: int,
    patient_id: str,
    allowed: Callable[[str | None], bool],
) -> Patient | None:
    """Patient if the caller's role on it passes `allowed`, else send an error.

    Unknown and not-visible patients get the same "not found" error, so the
    answer doesn't reveal which patients exist to users who can't see them.
    """
    patient = runtime.store.patients.get(patient_id)
    role = role_for(connection.user, patient) if patient else None
    if patient is None or not can_view(role):
        connection.send_error(msg_id, ERR_NOT_FOUND, f"Patient {patient_id} not found")
        return None
    if not allowed(role):
        connection.send_error(msg_id, ERR_UNAUTHORIZED, "Your NeoPill role doesn't allow this")
        return None
    return patient


def _check_medication(
    runtime,
    connection: websocket_api.ActiveConnection,
    msg_id: int,
    medication_id: str,
    allowed: Callable[[str | None], bool],
) -> Medication | None:
    medication = runtime.store.medications.get(medication_id)
    if medication is None:
        connection.send_error(msg_id, ERR_NOT_FOUND, f"Medication {medication_id} not found")
        return None
    if _check_patient(runtime, connection, msg_id, medication.patient_id, allowed) is None:
        return None
    return medication


def _visible_patient_ids(connection: websocket_api.ActiveConnection, runtime) -> set[str]:
    return {
        p.id for p in runtime.store.list_patients() if can_view(role_for(connection.user, p))
    }


def _medication_payload(runtime, medication: Medication) -> dict[str, Any]:
    """Medication dict plus the computed fields the panel needs (no client-side duplication)."""
    due_at = runtime.scheduler.next_dose_at(medication.id)
    depletion_at = medication.next_depletion_date()
    return {
        **medication.as_dict(),
        "is_due": runtime.scheduler.is_due(medication.id),
        "next_dose_at": due_at.isoformat() if due_at else None,
        "days_remaining": medication.days_remaining(),
        "is_low_stock": medication.is_low_stock(),
        "next_depletion_date": depletion_at.isoformat() if depletion_at else None,
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
    visible = _visible_patient_ids(connection, runtime)
    connection.send_result(
        msg["id"],
        {
            "patients": [
                _patient_payload(connection, p)
                for p in runtime.store.list_patients()
                if p.id in visible
            ]
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN_PREFIX}/patients/add", vol.Required("name"): str}
)
@websocket_api.async_response
async def ws_add_patient(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    user = connection.user
    if not can_create_patients(user, runtime.store):
        connection.send_error(msg["id"], ERR_UNAUTHORIZED, "Your NeoPill role doesn't allow this")
        return
    # A doctor who creates a patient follows it; admins see everything anyway.
    access = {} if user.is_admin else {user.id: ROLE_DOCTOR}
    patient = await runtime.store.async_add_patient(msg["name"], access=access)
    connection.send_result(msg["id"], {"patient": _patient_payload(connection, patient)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN_PREFIX}/patients/update",
        vol.Required("patient_id"): str,
        vol.Optional("name"): str,
        vol.Optional("restock_window_min_days"): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("restock_window_max_days"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }
)
@websocket_api.async_response
async def ws_update_patient(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    if _check_patient(runtime, connection, msg["id"], msg["patient_id"], can_edit) is None:
        return
    fields = {k: v for k, v in msg.items() if k not in ("type", "id", "patient_id")}
    try:
        patient = await runtime.store.async_update_patient(msg["patient_id"], **fields)
    except PatientNotFoundError as err:
        _error(connection, msg["id"], err)
        return
    except ValueError as err:
        _error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], {"patient": _patient_payload(connection, patient)})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN_PREFIX}/patients/delete", vol.Required("patient_id"): str}
)
@websocket_api.async_response
async def ws_delete_patient(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    if _check_patient(runtime, connection, msg["id"], msg["patient_id"], can_edit) is None:
        return
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
    if msg.get("patient_id"):
        if _check_patient(runtime, connection, msg["id"], msg["patient_id"], can_view) is None:
            return
        medications = runtime.store.list_medications(patient_id=msg["patient_id"])
    else:
        visible = _visible_patient_ids(connection, runtime)
        medications = [m for m in runtime.store.list_medications() if m.patient_id in visible]
    connection.send_result(
        msg["id"], {"medications": [_medication_payload(runtime, m) for m in medications]}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN_PREFIX}/medications/add",
        vol.Required("patient_id"): str,
        vol.Required("name"): str,
        vol.Optional("full_name", default=""): str,
        vol.Optional("dose_amount", default=1.0): vol.Coerce(float),
        vol.Optional("stock_quantity", default=0.0): vol.Coerce(float),
        vol.Optional("package_size"): vol.Coerce(float),
        vol.Optional("low_stock_days_threshold"): vol.Coerce(int),
        vol.Optional("dose_schedule"): _DOSE_SCHEDULE_SCHEMA,
        vol.Optional("notes", default=""): str,
    }
)
@websocket_api.async_response
async def ws_add_medication(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    if _check_patient(runtime, connection, msg["id"], msg["patient_id"], can_edit) is None:
        return
    schedule = msg.get("dose_schedule")
    try:
        medication = await runtime.store.async_add_medication(
            msg["patient_id"],
            msg["name"],
            full_name=msg["full_name"],
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
        vol.Optional("full_name"): str,
        vol.Optional("dose_amount"): vol.Coerce(float),
        vol.Optional("stock_quantity"): vol.Coerce(float),
        vol.Optional("package_size"): vol.Coerce(float),
        vol.Optional("low_stock_days_threshold"): vol.Coerce(int),
        vol.Optional("dose_schedule"): _DOSE_SCHEDULE_SCHEMA,
        vol.Optional("notes"): str,
    }
)
@websocket_api.async_response
async def ws_update_medication(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    if _check_medication(runtime, connection, msg["id"], msg["medication_id"], can_edit) is None:
        return
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
@websocket_api.async_response
async def ws_delete_medication(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    if _check_medication(runtime, connection, msg["id"], msg["medication_id"], can_edit) is None:
        return
    try:
        await runtime.store.async_delete_medication(msg["medication_id"])
    except MedicationNotFoundError as err:
        _error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"])


# ---- Actions (ROLE_PATIENT / ROLE_CAREGIVER and above) ----


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
    if _check_medication(runtime, connection, msg["id"], msg["medication_id"], can_act) is None:
        return
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
    if _check_medication(runtime, connection, msg["id"], msg["medication_id"], can_act) is None:
        return
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
    if _check_medication(runtime, connection, msg["id"], msg["medication_id"], can_act) is None:
        return
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
        if _check_medication(runtime, connection, msg["id"], msg["medication_id"], can_view) is None:
            return
        medication_ids = {msg["medication_id"]}
    elif msg.get("patient_id"):
        if _check_patient(runtime, connection, msg["id"], msg["patient_id"], can_view) is None:
            return
        medication_ids = {m.id for m in runtime.store.list_medications(patient_id=msg["patient_id"])}
    else:
        visible = _visible_patient_ids(connection, runtime)
        medication_ids = {m.id for m in runtime.store.list_medications() if m.patient_id in visible}
    events = runtime.store.events_in_range(medication_ids, start, end)
    connection.send_result(
        msg["id"],
        {
            "events": [
                {**e, "timestamp": e["timestamp"].isoformat()} for e in events
            ]
        },
    )


# ---- Current user, HA users, access and settings ----


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN_PREFIX}/me"})
@websocket_api.async_response
async def ws_me(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """What the caller may do globally, plus the settings the panel shows."""
    runtime = get_runtime_data(hass)
    user = connection.user
    connection.send_result(
        msg["id"],
        {
            "user_id": user.id,
            "is_admin": user.is_admin,
            "can_create_patients": can_create_patients(user, runtime.store),
            "settings": dict(runtime.store.settings),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN_PREFIX}/users/list"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_list_users(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    users = await async_list_ha_users(hass)
    connection.send_result(
        msg["id"],
        {"users": [{"id": u.id, "name": u.name, "is_admin": u.is_admin} for u in users]},
    )


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN_PREFIX}/users/import"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_import_users(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    created = await async_import_ha_users(hass, runtime.store)
    connection.send_result(
        msg["id"], {"patients": [_patient_payload(connection, p) for p in created]}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN_PREFIX}/access/set",
        vol.Required("patient_id"): str,
        vol.Required("user_id"): str,
        # None revokes the user's access to this patient.
        vol.Required("role"): vol.Any(None, vol.In(ASSIGNABLE_ROLES)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_access(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    if await hass.auth.async_get_user(msg["user_id"]) is None:
        connection.send_error(msg["id"], ERR_NOT_FOUND, f"User {msg['user_id']} not found")
        return
    try:
        patient = await runtime.store.async_set_access(msg["patient_id"], msg["user_id"], msg["role"])
    except PatientNotFoundError as err:
        _error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], {"patient": _patient_payload(connection, patient)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN_PREFIX}/patients/link_user",
        vol.Required("patient_id"): str,
        # None unlinks the patient from its HA user.
        vol.Required("user_id"): vol.Any(None, str),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_link_user(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    if msg["user_id"] is not None and await hass.auth.async_get_user(msg["user_id"]) is None:
        connection.send_error(msg["id"], ERR_NOT_FOUND, f"User {msg['user_id']} not found")
        return
    try:
        patient = await runtime.store.async_link_ha_user(
            msg["patient_id"], msg["user_id"], DEFAULT_OWN_ROLE
        )
    except (PatientNotFoundError, ValueError) as err:
        _error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], {"patient": _patient_payload(connection, patient)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN_PREFIX}/settings/update",
        vol.Optional("show_in_sidebar"): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_update_settings(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    runtime = get_runtime_data(hass)
    fields = {k: v for k, v in msg.items() if k not in ("type", "id")}
    settings = await runtime.store.async_update_settings(**fields)
    if "show_in_sidebar" in fields:
        async_update_panel_visibility(hass, settings["show_in_sidebar"])
    connection.send_result(msg["id"], {"settings": settings})
