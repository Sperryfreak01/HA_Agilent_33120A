"""Sensor entities: last SCPI error."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import Agilent33120ACoordinator
from .entity import Agilent33120AEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: Agilent33120ACoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([LastErrorSensor(coordinator, entry.entry_id)])


class LastErrorSensor(Agilent33120AEntity, SensorEntity):
    _attr_name = "Last Error"
    _attr_entity_registry_enabled_default = False  # diagnostic

    def __init__(self, coordinator: Agilent33120ACoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "last_error")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data and self.coordinator.data.last_error:
            return self.coordinator.data.last_error
        return None
