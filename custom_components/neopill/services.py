"""Home Assistant services for NeoPill, usable from automations/scripts/YAML.

Thin wrappers over actions.py - identical logic to what button.py and
websocket_api.py use, so a service call and a panel click behave the same way.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .actions import async_mark_missed, async_restock, async_take_dose
from .const import DOMAIN
from .runtime import get_runtime_data

SERVICE_ASSUMI_FARMACO = "assumi_farmaco"
SERVICE_SEGNA_NON_ASSUNTA = "segna_non_assunta"
SERVICE_RIFORNISCI_FARMACO = "rifornisci_farmaco"

ATTR_MEDICATION_ID = "medication_id"
ATTR_AMOUNT = "amount"
ATTR_PACKAGES = "packages"

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


def async_setup_services(hass: HomeAssistant) -> None:
    async def _handle_take(call: ServiceCall) -> None:
        runtime = get_runtime_data(hass)
        await async_take_dose(
            runtime.store,
            runtime.scheduler,
            call.data[ATTR_MEDICATION_ID],
            call.data.get(ATTR_AMOUNT),
        )

    async def _handle_missed(call: ServiceCall) -> None:
        runtime = get_runtime_data(hass)
        await async_mark_missed(runtime.store, runtime.scheduler, call.data[ATTR_MEDICATION_ID])

    async def _handle_restock(call: ServiceCall) -> None:
        runtime = get_runtime_data(hass)
        await async_restock(
            runtime.store,
            call.data[ATTR_MEDICATION_ID],
            amount=call.data.get(ATTR_AMOUNT),
            packages=call.data.get(ATTR_PACKAGES),
        )

    hass.services.async_register(DOMAIN, SERVICE_ASSUMI_FARMACO, _handle_take, schema=_TAKE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_SEGNA_NON_ASSUNTA, _handle_missed, schema=_MISSED_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RIFORNISCI_FARMACO, _handle_restock, schema=_RESTOCK_SCHEMA
    )


def async_unload_services(hass: HomeAssistant) -> None:
    hass.services.async_remove(DOMAIN, SERVICE_ASSUMI_FARMACO)
    hass.services.async_remove(DOMAIN, SERVICE_SEGNA_NON_ASSUNTA)
    hass.services.async_remove(DOMAIN, SERVICE_RIFORNISCI_FARMACO)
