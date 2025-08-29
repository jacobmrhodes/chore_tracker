from datetime import datetime, timedelta, time
import re
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time

from .const import DOMAIN, ENTITY_PREFIX

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up a chore switch from a config entry."""
    entity = ChoreSwitch(hass, entry)
    async_add_entities([entity])


class ChoreSwitch(SwitchEntity):
    """Representation of a Chore entity as a switch."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        self.hass = hass
        self.config_entry = config_entry

        # Human-friendly display name - exactly what user typed
        self._friendly_name = config_entry.data["Friendly_Name"]
        
        # Unique ID comes directly from config_flow "Name" (already has chore_ prefix)
        self._attr_unique_id = config_entry.data["Name"]
        
        # For entity_id generation: use the prefixed name
        entity_name = config_entry.data["Name"]
        if not entity_name.startswith(ENTITY_PREFIX):
            entity_name = f"{ENTITY_PREFIX}{entity_name}"
        
        # Set the internal name to prefixed version (for entity_id)
        self._attr_name = entity_name
        
        # Set the display name to the user's original input
        self._attr_friendly_name = self._friendly_name
        
        # FORCE the entity_id - this overrides Home Assistant's automatic generation
        self.entity_id = f"switch.{entity_name}"
        
        # Debug logging
        _LOGGER.error(f"=== CHORE DEBUG INIT ===")
        _LOGGER.error(f"Config entry data: {config_entry.data}")
        _LOGGER.error(f"ENTITY_PREFIX: '{ENTITY_PREFIX}'")
        _LOGGER.error(f"Raw Name from config: '{config_entry.data['Name']}'")
        _LOGGER.error(f"Raw Friendly_Name from config: '{config_entry.data['Friendly_Name']}'")
        _LOGGER.error(f"Final entity_name: '{entity_name}'")
        _LOGGER.error(f"self._friendly_name: '{self._friendly_name}'")
        _LOGGER.error(f"attr_name: '{self._attr_name}'")
        _LOGGER.error(f"attr_unique_id: '{self._attr_unique_id}'")
        _LOGGER.error(f"attr_friendly_name: '{self._attr_friendly_name}'")
        _LOGGER.error(f"FORCED entity_id: '{self.entity_id}'")
        _LOGGER.error(f"========================")

        # Default state → off (not due)
        self._state = False

        # Tracking
        self._last_completed = datetime.now()
        self._next_due = None

        # Init attributes
        self._update_from_config(config_entry.data)

        # Listen for config entry updates
        config_entry.add_update_listener(self.async_config_entry_updated)

    def _update_from_config(self, data):
        """Update internal state from config entry data."""
        # Keep user's exact friendly name for display
        self._friendly_name = data.get("Friendly_Name", self._friendly_name)
        self._attr_friendly_name = self._friendly_name

        # Keep the same unique_id from config entry
        self._attr_unique_id = data.get("Name", self._attr_unique_id)
        
        # Set the entity name to include the chore_ prefix for proper entity_id generation
        entity_name = data.get("Name", self._attr_unique_id)
        if not entity_name.startswith(ENTITY_PREFIX):
            entity_name = f"{ENTITY_PREFIX}{entity_name}"
        
        # Internal name (for entity_id) vs display name (for UI)
        self._attr_name = entity_name
        # Force entity_id update
        self.entity_id = f"switch.{entity_name}"

        self._interval = data.get("Interval")

        # Defaults for attributes
        self._assigned_to = data.get("Assigned_To", "Family").strip().title()
        if not self._assigned_to:
            self._assigned_to = "Family"

        self._room = data.get("Room", "Other").strip().title()
        if not self._room:
            self._room = "Other"

        # Handle dates
        last_completed_raw = data.get("Last_Completed")
        if last_completed_raw:
            try:
                self._last_completed = (
                    datetime.fromisoformat(last_completed_raw)
                    if isinstance(last_completed_raw, str)
                    else last_completed_raw
                )
            except Exception:
                self._last_completed = datetime.now()
        else:
            self._last_completed = datetime.now()

        next_due_raw = data.get("Next_Due")
        if next_due_raw:
            try:
                next_due_dt = (
                    datetime.fromisoformat(next_due_raw)
                    if isinstance(next_due_raw, str)
                    else next_due_raw
                )
                self._next_due = datetime.combine(next_due_dt.date(), time(hour=5))
            except Exception:
                self._next_due = None
        else:
            self._next_due = None

        # Auto rearm scheduling
        if getattr(self, "_unsub_timer", None):
            self._unsub_timer()
        if self._next_due:
            self._unsub_timer = async_track_point_in_time(
                self.hass, self._auto_rearm, self._next_due
            )
        else:
            self._unsub_timer = None

    async def async_config_entry_updated(self, hass, entry):
        """Update when config changes."""
        self._update_from_config(entry.data)
        self.async_write_ha_state()

    @property
    def name(self) -> str:
        """Return the display name of the entity - this should be the user's input."""
        return self._friendly_name
    
    @property
    def friendly_name(self) -> str:
        """Return the friendly name of the entity.""" 
        return self._friendly_name
    @property
    def is_on(self) -> bool:
        return self._state

    async def async_turn_on(self, **kwargs):
        self._state = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._state = False
        self._last_completed = datetime.now()
        self._next_due = self._calculate_next_due(self._last_completed)

        if self._next_due:
            if getattr(self, "_unsub_timer", None):
                self._unsub_timer()
            self._unsub_timer = async_track_point_in_time(
                self.hass, self._auto_rearm, self._next_due
            )
        self.async_write_ha_state()

    #
    # Attributes
    #
    @property
    def extra_state_attributes(self):
        return {
            "friendly_name": self._friendly_name,  # Use the user's original input, not the prefixed name
            "Interval": self._interval,
            "Assigned_To": self._assigned_to,
            "Room": self._room,
            "Last_Completed": self._last_completed.isoformat() if self._last_completed else None,
            "Next_Due": self._next_due.isoformat() if self._next_due else None,
            "Is Due": self._state,
        }

    #
    # Helpers
    #
    def _calculate_next_due(self, start: datetime) -> datetime:
        pattern = r"(\d+)\s*(day|days|week|weeks|month|months|year|years)"
        match = re.match(pattern, self._interval.strip().lower())
        if not match:
            return None

        num = int(match.group(1))
        unit = match.group(2)

        if "day" in unit:
            due = start + timedelta(days=num)
        elif "week" in unit:
            due = start + timedelta(weeks=num)
        elif "month" in unit:
            due = start + timedelta(days=30 * num)
        elif "year" in unit:
            due = start + timedelta(days=365 * num)
        else:
            return None

        return datetime.combine(due.date(), time(hour=5))

    @callback
    def _auto_rearm(self, now):
        self._state = True
        self.async_write_ha_state()
        self._unsub_timer = None