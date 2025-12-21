import voluptuous as vol
from homeassistant import config_entries
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import entity_registry as er
from datetime import datetime, timedelta
import re

from .const import DOMAIN, ENTITY_PREFIX


def slugify(value: str) -> str:
    """Convert text into a safe slug for entity IDs."""
    return re.sub(r'[^a-z0-9_]+', '_', value.lower()).strip('_')


class ChoreTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Chore Tracker."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            # Auto-generate internal Name (used as unique_id) with prefix
            friendly_name = user_input["Friendly_Name"]
            slug = re.sub(r'[^a-z0-9_]+', '_', friendly_name.lower()).strip('_')
            user_input["Name"] = f"chore_{slug}"

            return self.async_create_entry(
                title=friendly_name,
                data=user_input
            )

        schema = self._get_schema(None)
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    def _get_schema(self, current=None):
        """Get the form schema."""
        # Default Next_Due = tomorrow
        default_next_due = (datetime.now() + timedelta(days=1)).date().isoformat()
        
        return vol.Schema(
            {
                vol.Required("Friendly_Name", default=""): cv.string,
                vol.Required("Interval", default="1 week"): cv.string,
                vol.Optional("Assigned_To", default=""): cv.string,
                vol.Optional("Room", default=""): cv.string,
                vol.Optional("Next_Due", default=default_next_due): cv.string,
            }
        )

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(config_entry):
        return ChoreTrackerOptionsFlow(config_entry)


class ChoreTrackerOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Chore Tracker."""

    def __init__(self, config_entry):
        self.entry = config_entry

    async def async_step_init(self, user_input=None):
        errors = {}

        if user_input is not None:
            # Note: In OptionsFlow, async_create_entry saves to entry.options, not entry.data
            
            # Re-generate name if friendly name changed (optional, but consistent)
            friendly_name = user_input["Friendly_Name"]
            slug = re.sub(r'[^a-z0-9_]+', '_', friendly_name.lower()).strip('_')
            user_input["Name"] = f"chore_{slug}"

            return self.async_create_entry(
                title=self.entry.title,
                data=user_input
            )

        # --- FIX 1: Merge Data and Options ---
        # We must merge existing data and options so the form shows the *latest* saved values,
        # otherwise it will revert to the original setup values every time you open it.
        config_data = self.entry.data.copy()
        config_data.update(self.entry.options)
        
        # --- FIX 2: Fetch current runtime state for Next_Due ---
        current_next_due = None
        
        # Get the entity registry
        ent_reg = er.async_get(self.hass)
        
        # Find the entity associated with this config entry
        entries = er.async_entries_for_config_entry(ent_reg, self.entry.entry_id)
        
        if entries:
            entity_id = entries[0].entity_id
            # Get the actual state object from Home Assistant
            state_obj = self.hass.states.get(entity_id)
            
            if state_obj and "Next_Due" in state_obj.attributes:
                current_next_due = state_obj.attributes["Next_Due"]

        # Pass the merged config_data to the schema
        schema = self._get_options_schema(config_data, current_next_due)

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    def _get_options_schema(self, current, current_next_due=None):
        """Get the options form schema."""
        
        # Use the retrieved runtime value if it exists, otherwise default to tomorrow
        if current_next_due:
            default_next_due = str(current_next_due)
        else:
            default_next_due = (datetime.now() + timedelta(days=1)).date().isoformat()

        return vol.Schema(
            {
                vol.Required("Friendly_Name", default=current.get("Friendly_Name", "")): cv.string,
                vol.Required("Interval", default=current.get("Interval", "1 week")): cv.string,
                vol.Optional("Assigned_To", default=current.get("Assigned_To", "")): cv.string,
                vol.Optional("Room", default=current.get("Room", "")): cv.string,
                vol.Optional("Next_Due", default=default_next_due): cv.string,
            }
        )