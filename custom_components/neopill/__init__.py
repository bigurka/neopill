"""The NeoPill integration: medication management for Home Assistant."""
from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, SIGNAL_MEDICATION_REMOVED
from .coordinator import DoseScheduler
from .panel import async_register_panel, async_unregister_panel
from .services import async_setup_services, async_unload_services
from .storage import NeoPillStore
from .websocket_api import async_setup_websocket_api

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.CALENDAR]


@dataclass
class NeoPillRuntimeData:
    """Objects shared across platforms/services/websocket handlers for one entry."""

    store: NeoPillStore
    scheduler: DoseScheduler


type NeoPillConfigEntry = ConfigEntry[NeoPillRuntimeData]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the (process-global) websocket API once, regardless of config entries."""
    async_setup_websocket_api(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NeoPillConfigEntry) -> bool:
    store = NeoPillStore(hass)
    await store.async_load()

    scheduler = DoseScheduler(hass, store)
    await scheduler.async_setup()

    entry.runtime_data = NeoPillRuntimeData(store=store, scheduler=scheduler)

    device_registry = dr.async_get(hass)

    @callback
    def _remove_medication_device(medication_id: str) -> None:
        device = device_registry.async_get_device(identifiers={(DOMAIN, medication_id)})
        if device is not None:
            device_registry.async_remove_device(device.id)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_MEDICATION_REMOVED, _remove_medication_device)
    )

    async_setup_services(hass)
    await async_register_panel(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NeoPillConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.scheduler.async_unload()
        async_unload_services(hass)
        await async_unregister_panel(hass)
    return unload_ok
