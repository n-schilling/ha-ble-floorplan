"""Check the page and the card in a real browser against a throwaway Home Assistant.

Starts Home Assistant with a made-up flat in a temporary directory, reachable
from this machine only (see run_hass.py). Made-up scanners (demo_ble) hear
made-up trackers, so the plan shows them where they are. Playwright drives the
page and the card and checks what they show and what reaches the integration.
Home Assistant is stopped through its own stop action at the end, also after a
failure.

Usage (from the repository root, with the packages of requirements_panel.txt):

    python -I scripts/panel/check_panel.py [--screenshots DIR] [--keep]
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
STAMP = re.compile(r"^As of \d{2}:\d{2}:\d{2}$")

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
    """Two finished calibration runs of the key tag."""
    runs = []
    for i, (x, y) in enumerate([(2.0, 2.0), (8.0, 7.0)]):
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
        # A dashboard with the card
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
                        {
                            "title": "Plan",
                            "type": "panel",
                            "cards": [{"type": "custom:ble-floorplan-card", "title": "Home"}],
                        }
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

    async def run(self, name: str, check: Callable[[], Awaitable[None]]) -> None:
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


async def _goto(page: Page, instance: Instance, tab: str) -> None:
    """A tab of the page, with the plan drawn and Home Assistant's loading screen gone."""
    await page.goto(f"{instance.base}/ble-floorplan/{tab}")
    # The first load of the frontend takes a while on a slow CI machine
    await page.locator(f"{PANEL} .about").first.wait_for(timeout=90000)
    await page.locator("#ha-launch-screen").wait_for(state="detached")
    if tab != "settings":
        await page.locator(f"{PANEL} #svg .room").first.wait_for()


async def _title(page: Page) -> str:
    return (await page.locator(f"{PANEL} [slot=title] .name").inner_text()).strip()


async def _header_row(page: Page, *, tabs: bool, brand: bool = True) -> None:
    """One header row: the integration's icon, the name, the tabs right after it."""
    row = await page.locator(PANEL).evaluate(
        """el => {
          const root = el.shadowRoot;
          const box = (x) => x && x.getBoundingClientRect();
          const img = root.querySelector('[slot=title] img.brand');
          const name = box(root.querySelector('[slot=title] .name'));
          const nav = root.querySelector('[slot=title] nav.tabs');
          return {
            brand: img ? { width: img.naturalWidth, shown: box(img).width, top: box(img).top,
              bottom: box(img).bottom, right: box(img).right } : null,
            name: { top: name.top, bottom: name.bottom, left: name.left, right: name.right },
            tabs: nav ? { top: box(nav).top, bottom: box(nav).bottom, left: box(nav).left,
              count: nav.querySelectorAll('a.tab').length,
              active: nav.querySelectorAll('a.tab.active').length } : null,
            second: !!root.querySelector('.app > nav.tabs'),
          };
        }"""
    )
    middle = (row["name"]["top"] + row["name"]["bottom"]) / 2
    if brand:
        icon = row["brand"]
        expect(icon is not None, "no integration icon in the header")
        expect(icon["width"] > 0, "the integration icon did not load")
        expect(icon["shown"] == 24, f"icon {icon['shown']} px wide")
        expect(icon["right"] <= row["name"]["left"], "the icon is not left of the name")
        expect(
            abs((icon["top"] + icon["bottom"]) / 2 - middle) <= 2, "icon and name not in one row"
        )
    else:
        expect(row["brand"] is None, "an icon next to the back arrow")
    expect(not row["second"], "a second header row for the tabs")
    if tabs:
        nav = row["tabs"]
        expect(nav is not None, "no tabs in the header row")
        expect(
            nav["count"] == 7 and nav["active"] == 1, f"{nav['count']} tabs, {nav['active']} active"
        )
        expect(nav["left"] >= row["name"]["right"], "the tabs are not right of the name")
        expect(
            abs((nav["top"] + nav["bottom"]) / 2 - middle) <= 2,
            f"tabs {nav['top']}-{nav['bottom']} not in the name's row {row['name']}",
        )
    else:
        expect(row["tabs"] is None, "tabs in the header")


async def _header(page: Page) -> None:
    """The header of every page and subpage: stamp, refresh, settings, in this order."""
    bar = page.locator(f"{PANEL} ha-top-app-bar-fixed")
    order = await bar.evaluate(
        "bar => [...bar.querySelectorAll(':scope > [slot=actionItems]')].map(el => el.id)"
    )
    expect(order == ["stamp", "refresh", "integration"], f"header actions {order}")
    stamp = page.locator(f"{PANEL} #stamp")
    await _until(lambda: _stamp_ok(stamp), "the stamp 'As of HH:MM:SS' in the header", seconds=10)
    for button, path, label in (
        ("refresh", "M17.65,6.35", "Refresh"),
        ("integration", "M12,8A4,4", "Settings"),
    ):
        el = page.locator(f"{PANEL} ha-icon-button#{button}")
        expect(await el.is_visible(), f"{button} button not visible")
        expect((await el.get_attribute("path") or "").startswith(path), f"{button}: wrong icon")
        expect(await el.get_attribute("label") == label, f"{button}: label")


async def _brand_loaded(page: Page) -> bool:
    return bool(
        await page.locator(PANEL).evaluate(
            "el => (el.shadowRoot.querySelector('img.brand')?.naturalWidth || 0) > 0"
        )
    )


async def _stamp_ok(stamp: Any) -> bool:
    return await stamp.is_visible() and bool(STAMP.match((await stamp.inner_text()).strip()))


async def _plan(api: Api, instance: Instance) -> dict[str, Any]:
    reply = await api.ws(instance.token, {"type": "ble_floorplan/get_floorplan"})
    return dict(reply["result"]["floorplan"])


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


async def check_page(browser: Browser, instance: Instance, api: Api, shots: Path | None) -> Checks:
    page = await _open(browser, instance, ADMIN, "/ble-floorplan/plan")
    checks = Checks()

    async def plan_and_version() -> None:
        await _goto(page, instance, "plan")
        rooms = await page.locator(f"{PANEL} #svg .room").count()
        expect(rooms >= 5, f"{rooms} rooms drawn")
        expect(await _title(page) == "BLE Floorplan", await _title(page))
        await page.locator(f"{PANEL} ha-menu-button[slot=navigationIcon]").wait_for()
        about = (await page.locator(f"{PANEL} .about").first.inner_text()).strip()
        expect(about == f"BLE Floorplan {VERSION} · commit {instance.commit}", about)
        layout = await page.locator(f"{PANEL} textarea").input_value()
        expect("Living room" in layout, "the floor plan as YAML is missing")
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "plan.png"))

    await checks.run("floor plan with the YAML and the version at the bottom", plan_and_version)

    async def header_on_every_tab() -> None:
        for tab in (
            "plan",
            "scanners",
            "trackers",
            "calibration",
            "coverage",
            "timeline",
            "settings",
        ):
            await _goto(page, instance, tab)
            try:
                await _header(page)
                await _until(lambda: _brand_loaded(page), "the icon in the header", seconds=10)
                await _header_row(page, tabs=True)
            except AssertionError as err:
                raise AssertionError(f"{tab}: {err}") from err

    await checks.run(
        "every tab has one header row: icon, name, tabs, stamp, refresh, settings",
        header_on_every_tab,
    )

    async def refresh_fetches_again() -> None:
        await _goto(page, instance, "plan")
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
        await _goto(page, instance, "trackers")
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
        await _goto(page, instance, "trackers")

        async def placed() -> bool:
            text = await page.locator(f"{PANEL} ha-card").first.inner_text()
            return "Living room" in text and "Kitchen" in text and "not seen" in text

        await _until(placed, "the key tag in the living room, the phone in the kitchen")

    await checks.run("the trackers are where the scanners hear them", trackers_where_they_are)

    async def tracker_subpage() -> None:
        await _goto(page, instance, "trackers")
        await page.locator(f"{PANEL} .item[data-key='tag']").click()
        await page.locator(f"{PANEL} ha-icon-button[data-act='back']").wait_for()
        expect(await _title(page) == "Key tag", await _title(page))
        await page.locator(f"{PANEL} ha-menu-button[slot=navigationIcon]").wait_for(
            state="detached"
        )
        await _header(page)
        await _header_row(page, tabs=False, brand=False)
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "tracker.png"))
        await page.locator(f"{PANEL} ha-icon-button[data-act='back']").click()
        await page.locator(f"{PANEL} .item[data-key='tag']").wait_for()
        expect(await _title(page) == "BLE Floorplan", await _title(page))

    await checks.run("a tracker opens as a subpage with a back arrow", tracker_subpage)

    async def edit_tracker() -> None:
        await _goto(page, instance, "trackers")
        await page.locator(f"{PANEL} .item[data-key='phone']").click()
        await page.locator(f"{PANEL} ha-button[data-act='edit-tracker']").click()
        await page.get_by_role("textbox", name="Name").fill("Work phone")
        height = page.get_by_role("spinbutton", name="Height")
        await height.fill("1.4")
        await page.locator(f"{PANEL} ha-button[data-act='save-tracker']").click()

        async def saved() -> bool:
            plan = await _plan(api, instance)
            phone = next(t for t in plan["trackers"] if t["key"] == "phone")
            return bool(phone["height"] == 1.4 and phone["name"] == "Work phone")

        await _until(saved, "the new name and height in the integration")
        await page.locator(f"{PANEL} ha-alert[alert-type='success']").wait_for()
        expect(await _title(page) == "Work phone", await _title(page))
        # Back to the name the other checks and the screenshots show
        reply = await api.ws(
            instance.token, {"type": "ble_floorplan/set_tracker", "key": "phone", "name": "Phone"}
        )
        expect(reply["success"], str(reply))

    await checks.run("editing a tracker in ha-form reaches the integration", edit_tracker)

    async def remove_asks_first() -> None:
        await _goto(page, instance, "scanners")
        await page.locator(f"{PANEL} .item[data-key='hall']").click()
        await page.locator(f"{PANEL} ha-icon-button[data-act='back']").wait_for()
        await _header(page)
        await _header_row(page, tabs=False, brand=False)
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
            await _goto(page, instance, "scanners")
            item = page.locator(f"{PANEL} .item[data-key='attic']")
            await item.locator(".icon-bg.offline").wait_for()
            expect("not reachable" in await item.inner_text(), await item.inner_text())
            living = page.locator(f"{PANEL} .item[data-key='living']")
            expect(
                await living.locator(".icon-bg.offline").count() == 0, "a hearing scanner is marked"
            )
            await page.locator(f"{PANEL} svg g.scanner.offline[data-key='attic']").wait_for()
            await item.click()
            await page.locator(
                f"{PANEL} ha-alert[alert-type='warning']", has_text="nothing for over a minute"
            ).wait_for()
        finally:
            reply = await api.ws(
                instance.token, {"type": "ble_floorplan/set_floorplan", "floorplan": plan}
            )
            expect(reply["success"], str(reply))

    await checks.run(
        "a silent scanner is marked in the list, on the plan and on its page", silent_scanner
    )

    async def settings_saved() -> None:
        await _goto(page, instance, "settings")
        smoothing = page.get_by_role("spinbutton", name="Smoothing (s)")
        await smoothing.wait_for()
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "settings.png"))
        await smoothing.fill("15")
        await page.locator(f"{PANEL} ha-button[data-act='save-settings']").first.click()

        async def saved() -> bool:
            plan = await _plan(api, instance)
            return bool(plan["settings"]["smoothing_seconds"] == 15)

        await _until(saved, "the new smoothing in the integration")

    await checks.run("a setting changed in ha-form reaches the integration", settings_saved)

    async def calibration_runs() -> None:
        await _goto(page, instance, "calibration")
        rows = page.locator(f"{PANEL} table.runs tr")
        await rows.nth(2).wait_for()
        expect(await rows.count() == 3, f"{await rows.count() - 1} runs listed")
        if shots is not None:
            await _settle(page)
            await page.screenshot(path=str(shots / "calibration.png"))

    await checks.run("the calibration runs are listed", calibration_runs)

    async def timeline() -> None:
        await _goto(page, instance, "timeline")
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
        await _goto(page, instance, "coverage")
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

    async def card_only_shows() -> None:
        card_page = await _open(browser, instance, ADMIN, f"/{DASHBOARD}/0")
        card = card_page.locator(CARD)
        await card.locator(".tracker").first.wait_for(timeout=90000)
        await card_page.locator("#ha-launch-screen").wait_for(state="detached")
        expect(
            await card.locator("[data-act]").count() == 0, "the card has buttons to change things"
        )
        await card.locator(".tracker[data-key='tag']").click()
        await card.locator(".info").wait_for()
        if shots is not None:
            await _settle(card_page)
            await card.locator("ha-card").screenshot(path=str(shots / "card.png"))
        await card_page.context.close()

    await checks.run(
        "the card on a dashboard shows the trackers and nothing to change", card_only_shows
    )

    async def phone_and_dark() -> None:
        for scheme in ("light", "dark"):
            phone = await _open(
                browser,
                instance,
                ADMIN,
                "/ble-floorplan/trackers",
                viewport={"width": 390, "height": 844},
                color_scheme=scheme,
            )
            await _goto(phone, instance, "trackers")
            await phone.locator(f"{PANEL} .bottom-tabs").wait_for()
            # The header keeps icon and name; the tabs are the bar at the bottom
            await _until(
                lambda: _brand_loaded(phone),  # noqa: B023 awaited right here
                f"{scheme}: the icon in the header",
                seconds=10,
            )
            await _header_row(phone, tabs=False)
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

    async def users_get_what_the_card_draws() -> None:
        token = await api.login(*USER)
        panels = await api.ws(token, {"type": "get_panels"})
        expect("ble-floorplan" not in panels["result"], "the page is offered to a user")
        plan = (await api.ws(token, {"type": "ble_floorplan/get_floorplan"}))["result"]["floorplan"]
        expect(all("source" not in s for s in plan["scanners"]), "scanner addresses for a user")
        expect(all("address" not in t for t in plan["trackers"]), "tracker addresses for a user")
        reply = await api.ws(token, {"type": "ble_floorplan/set_scanner", "key": "hall", "x": 1})
        expect(not reply["success"] and reply["error"]["code"] == "unauthorized", str(reply))

    await checks.run(
        "users without administrator rights get no page, no addresses, no changes",
        users_get_what_the_card_draws,
    )
    await page.context.close()
    return checks


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--screenshots", type=Path, help="write the README pictures into this directory"
    )
    parser.add_argument("--keep", action="store_true", help="keep the temporary directory")
    parser.add_argument("--browser", choices=["chrome", "chromium"], default="chromium")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    if args.screenshots is not None:
        args.screenshots.mkdir(parents=True, exist_ok=True)

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
                    checks = await check_page(browser, instance, api, args.screenshots)
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
    print(f"\n{len(checks.passed)} passed, {len(checks.failed)} failed")
    if args.keep or checks.failed:
        print(f"Files kept in {directory}")
    else:
        shutil.rmtree(directory, ignore_errors=True)
    return 1 if checks.failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
