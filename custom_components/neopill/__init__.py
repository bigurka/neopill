"""The NeoPill integration: medication management for Home Assistant."""
from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .access import async_import_ha_users
from .const import DOMAIN, SIGNAL_MEDICATION_REMOVED, SIGNAL_PATIENT_REMOVED
from .coordinator import DoseScheduler
from .entity import patient_hub_identifier
from .migrations import async_cleanup_legacy_entities
from .panel import async_register_panel, async_unregister_panel
from .services import async_setup_services
from .storage import NeoPillStore
from .websocket_api import async_setup_websocket_api

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.CALENDAR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class NeoPillRuntimeData:
    """Objects shared across platforms/services/websocket handlers for one entry."""

    store: NeoPillStore
    scheduler: DoseScheduler


type NeoPillConfigEntry = ConfigEntry[NeoPillRuntimeData]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the (process-global) websocket API and services once, regardless of
    config entries - services must exist even while the entry isn't loaded."""
    async_setup_websocket_api(hass)
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NeoPillConfigEntry) -> bool:
    store = NeoPillStore(hass)
    await store.async_load()

    if not store.settings["initial_import_done"]:
        # First install: every non-admin HA user starts with their own patient.
        # Later users are added by an admin from the panel ("Import HA users").
        await async_import_ha_users(hass, store)
        await store.async_update_settings(initial_import_done=True)

    scheduler = DoseScheduler(hass, store)
    await scheduler.async_setup()

    entry.runtime_data = NeoPillRuntimeData(store=store, scheduler=scheduler)

    async_cleanup_legacy_entities(hass, entry.entry_id)

    device_registry = dr.async_get(hass)

    @callback
    def _remove_medication_device(medication_id: str) -> None:
        device = device_registry.async_get_device(identifiers={(DOMAIN, medication_id)})
        if device is not None:
            device_registry.async_remove_device(device.id)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_MEDICATION_REMOVED, _remove_medication_device)
    )

    @callback
    def _remove_patient_device(patient_id: str) -> None:
        device = device_registry.async_get_device(identifiers={patient_hub_identifier(patient_id)})
        if device is not None:
            device_registry.async_remove_device(device.id)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_PATIENT_REMOVED, _remove_patient_device)
    )

    await async_register_panel(hass, store.settings["show_in_sidebar"])
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NeoPillConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.scheduler.async_unload()
        await async_unregister_panel(hass)
    return unload_ok
