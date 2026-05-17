"""asyncio TCP transport for the 33120A serial proxy."""
from __future__ import annotations

import asyncio
import logging

_LOGGER = logging.getLogger(__name__)

CTRL_C = b"\x03"
TIMEOUT = 3.0
BACKOFF = (1, 2, 5, 10)


class Disconnected(Exception):
    """Raised when the TCP connection is lost."""


class Transport:
    """Serialised asyncio TCP client for the ESPHome stream_server."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Open the TCP connection."""
        self._reader, self._writer = await asyncio.open_connection(self._host, self._port)
        _LOGGER.debug("Connected to %s:%s", self._host, self._port)

    async def disconnect(self) -> None:
        """Close the TCP connection cleanly."""
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            self._writer = None
            self._reader = None

    async def send(self, cmd: str) -> None:
        """Send a SCPI command (no response expected)."""
        _validate(cmd)
        async with self._lock:
            await self._write(cmd)

    async def query(self, cmd: str) -> str:
        """Send a SCPI query and return the stripped response line."""
        _validate(cmd)
        async with self._lock:
            await self._write(cmd)
            return await self._read()

    async def _write(self, cmd: str) -> None:
        if not self._writer:
            raise Disconnected
        self._writer.write((cmd + "\n").encode())
        await asyncio.wait_for(self._writer.drain(), timeout=TIMEOUT)

    async def _read(self) -> str:
        if not self._reader:
            raise Disconnected
        line = await asyncio.wait_for(self._reader.readuntil(b"\n"), timeout=TIMEOUT)
        return line.decode().strip()

    async def _reset(self) -> None:
        """Send Ctrl-C to abort a stuck operation, then reconnect."""
        if self._writer:
            try:
                self._writer.write(CTRL_C)
                await self._writer.drain()
            except Exception:  # noqa: BLE001
                pass
        await self.disconnect()
        for delay in BACKOFF:
            try:
                await self.connect()
                return
            except OSError:
                _LOGGER.debug("Reconnect failed, retrying in %s s", delay)
                await asyncio.sleep(delay)
        raise Disconnected("All reconnect attempts failed")


def _validate(cmd: str) -> None:
    if not cmd.isascii() or "\n" in cmd or ";" in cmd:
        raise ValueError(f"Invalid SCPI command: {cmd!r}")
