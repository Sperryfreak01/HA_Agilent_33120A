"""Number entities: frequency, amplitude, offset, duty cycle."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import AMP_LIMITS, CONF_TERMINATION, DOMAIN, FREQ_LIMITS, VMAX
from .coordinator import Agilent33120ACoordinator
from .entity import Agilent33120AEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: Agilent33120ACoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    term = entry.data[CONF_TERMINATION]
    async_add_entities([
        FrequencyNumber(coordinator, entry.entry_id),
        AmplitudeNumber(coordinator, entry.entry_id, term),
        OffsetNumber(coordinator, entry.entry_id, term),
        DutyCycleNumber(coordinator, entry.entry_id),
    ])


class FrequencyNumber(Agilent33120AEntity, NumberEntity):
    _attr_name = "Frequency"
    _attr_native_unit_of_measurement = "Hz"
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: Agilent33120ACoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "frequency")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.freq_hz if self.coordinator.data else None

    @property
    def native_min_value(self) -> float:
        shape = self.coordinator.data.shape if self.coordinator.data else "SIN"
        return FREQ_LIMITS.get(shape, FREQ_LIMITS["SIN"])[0]

    @property
    def native_max_value(self) -> float:
        shape = self.coordinator.data.shape if self.coordinator.data else "SIN"
        return FREQ_LIMITS.get(shape, FREQ_LIMITS["SIN"])[1]

    @property
    def native_step(self) -> float:
        return 1e-4

    async def async_set_native_value(self, value: float) -> None:
        transport = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["transport"]
        await transport.send(f"FREQ {value:.6E}")
        await transport.send("SYST:LOC")
        await self.coordinator.async_request_refresh()


class AmplitudeNumber(Agilent33120AEntity, NumberEntity):
    _attr_name = "Amplitude"
    _attr_native_unit_of_measurement = "Vpp"
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: Agilent33120ACoordinator, entry_id: str, termination: str) -> None:
        super().__init__(coordinator, entry_id, "amplitude")
        self._term = termination

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.amplitude_vpp if self.coordinator.data else None

    @property
    def native_min_value(self) -> float:
        return AMP_LIMITS[self._term][0]

    @property
    def native_max_value(self) -> float:
        return AMP_LIMITS[self._term][1]

    @property
    def native_step(self) -> float:
        return 0.001

    async def async_set_native_value(self, value: float) -> None:
        transport = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["transport"]
        await transport.send(f"VOLT {value:.6E}")
        await transport.send("SYST:LOC")
        await self.coordinator.async_request_refresh()


class OffsetNumber(Agilent33120AEntity, NumberEntity):
    _attr_name = "DC Offset"
    _attr_native_unit_of_measurement = "V"
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: Agilent33120ACoordinator, entry_id: str, termination: str) -> None:
        super().__init__(coordinator, entry_id, "offset")
        self._term = termination

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.offset_v if self.coordinator.data else None

    @property
    def native_min_value(self) -> float:
        vmax = VMAX[self._term]
        if self.coordinator.data:
            vpp = self.coordinator.data.amplitude_vpp
            limit = min(vmax - vpp / 2, 2 * vpp)
            return -limit
        return -vmax

    @property
    def native_max_value(self) -> float:
        vmax = VMAX[self._term]
        if self.coordinator.data:
            vpp = self.coordinator.data.amplitude_vpp
            return min(vmax - vpp / 2, 2 * vpp)
        return vmax

    @property
    def native_step(self) -> float:
        return 0.001

    async def async_set_native_value(self, value: float) -> None:
        transport = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["transport"]
        await transport.send(f"VOLT:OFFS {value:.6E}")
        await transport.send("SYST:LOC")
        await self.coordinator.async_request_refresh()


class DutyCycleNumber(Agilent33120AEntity, NumberEntity):
    _attr_name = "Duty Cycle"
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: Agilent33120ACoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "duty_cycle")

    @property
    def available(self) -> bool:
        return self.coordinator.data is not None and self.coordinator.data.shape == "SQU"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.duty_pct if self.coordinator.data else None

    @property
    def native_min_value(self) -> float:
        if self.coordinator.data and self.coordinator.data.freq_hz > 5e6:
            return 40.0
        return 20.0

    @property
    def native_max_value(self) -> float:
        if self.coordinator.data and self.coordinator.data.freq_hz > 5e6:
            return 60.0
        return 80.0

    @property
    def native_step(self) -> float:
        return 0.1

    async def async_set_native_value(self, value: float) -> None:
        transport = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["transport"]
        await transport.send(f"PULS:DCYC {value:.2f}")
        await transport.send("SYST:LOC")
        await self.coordinator.async_request_refresh()
