"""Check the page and the card in a real browser against a throwaway Home Assistant.

Starts Home Assistant with a made-up flat in a temporary directory, reachable
from this machine only (see run_hass.py). Made-up scanners (demo_ble) hear
made-up trackers, so the plan shows them where they are. Playwright drives the
page and the card and checks what they show and what reaches the integration.
Home Assistant is stopped through its own stop action at the end, also after a
failure.

Usage (from the repository root, with the packages of requirements_panel.txt):

    python -I scripts/panel/check_panel.py [--screenshots DIR] [--keep] [--only TEXT]
        [--browser chrome|chromium] [--headed]

--screenshots writes the pictures of the README into DIR (docs/screenshots).
--keep leaves the temporary directory for a look at the log.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
import itertools
import json
import math
from pathlib import Path
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
from playwright.async_api import Browser, Page, async_playwright

ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = ROOT / "custom_components" / "ble_floorplan"
DEMO = Path(__file__).resolve().parent / "demo_ble"
VERSION = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))["version"]
TIME_ZONE = ZoneInfo("Europe/Berlin")
# Accounts of the throwaway instance; it listens on 127.0.0.1 only and is deleted afterwards
ADMIN = ("admin", "panel-check-admin")
USER = ("user", "panel-check-user")
PANEL = "ble-floorplan-panel"
CARD = "ble-floorplan-card"
DASHBOARD = "dashboard-plan"
# The header's cog: Home Assistant's own page of the integration
INTEGRATION_PAGE = "/config/integrations/integration/ble_floorplan"
# The five areas of the page and their pages, as the addresses have them
PAGES = [
    "live/now",
    "live/history",
    "devices/scanners",
    "devices/trackers",
    "calibration/measure",
    "calibration/runs",
    "calibration/tuning",
    "analysis/coverage",
    "analysis/quality",
    "setup/overview",
    "setup/plan",
    "setup/location",
    "setup/recording",
]
# Pages without the floor plan beside them
MAP_LESS = {
    "setup/overview",
    "setup/location",
    "setup/recording",
    "analysis/quality",
    "calibration/tuning",
    "calibration/runs",
}
STAMP = re.compile(r"^As of \d{2}:\d{2}:\d{2}$")
# An iPhone's safe area (47 px above, 34 px below), as Home Assistant's debug setting sets it
SAFE_AREA = """() => {
  const style = document.createElement('style');
  style.textContent =
    ':root{--app-safe-area-inset-top:47px !important;--app-safe-area-inset-bottom:34px !important;}';
  document.head.append(style);
}"""
# Top and bottom of Home Assistant's frame for pages with tabs, the height of its header and
# top and bottom of its bar at the bottom, in the viewport
SAFE_AREA_MEASURE = """() => {
  const find = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.localName === 'hass-tabs-subpage') return el;
      const inner = el.shadowRoot && find(el.shadowRoot);
      if (inner) return inner;
    }
    return null;
  };
  const frame = find(document);
  if (!frame) return 'no hass-tabs-subpage';
  const box = (el) => {
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return [Math.round(b.top), Math.round(b.bottom)];
  };
  const toolbar = frame.shadowRoot.querySelector('.toolbar');
  return {
    viewport: innerHeight,
    frame: box(frame),
    toolbar: toolbar ? Math.round(toolbar.getBoundingClientRect().height) : null,
    tabbar: box(frame.shadowRoot.querySelector('#tabbar.bottom-bar')),
  };
}"""

# The made-up flat, the same as in the tests: addresses of the example range only
ROOMS: list[dict[str, Any]] = [
    {"name": "Living room", "x": 0, "y": 0, "w": 6, "h": 5},
    {"name": "Kitchen", "x": 6, "y": 0, "w": 4, "h": 5},
    {
        "name": "Bedroom",
        "points": [[0, 5], [6, 5], [6, 9], [2, 9], [2, 8], [0, 8]],
        "lx": 2.5,
        "ly": 6.5,
    },
    {"name": "Hall", "x": 6, "y": 5, "w": 4, "h": 4, "fs": 0.3, "rot": -90},
    {"name": "Dining", "x": 3, "y": 0, "w": 3, "h": 2.5, "zone": True},
    {"name": "Balcony", "x": 0, "y": 9, "w": 10, "h": 2, "outdoor": True, "label": False},
]
OPENINGS = [[6, 1, 6, 2.5], [3, 5, 4, 5], [6, 6, 6, 7]]
SCANNERS: list[dict[str, Any]] = [
    {
        "key": "living",
        "name": "Living room proxy",
        "source": "AA:BB:CC:DD:EE:01",
        "x": 1,
        "y": 1,
        "z": 0.8,
    },
    {
        "key": "kitchen",
        "name": "Kitchen plug",
        "source": "AA:BB:CC:DD:EE:02",
        "x": 9,
        "y": 1,
        "z": 2.0,
    },
    {
        "key": "bedroom",
        "name": "Bedroom proxy",
        "source": "AA:BB:CC:DD:EE:03",
        "x": 1,
        "y": 8,
        "z": 0.5,
    },
    {"key": "hall", "name": "Hall plug", "source": "AA:BB:CC:DD:EE:04", "x": 9, "y": 8, "z": 1.0},
]
TRACKERS: list[dict[str, Any]] = [
    {
        "key": "tag",
        "name": "Key tag",
        "address": "AA:BB:CC:DD:EE:10",
        "height": 0.3,
        "ref_power": -60,
    },
    {
        "key": "phone",
        "name": "Phone",
        "address": "AA:BB:CC:DD:EE:20",
        "height": 1.0,
        "ref_power": -58,
    },
    {"key": "watch", "name": "Watch", "address": "AA:BB:CC:DD:EE:30", "height": 1.2},
]
# Where demo_ble lets the scanners hear the trackers; the watch is out
HEARD = [
    {**TRACKERS[0], "x": 2.4, "y": 2.8},
    {**TRACKERS[1], "x": 7.6, "y": 3.4},
]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _configuration(port: int) -> str:
    demo = json.dumps(
        {
            "scanners": [{k: s[k] for k in ("source", "name", "x", "y", "z")} for s in SCANNERS],
            "trackers": HEARD,
        }
    )
    return f"""homeassistant:
  name: Home
  time_zone: {TIME_ZONE.key}
  unit_system: metric
  country: DE
  language: en
http:
  server_host: 127.0.0.1
  server_port: {port}
frontend:
config:
logger:
  default: warning
demo_ble: {demo}
"""


def _stored(key: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "minor_version": 1, "key": key, "data": data}


def _rssi(tracker: dict[str, Any], scanner: dict[str, Any], x: float, y: float, h: float) -> float:
    line = math.dist((x, y, h), (scanner["x"], scanner["y"], scanner["z"]))
    return tracker["ref_power"] - 30 * math.log10(max(line, 0.1))


def _runs(rng: random.Random) -> dict[str, Any]:
    """Three finished runs of the key tag: with today's scanners, with a moved one and one missing, and from before the setup was kept."""
    runs = []
    for i, (x, y) in enumerate([(2.0, 2.0), (8.0, 7.0), (4.0, 6.0)]):
        samples = {
            s["key"]: [
                [float(t), round(_rssi(TRACKERS[0], s, x, y, 0.3) + rng.choice([-2, -1, 0, 1, 2]))]
                for t in range(0, 60, 4)
            ]
            for s in SCANNERS
        }
        runs.append(
            {
                "id": f"01KCHECKRUN{i:015d}",
                "tracker": "tag",
                "x": x,
                "y": y,
                "height": 0.3,
                "started": datetime(2026, 1, 10 + i, 18, tzinfo=UTC).isoformat(),
                "duration": 60.0,
                "samples": samples,
            }
        )
    setup = {sc["key"]: [sc["x"], sc["y"], sc["z"]] for sc in SCANNERS}
    runs[0]["scanners"] = setup
    runs[1]["scanners"] = {
        k: [p[0] + 1.0, p[1], p[2]] if k == "kitchen" else p
        for k, p in setup.items()
        if k != "hall"
    }
    return {"runs": runs}


def _track(now: float, waypoints: list[tuple[float, float, str]], start: float) -> list[list[Any]]:
    """A track that walks through the waypoints, a point every 20 s, two minutes at each."""
    points: list[list[Any]] = []
    t = start
    for (x0, y0, room0), (x1, y1, _) in itertools.pairwise(waypoints):
        for _ in range(6):
            points.append([round(t, 1), x0, y0, room0])
            t += 20
        for step in range(1, 4):
            f = step / 3
            points.append(
                [round(t, 1), round(x0 + (x1 - x0) * f, 2), round(y0 + (y1 - y0) * f, 2), room0]
            )
            t += 20
    last = waypoints[-1]
    while t < now - 30:
        points.append([round(t, 1), last[0], last[1], last[2]])
        t += 300
    return points


def _history(now: float) -> tuple[str, dict[str, Any]]:
    """Today's made-up tracks, from an hour and a half ago up to now."""
    day = datetime.fromtimestamp(now, UTC).date().isoformat()
    midnight = datetime.fromisoformat(f"{day}T00:00:00+00:00").timestamp()
    start = max(midnight + 60, now - 5400)
    tag = [
        (2.4, 2.8, "Living room"),
        (4.0, 6.5, "Bedroom"),
        (8.0, 7.0, "Hall"),
        (2.4, 2.8, "Living room"),
    ]
    phone = [(7.6, 3.4, "Kitchen"), (8.5, 6.5, "Hall"), (7.6, 3.4, "Kitchen")]
    return day, {
        "saved": now,
        "tracks": {"tag": _track(now, tag, start), "phone": _track(now, phone, start + 600)},
    }


class Api:
    """REST and WebSocket access to the throwaway instance."""

    def __init__(self, session: aiohttp.ClientSession, base: str) -> None:
        self.session = session
        self.base = base
        self.client_id = f"{base}/"

    async def login(self, username: str, password: str) -> str:
        """An access token for a user, through the login flow the page uses."""
        flow = await self._json(
            "post",
            "/auth/login_flow",
            json={
                "client_id": self.client_id,
                "handler": ["homeassistant", None],
                "redirect_uri": self.client_id,
            },
        )
        step = await self._json(
            "post",
            f"/auth/login_flow/{flow['flow_id']}",
            json={"client_id": self.client_id, "username": username, "password": password},
        )
        token = await self._json(
            "post",
            "/auth/token",
            data={
                "grant_type": "authorization_code",
                "code": step["result"],
                "client_id": self.client_id,
            },
        )
        return str(token["access_token"])

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        async with self.session.request(method, self.base + path, **kwargs) as response:
            response.raise_for_status()
            return await response.json()

    async def post(self, token: str, path: str, body: dict[str, Any] | None = None) -> Any:
        """A REST call as the user of the token."""
        headers = {"Authorization": f"Bearer {token}"}
        return await self._json("post", path, headers=headers, json=body or {})

    async def ws(self, token: str, message: dict[str, Any]) -> dict[str, Any]:
        """One WebSocket command; the whole result message, success or not."""
        async with self.session.ws_connect(self.base + "/api/websocket") as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": token})
            if (await ws.receive_json())["type"] != "auth_ok":
                raise RuntimeError("WebSocket login failed")
            await ws.send_json({"id": 1, **message})
            while True:
                reply = await ws.receive_json()
                if reply.get("id") == 1 and reply.get("type") == "result":
                    return dict(reply)


class Instance:
    """A throwaway Home Assistant with the made-up flat."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.config = directory / "config"
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.process: subprocess.Popen[bytes] | None = None
        self.token = ""
        self.commit = ""

    def _launch(self) -> None:
        """Copy the integration and the made-up scanners, start Home Assistant in the background."""
        components = self.config / "custom_components"
        components.mkdir(parents=True)
        shutil.copytree(
            INTEGRATION,
            components / "ble_floorplan",
            ignore=shutil.ignore_patterns("__pycache__", "BUILD"),
        )
        shutil.copytree(DEMO, components / "demo_ble", ignore=shutil.ignore_patterns("__pycache__"))
        self.commit = (
            subprocess.run(
                ["git", "rev-parse", "--short=12", "HEAD"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            or "panel-check"
        )
        (components / "ble_floorplan" / "BUILD").write_text(self.commit)
        (self.config / "configuration.yaml").write_text(_configuration(self.port))
        log = (self.directory / "hass.log").open("wb")
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                str(Path(__file__).with_name("run_hass.py")),
                "-c",
                str(self.config),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )

    async def start(self, session: aiohttp.ClientSession) -> Api:
        """Start, onboard and set up BLE Floorplan with the made-up flat."""
        await asyncio.to_thread(self._launch)
        api = Api(session, self.base)
        await self._wait_ready(session)
        self.token = await self._onboard(api)
        await self._seed(api)
        return api

    async def _wait_ready(self, session: aiohttp.ClientSession) -> None:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(f"Home Assistant ended, see {self.directory / 'hass.log'}")
            try:
                async with session.get(self.base + "/api/onboarding") as response:
                    if response.status == 200:
                        return
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(1)
        raise RuntimeError("Home Assistant did not start within 3 minutes")

    async def _onboard(self, api: Api) -> str:
        user = await api._json(
            "post",
            "/api/onboarding/users",
            json={
                "client_id": api.client_id,
                "name": "Sam",
                "username": ADMIN[0],
                "password": ADMIN[1],
                "language": "en",
            },
        )
        token = await api._json(
            "post",
            "/auth/token",
            data={
                "grant_type": "authorization_code",
                "code": user["auth_code"],
                "client_id": api.client_id,
            },
        )
        access = str(token["access_token"])
        await api.post(access, "/api/onboarding/core_config")
        await api.post(access, "/api/onboarding/analytics")
        await api.post(
            access,
            "/api/onboarding/integration",
            {"client_id": api.client_id, "redirect_uri": api.client_id},
        )
        # The HTTP settings of configuration.yaml start as a trial that the page
        # asks to confirm and that reverts after five minutes; keep them
        promoted = await api.ws(access, {"type": "http/config/promote"})
        if not promoted["success"]:
            raise RuntimeError(f"HTTP settings not kept: {promoted}")
        return access

    async def _seed(self, api: Api) -> None:
        storage = self.config / ".storage"
        plan = {
            "rooms": ROOMS,
            "openings": OPENINGS,
            "scanners": SCANNERS,
            "trackers": TRACKERS,
            "settings": {"history_days": 7},
            "pair_offsets": {"kitchen": {"tag": -1.5}},
        }
        now = time.time()
        day, track = _history(now)
        files = {
            "ble_floorplan.floorplan": plan,
            "ble_floorplan.calibration": _runs(random.Random(7)),
            "ble_floorplan.history": {"days": [day]},
            f"ble_floorplan.history.{day}": track,
        }
        for key, data in files.items():
            (storage / key).write_text(json.dumps(_stored(key, data)))
        flow = await api.post(
            self.token, "/api/config/config_entries/flow", {"handler": "ble_floorplan"}
        )
        result = await api.post(self.token, f"/api/config/config_entries/flow/{flow['flow_id']}")
        if result.get("type") != "create_entry" or result["result"]["state"] != "loaded":
            raise RuntimeError(f"BLE Floorplan did not load: {result}")
        # A dashboard with the card: the overview as it comes, and in a sections view
        # with one, three and six rows, where it has to show what fits (STANDARD §7);
        # the live plan, as a panel and with a fixed height
        card = {"type": f"custom:{CARD}"}
        plan = {**card, "mode": "plan", "title": "Home"}
        created = await api.ws(
            self.token,
            {
                "type": "lovelace/dashboards/create",
                "url_path": DASHBOARD,
                "title": "Plan",
                "mode": "storage",
            },
        )
        if not created["success"]:
            raise RuntimeError(f"Dashboard not created: {created}")
        saved = await api.ws(
            self.token,
            {
                "type": "lovelace/config/save",
                "url_path": DASHBOARD,
                "config": {
                    "views": [
                        {"path": "plan", "title": "Plan", "type": "panel", "cards": [plan]},
                        {"path": "plain", "title": "Plain", "cards": [card]},
                        {
                            "path": "sizes",
                            "title": "Sizes",
                            "type": "sections",
                            "sections": [
                                {
                                    "type": "grid",
                                    "cards": [
                                        {**card, "grid_options": {"columns": 12, "rows": rows}}
                                        for rows in (1, 3, 6)
                                    ]
                                    + [card, {**card, "grid_options": {"columns": 6, "rows": 1}}],
                                }
                            ],
                        },
                        {
                            "path": "plan-rows",
                            "title": "Plan rows",
                            "type": "sections",
                            "sections": [
                                {
                                    "type": "grid",
                                    "cards": [
                                        {**plan, "grid_options": {"columns": 12, "rows": 6}},
                                        {**plan, "show_scanners": True, "rotation": 90},
                                    ],
                                }
                            ],
                        },
                    ]
                },
            },
        )
        if not saved["success"]:
            raise RuntimeError(f"Dashboard not saved: {saved}")
        # A user without administrator rights, for the access check
        user = await api.ws(
            self.token,
            {"type": "config/auth/create", "name": "Visitor", "group_ids": ["system-users"]},
        )
        await api.ws(
            self.token,
            {
                "type": "config/auth_provider/homeassistant/create",
                "user_id": user["result"]["user"]["id"],
                "username": USER[0],
                "password": USER[1],
            },
        )

    async def stop(self, session: aiohttp.ClientSession) -> None:
        """Stop through Home Assistant's own stop action; force only if that fails."""
        if self.process is None or self.process.poll() is not None:
            return
        try:
            if self.token:
                async with session.post(
                    self.base + "/api/services/homeassistant/stop",
                    headers={"Authorization": f"Bearer {self.token}"},
                ):
                    pass
        except aiohttp.ClientError:
            pass
        try:
            self.process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=30)


@dataclass
class Checks:
    """The checks that ran and the ones that failed."""

    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    # With --only: run just the checks whose name contains this
    only: str | None = None

    async def run(self, name: str, check: Callable[[], Awaitable[None]]) -> None:
        if self.only is not None and self.only not in name:
            return
        try:
            await check()
        except Exception as err:
            self.failed.append(f"{name}: {err!r}")
            print(f"FAIL {name}: {err!r}")
        else:
            self.passed.append(name)
            print(f"ok   {name}")


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _until(check: Callable[[], Awaitable[bool]], what: str, seconds: float = 15) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if await check():
            return
        await asyncio.sleep(0.25)
    raise AssertionError(f"timed out waiting for {what}")


async def _shot(page: Page, element: Any, path: Path) -> None:
    """A picture of an element of a dashboard, where it lies on the page.

    An element's own screenshot scrolls it to the top of the window, under the
    dashboard's header.
    """
    await page.evaluate("window.scrollTo(0, 0)")
    box = await element.bounding_box()
    await page.screenshot(path=str(path), clip=box, full_page=True)


async def _says(element: Any, text: str) -> bool:
    """Whether an element is there and shows the text."""
    return bool(await element.count()) and text in await element.inner_text()


async def _fits(line: Any) -> bool:
    """Whether a line's text is no wider than the line, to the fraction of a pixel.

    scrollWidth and clientWidth are whole numbers: a text 0.2 px too wide passes them
    and is cut off all the same.
    """
    return bool(
        await line.evaluate(
            """(el) => {
              const probe = document.createElement('span');
              probe.className = el.className;
              probe.style.cssText = 'position:absolute;visibility:hidden;overflow:visible;width:auto;display:inline-block';
              probe.textContent = el.textContent;
              el.parentElement.appendChild(probe);
              const fits = probe.getBoundingClientRect().width <= el.getBoundingClientRect().width;
              probe.remove();
              return fits;
            }"""
        )
    )


async def _open(
    browser: Browser, instance: Instance, user: tuple[str, str], path: str, **options: Any
) -> Page:
    """A new page, logged in, at the path."""
    context = await browser.new_context(
        viewport=options.pop("viewport", {"width": 1200, "height": 760}),
        device_scale_factor=2,
        locale="en-US",
        timezone_id=TIME_ZONE.key,
        color_scheme=options.pop("color_scheme", "light"),
    )
    page = await context.new_page()
    await page.goto(f"{instance.base}{path}")
    await page.get_by_label("Username").fill(user[0])
    await page.get_by_label("Password", exact=True).fill(user[1])
    await page.keyboard.press("Enter")
    await page.wait_for_load_state("networkidle")
    # Keep the sidebar out of the pictures
    await page.evaluate("localStorage.setItem('dockedSidebar', JSON.stringify('always_hidden'))")
    await page.reload()
    await page.wait_for_load_state("networkidle")
    return page


async def _goto(page: Page, instance: Instance, path: str) -> None:
    """A page of the panel, with the plan drawn and Home Assistant's loading screen gone."""
    await page.goto(f"{instance.base}/ble-floorplan/{path}")
    # The first load of the frontend takes a while on a slow CI machine
    await page.locator(f"{PANEL} hass-tabs-subpage").first.wait_for(timeout=90000)
    await page.locator("#ha-launch-screen").wait_for(state="detached")
    if path.split("?")[0] not in MAP_LESS:
        await page.locator(f"{PANEL} #svg .room").first.wait_for()


async def _subname(page: Page) -> str:
    """The name in the header of a scanner's or a tracker's page."""
    return (await page.locator(f"{PANEL} .subname").inner_text()).strip()


async def _frame(page: Page, *, sub: bool, page_id: str | None = None) -> None:
    """Home Assistant's frame: the five areas as tabs and the menu, or a back arrow and a name."""
    info = await page.locator(PANEL).evaluate(
        """el => {
          const frame = el.shadowRoot.getElementById('frame');
          const bar = frame.shadowRoot.getElementById('tabbar');
          const tabs = bar ? [...bar.querySelectorAll('ha-tab')] : [];
          const active = el.shadowRoot.querySelector('#subtabs ha-tab-group-tab[active]');
          return {
            tabs: tabs.length,
            active: tabs.filter((t) => t.active).length,
            bottom: !!bar && bar.classList.contains('bottom-bar'),
            back: !!frame.shadowRoot.querySelector('ha-icon-button-arrow-prev'),
            menu: !!frame.shadowRoot.querySelector('ha-menu-button'),
            name: el.shadowRoot.querySelector('.subname')?.textContent.trim() || null,
            page: active ? active.getAttribute('panel') : null,
          };
        }"""
    )
    if sub:
        expect(info["tabs"] == 0 and info["back"] and not info["menu"], f"subpage frame {info}")
        expect(bool(info["name"]), f"no name in the header {info}")
    else:
        expect(
            info["tabs"] == 5 and info["active"] == 1 and info["menu"] and not info["back"],
            f"frame {info}",
        )
        if page_id is not None:
            expect(info["page"] == page_id, f"tab of the page: {info['page']} for {page_id}")


async def _header(page: Page) -> None:
    """The header's actions on every page and subpage: stamp, refresh, integration."""
    order = await page.locator(PANEL).evaluate(
        "el => [...el.shadowRoot.querySelector('[slot=toolbar-icon]').children].map(e => e.id)"
    )
    expect(order == ["stamp", "refresh", "integration"], f"header actions {order}")
    stamp = page.locator(f"{PANEL} #stamp")
    await _until(lambda: _stamp_ok(stamp), "the stamp 'As of HH:MM:SS' in the header", seconds=10)
    for button, path, label in (
        ("refresh", "M17.65,6.35", "Refresh"),
        ("integration", "M12,8A4,4", "Integration in Home Assistant"),
    ):
        el = page.locator(f"{PANEL} ha-icon-button#{button}")
        expect(await el.is_visible(), f"{button} button not visible")
        expect((await el.get_attribute("path") or "").startswith(path), f"{button}: wrong icon")
        expect(await el.get_attribute("label") == label, f"{button}: label")


async def _stamp_ok(stamp: Any) -> bool:
    return await stamp.is_visible() and bool(STAMP.match((await stamp.inner_text()).strip()))


async def _plan(api: Api, instance: Instance) -> dict[str, Any]:
    reply = await api.ws(instance.token, {"type": "ble_floorplan/get_floorplan"})
    return dict(reply["result"]["floorplan"])


async def _named(page: Page, name: str) -> bool:
    return bool(await page.locator(f"{PANEL} .subname").count()) and await _subname(page) == name


async def _has(field: Any, text: str) -> bool:
    return text in await field.input_value()


async def _not_loading(page: Page) -> bool:
    classes = await page.locator(f"{PANEL} ha-icon-button#refresh").get_attribute("class")
    return "loading" not in (classes or "")


async def _count_at_least(locator: Any, n: int) -> bool:
    return bool(await locator.count() >= n)


async def rows_at_least(locator: Any, n: int) -> None:
    """Wait until the locator matches at least n elements."""
    await _until(lambda: _count_at_least(locator, n), f"{n} rows")


async def _settle(page: Page) -> None:
    """Let animations end before a picture."""
    await page.wait_for_timeout(600)


async def check_page(
    browser: Browser, instance: Instance, api: Api, shots: Path | None, only: str | None = None
) -> Checks:
    page = await _open(browser, instance, ADMIN, "/ble-floorplan/setup/plan")
    checks = Checks(only=only)

    async def plan_and_version() -> None:
        await _goto(page, instance, "setup/overview")
        about = (await page.locator(f"{PANEL} .about").first.inner_text()).strip()
        expect(about == f"BLE Floorplan {VERSION} · commit {instance.commit}", about)
        await _goto(page, instance, "setup/plan")
        rooms = await page.locator(f"{PANEL} #svg .room").count()
        expect(rooms >= 5, f"{rooms} rooms drawn")
        await _frame(page, sub=False, page_id="plan")
        # Drawing is the start; YAML is the other way, one of the two at a time
        await page.locator(f"{PANEL} ha-button[data-act='ed-tool']").first.wait_for()
        expect(await page.locator(f"{PANEL} textarea").count() == 0, "the YAML beside the drawing")
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "plan.png"))
        await page.locator(f"{PANEL} ha-button[data-act='plan-mode'][data-key='yaml']").click()
        textarea = page.locator(f"{PANEL} textarea")
        await textarea.wait_for()
        expect(
            await page.locator(f"{PANEL} ha-button[data-act='ed-tool']").count() == 0,
            "tools beside the YAML",
        )
        layout = await textarea.input_value()
        expect("Living room" in layout, "the floor plan as YAML is missing")
        # The text field fits the window and scrolls in itself
        box = await textarea.bounding_box()
        size = page.viewport_size
        assert box is not None and size is not None
        expect(
            box["y"] + box["height"] <= size["height"],
            f"the YAML ends at {box['y'] + box['height']}",
        )
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "plan-yaml.png"))

    await checks.run(
        "floor plan with the YAML; the version on the setup overview", plan_and_version
    )

    async def header_on_every_page() -> None:
        for path in PAGES:
            await _goto(page, instance, path)
            try:
                await _header(page)
                await _frame(page, sub=False, page_id=path.split("/")[1])
            except AssertionError as err:
                raise AssertionError(f"{path}: {err}") from err

    await checks.run(
        "every page: the five areas as Home Assistant's tabs, its own tab, stamp, refresh, integration",
        header_on_every_page,
    )

    async def old_addresses() -> None:
        # Bookmarks and links of before: to the page that took the place
        for old, new in (
            ("settings", "/ble-floorplan/setup/location"),
            ("timeline", "/ble-floorplan/live/history"),
            ("plan", "/ble-floorplan/setup/plan"),
            ("calibration", "/ble-floorplan/calibration/measure"),
            ("", "/ble-floorplan/live/now"),
        ):
            await page.goto(f"{instance.base}/ble-floorplan/{old}")
            await page.wait_for_url(f"**{new}")
        await page.goto(f"{instance.base}/ble-floorplan/scanners?key=hall")
        await page.wait_for_url("**/ble-floorplan/devices/scanners?key=hall")
        await _until(lambda: _named(page, "Hall plug"), "the hall plug's page")

    await checks.run("old addresses lead to the pages that took their place", old_addresses)

    async def refresh_fetches_again() -> None:
        await _goto(page, instance, "setup/plan")
        textarea = page.locator(f"{PANEL} textarea")
        await _until(lambda: _has(textarea, "Living room"), "the floor plan as YAML", seconds=10)
        # The YAML on the page is fetched once; a change made elsewhere shows after a refresh
        before = (await api.ws(instance.token, {"type": "ble_floorplan/get_layout"}))["result"]
        changed = before["yaml"].replace("name: Kitchen", "name: Kitchenette", 1)
        expect(changed != before["yaml"], "no kitchen in the YAML to rename")
        reply = await api.ws(instance.token, {"type": "ble_floorplan/set_layout", "yaml": changed})
        expect(reply["success"], str(reply))
        try:
            await page.wait_for_timeout(500)
            expect("Kitchenette" not in await textarea.input_value(), "the YAML came by itself")
            await page.evaluate("window.__noReload = true")
            panel = page.locator(PANEL)
            await panel.evaluate(
                """el => {
                  const b = el.shadowRoot.getElementById('refresh');
                  window.__spun = false;
                  new MutationObserver(() => {
                    if (b.classList.contains('loading')) window.__spun = true;
                  }).observe(b, { attributes: true });
                }"""
            )
            stamp = page.locator(f"{PANEL} #stamp")
            # The stamp shows seconds: one later, a new stamp has to differ
            await page.wait_for_timeout(1100)
            await page.locator(f"{PANEL} ha-icon-button#refresh").click()
            await _until(lambda: _has(textarea, "Kitchenette"), "the new YAML after Refresh")
            expect(await page.evaluate("window.__spun === true"), "the button did not spin")
            await _until(
                lambda: _not_loading(page), "the refresh button to stop spinning", seconds=10
            )
            after = (await stamp.inner_text()).strip()
            expect(bool(STAMP.match(after)), f"stamp after refresh: {after!r}")
            now = datetime.now(TIME_ZONE)
            shown = datetime.strptime(after.removeprefix("As of "), "%H:%M:%S").time()
            gap = (now.hour * 3600 + now.minute * 60 + now.second) - (
                shown.hour * 3600 + shown.minute * 60 + shown.second
            )
            expect(0 <= gap % 86400 <= 5, f"stamp {after} is not the time of the refresh")
            expect(await page.evaluate("window.__noReload === true"), "Refresh reloaded the page")
        finally:
            await api.ws(
                instance.token, {"type": "ble_floorplan/set_layout", "yaml": before["yaml"]}
            )

    await checks.run(
        "Refresh fetches the data again over the WebSocket, spins, sets the stamp",
        refresh_fetches_again,
    )

    async def cog_opens_integration_page() -> None:
        await _goto(page, instance, "devices/trackers")
        await page.evaluate("window.__noReload = true")
        await page.locator(f"{PANEL} ha-icon-button#integration").click()
        await page.wait_for_url(f"**{INTEGRATION_PAGE}")
        await page.locator("ha-config-integration-page").wait_for(timeout=30000)
        expect(
            await page.evaluate("window.__noReload === true"),
            "the cog loaded the whole page instead of navigating in the app",
        )
        await page.go_back()
        await page.locator(f"{PANEL} .item[data-key='tag']").wait_for()

    await checks.run(
        "the cog opens Home Assistant's page of the integration in the app",
        cog_opens_integration_page,
    )

    async def trackers_where_they_are() -> None:
        await _goto(page, instance, "devices/trackers")

        async def placed() -> bool:
            text = await page.locator(f"{PANEL} ha-card.list").first.inner_text()
            return "Living room" in text and "Kitchen" in text and "not seen" in text

        await _until(placed, "the key tag in the living room, the phone in the kitchen")

    await checks.run("the trackers are where the scanners hear them", trackers_where_they_are)

    async def tracker_subpage() -> None:
        await _goto(page, instance, "devices/trackers")
        await page.locator(f"{PANEL} .item[data-key='tag']").click()
        await page.locator(f"{PANEL} ha-icon-button-arrow-prev").wait_for()
        await _frame(page, sub=True)
        expect(await _subname(page) == "Key tag", await _subname(page))
        await _header(page)
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "tracker.png"))
        await page.locator(f"{PANEL} ha-icon-button-arrow-prev").click()
        await page.locator(f"{PANEL} .item[data-key='tag']").wait_for()
        await _frame(page, sub=False, page_id="trackers")

    await checks.run("a tracker opens as a subpage with a back arrow", tracker_subpage)

    async def edit_tracker() -> None:
        await _goto(page, instance, "devices/trackers")
        await page.locator(f"{PANEL} .item[data-key='phone']").click()
        await page.locator(f"{PANEL} ha-button[data-act='edit-tracker']").click()
        await page.get_by_role("textbox", name="Name").fill("Work phone")
        height = page.get_by_role("textbox", name="Height")
        await height.fill("1.4")
        await page.locator(f"{PANEL} ha-button[data-act='save-tracker']").click()

        async def saved() -> bool:
            plan = await _plan(api, instance)
            phone = next(t for t in plan["trackers"] if t["key"] == "phone")
            return bool(phone["height"] == 1.4 and phone["name"] == "Work phone")

        await _until(saved, "the new name and height in the integration")
        await page.locator(f"{PANEL} ha-alert[alert-type='success']").wait_for()
        await _until(lambda: _named(page, "Work phone"), "the new name in the header")
        # Back to the name the other checks and the screenshots show
        reply = await api.ws(
            instance.token, {"type": "ble_floorplan/set_tracker", "key": "phone", "name": "Phone"}
        )
        expect(reply["success"], str(reply))

    await checks.run("editing a tracker in ha-form reaches the integration", edit_tracker)

    async def remove_asks_first() -> None:
        await _goto(page, instance, "devices/scanners")
        await page.locator(f"{PANEL} .item[data-key='hall']").click()
        await page.locator(f"{PANEL} ha-icon-button-arrow-prev").wait_for()
        await _header(page)
        await _frame(page, sub=True)
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "scanner.png"))
        await page.locator(f"{PANEL} ha-button[data-act='remove-scanner']").click()
        alert = page.locator(f"{PANEL} ha-alert[alert-type='warning']", has_text="Hall plug")
        await alert.wait_for()
        await page.locator(f"{PANEL} ha-button[data-act='confirm-cancel']").click()
        await alert.wait_for(state="detached")
        plan = await _plan(api, instance)
        expect(any(s["key"] == "hall" for s in plan["scanners"]), "cancel removed the scanner")

    await checks.run("removing a scanner asks first, Cancel keeps it", remove_asks_first)

    async def system_details() -> None:
        # A page of the scanner of its own, as a tab beside its overview and its quality
        await _goto(page, instance, "devices/scanners")
        await page.locator(f"{PANEL} .item[data-key='living']").click()
        await page.locator(f"{PANEL} #views ha-tab-group-tab[panel='system']").click()
        await page.wait_for_url("**view=system")
        sheet = page.locator(f"{PANEL} #sheet")

        async def told() -> bool:
            return "Last received" in await sheet.inner_text()

        await _until(told, "the system details of the scanner")
        text = await sheet.inner_text()
        for label in ("Devices in range", "Connection slots"):
            expect(label in text, text)
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "scanner-system.png"))
        await page.locator(f"{PANEL} #views ha-tab-group-tab[panel='overview']").click()
        await page.locator(f"{PANEL} ha-button[data-act='edit-scanner']").wait_for()
        # An address that changes only its query, as a link within the app: the page follows
        await page.evaluate(
            """() => {
              history.pushState(null, "", "/ble-floorplan/devices/scanners?key=hall&view=quality");
              window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
            }"""
        )
        await _until(lambda: _named(page, "Hall plug"), "the hall plug's page from the query")
        await page.locator(f"{PANEL} #views ha-tab-group-tab[panel='quality'][active]").wait_for()
        await page.locator(f"{PANEL} #sheet .qoverall").wait_for()

    await checks.run(
        "the system details are a page of the scanner; a query alone switches the page",
        system_details,
    )

    async def pause_and_resume() -> None:
        # A paused scanner and tracker: grey with "paused", left out until resumed
        await _goto(page, instance, "devices/scanners")
        await page.locator(f"{PANEL} .item[data-key='hall']").click()
        await page.locator(f"{PANEL} ha-button[data-act='pause-scanner']").click()
        await page.locator(f"{PANEL} ha-alert[alert-type='info']", has_text="Paused").wait_for()
        await page.locator(f"{PANEL} svg g.scanner.paused[data-key='hall']").wait_for()
        plan = await _plan(api, instance)
        expect(
            next(s for s in plan["scanners"] if s["key"] == "hall").get("paused") is True,
            "scanner paused",
        )
        await page.locator(f"{PANEL} ha-icon-button-arrow-prev").click()
        item = page.locator(f"{PANEL} .item[data-key='hall']")
        await item.locator(".icon-bg.paused").wait_for()
        expect("paused" in await item.inner_text(), await item.inner_text())
        await item.click()
        await page.locator(f"{PANEL} ha-button[data-act='resume-scanner']").click()
        await page.locator(f"{PANEL} svg g.scanner.paused").wait_for(state="detached")

        await _goto(page, instance, "devices/trackers")
        await page.locator(f"{PANEL} .item[data-key='tag']").click()
        await page.locator(f"{PANEL} ha-button[data-act='pause-tracker']").click()
        await page.locator(f"{PANEL} ha-alert[alert-type='info']", has_text="Paused").wait_for()
        await page.locator(f"{PANEL} svg g.tracker[data-key='tag']").wait_for(state="detached")
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "tracker-paused.png"))
        await page.locator(f"{PANEL} ha-button[data-act='resume-tracker']").click()
        await page.locator(f"{PANEL} svg g.tracker[data-key='tag']").wait_for()
        plan = await _plan(api, instance)
        expect(all(not x.get("paused") for x in plan["scanners"] + plan["trackers"]), str(plan))

    await checks.run("a scanner and a tracker are paused and resumed", pause_and_resume)

    async def silent_scanner() -> None:
        # A scanner Home Assistant does not have: silent, as one without power
        plan = await _plan(api, instance)
        attic = {**SCANNERS[3], "key": "attic", "name": "Attic plug", "source": "AA:BB:CC:DD:EE:05"}
        attic["x"], attic["y"] = 5.0, 7.0
        changed = {**plan, "scanners": [*plan["scanners"], attic]}
        reply = await api.ws(
            instance.token, {"type": "ble_floorplan/set_floorplan", "floorplan": changed}
        )
        expect(reply["success"], str(reply))
        try:
            await _goto(page, instance, "devices/scanners")
            item = page.locator(f"{PANEL} .item[data-key='attic']")
            await item.locator(".icon-bg.offline").wait_for()
            expect("not reachable" in await item.inner_text(), await item.inner_text())
            living = page.locator(f"{PANEL} .item[data-key='living']")
            expect(
                await living.locator(".icon-bg.offline").count() == 0, "a hearing scanner is marked"
            )
            await page.locator(f"{PANEL} svg g.scanner.offline[data-key='attic']").wait_for()
            await item.click()
            # One line on the page, the why behind its (i)
            alert = page.locator(
                f"{PANEL} ha-alert[alert-type='warning']", has_text="Not reachable"
            )
            await alert.wait_for()
            why = await alert.locator("ha-tooltip").evaluate("el => el.textContent")
            expect("nothing for over a minute" in why, why)
        finally:
            reply = await api.ws(
                instance.token, {"type": "ble_floorplan/set_floorplan", "floorplan": plan}
            )
            expect(reply["success"], str(reply))

    await checks.run(
        "a silent scanner is marked in the list, on the plan and on its page", silent_scanner
    )

    async def settings_saved() -> None:
        await _goto(page, instance, "setup/location")
        smoothing = page.get_by_role("textbox", name="Smoothing")
        await smoothing.wait_for()
        rows = page.locator(f"{PANEL} ha-settings-row")
        helps = page.locator(f"{PANEL} ha-settings-row ha-icon-button.help")
        expect(await rows.count() == await helps.count() > 10, "a settings row without its (i)")
        expect(
            await page.locator(f"{PANEL} ha-button#save").is_hidden(),
            "a save button with nothing changed",
        )
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "settings.png"))
        # The (i) beside a setting: a tap shows its explanation in Home Assistant's tooltip
        row = page.locator(f"{PANEL} ha-settings-row", has_text="Smoothing")
        await row.locator("ha-icon-button.help").click()
        tip = row.locator("ha-tooltip")
        await _until(lambda: tip.evaluate("el => el.open === true"), "the explanation of smoothing")
        expect("time constant" in await tip.evaluate("el => el.textContent"), "wrong explanation")
        await smoothing.fill("15")
        await page.locator(f"{PANEL} ha-button#save:not([hidden])").click()

        async def saved() -> bool:
            plan = await _plan(api, instance)
            return bool(plan["settings"]["smoothing_seconds"] == 15)

        await _until(saved, "the new smoothing in the integration")
        await page.locator(f"{PANEL} ha-button#save").wait_for(state="hidden")

    await checks.run(
        "a setting: a row with its (i), one save button while changed, reaches the integration",
        settings_saved,
    )

    async def calibration_runs() -> None:
        await _goto(page, instance, "calibration/runs")
        rows = page.locator(f"{PANEL} table.runs tr")
        await rows.nth(3).wait_for()
        expect(await rows.count() == 4, f"{await rows.count() - 1} runs listed")
        # The date, and what changed in the scanner setup since a run
        expect("Date" in await rows.nth(0).inner_text(), await rows.nth(0).inner_text())
        changed = page.locator(f"{PANEL} table.runs .setup.changed")
        expect(await changed.count() == 1, f"{await changed.count()} runs marked changed")
        text = await changed.inner_text()
        expect("Kitchen plug moved" in text and "Hall plug new" in text, text)
        expect(
            await page.locator(f"{PANEL} table.runs .setup:not(.changed)").count() == 1,
            "one run of unknown setup",
        )
        await page.locator(
            f"{PANEL} ha-alert[alert-type='warning']", has_text="another scanner setup"
        ).wait_for()
        await page.locator(
            f"{PANEL} ha-alert[alert-type='info']", has_text="unknown setup"
        ).wait_for()
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "calibration.png"))

    await checks.run("the calibration runs are listed", calibration_runs)

    async def calibration_guide() -> None:
        await _goto(page, instance, "calibration/measure")
        guide = page.locator(f"{PANEL} table.guide")
        await guide.wait_for()
        # The key tag: a run in the living room and one of unknown setup in the bedroom;
        # the one in the hall was made with the scanners standing elsewhere
        rows = guide.locator("tr")
        living = await rows.nth(1).inner_text()
        expect(living.split()[:3] == ["Living", "room", "1"], living)
        hall = guide.locator("tr", has_text="Hall").locator("td").nth(1)
        expect(await hall.get_attribute("class") == "n missing", "the hall not marked missing")
        expect("2 of 5 rooms" in await rows.last.inner_text(), await rows.last.inner_text())

    await checks.run(
        "the guide shows per room and tracker where runs are missing", calibration_guide
    )

    async def guided_run() -> None:
        await _goto(page, instance, "calibration/measure")
        await page.locator(
            f"{PANEL} ha-assist-chip[data-act='cal-height'][data-key='0.75']"
        ).click()
        box = await page.locator(f"{PANEL} #svg svg").bounding_box()
        assert box is not None
        await page.mouse.click(box["x"] + box["width"] * 0.3, box["y"] + box["height"] * 0.3)
        await page.locator(f"{PANEL} ha-button[data-act='cal-start']:not([disabled])").click()
        # Each scanner gets a bar; with the made-up steady signals they fill quickly
        await page.locator(f"{PANEL} table.progress tr.prog").first.wait_for()
        await page.locator(f"{PANEL} table.progress tr.prog.done").first.wait_for(timeout=30000)
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "calibration-run.png"))
        # It ends by itself after the shortest time and says what it saved
        await page.locator(
            f"{PANEL} ha-alert[alert-type='success']", has_text="ended by itself"
        ).wait_for(timeout=90000)
        reply = await api.ws(instance.token, {"type": "ble_floorplan/calibration/list"})
        result = reply["result"]
        run = result["runs"][-1]
        expect(result["active"] is None, "the run still going")
        expect(run["height"] == 0.75, f"height {run['height']}")
        expect(45 <= run["duration"] < 120, f"duration {run['duration']}")
        expect(result["stopped"]["auto"] is True, str(result.get("stopped")))
        await api.ws(
            instance.token, {"type": "ble_floorplan/calibration/delete", "run_id": run["id"]}
        )

    await checks.run("a guided run shows its progress and ends by itself", guided_run)

    async def clear_runs() -> None:
        # Delete all asks first; Cancel keeps the runs
        await _goto(page, instance, "calibration/runs")
        await page.locator(f"{PANEL} ha-button[data-act='cal-clear']").click()
        await page.locator(f"{PANEL} ha-button[data-act='cal-clear-cancel']").click()
        await page.locator(f"{PANEL} ha-button[data-act='cal-clear-cancel']").wait_for(
            state="detached"
        )
        reply = await api.ws(instance.token, {"type": "ble_floorplan/calibration/list"})
        expect(len(reply["result"]["runs"]) == 3, "cancel deleted runs")
        await page.locator(f"{PANEL} ha-button[data-act='cal-clear']").click()
        await page.locator(f"{PANEL} ha-button[data-act='cal-clear-ok']").click()
        await page.locator(f"{PANEL} table.runs").wait_for(state="detached")
        reply = await api.ws(instance.token, {"type": "ble_floorplan/calibration/list"})
        expect(reply["result"]["runs"] == [], str(reply["result"]))

    await checks.run("all calibration runs are deleted after a confirmation", clear_runs)

    async def timeline() -> None:
        await _goto(page, instance, "live/history")
        await page.locator(f"{PANEL} .tlbar").first.wait_for()
        # Dragging the axis up goes back in time: the trackers where they were, with their trails
        axis = page.locator(f"{PANEL} #tlaxis")
        box = await axis.bounding_box()
        assert box is not None
        x = box["x"] + box["width"] / 2
        await page.mouse.move(x, box["y"] + box["height"] - 20)
        await page.mouse.down()
        await page.mouse.move(x, box["y"] + 40, steps=10)
        await page.mouse.up()
        await page.locator(f"{PANEL} #svg .trail").first.wait_for(state="attached")
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "timeline.png"))

    await checks.run("the timeline plays back the made-up tracks", timeline)

    async def coverage() -> None:
        await _goto(page, instance, "analysis/coverage")
        cells = page.locator(f"{PANEL} #svg rect.cov")
        await cells.first.wait_for(state="attached")
        expect(await cells.count() > 100, f"{await cells.count()} model cells drawn")
        rooms = page.locator(f"{PANEL} ha-card table.data tr")
        await rows_at_least(rooms, 5)
        # A tap on the plan places a probe scanner; the model is fetched with it
        box = await page.locator(f"{PANEL} #svg svg").bounding_box()
        assert box is not None
        await page.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
        await page.locator(f"{PANEL} #svg g.probe").first.wait_for(state="attached")
        await _until(
            lambda: _count_at_least(
                page.locator(f"{PANEL} ha-card table.data td:has-text('P1')"), 1
            ),
            "the probe scanner in its list",
        )
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "coverage.png"))
        # The measurement: the made-up trackers stayed long enough in their cells
        await page.locator(f"{PANEL} ha-form").get_by_text("Measured", exact=True).click()
        try:
            await _until(
                lambda: _count_at_least(page.locator(f"{PANEL} #svg rect.cov"), 1),
                "measured cells",
                seconds=90,
            )
        except AssertionError as err:
            state = await page.locator(PANEL).evaluate(
                "el => JSON.stringify({mode: el._cov.mode, key: el._cov.key,"
                " data: el._cov.data && {mode: el._cov.data.mode, cells: el._cov.data.cells,"
                " days: el._cov.data.days, recording: el._cov.data.recording}})"
            )
            raise AssertionError(f"{err}: {state}") from err
        expect(
            await page.locator(f"{PANEL} #svg g.probe").count() == 0,
            "probe scanners drawn on the measurement",
        )

    await checks.run("the coverage: model, probe scanner, measurement", coverage)

    async def coverage_change() -> None:
        # Calibration values changed after days were measured: the days before are named
        plan = await _plan(api, instance)
        kitchen = next(sc for sc in plan["scanners"] if sc["key"] == "kitchen")
        reply = await api.ws(
            instance.token,
            {
                "type": "ble_floorplan/set_scanner",
                "key": "kitchen",
                "rssi_offset": kitchen["rssi_offset"] + 2,
            },
        )
        expect(reply["success"], str(reply))
        try:
            stale = page.locator(f"{PANEL} ha-alert.covstale")

            async def noted() -> bool:
                measured = await api.ws(instance.token, {"type": "ble_floorplan/coverage/measured"})
                change = measured["result"]["change"]
                return change is not None and change["reason"] == "calibration"

            # Noted with the next computation, within a second or two
            await _until(noted, "the change in the measurement", seconds=10)

            async def shown() -> bool:
                return await stale.count() == 1

            # The page fetches the measurement again every minute
            await _until(shown, "the hint on the days before the change", seconds=90)
            why = await stale.locator("ha-tooltip").evaluate("el => el.textContent")
            expect("calibration values changed" in why, why)
            await stale.locator("ha-button[data-act='cov-reset']").click()
            await page.locator(f"{PANEL} ha-button[data-act='cov-reset-cancel']").click()
        finally:
            reply = await api.ws(
                instance.token,
                {
                    "type": "ble_floorplan/set_scanner",
                    "key": "kitchen",
                    "rssi_offset": kitchen["rssi_offset"],
                },
            )
            expect(reply["success"], str(reply))

    await checks.run("a calibration change names the measured days before it", coverage_change)

    async def plan_card() -> None:
        card_page = await _open(browser, instance, ADMIN, f"/{DASHBOARD}/plan")
        card = card_page.locator(CARD)
        await card.locator(".tracker").first.wait_for(timeout=90000)
        await card_page.locator("#ha-launch-screen").wait_for(state="detached")
        # The level switch and the zoom change the view only
        expect(
            await card.locator("[data-act], input, select").count() == 0,
            "the plan card has something to change",
        )
        # Scanners are drawn only where the card is told to
        expect(await card.locator(".scanner").count() == 0, "scanners on the plan card")
        if shots is not None:
            await _settle(card_page)
            await _shot(card_page, card.locator("ha-card"), shots / "card-plan.png")
        # An administrator sees the readings of a tapped tracker
        await card.locator(".tracker[data-key='tag']").click()
        await card.locator(".info table tr").first.wait_for()
        expect("dBm" in await card.locator(".info").inner_text(), "no readings for an admin")
        await card_page.context.close()

    await checks.run("the plan card shows the trackers live and nothing to change", plan_card)

    async def card_for_every_user() -> None:
        # A user without administrator rights. Texts inside the card are read
        # through locators: inner_text() of an element outside does not reach
        # into a shadow root.
        visitor = await _open(browser, instance, USER, f"/{DASHBOARD}/plain")
        try:
            cards = visitor.locator(CARD)
            await cards.first.locator(".head").wait_for(timeout=90000)
            await visitor.locator("#ha-launch-screen").wait_for(state="detached")
            expect(
                await cards.first.locator("button, ha-button, input, select").count() == 0,
                "the card has something to change",
            )
            await _until(
                lambda: _says(cards.first.locator(".row").first, "Living room"),
                "the key tag in the living room",
            )
            text = await cards.first.locator(".content").inner_text()
            expect("Key tag" in text and "home" in text, f"the overview lacks its parts: {text}")
            expect("dBm" not in text and "proxy" not in text, f"readings or scanners: {text}")
            # The card picker knows the card, and its editor has a text for every field
            offered = await visitor.evaluate(
                f"""() => {{
                  const form = customElements.get('{CARD}').getConfigForm();
                  const names = (schema) => schema.flatMap((f) => f.schema ? names(f.schema) : [f.name]);
                  return {{
                    picker: (window.customCards || []).filter((c) => c.type === '{CARD}').length,
                    fields: names(form.schema),
                    labels: names(form.schema).map((name) => form.computeLabel({{ name }})),
                  }};
                }}"""
            )
            expect(offered["picker"] == 1, "the card is not in the card picker once")
            expect(
                not set(offered["fields"]) & set(offered["labels"]),
                f"an editor field without its text: {offered['labels']}",
            )
            # What does not fit is left out: one row, three rows, six rows; no rows; half as wide
            await visitor.goto(f"{instance.base}/{DASHBOARD}/sizes")
            cards = visitor.locator(CARD)
            await cards.nth(2).locator(".head").wait_for()
            await _until(
                lambda: _says(cards.nth(2).locator(".row").first, "Living room"),
                "the key tag in the living room on the large card",
            )
            expect(
                await cards.nth(0).locator(".small").count() == 1, "one row is not the small card"
            )
            expect(
                await cards.nth(1).locator(".row.slim").count() >= 1,
                "three rows are not the medium card",
            )
            expect(
                await cards.nth(2).locator(".row:not(.slim)").count() >= 1,
                "six rows are not the large card",
            )
            for index in range(3):
                fits = (
                    await cards.nth(index)
                    .locator("ha-card")
                    .evaluate(
                        "el => el.querySelector('.content').getBoundingClientRect().bottom"
                        " <= el.getBoundingClientRect().bottom + 1"
                    )
                )
                expect(fits, "a card that cuts off what it shows")
            spare = await cards.nth(3).evaluate(
                "el => { const card = el.shadowRoot.querySelector('ha-card');"
                " const style = getComputedStyle(card);"
                " return card.clientHeight - parseFloat(style.paddingTop)"
                " - parseFloat(style.paddingBottom)"
                " - card.querySelector('.content').scrollHeight; }"
            )
            expect(abs(spare) <= 2, f"a card without rows is {spare} px off its content")
            expect(
                await _fits(cards.nth(4).locator(".small .sub")), "a second line that is cut off"
            )
            # A problem cannot be waited for: a card made in the page gets a changed
            # copy of the user's hass, with the problem sensor on
            told = await visitor.evaluate(
                f"""() => {{
                  const real = document.querySelector('home-assistant').hass;
                  const entry = Object.values(real.entities).find(
                    (e) => e.platform === 'ble_floorplan' && e.translation_key === 'unreachable');
                  const state = {{ ...real.states[entry.entity_id], state: 'on',
                    attributes: {{ scanners: ['Hall plug', 'Kitchen plug'] }} }};
                  const hass = {{ ...real, states: {{ ...real.states, [entry.entity_id]: state }} }};
                  const texts = [];
                  for (const config of [{{}}, {{ show_problem: true }}]) {{
                    const card = document.createElement('{CARD}');
                    card.setConfig(config);
                    document.body.appendChild(card);
                    card.hass = hass;
                    texts.push(card.shadowRoot.querySelector('.problem')?.textContent ?? null);
                    card.remove();
                  }}
                  return texts;
                }}"""
            )
            expect(told == [None, "2 scanners unreachable"], f"the problem line: {told}")
            if shots is not None:
                await _settle(visitor)
                await _shot(visitor, visitor.locator("hui-grid-section").first, shots / "card.png")
            # The live plan for this user: the trackers, a level's rooms, no scanners
            # unless the card asks for them, and of a tapped tracker the name and the room
            await visitor.goto(f"{instance.base}/{DASHBOARD}/plan-rows")
            cards = visitor.locator(CARD)
            await cards.nth(1).locator(".tracker").first.wait_for(timeout=30000)
            expect(await cards.nth(0).locator(".scanner").count() == 0, "scanners without asking")
            expect(await cards.nth(1).locator(".scanner").count() >= 3, "no scanners when asked")
            inside = await cards.nth(0).evaluate(
                "el => { const card = el.shadowRoot.querySelector('ha-card').getBoundingClientRect();"
                " const svg = el.shadowRoot.querySelector('.map svg').getBoundingClientRect();"
                " return svg.height > 100 && svg.bottom <= card.bottom + 1; }"
            )
            expect(inside, "the plan does not fit the rows the card got")
            await cards.nth(0).locator(".tracker[data-key='tag']").click()
            await cards.nth(0).locator(".info").wait_for()
            info = await cards.nth(0).locator(".info").inner_text()
            expect("Key tag" in info and "Living room" in info, f"name and room: {info}")
            expect("dBm" not in info and " m" not in info, f"readings for a user: {info}")
        finally:
            await visitor.context.close()

    await checks.run(
        "the card shows every user the basics, in the size its space allows, nothing to change",
        card_for_every_user,
    )

    async def phone_and_dark() -> None:
        for scheme in ("light", "dark"):
            phone = await _open(
                browser,
                instance,
                ADMIN,
                "/ble-floorplan/devices/trackers",
                viewport={"width": 390, "height": 844},
                color_scheme=scheme,
            )
            await _goto(phone, instance, "devices/trackers")
            # The areas are Home Assistant's bar at the bottom
            await _frame(phone, sub=False, page_id="trackers")
            bottom = await phone.locator(PANEL).evaluate(
                "el => !!el.shadowRoot.getElementById('frame').shadowRoot.querySelector('#tabbar.bottom-bar')"
            )
            expect(bottom, f"{scheme}: the areas are not at the bottom")
            # On a phone the stamp makes room; refresh and settings stay
            await phone.locator(f"{PANEL} ha-icon-button#refresh").wait_for()
            await phone.locator(f"{PANEL} ha-icon-button#integration").wait_for()
            expect(
                not await phone.locator(f"{PANEL} #stamp").is_visible(),
                f"{scheme}: the stamp shows at phone width",
            )
            overflow = await phone.evaluate(
                "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            expect(overflow <= 0, f"{scheme}: page scrolls sideways by {overflow} px")
            background = await phone.locator(PANEL).evaluate(
                "el => getComputedStyle(el).backgroundColor"
            )
            if scheme == "dark":
                channels = [
                    int(part) for part in background[background.index("(") + 1 : -1].split(",")[:3]
                ]
                expect(sum(channels) < 200, f"dark mode background is {background}")
                if shots is not None:
                    await _settle(phone)
                    await phone.screenshot(path=str(shots / "phone-dark.png"))
            await phone.context.close()

    await checks.run(
        "phone width and dark mode: tabs at the bottom, no sideways scrolling", phone_and_dark
    )

    async def iphone_safe_area() -> None:
        # An iPhone's safe area, set the way Home Assistant's own debug setting sets it; the frame
        # pads itself, so it fills the screen like Home Assistant's own pages
        phone = await _open(
            browser,
            instance,
            ADMIN,
            "/ble-floorplan/live/now",
            viewport={"width": 390, "height": 844},
            color_scheme="dark",
        )
        measured = {}
        for name, path in (
            ("BLE Floorplan", "/ble-floorplan/live/now"),
            ("Automations", "/config/automation/dashboard"),
        ):
            await phone.goto(f"{instance.base}{path}")
            await phone.wait_for_load_state("networkidle")
            await phone.locator("#ha-launch-screen").wait_for(state="detached")
            await phone.evaluate(SAFE_AREA)
            await phone.wait_for_timeout(800)
            measured[name] = box = await phone.evaluate(SAFE_AREA_MEASURE)
            expect(isinstance(box, dict), f"{name}: {box}")
            height = box["viewport"]
            expect(box["frame"] == [0, height], f"{name}: frame {box['frame']} in {height}")
            expect(box["toolbar"] == 56 + 47, f"{name}: header {box['toolbar']} high")
            expect(
                box["tabbar"] is not None and box["tabbar"][1] == height,
                f"{name}: bar at the bottom {box['tabbar']} in {height}",
            )
            expect(box["tabbar"][0] >= 0, f"{name}: bar at the bottom {box['tabbar']}")
        expect(
            measured["BLE Floorplan"] == measured["Automations"],
            f"unlike Home Assistant's page: {measured}",
        )
        await phone.context.close()

    await checks.run(
        "iPhone safe area: header and bottom bar as on Home Assistant's own pages", iphone_safe_area
    )

    async def ignored_suggestions() -> None:
        # Off the plan, the hall plug is a suggestion; ignored, the card goes and the list folds it below
        before = await _plan(api, instance)
        reply = await api.ws(
            instance.token, {"type": "ble_floorplan/remove_scanner", "key": "hall"}
        )
        expect(reply["success"], str(reply))
        await _goto(page, instance, "devices/scanners")
        card = page.locator(f"{PANEL} ha-card", has_text="Add scanner")
        await card.wait_for()
        await card.locator("ha-button[data-act='ignore']").click()
        await card.wait_for(state="detached")
        ignored = page.locator(f"{PANEL} ha-expansion-panel.ignored")
        await ignored.wait_for()
        expect("Ignored suggestions" in (await ignored.get_attribute("header") or ""), "header")
        await ignored.locator("#summary").click()
        await page.locator(f"{PANEL} ha-expansion-panel.ignored[expanded]").wait_for()
        expect("Hall" in await ignored.inner_text(), await ignored.inner_text())
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "ignored.png"))
        await ignored.locator("ha-button[data-act='unignore']").click()
        await ignored.wait_for(state="detached")
        await page.locator(f"{PANEL} ha-card", has_text="Add scanner").wait_for()
        reply = await api.ws(
            instance.token, {"type": "ble_floorplan/set_floorplan", "floorplan": before}
        )
        expect(reply["success"], str(reply))

    await checks.run("suggestions are ignored and suggested again", ignored_suggestions)

    async def scanner_quality() -> None:
        # The made-up scanners hear steadily: after a little while the lights come up
        await _goto(page, instance, "devices/scanners")
        await _until(
            lambda: _count_at_least(page.locator(f"{PANEL} .item .qdot"), 1),
            "a quality light in the list",
            seconds=150,
        )
        await page.locator(f"{PANEL} .item[data-key='living']").click()
        # The buttons under the scanner: the right ones on one line, also where the sheet is narrow
        size = page.viewport_size
        await page.set_viewport_size({"width": 1000, "height": 900})
        tops = await page.locator(f"{PANEL} .card-actions ha-button").evaluate_all(
            "els => els.map(e => Math.round(e.getBoundingClientRect().top))"
        )
        right = tops[1:]
        expect(len(set(right)) == 1, f"buttons on {len(set(right))} lines: {tops}")
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "scanner-actions.png"))
        if size is not None:
            await page.set_viewport_size(size)
        # For the picture, enough misses for a finding: a few minutes of the made-up trackers
        if shots is not None:

            async def fidelity_known() -> bool:
                reply = await api.ws(
                    instance.token, {"type": "ble_floorplan/scanner_quality", "key": "living"}
                )
                return bool(reply["result"]["fidelity"]["state"] != "unknown")

            await _until(fidelity_known, "enough misses of the living room proxy", seconds=240)
        await page.locator(f"{PANEL} #views ha-tab-group-tab[panel='quality']").click()
        await page.wait_for_url("**view=quality")
        sheet = page.locator(f"{PANEL} #sheet")
        await sheet.locator(".qtile").nth(2).wait_for()
        expect(await sheet.locator(".qtile").count() == 3, "three tiles")
        text = await sheet.inner_text()
        expect("Reception" in text and "Fidelity" in text and "Contribution" in text, text)
        await sheet.locator("ha-alert").first.wait_for()
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "scanner-quality.png"))
        # The same state as in the list: good only so far while a figure lacks data
        reply = await api.ws(instance.token, {"type": "ble_floorplan/scanner_quality"})
        summary = reply["result"]["living"]
        overall = await sheet.locator(".qoverall .qdot").get_attribute("class")
        if (
            "unknown" in (summary["rate"]["state"], summary["fidelity"]["state"])
            and summary["state"] == "good"
        ):
            expect("prelim" in (overall or ""), f"quality {overall} while a figure lacks data")

    await checks.run(
        "the quality of a scanner: lights in the list, its page with three tiles and findings",
        scanner_quality,
    )

    async def quality_overview() -> None:
        # Analysis: every active scanner in one table; a row opens its quality page
        await _goto(page, instance, "analysis/quality")
        rows = page.locator(f"{PANEL} table.qlist tr[data-act='go']")
        await rows_at_least(rows, 4)
        await rows.first.click()
        await page.wait_for_url("**/devices/scanners?key=*view=quality")
        await page.locator(f"{PANEL} .qtile").first.wait_for()

    await checks.run("the quality of every scanner in one table", quality_overview)

    async def setup_and_notices() -> None:
        # Setup: five steps, the first open one is where Continue leads
        await _goto(page, instance, "setup/overview")
        steps = page.locator(f"{PANEL} ha-card .item[data-act='go']")
        await rows_at_least(steps, 5)
        expect(await steps.count() == 5, f"{await steps.count()} steps")
        done = await page.locator(f"{PANEL} .icon-bg.step.done").count()
        expect(done >= 3, f"{done} steps done in the made-up flat")
        nxt = page.locator(f"{PANEL} ha-button[data-act='go']", has_text="Continue")
        target = await nxt.get_attribute("data-key")
        await nxt.click()
        await page.wait_for_url(f"**/ble-floorplan/{target}")
        # Live: a scanner that hears nothing is a notice that leads to it; the trackers follow
        plan = await _plan(api, instance)
        attic = {**SCANNERS[3], "key": "attic", "name": "Attic plug", "source": "AA:BB:CC:DD:EE:05"}
        changed = {**plan, "scanners": [*plan["scanners"], attic]}
        reply = await api.ws(
            instance.token, {"type": "ble_floorplan/set_floorplan", "floorplan": changed}
        )
        expect(reply["success"], str(reply))
        try:
            await _goto(page, instance, "live/now")
            notice = page.locator(f"{PANEL} ha-card", has_text="Notices")
            await notice.locator(".item", has_text="Attic plug is not reachable").wait_for(
                timeout=90000
            )
            await page.locator(f"{PANEL} .item[data-key='devices/trackers?key=tag']").wait_for()
            await notice.locator(".item", has_text="Attic plug").click()
            await page.wait_for_url("**/devices/scanners?key=attic")
        finally:
            reply = await api.ws(
                instance.token, {"type": "ble_floorplan/set_floorplan", "floorplan": plan}
            )
            expect(reply["success"], str(reply))

            # A whole plan reloads the integration: the next check waits for it to answer again
            async def loaded() -> bool:
                again = await api.ws(instance.token, {"type": "ble_floorplan/get_floorplan"})
                return bool(again["success"])

            await _until(loaded, "the integration loaded again")

    await checks.run("the setup in five steps and the notices on Live", setup_and_notices)

    async def arrow_keys_place() -> None:
        # Without a mouse: the plan takes the focus, the arrow keys move the point of a run
        await _goto(page, instance, "calibration/measure")
        start = page.locator(f"{PANEL} ha-button[data-act='cal-start']")
        expect(
            await start.get_attribute("disabled") is not None, "a run could start without a place"
        )
        await page.locator(f"{PANEL} #map").focus()
        await page.keyboard.press("Shift+ArrowRight")
        await page.keyboard.press("ArrowDown")
        await page.locator(f"{PANEL} ha-button[data-act='cal-start']:not([disabled])").wait_for()
        await page.locator(f"{PANEL} #svg g.truepos").wait_for(state="attached")
        # On the coverage they move a cross, Enter places a test scanner there
        await _goto(page, instance, "analysis/coverage")
        await page.locator(f"{PANEL} #map").focus()
        await page.keyboard.press("Shift+ArrowLeft")
        await page.keyboard.press("Enter")
        await page.locator(f"{PANEL} #svg g.probe").first.wait_for(state="attached")

    await checks.run("the arrow keys place a point on the plan", arrow_keys_place)

    async def numbers_in_the_language() -> None:
        # A German page writes 0,25 in the fields as elsewhere, and takes a comma back
        await page.evaluate("localStorage.setItem('selectedLanguage', JSON.stringify('de'))")
        try:
            await _goto(page, instance, "setup/location")
            dead = page.get_by_role("textbox", name="Totzone")
            await dead.wait_for()
            expect(await dead.input_value() == "0,25", await dead.input_value())
            await dead.fill("0,3")
            await page.locator(f"{PANEL} ha-button#save:not([hidden])").click()

            async def saved() -> bool:
                plan = await _plan(api, instance)
                return bool(plan["settings"]["min_move"] == 0.3)

            await _until(saved, "0,3 saved as 0.3")
        finally:
            await page.evaluate("localStorage.setItem('selectedLanguage', JSON.stringify('en'))")
            reply = await api.ws(instance.token, {"type": "ble_floorplan/get_floorplan"})
            settings = {**reply["result"]["floorplan"]["settings"], "min_move": 0.25}
            await api.ws(
                instance.token, {"type": "ble_floorplan/set_settings", "settings": settings}
            )
            await page.reload()

    await checks.run(
        "numbers in the fields as on the rest of the page, a comma typed back",
        numbers_in_the_language,
    )

    async def errors_read_alike() -> None:
        # A mistake in the YAML: one line by its kind, what Home Assistant said behind the (i)
        await _goto(page, instance, "setup/plan")
        await page.locator(f"{PANEL} ha-button[data-act='plan-mode'][data-key='yaml']").click()
        textarea = page.locator(f"{PANEL} textarea")
        await textarea.wait_for()
        await textarea.fill("rooms: [")
        await page.locator(f"{PANEL} ha-button[data-act='save-layout']").click()
        alert = page.locator(
            f"{PANEL} ha-alert[alert-type='error']", has_text="The input does not fit."
        )
        await alert.wait_for()
        said = await alert.locator("ha-tooltip").evaluate("el => el.textContent")
        expect(said.strip().startswith("Message:"), said)
        # Nothing was saved; a reload leaves the typed YAML behind
        plan = await _plan(api, instance)
        expect(len(plan["rooms"]) >= 5, "the broken YAML replaced the plan")
        await page.reload()

    await checks.run(
        "an error reads one line by its kind, the message behind its (i)", errors_read_alike
    )

    async def at(x: float, y: float) -> tuple[float, float]:
        """The point of the screen where the plan has x, y."""
        point = await page.locator(PANEL).evaluate(
            """(e, [x, y]) => {
                const g = e.shadowRoot.getElementById("plan");
                const pt = g.ownerSVGElement.createSVGPoint();
                pt.x = x; pt.y = y;
                const p = pt.matrixTransform(g.getScreenCTM());
                return [p.x, p.y];
            }""",
            [x, y],
        )
        return float(point[0]), float(point[1])

    async def drag(a: tuple[float, float], b: tuple[float, float]) -> None:
        start = await at(*a)
        end = await at(*b)
        await page.mouse.move(*start)
        await page.mouse.down()
        await page.mouse.move(*end, steps=8)
        await page.mouse.up()

    async def draft() -> dict[str, Any]:
        return dict(await page.locator(PANEL).evaluate("e => e._editor.draft"))

    async def drawing() -> None:
        before = await _plan(api, instance)
        layout = {k: before[k] for k in ("rooms", "openings") if k in before}
        await _goto(page, instance, "setup/plan")
        await page.locator(f"{PANEL} ha-button[data-act='plan-mode'][data-key='draw']").click()
        tool = f"{PANEL} ha-button[data-act='ed-tool']"
        # A room beside the flat, then a door in its left wall
        await page.locator(f"{tool}[data-key='rect']").click()
        await drag((11, 1), (14, 4))
        rooms = (await draft())["rooms"]
        expect(len(rooms) == len(before["rooms"]) + 1, f"{len(rooms)} rooms drawn")
        expect(rooms[-1]["x"] == 11 and rooms[-1]["w"] == 3, str(rooms[-1]))
        await page.locator(f"{PANEL} ha-card", has_text="Room").first.wait_for()
        await page.locator(f"{tool}[data-key='door']").click()
        click = await at(11.05, 2.5)
        await page.mouse.click(*click)
        openings = (await draft())["openings"]
        expect(len(openings) == len(before["openings"]) + 1, f"{len(openings)} openings")
        expect(
            abs(openings[-1][0] - 11) < 0.01 and abs(openings[-1][2] - 11) < 0.01, str(openings[-1])
        )
        # A garage as a building of its own, and a floor above the house
        await page.locator(f"{PANEL} ha-button[data-act='ed-add-building']").click()
        floors = (await draft())["floors"]
        expect([f["elevation"] for f in floors] == [0, 0], str(floors))
        await page.locator(f"{PANEL} tr[data-act='ed-floor'][data-key='0']").click()
        await page.locator(f"{PANEL} ha-button[data-act='ed-add-floor']").click()
        floors = (await draft())["floors"]
        expect(floors[-1]["elevation"] == 2.8, str(floors[-1]))
        await page.locator(f"{PANEL} .levels button", has_text=floors[-1]["name"]).wait_for()
        # On the upper floor: a room and stairs down
        await page.locator(f"{tool}[data-key='rect']").click()
        await drag((0, 0), (6, 5))
        await page.locator(f"{tool}[data-key='stairs']").click()
        await drag((4, 3), (5.5, 4.5))
        got = await draft()
        expect(got["rooms"][-1]["floor"] == floors[-1]["key"], str(got["rooms"][-1]))
        expect(len(got["stairs"]) == 1 and got["stairs"][0]["to"] == "eg", str(got["stairs"]))
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "editor.png"))
        await page.locator(f"{PANEL} ha-button[data-act='ed-save']").click()
        await page.locator(f"{PANEL} ha-button[data-act='ed-save'][disabled]").wait_for()
        saved = await _plan(api, instance)
        expect(len(saved["floors"]) == 3, str(saved.get("floors")))
        expect(saved["stairs"][0]["floor"] == floors[-1]["key"], str(saved.get("stairs")))
        expect(saved["openings"][-1][4] == "eg", str(saved["openings"][-1]))
        # Back to the flat as it was, for the checks after this one
        reply = await api.ws(instance.token, {"type": "ble_floorplan/set_layout", "layout": layout})
        expect(reply["success"], str(reply))

    await checks.run("the drawing: a room, a door, a building, a floor with stairs", drawing)

    async def users_get_what_the_card_draws() -> None:
        token = await api.login(*USER)
        panels = await api.ws(token, {"type": "get_panels"})
        expect("ble-floorplan" not in panels["result"], "the page is offered to a user")
        result = (await api.ws(token, {"type": "ble_floorplan/get_floorplan"}))["result"]
        plan = result["floorplan"]
        expect(all("source" not in s for s in plan["scanners"]), "scanner addresses for a user")
        expect(all("address" not in t for t in plan["trackers"]), "tracker addresses for a user")
        expect(
            all("readings" not in p for p in result["positions"].values()),
            "scanner readings for a user",
        )
        reply = await api.ws(token, {"type": "ble_floorplan/set_scanner", "key": "hall", "x": 1})
        expect(not reply["success"] and reply["error"]["code"] == "unauthorized", str(reply))

    await checks.run(
        "users without administrator rights get no page, no addresses, no changes",
        users_get_what_the_card_draws,
    )
    await page.context.close()
    return checks


# The pictures the README shows; the checks take more, for a look while developing
README_SHOTS = {
    "tracker.png",
    "editor.png",
    "calibration-run.png",
    "coverage.png",
    "scanner-quality.png",
    "card.png",
    "card-plan.png",
    "phone-dark.png",
}


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--screenshots", type=Path, help="write the README pictures into this directory"
    )
    parser.add_argument(
        "--all-screenshots",
        action="store_true",
        help="keep the pictures of every check, not only those of the README",
    )
    parser.add_argument("--keep", action="store_true", help="keep the temporary directory")
    parser.add_argument("--browser", choices=["chrome", "chromium"], default="chromium")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--only", help="run only the checks whose name contains this text")
    args = parser.parse_args()
    if args.screenshots is not None:
        args.screenshots.mkdir(parents=True, exist_ok=True)

    started = time.time()
    directory = Path(tempfile.mkdtemp(prefix="ble-floorplan-panel-"))
    instance = Instance(directory)
    checks = Checks()
    async with aiohttp.ClientSession() as session:
        try:
            api = await instance.start(session)
            print(f"Home Assistant on {instance.base}, files in {directory}")
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    channel="chrome" if args.browser == "chrome" else None,
                    headless=not args.headed,
                )
                try:
                    checks = await check_page(browser, instance, api, args.screenshots, args.only)
                finally:
                    await browser.close()
        except Exception as err:
            checks.failed.append(f"setup: {err!r}")
            print(f"FAIL setup: {err!r}")
            log = directory / "hass.log"
            if log.exists():
                print("".join(log.read_text(errors="replace").splitlines(keepends=True)[-60:]))
        finally:
            await instance.stop(session)
    errors = (
        [
            line
            for line in (directory / "config" / "home-assistant.log")
            .read_text(errors="replace")
            .splitlines()
            if " ERROR " in line and "ble_floorplan" in line
        ]
        if (directory / "config" / "home-assistant.log").exists()
        else []
    )
    for line in errors:
        checks.failed.append(f"log: {line}")
        print(f"FAIL log: {line}")
    if args.screenshots is not None and not args.all_screenshots:
        for path in args.screenshots.glob("*.png"):
            if path.name not in README_SHOTS and path.stat().st_mtime >= started:
                path.unlink()
    print(f"\n{len(checks.passed)} passed, {len(checks.failed)} failed")
    if args.keep or checks.failed:
        print(f"Files kept in {directory}")
    else:
        shutil.rmtree(directory, ignore_errors=True)
    return 1 if checks.failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
