"""Registers the NeoPill custom sidebar panel (a dedicated page outside Lovelace).

Uses the same approach HACS itself uses in production: a direct call to
frontend.async_register_built_in_panel with a hand-built "_panel_custom" config,
rather than depending on the panel_custom component.
"""
from __future__ import annotations

import json
import pathlib

from homeassistant.components.frontend import (
    add_extra_js_url,
    async_register_built_in_panel,
    async_remove_panel,
    remove_extra_js_url,
)
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, PANEL_ICON, PANEL_TITLE, PANEL_URL_PATH

_INTEGRATION_DIR = pathlib.Path(__file__).parent
_PANEL_DIST_DIR = _INTEGRATION_DIR / "panel_dist"
_WEBCOMPONENT_NAME = "neopill-panel"

_MANIFEST = json.loads((_INTEGRATION_DIR / "manifest.json").read_text(encoding="utf-8"))
_VERSION = _MANIFEST.get("version", "0")
# Version-scoped so that entrypoint.js's relative imports (./styles.js, ./i18n.js) also
# get a fresh URL on every release — without this, cache_headers=True below means browsers
# keep serving stale styles.js/i18n.js indefinitely even after entrypoint.js itself updates.
_STATIC_URL_PATH = f"/api/neopill/panel/{_VERSION}"
_EXTRA_JS_URLS = (
    f"{_STATIC_URL_PATH}/neopill-card.js",
    f"{_STATIC_URL_PATH}/neopill-strategy.js",
)
# HTTP routes can't be unregistered, so a config entry reload must not add them twice.
_STATIC_REGISTERED_KEY = f"{DOMAIN}_static_registered"


@callback
def _register_panel(hass: HomeAssistant, show_in_sidebar: bool, *, update: bool = False) -> None:
    # A panel without a sidebar title is left out of the sidebar by every frontend
    # version, while staying reachable at /neopill (and from the patient device's
    # "Visit" link) - more widely supported than the newer show_in_sidebar flag.
    async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=PANEL_TITLE if show_in_sidebar else None,
        sidebar_icon=PANEL_ICON if show_in_sidebar else None,
        frontend_url_path=PANEL_URL_PATH,
        config={
            "_panel_custom": {
                "name": _WEBCOMPONENT_NAME,
                "embed_iframe": False,
                "trust_external": False,
                "module_url": f"{_STATIC_URL_PATH}/entrypoint.js",
            }
        },
        require_admin=False,
        update=update,
    )


async def async_register_panel(hass: HomeAssistant, show_in_sidebar: bool) -> None:
    if not hass.data.get(_STATIC_REGISTERED_KEY):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(_STATIC_URL_PATH, str(_PANEL_DIST_DIR), True)]
        )
        hass.data[_STATIC_REGISTERED_KEY] = True
    _register_panel(hass, show_in_sidebar)
    # Loads the Lovelace card + dashboard strategy on every frontend page, so they
    # register themselves (customElements.define) without the user ever touching
    # Settings > Dashboards > Resources by hand.
    for url in _EXTRA_JS_URLS:
        add_extra_js_url(hass, url)


@callback
def async_update_panel_visibility(hass: HomeAssistant, show_in_sidebar: bool) -> None:
    """Show/hide the sidebar entry live (connected frontends refresh their panels)."""
    _register_panel(hass, show_in_sidebar, update=True)


async def async_unregister_panel(hass: HomeAssistant) -> None:
    async_remove_panel(hass, PANEL_URL_PATH)
    for url in _EXTRA_JS_URLS:
        remove_extra_js_url(hass, url)
