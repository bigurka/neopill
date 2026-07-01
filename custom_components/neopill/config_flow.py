"""Config flow for NeoPill.

Single-instance, zero-field: the real setup (patients, medications) happens in the
NeoPill sidebar panel, not in this wizard. This flow only exists because Home
Assistant requires a config entry to load an integration.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN


class NeoPillConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the (single-step, no-field) NeoPill config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="NeoPill", data={})
        return self.async_show_form(step_id="user")
