from datetime import datetime, timedelta, time
import re
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, ENTITY_PREFIX

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up a chore switch from a config entry."""
    entity = ChoreSwitch(hass, entry)
    async_add_entities([entity])


class ChoreSwitch(SwitchEntity, RestoreEntity):
    """Representation of a Chore entity as a switch."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        self.hass = hass
        self.config_entry = config_entry

        # --- 1. CAPTURE INITIAL DATA ---
        # Capture Next_Due from the config (user input) before we delete it.
        self._initial_next_due = None
        
        if "Next_Due" in config_entry.data:
            nd_val = config_entry.data["Next_Due"]
            # Only use it if the user actually typed something (not empty)
            if nd_val:
                try:
                    self._initial_next_due = datetime.fromisoformat(nd_val)
                    _LOGGER.info(f"=== INIT: Captured initial Next_Due from config: {self._initial_next_due}")
                except Exception as e:
                    _LOGGER.warning(f"=== INIT: Could not parse initial Next_Due: {e}")

        # --- 2. CLEANUP CONFIG ENTRY ---
        # FIX: Create a mutable COPY of the dictionary to modify it
        # This prevents the "mappingproxy object has no attribute pop" error
        new_data = dict(config_entry.data)
        needs_update = False
        
        _LOGGER.info(f"=== INIT: Config entry data keys: {list(new_data.keys())}")
        _LOGGER.info(f"=== INIT: Config entry data: {new_data}")
        
        # Remove 'Next_Due' from the stored config so it doesn't overwrite state on future restarts
        if "Next_Due" in new_data:
            _LOGGER.warning(f"=== INIT: Found Next_Due in config: {new_data.get('Next_Due')} - REMOVING IT (One-time setup)")
            new_data.pop("Next_Due")
            needs_update = True
            
        # Remove 'Last_Completed' if present (cleanup old data)
        if "Last_Completed" in new_data:
            _LOGGER.warning(f"=== INIT: Found stale Last_Completed in config: {new_data.get('Last_Completed')} - REMOVING IT")
            new_data.pop("Last_Completed")
            needs_update = True
            
        # Save the cleaned data back to Home Assistant
        if needs_update:
            hass.config_entries.async_update_entry(config_entry, data=new_data)
            _LOGGER.warning(f"=== INIT: Updated config entry to remove runtime state")

        # --- 3. STANDARD SETUP ---
        # Human-friendly display name - exactly what user typed
        self._friendly_name = config_entry.data["Friendly_Name"]
        _LOGGER.info(f"=== INIT: Friendly name: {self._friendly_name}")
        
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
        _LOGGER.debug(f"=== CHORE DEBUG INIT ===")
        _LOGGER.debug(f"ENTITY_PREFIX: '{ENTITY_PREFIX}'")
        _LOGGER.debug(f"Raw Name from config: '{config_entry.data['Name']}'")
        _LOGGER.debug(f"Raw Friendly_Name from config: '{config_entry.data['Friendly_Name']}'")
        _LOGGER.debug(f"Final entity_name: '{entity_name}'")
        _LOGGER.debug(f"self._friendly_name: '{self._friendly_name}'")
        _LOGGER.debug(f"attr_name: '{self._attr_name}'")
        _LOGGER.debug(f"attr_unique_id: '{self._attr_unique_id}'")
        _LOGGER.debug(f"FORCED entity_id: '{self.entity_id}'")
        _LOGGER.debug(f"========================")

        # Default state → off (not due)
        self._state = False

        # Tracking - initialize to None, will be restored in async_added_to_hass()
        self._last_completed = None
        self._next_due = None

        # Init attributes
        self._update_from_config(config_entry.data)

        # Listen for config entry updates
        config_entry.add_update_listener(self.async_config_entry_updated)

    async def async_added_to_hass(self) -> None:
        """Restore state when entity is added to Home Assistant."""
        await super().async_added_to_hass()
        
        _LOGGER.info(f"[{self.entity_id}] async_added_to_hass() called")
        
        # Try to restore previous state
        last_state = await self.async_get_last_state()
        _LOGGER.info(f"[{self.entity_id}] Last state from DB: {last_state}")
        
        if last_state is not None:
            self._state = last_state.state == "on"
            _LOGGER.info(f"[{self.entity_id}] Restored state: {self._state}")
            
            # Restore attributes from previous state
            if last_state.attributes:
                _LOGGER.info(f"[{self.entity_id}] Available attributes: {list(last_state.attributes.keys())}")
                
                last_completed_str = last_state.attributes.get("Last_Completed")
                _LOGGER.info(f"[{self.entity_id}] Last_Completed from DB: {last_completed_str}")
                if last_completed_str:
                    try:
                        self._last_completed = datetime.fromisoformat(last_completed_str)
                        _LOGGER.info(f"[{self.entity_id}] Successfully restored Last_Completed: {self._last_completed}")
                    except Exception as e:
                        _LOGGER.warning(f"[{self.entity_id}] Could not parse Last_Completed: {last_completed_str}, error: {e}")
                        self._last_completed = datetime.now()
                else:
                    self._last_completed = datetime.now()
                    _LOGGER.info(f"[{self.entity_id}] No Last_Completed in attributes, using now()")
                
                next_due_str = last_state.attributes.get("Next_Due")
                _LOGGER.info(f"[{self.entity_id}] Next_Due from DB: {next_due_str}")
                if next_due_str:
                    try:
                        self._next_due = datetime.fromisoformat(next_due_str)
                        _LOGGER.info(f"[{self.entity_id}] Successfully restored Next_Due: {self._next_due}")
                        # Reschedule the auto-rearm timer
                        if self._next_due:
                            if getattr(self, "_unsub_timer", None):
                                self._unsub_timer()
                            self._unsub_timer = async_track_point_in_time(
                                self.hass, self._auto_rearm, self._next_due
                            )
                            _LOGGER.info(f"[{self.entity_id}] Rescheduled auto-rearm timer for {self._next_due}")
                    except Exception as e:
                        _LOGGER.warning(f"[{self.entity_id}] Could not parse Next_Due: {next_due_str}, error: {e}")
                        self._next_due = None
                else:
                    self._next_due = None
                    _LOGGER.info(f"[{self.entity_id}] No Next_Due in attributes")
            else:
                # No attributes, set defaults
                self._last_completed = datetime.now()
                self._next_due = None
                _LOGGER.info(f"[{self.entity_id}] No attributes found, using defaults")
            
            _LOGGER.info(f"[{self.entity_id}] === RESTORE COMPLETE === state={self._state}, last_completed={self._last_completed}, next_due={self._next_due}")
        else:
            # First time setup - no previous state exists
            self._last_completed = datetime.now()
            
            if self._initial_next_due:
                # User provided a specific Next Due date in the form
                self._next_due = self._initial_next_due
                _LOGGER.info(f"[{self.entity_id}] First time setup: Using user-defined Next_Due: {self._next_due}")
            else:
                # No user date provided (or cleared), calculate based on interval
                self._next_due = self._calculate_next_due(self._last_completed)
                _LOGGER.info(f"[{self.entity_id}] First time setup: Calculated Next_Due based on interval: {self._next_due}")

            # Schedule the timer immediately for the first run
            if self._next_due:
                self._unsub_timer = async_track_point_in_time(
                    self.hass, self._auto_rearm, self._next_due
                )
                _LOGGER.info(f"[{self.entity_id}] Scheduled initial auto-rearm for: {self._next_due}")

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

        self._interval = data.get("Interval", "1 week")
        if not self._interval:
            self._interval = "1 week"

        # Defaults for attributes
        self._assigned_to = data.get("Assigned_To", "Family").strip().title()
        if not self._assigned_to:
            self._assigned_to = "Family"

        self._room = data.get("Room", "Other").strip().title()
        if not self._room:
            self._room = "Other"
        
        # NOTE: Last_Completed and Next_Due are runtime state, NOT configuration.
        # They are restored ONLY from saved entity state in async_added_to_hass(),
        # never from the config entry. This is intentional to preserve state across restarts.

    async def async_config_entry_updated(self, hass, entry):
        """Update when config changes."""
        self._update_from_config(entry.data)
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed from Home Assistant."""
        if getattr(self, "_unsub_timer", None):
            self._unsub_timer()
            self._unsub_timer = None

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
        _LOGGER.info(f"[{self.entity_id}] async_turn_off() called - marking chore as complete")
        self._state = False
        self._last_completed = datetime.now()
        _LOGGER.info(f"[{self.entity_id}] Set Last_Completed to: {self._last_completed}")
        
        self._next_due = self._calculate_next_due(self._last_completed)
        _LOGGER.info(f"[{self.entity_id}] Calculated Next_Due: {self._next_due}")

        if self._next_due:
            if getattr(self, "_unsub_timer", None):
                self._unsub_timer()
            self._unsub_timer = async_track_point_in_time(
                self.hass, self._auto_rearm, self._next_due
            )
            _LOGGER.info(f"[{self.entity_id}] Scheduled auto-rearm for: {self._next_due}")
        
        _LOGGER.info(f"[{self.entity_id}] About to call async_write_ha_state() with attributes: Last_Completed={self._last_completed}, Next_Due={self._next_due}")
        self.async_write_ha_state()
        _LOGGER.info(f"[{self.entity_id}] State saved to database")

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
        _LOGGER.info(f"[_calculate_next_due] Input: start={start}, interval='{self._interval}'")
        
        if not self._interval:
            _LOGGER.warning(f"[_calculate_next_due] Interval is empty or None!")
            return None
        
        pattern = r"(\d+)\s*(day|days|week|weeks|month|months|year|years)"
        match = re.match(pattern, self._interval.strip().lower())
        if not match:
            _LOGGER.error(f"[_calculate_next_due] Interval '{self._interval}' does not match pattern")
            return None

        num = int(match.group(1))
        unit = match.group(2)
        _LOGGER.info(f"[_calculate_next_due] Parsed: num={num}, unit='{unit}'")

        if "day" in unit:
            due = start + timedelta(days=num)
        elif "week" in unit:
            due = start + timedelta(weeks=num)
        elif "month" in unit:
            due = start + timedelta(days=30 * num)
        elif "year" in unit:
            due = start + timedelta(days=365 * num)
        else:
            _LOGGER.error(f"[_calculate_next_due] Unknown unit: {unit}")
            return None

        result = datetime.combine(due.date(), time(hour=5))
        _LOGGER.info(f"[_calculate_next_due] Calculated result: {result}")
        return result

    @callback
    def _auto_rearm(self, now):
        """Auto-rearm the chore when due date is reached."""
        try:
            self._state = True
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error(f"Error in auto-rearm for {self.entity_id}: {err}")
        finally:
            self._unsub_timer = None