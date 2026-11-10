"""Start Home Assistant for the page tests, reachable from this machine only.

Home Assistant resolves names with an mDNS resolver that listens on every
network interface (UDP 5353). The page tests need no name resolution, so this
starter swaps it for the plain resolver of aiohttp; together with
`server_host: 127.0.0.1` nothing listens beyond the loopback interface, and the
desktop firewall has nothing to ask about.

The Bluetooth integration would also look for the adapters of this machine.
The page tests bring their own made-up scanners (demo_ble), so it is told
there are none: no Bluetooth radio is touched and no permission is asked for.

Usage: python -I run_hass.py -c <config dir>
"""

import sys

import aiohttp
from bluetooth_adapters import BluetoothAdapters

import homeassistant.components.bluetooth as bluetooth
import homeassistant.components.bluetooth.config_flow as bluetooth_config_flow
import homeassistant.helpers.aiohttp_client as aiohttp_client


class _LocalResolver(aiohttp.ThreadedResolver):
    """The resolver of aiohttp, closed the way Home Assistant closes its own."""

    async def real_close(self) -> None:
        await self.close()


class _NoAdapters(BluetoothAdapters):
    """A machine without Bluetooth adapters."""

    @property
    def adapters(self) -> dict:  # type: ignore[type-arg]
        return {}

    @property
    def default_adapter(self) -> str:
        return "hci0"


aiohttp_client._async_make_resolver = lambda hass: _LocalResolver()
bluetooth.get_adapters = _NoAdapters
bluetooth_config_flow.get_adapters = _NoAdapters

from homeassistant.__main__ import main

sys.exit(main())
