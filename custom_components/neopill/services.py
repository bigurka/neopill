"""Home Assistant services for NeoPill, usable from automations/scripts/YAML.

Thin wrappers over actions.py - identical logic to what button.py and
websocket_api.py use, so a service call and a panel click behave the same way.
Registered once in async_setup (not per config entry), as Home Assistant asks:
calls made while NeoPill isn't loaded get a clear error instead of "unknown action".
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
import functools

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .actions import async_correct_taken_to_missed, async_mark_missed, async_restock, async_take_dose
from .const import DOMAIN
from .runtime import get_runtime_data
from .storage import IntakeEventNotFoundError, MedicationNotFoundError, PatientNotFoundError

SERVICE_ASSUMI_FARMACO = "assumi_farmaco"
SERVICE_SEGNA_NON_ASSUNTA = "segna_non_assunta"
SERVICE_RIFORNISCI_FARMACO = "rifornisci_farmaco"
SERVICE_SEGNA_RIFORNIMENTO_NOTIFICATO = "segna_rifornimento_notificato"
SERVICE_CORREGGI_ASSUNZIONE = "correggi_assunzione"

ATTR_MEDICATION_ID = "medication_id"
ATTR_AMOUNT = "amount"
ATTR_PACKAGES = "packages"
ATTR_PATIENT_ID = "patient_id"
ATTR_EVENT_ID = "event_id"

_TAKE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MEDICATION_ID): cv.string,
        vol.Optional(ATTR_AMOUNT): vol.Coerce(float),
    }
)
_MISSED_SCHEMA = vol.Schema({vol.Required(ATTR_MEDICATION_ID): cv.string})
_RESTOCK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MEDICATION_ID): cv.string,
        vol.Optional(ATTR_AMOUNT): vol.Coerce(float),
        vol.Optional(ATTR_PACKAGES): vol.Coerce(float),
    }
)
_RESTOCK_NOTIFIED_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional(ATTR_MEDICATION_ID): cv.string,
            vol.Optional(ATTR_PATIENT_ID): cv.string,
        }
    ),
    cv.has_at_least_one_key(ATTR_MEDICATION_ID, ATTR_PATIENT_ID),
)
_CORREGGI_ASSUNZIONE_SCHEMA = vol.Schema({vol.Required(ATTR_EVENT_ID): cv.string})


def _validation_error(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders or None,
    )


def _translate_errors(
    handler: Callable[[ServiceCall], Awaitable[None]],
) -> Callable[[ServiceCall], Awaitable[None]]:
    """Turn NeoPill's internal errors into translated, user-facing ones."""

    @functools.wraps(handler)
    async def wrapper(call: ServiceCall) -> None:
        try:
            await handler(call)
        except MedicationNotFoundError as err:
            raise _validation_error("medication_not_found", id=str(err.args[0])) from err
        except PatientNotFoundError as err:
            raise _validation_error("patient_not_found", id=str(err.args[0])) from err
        except IntakeEventNotFoundError as err:
            raise _validation_error("event_not_found", id=str(err.args[0])) from err
        except ValueError as err:
            raise _validation_error("invalid_restock", error=str(err)) from err

    return wrapper


def _runtime(hass: HomeAssistant):
    try:
        return get_runtime_data(hass)
    except RuntimeError as err:
        raise _validation_error("not_loaded") from err


def async_setup_services(hass: HomeAssistant) -> None:
    @_translate_errors
    async def _handle_take(call: ServiceCall) -> None:
        runtime = _runtime(hass)
        await async_take_dose(
            runtime.store,
            runtime.scheduler,
            call.data[ATTR_MEDICATION_ID],
            call.data.get(ATTR_AMOUNT),
        )

    @_translate_errors
    async def _handle_missed(call: ServiceCall) -> None:
        runtime = _runtime(hass)
        await async_mark_missed(runtime.store, runtime.scheduler, call.data[ATTR_MEDICATION_ID])

    @_translate_errors
    async def _handle_restock(call: ServiceCall) -> None:
        runtime = _runtime(hass)
        await async_restock(
            runtime.store,
            call.data[ATTR_MEDICATION_ID],
            amount=call.data.get(ATTR_AMOUNT),
            packages=call.data.get(ATTR_PACKAGES),
        )

    @_translate_errors
    async def _handle_restock_notified(call: ServiceCall) -> None:
        runtime = _runtime(hass)
        medication_id = call.data.get(ATTR_MEDICATION_ID)
        if medication_id:
            await runtime.store.async_set_restock_notify_pending(medication_id, False)
            return
        patient_id = call.data[ATTR_PATIENT_ID]
        runtime.store.get_patient(patient_id)  # unknown id -> clear error, not a silent no-op
        for medication in runtime.store.list_medications(patient_id=patient_id):
            if medication.restock_notify_pending:
                await runtime.store.async_set_restock_notify_pending(medication.id, False)

    @_translate_errors
    async def _handle_correggi_assunzione(call: ServiceCall) -> None:
        runtime = _runtime(hass)
        await async_correct_taken_to_missed(runtime.store, call.data[ATTR_EVENT_ID])

    hass.services.async_register(DOMAIN, SERVICE_ASSUMI_FARMACO, _handle_take, schema=_TAKE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_SEGNA_NON_ASSUNTA, _handle_missed, schema=_MISSED_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RIFORNISCI_FARMACO, _handle_restock, schema=_RESTOCK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEGNA_RIFORNIMENTO_NOTIFICATO,
        _handle_restock_notified,
        schema=_RESTOCK_NOTIFIED_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CORREGGI_ASSUNZIONE,
        _handle_correggi_assunzione,
        schema=_CORREGGI_ASSUNZIONE_SCHEMA,
    )
