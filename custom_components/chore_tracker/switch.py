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
        self._initial_next_due = None
        
        # Check both data (setup) and options (updates) for Next_Due
        merged_data = config_entry.data.copy()
        merged_data.update(config_entry.options)

        if "Next_Due" in merged_data:
            nd_val = merged_data["Next_Due"]
            if nd_val:
                try:
                    self._initial_next_due = datetime.fromisoformat(nd_val)
                    _LOGGER.info(f"=== INIT: Captured initial Next_Due from config: {self._initial_next_due}")
                except Exception as e:
                    _LOGGER.warning(f"=== INIT: Could not parse initial Next_Due: {e}")

        # --- 2. CLEANUP CONFIG ENTRY ---
        # Note: We can only clean up 'data', we shouldn't touch 'options' automatically usually,
        # but here we just ensure 'data' is clean.
        new_data = dict(config_entry.data)
        needs_update = False
        
        _LOGGER.info(f"=== INIT: Config entry data keys: {list(new_data.keys())}")
        
        # Remove 'Next_Due' from the stored config so it doesn't overwrite state on future restarts
        if "Next_Due" in new_data:
            _LOGGER.warning(f"=== INIT: Found Next_Due in config - REMOVING IT (One-time setup)")
            new_data.pop("Next_Due")
            needs_update = True
            
        if "Last_Completed" in new_data:
            new_data.pop("Last_Completed")
            needs_update = True
            
        if needs_update:
            hass.config_entries.async_update_entry(config_entry, data=new_data)
            _LOGGER.warning(f"=== INIT: Updated config entry to remove runtime state")

        # --- 3. STANDARD SETUP ---
        # Use merged data for setup to respect any existing options
        setup_data = config_entry.data.copy()
        setup_data.update(config_entry.options)

        self._friendly_name = setup_data.get("Friendly_Name", "")
        self._attr_unique_id = setup_data.get("Name", "")
        
        entity_name = setup_data.get("Name", "")
        if not entity_name.startswith(ENTITY_PREFIX):
            entity_name = f"{ENTITY_PREFIX}{entity_name}"
        
        self._attr_name = entity_name
        self._attr_friendly_name = self._friendly_name
        self.entity_id = f"switch.{entity_name}"
        
        self._state = False
        self._last_completed = None
        self._next_due = None

        # Initialize attributes using the merged data
        self._update_from_config(setup_data)

        config_entry.add_update_listener(self.async_config_entry_updated)

    async def async_added_to_hass(self) -> None:
        """Restore state when entity is added to Home Assistant."""
        await super().async_added_to_hass()
        
        _LOGGER.info(f"[{self.entity_id}] async_added_to_hass() called")
        
        last_state = await self.async_get_last_state()
        
        if last_state is not None:
            self._state = last_state.state == "on"
            
            if last_state.attributes:
                last_completed_str = last_state.attributes.get("Last_Completed")
                if last_completed_str:
                    try:
                        self._last_completed = datetime.fromisoformat(last_completed_str)
                    except Exception as e:
                        self._last_completed = datetime.now()
                else:
                    self._last_completed = datetime.now()
                
                next_due_str = last_state.attributes.get("Next_Due")
                if next_due_str:
                    try:
                        self._next_due = datetime.fromisoformat(next_due_str)
                        if self._next_due:
                            if getattr(self, "_unsub_timer", None):
                                self._unsub_timer()
                            self._unsub_timer = async_track_point_in_time(
                                self.hass, self._auto_rearm, self._next_due
                            )
                    except Exception as e:
                        self._next_due = None
                else:
                    self._next_due = None
            else:
                self._last_completed = datetime.now()
                self._next_due = None
            
            _LOGGER.info(f"[{self.entity_id}] === RESTORE COMPLETE === state={self._state}")
        else:
            self._last_completed = datetime.now()
            
            if self._initial_next_due:
                self._next_due = self._initial_next_due
                _LOGGER.info(f"[{self.entity_id}] First time setup: Using user-defined Next_Due: {self._next_due}")
            else:
                self._next_due = self._calculate_next_due(self._last_completed)

            if self._next_due:
                self._unsub_timer = async_track_point_in_time(
                    self.hass, self._auto_rearm, self._next_due
                )

    def _update_from_config(self, data):
        """Update internal state from config entry data."""
        self._friendly_name = data.get("Friendly_Name", self._friendly_name)
        self._attr_friendly_name = self._friendly_name

        self._attr_unique_id = data.get("Name", self._attr_unique_id)
        
        entity_name = data.get("Name", self._attr_unique_id)
        if not entity_name.startswith(ENTITY_PREFIX):
            entity_name = f"{ENTITY_PREFIX}{entity_name}"
        
        self._attr_name = entity_name
        self.entity_id = f"switch.{entity_name}"

        self._interval = data.get("Interval", "1 week")
        if not self._interval:
            self._interval = "1 week"

        self._assigned_to = data.get("Assigned_To", "Family").strip().title()
        if not self._assigned_to:
            self._assigned_to = "Family"

        self._room = data.get("Room", "Other").strip().title()
        if not self._room:
            self._room = "Other"

        # --- FIX: Handle manual Next_Due update ---
        if "Next_Due" in data:
            new_next_due_str = data["Next_Due"]
            if new_next_due_str:
                try:
                    new_next_due = datetime.fromisoformat(new_next_due_str)
                    
                    # Update logic if the date actually changed
                    current_str = self._next_due.isoformat() if self._next_due else ""
                    
                    if current_str != new_next_due_str:
                        _LOGGER.info(f"[{self.entity_id}] Manual update of Next_Due detected: {new_next_due}")
                        self._next_due = new_next_due
                        
                        # Reschedule the auto-rearm timer for the new date
                        if getattr(self, "_unsub_timer", None):
                            self._unsub_timer()
                            
                        self._unsub_timer = async_track_point_in_time(
                            self.hass, self._auto_rearm, self._next_due
                        )
                except Exception as e:
                    _LOGGER.warning(f"[{self.entity_id}] Could not parse manual Next_Due update: {e}")

    async def async_config_entry_updated(self, hass, entry):
        """Update when config changes."""
        # --- FIX: Merge Data and Options ---
        # The Options Flow saves to entry.options. We must merge this with entry.data
        # to ensure _update_from_config sees the new values.
        updated_data = entry.data.copy()
        updated_data.update(entry.options)
        
        self._update_from_config(updated_data)
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed from Home Assistant."""
        if getattr(self, "_unsub_timer", None):
            self._unsub_timer()
            self._unsub_timer = None

    @property
    def name(self) -> str:
        return self._friendly_name
    
    @property
    def friendly_name(self) -> str:
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
        
        self._next_due = self._calculate_next_due(self._last_completed)

        if self._next_due:
            if getattr(self, "_unsub_timer", None):
                self._unsub_timer()
            self._unsub_timer = async_track_point_in_time(
                self.hass, self._auto_rearm, self._next_due
            )
        
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        return {
            "friendly_name": self._friendly_name,
            "Interval": self._interval,
            "Assigned_To": self._assigned_to,
            "Room": self._room,
            "Last_Completed": self._last_completed.isoformat() if self._last_completed else None,
            "Next_Due": self._next_due.isoformat() if self._next_due else None,
            "Is Due": self._state,
        }

    def _calculate_next_due(self, start: datetime) -> datetime:
        if not self._interval:
            return None
        
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

        result = datetime.combine(due.date(), time(hour=5))
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