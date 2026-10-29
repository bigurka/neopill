"""Per-user access to NeoPill patients (roles) and import of HA users as patients.

Roles are stored per (HA user, patient) pair in Patient.access. HA administrators
are never stored there: they always get ROLE_ADMIN on every patient. These checks
guard the panel/card websocket API; HA entities and neopill.* services stay usable
by any HA user, since Home Assistant has no per-user entity permissions.
"""
from __future__ import annotations

from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant

from .const import ACTION_ROLES, DEFAULT_OWN_ROLE, EDIT_ROLES, ROLE_ADMIN, ROLE_DOCTOR
from .models import Patient
from .storage import NeoPillStore


def role_for(user: User | None, patient: Patient) -> str | None:
    """The user's role on this patient, or None if they can't see it at all."""
    if user is None:
        return None
    if user.is_admin:
        return ROLE_ADMIN
    return patient.access.get(user.id)


def can_view(role: str | None) -> bool:
    return role is not None


def can_act(role: str | None) -> bool:
    """Record intakes / missed doses / restocks."""
    return role in ACTION_ROLES


def can_edit(role: str | None) -> bool:
    """Add/edit/delete medications, edit or delete the patient itself."""
    return role in EDIT_ROLES


def can_create_patients(user: User | None, store: NeoPillStore) -> bool:
    """Admins, and anyone who is a doctor on at least one patient."""
    if user is None:
        return False
    if user.is_admin:
        return True
    return any(p.access.get(user.id) == ROLE_DOCTOR for p in store.patients.values())


async def async_list_ha_users(hass: HomeAssistant) -> list[User]:
    """Real, active HA users (no system-generated ones like Supervisor)."""
    users = await hass.auth.async_get_users()
    return [u for u in users if not u.system_generated and u.is_active]


async def async_import_ha_users(hass: HomeAssistant, store: NeoPillStore) -> list[Patient]:
    """Create a patient for every non-admin HA user that doesn't have one yet.

    The new patient is linked to its user, who gets DEFAULT_OWN_ROLE on it (they
    manage their own therapy); an admin can change that role afterwards.
    """
    created: list[Patient] = []
    for user in await async_list_ha_users(hass):
        if user.is_admin or store.patient_for_ha_user(user.id) is not None:
            continue
        created.append(
            await store.async_add_patient(
                user.name or user.id[:8],
                ha_user_id=user.id,
                access={user.id: DEFAULT_OWN_ROLE},
            )
        )
    return created
