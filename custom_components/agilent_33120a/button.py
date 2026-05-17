"""Button entities: local, clear_errors, beep."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import Agilent33120ACoordinator
from .entity import Agilent33120AEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: Agilent33120ACoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([
        LocalButton(coordinator, entry.entry_id),
        ClearErrorsButton(coordinator, entry.entry_id),
        BeepButton(coordinator, entry.entry_id),
    ])


class _TransportButton(Agilent33120AEntity, ButtonEntity):
    _cmd: str

    async def async_press(self) -> None:
        transport = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["transport"]
        await transport.send(self._cmd)


class LocalButton(_TransportButton):
    _attr_name = "Local"
    _cmd = "SYST:LOC"

    def __init__(self, coordinator: Agilent33120ACoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "local")


class ClearErrorsButton(_TransportButton):
    _attr_name = "Clear Errors"
    _cmd = "*CLS"

    def __init__(self, coordinator: Agilent33120ACoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "clear_errors")


class BeepButton(_TransportButton):
    _attr_name = "Beep"
    _cmd = "SYST:BEEP"

    def __init__(self, coordinator: Agilent33120ACoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "beep")
