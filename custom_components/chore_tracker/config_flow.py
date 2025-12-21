import voluptuous as vol
from homeassistant import config_entries
import homeassistant.helpers.config_validation as cv
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
        # Default Next_Due = tomorrow (for display only, not stored in config)
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
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        errors = {}

        if user_input is not None:
            # Remove Next_Due from user_input - it's runtime state, not config
            user_input.pop("Next_Due", None)

            friendly_name = user_input["Friendly_Name"]
            slug = re.sub(r'[^a-z0-9_]+', '_', friendly_name.lower()).strip('_')
            user_input["Name"] = f"chore_{slug}"

            return self.async_create_entry(
                title=self.config_entry.title,
                data=user_input
            )

        schema = self._get_options_schema(self.config_entry.data)
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    def _get_options_schema(self, current):
        """Get the options form schema."""
        # Default Next_Due = tomorrow (for display only, not stored in config)
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
