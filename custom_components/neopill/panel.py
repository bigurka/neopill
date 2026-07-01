"""Registers the NeoPill custom sidebar panel (a dedicated page outside Lovelace).

Uses the same approach HACS itself uses in production: a direct call to
frontend.async_register_built_in_panel with a hand-built "_panel_custom" config,
rather than depending on the panel_custom component.
"""
from __future__ import annotations

import json
import pathlib

from homeassistant.components.frontend import async_register_built_in_panel, async_remove_panel
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import PANEL_ICON, PANEL_TITLE, PANEL_URL_PATH

_INTEGRATION_DIR = pathlib.Path(__file__).parent
_PANEL_DIST_DIR = _INTEGRATION_DIR / "panel_dist"
_STATIC_URL_PATH = "/api/neopill/panel"
_WEBCOMPONENT_NAME = "neopill-panel"

_MANIFEST = json.loads((_INTEGRATION_DIR / "manifest.json").read_text(encoding="utf-8"))
_VERSION = _MANIFEST.get("version", "0")


async def async_register_panel(hass: HomeAssistant) -> None:
    await hass.http.async_register_static_paths(
        [StaticPathConfig(_STATIC_URL_PATH, str(_PANEL_DIST_DIR), True)]
    )
    async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_URL_PATH,
        config={
            "_panel_custom": {
                "name": _WEBCOMPONENT_NAME,
                "embed_iframe": False,
                "trust_external": False,
                "module_url": f"{_STATIC_URL_PATH}/entrypoint.js?v={_VERSION}",
            }
        },
        require_admin=False,
    )


async def async_unregister_panel(hass: HomeAssistant) -> None:
    async_remove_panel(hass, PANEL_URL_PATH)
