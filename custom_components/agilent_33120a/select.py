"""Waveform shape select entity."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SHAPE_LABELS
from .coordinator import Agilent33120ACoordinator
from .entity import Agilent33120AEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: Agilent33120ACoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([WaveformSelect(coordinator, entry.entry_id)])


class WaveformSelect(Agilent33120AEntity, SelectEntity):
    _attr_name = "Waveform"
    _attr_options = list(SHAPE_LABELS.values())

    def __init__(self, coordinator: Agilent33120ACoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "waveform")

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return SHAPE_LABELS.get(self.coordinator.data.shape)

    async def async_select_option(self, option: str) -> None:
        shape = next(k for k, v in SHAPE_LABELS.items() if v == option)
        state = self.coordinator.data
        cmd = f"APPL:{shape} {state.freq_hz:.6E},{state.amplitude_vpp:.6E},{state.offset_v:.6E}"
        transport = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["transport"]
        await transport.send(cmd)
        await transport.send("SYST:LOC")
        await self.coordinator.async_request_refresh()
