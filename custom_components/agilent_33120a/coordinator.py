"""DataUpdateCoordinator for the 33120A."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .transport import Transport

_LOGGER = logging.getLogger(__name__)

# "SIN +1.000000000000E+03,+1.000000E-01,+0.000000E+00"
_APPL_RE = re.compile(
    r'"?(\w+)\s+([+-]?\d+\.?\d*[Ee][+-]?\d+),([+-]?\d+\.?\d*[Ee][+-]?\d+),([+-]?\d+\.?\d*[Ee][+-]?\d+)"?'
)


class ParseError(Exception):
    """Raised when APPL? response cannot be parsed."""


@dataclass
class InstrumentState:
    shape: str
    freq_hz: float
    amplitude_vpp: float
    offset_v: float
    duty_pct: float | None
    last_error: str | None


class Agilent33120ACoordinator(DataUpdateCoordinator[InstrumentState]):
    """Poll the 33120A and coalesce into an InstrumentState."""

    def __init__(self, hass: HomeAssistant, transport: Transport, poll_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="agilent_33120a",
            update_interval=timedelta(seconds=poll_interval),
        )
        self._transport = transport

    async def _async_update_data(self) -> InstrumentState:
        try:
            raw = await self._transport.query("APPL?")
            state = _parse_appl(raw)

            duty = None
            if state.shape == "SQU":
                duty_raw = await self._transport.query("PULS:DCYC?")
                duty = float(duty_raw)

            last_error = await self._drain_errors()

            return InstrumentState(
                shape=state.shape,
                freq_hz=state.freq_hz,
                amplitude_vpp=state.amplitude_vpp,
                offset_v=state.offset_v,
                duty_pct=duty,
                last_error=last_error,
            )
        except Exception as exc:
            raise UpdateFailed(f"33120A poll failed: {exc}") from exc

    async def _drain_errors(self) -> str | None:
        last: str | None = None
        for _ in range(5):
            err = await self._transport.query("SYST:ERR?")
            if err.startswith("+0"):
                break
            last = err
        return last


def _parse_appl(raw: str) -> InstrumentState:
    m = _APPL_RE.match(raw.strip())
    if not m:
        raise ParseError(f"Cannot parse APPL? response: {raw!r}")
    shape, freq, amp, offs = m.group(1), float(m.group(2)), float(m.group(3)), float(m.group(4))
    return InstrumentState(shape=shape, freq_hz=freq, amplitude_vpp=amp, offset_v=offs, duty_pct=None, last_error=None)
