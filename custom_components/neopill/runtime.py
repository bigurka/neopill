"""Lookup helper for the single NeoPill config entry's runtime data.

Kept separate from __init__.py so services.py and websocket_api.py (both imported
from __init__.py) can use it without creating a circular import.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import DOMAIN


def get_runtime_data(hass: HomeAssistant):
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries or entries[0].runtime_data is None:
        raise RuntimeError("NeoPill non è configurato")
    return entries[0].runtime_data
