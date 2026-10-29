"""Lookup helper for the single NeoPill config entry's runtime data.

Kept separate from __init__.py so services.py and websocket_api.py (both imported
from __init__.py) can use it without creating a circular import.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import DOMAIN


def get_runtime_data(hass: HomeAssistant):
    entries = hass.config_entries.async_entries(DOMAIN)
    # runtime_data doesn't exist at all on an entry that was never set up (or
    # failed to), so getattr rather than a plain attribute read.
    if not entries or getattr(entries[0], "runtime_data", None) is None:
        raise RuntimeError("NeoPill non è configurato")
    return entries[0].runtime_data
