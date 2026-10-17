"""Synchronize UI assertions with background storage operations."""

import asyncio

from textual.pilot import Pilot

from hiper.tui.app import HiperApp


async def wait_for_app(pilot: Pilot[None]) -> None:
    """Drain UI events and wait for the app's I/O and refresh to finish."""
    app = pilot.app
    assert isinstance(app, HiperApp)
    async with asyncio.timeout(10):
        await pilot.pause()
        while app.busy:
            await asyncio.sleep(0.01)
        await pilot.pause()
