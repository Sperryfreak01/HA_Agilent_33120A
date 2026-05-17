"""Shared base entity for the 33120A integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Agilent33120ACoordinator


class Agilent33120AEntity(CoordinatorEntity[Agilent33120ACoordinator]):
    """Base entity: ties DeviceInfo and unique_id prefix to the coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: Agilent33120ACoordinator, entry_id: str, unique_suffix: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_{unique_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Agilent 33120A",
            manufacturer="Agilent Technologies / HP",
            model="33120A",
        )
