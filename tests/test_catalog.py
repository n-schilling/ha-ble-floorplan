"""Adding scanners and trackers from what Home Assistant has, and the layout as YAML."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH

from custom_components.ble_floorplan.catalog import (
    LayoutProblem,
    layout_yaml,
    new_key,
    remove_scanner,
    remove_tracker,
    with_layout,
)
from custom_components.ble_floorplan.const import (
    WS_ADD_SCANNER,
    WS_ADD_TRACKER,
    WS_CANDIDATES,
    WS_GET_LAYOUT,
    WS_REMOVE_SCANNER,
    WS_REMOVE_TRACKER,
    WS_SET_LAYOUT,
)

from . import SCANNER_BEDROOM, SCANNER_KITCHEN, SCANNER_LIVING, FakeScanner, make_plan

SCANNER_HALL = "AA:BB:CC:DD:EE:04"
KEYS = "AA:BB:CC:DD:EE:30"


@pytest.fixture
def current() -> Generator[list[FakeScanner]]:
    """Home Assistant's scanners: the three of the plan and one that is not on it."""
    scanners = [
        FakeScanner(SCANNER_LIVING, "Living room scanner"),
        FakeScanner(SCANNER_KITCHEN, "Kitchen plug"),
        FakeScanner(SCANNER_BEDROOM, "Bedroom proxy"),
        FakeScanner(SCANNER_HALL.lower(), SCANNER_HALL),
    ]
    with patch(
        "custom_components.ble_floorplan.catalog.async_current_scanners", return_value=scanners
    ):
        yield scanners


@pytest.fixture
def devices(hass: HomeAssistant, entry: MockConfigEntry, current: list[FakeScanner]) -> str:
    """The hall scanner's device, a key finder with a fixed address, a watch; returns its id."""
    other = MockConfigEntry(domain="other", data={})
    other.add_to_hass(hass)
    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=other.entry_id,
        connections={(CONNECTION_BLUETOOTH, SCANNER_HALL)},
        name="Hall proxy",
    )
    registry.async_get_or_create(
        config_entry_id=other.entry_id, connections={(CONNECTION_BLUETOOTH, KEYS)}, name="Keys"
    )
    private = MockConfigEntry(domain="private_ble_device", data={})
    private.add_to_hass(hass)
    watch = registry.async_get_or_create(
        config_entry_id=private.entry_id,
        identifiers={("private_ble_device", "watch")},
        name="Watch",
    )
    er.async_get(hass).async_get_or_create(
        "device_tracker",
        "private_ble_device",
        "watch",
        config_entry=private,
        device_id=watch.id,
    )
    # A tracker entity without a device is no candidate
    er.async_get(hass).async_get_or_create(
        "device_tracker", "private_ble_device", "lost", config_entry=private
    )
    return watch.id


def test_new_key() -> None:
    """Keys are slugs of the name, numbered when taken."""
    assert new_key("Hall proxy", []) == "hall_proxy"
    assert new_key("Hall proxy", ["hall_proxy"]) == "hall_proxy_2"
    assert new_key("Hall proxy", ["hall_proxy", "hall_proxy_2"]) == "hall_proxy_3"
    assert new_key("", []) == "item"


def test_remove_drops_pairs() -> None:
    """A removed scanner or tracker takes its pair corrections along."""
    plan = make_plan(pair_offsets={"living": {"tag": 1, "phone": 2}, "kitchen": {"tag": 3}})
    without_living = remove_scanner(plan, "living")
    assert [s.key for s in without_living.scanners] == ["kitchen", "bedroom"]
    assert without_living.pair_offsets == {"kitchen": {"tag": 3.0}}
    without_tag = remove_tracker(plan, "tag")
    assert [t.key for t in without_tag.trackers] == ["phone"]
    assert without_tag.pair_offsets == {"living": {"phone": 2.0}}


def test_layout_round_trip() -> None:
    """The YAML of the rooms and openings comes back as the same plan."""
    plan = make_plan(pair_offsets={"living": {"tag": 1}})
    text = layout_yaml(plan)
    assert "Living room" in text
    assert "openings:" in text
    # Defaults are left out, set values stay
    assert "outdoor: false" not in text
    assert "label: true" not in text
    assert "zone: true" in text
    assert "label: false" in text
    assert with_layout(plan, text) == plan
    small = with_layout(plan, "rooms:\n  - {name: Studio, x: 0, y: 0, w: 4, h: 3}\n")
    assert [r.name for r in small.rooms] == ["Studio"]
    assert small.openings == ()
    assert small.scanners == plan.scanners
    assert small.pair_offsets == plan.pair_offsets
    assert with_layout(plan, "").rooms == ()
    # An empty plan gets a template that is itself a valid layout
    empty = with_layout(plan, "")
    template = layout_yaml(empty)
    assert template.startswith("# Metres")
    assert [r.name for r in with_layout(empty, template).rooms] == ["Living room", "Kitchen"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("rooms: [", "not YAML"),
        ("- a", "mapping"),
        ("scanners: []", "mapping"),
        ("rooms:\n  - {name: A, x: 0}", "room"),
    ],
)
def test_layout_problems(text: str, message: str) -> None:
    """Broken YAML and bad rooms are refused with a message."""
    with pytest.raises(LayoutProblem, match=message):
        with_layout(make_plan(), text)


async def test_candidates(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    devices: str,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Scanners and devices not on the plan, named as the user sees them."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_CANDIDATES})
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["scanners"] == [{"source": SCANNER_HALL, "name": "Hall proxy"}]
    # The tag is on the plan, the scanners are scanners, the integration's own devices are its own
    assert msg["result"]["trackers"] == [
        {"address": KEYS, "name": "Keys"},
        {"device_id": devices, "name": "Watch"},
    ]


async def test_add_and_remove_scanner(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    devices: str,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A scanner lands in the middle of the plan; twice is refused; removing takes it off."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_ADD_SCANNER, "source": SCANNER_HALL.lower()})
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"] == {
        "key": "hall_proxy",
        "name": "Hall proxy",
        "source": SCANNER_HALL,
        "x": 5.0,
        "y": 5.5,
        "z": 1.0,
        "rssi_offset": 0.0,
    }
    assert entry.runtime_data.store.plan.scanner("hall_proxy") is not None

    await client.send_json_auto_id({"type": WS_ADD_SCANNER, "source": SCANNER_HALL})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "invalid_format"
    await client.send_json_auto_id({"type": WS_ADD_SCANNER, "source": "AA:BB:CC:DD:EE:77"})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "not_found"
    await client.send_json_auto_id(
        {"type": WS_ADD_SCANNER, "source": "AA:BB:CC:DD:EE:77", "name": "Spare", "z": 0.4}
    )
    msg = await client.receive_json()
    assert msg["result"]["key"] == "spare"
    assert msg["result"]["z"] == 0.4

    await client.send_json_auto_id({"type": WS_REMOVE_SCANNER, "key": "hall_proxy"})
    msg = await client.receive_json()
    assert msg["success"]
    assert entry.runtime_data.store.plan.scanner("hall_proxy") is None
    await client.send_json_auto_id({"type": WS_REMOVE_SCANNER, "key": "hall_proxy"})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "not_found"


async def test_add_and_remove_tracker(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    devices: str,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A tracker gets its sensors with the reload; twice or without a device is refused."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_ADD_TRACKER, "address": KEYS.lower(), "name": "Keys"}
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"] == {"key": "keys", "name": "Keys", "address": KEYS, "height": 1.0}
    await hass.async_block_till_done()
    assert hass.states.get("sensor.keys_room") is not None

    await client.send_json_auto_id(
        {"type": WS_ADD_TRACKER, "device_id": devices, "name": "Watch", "height": 1.2}
    )
    msg = await client.receive_json()
    assert msg["result"]["key"] == "watch"
    await hass.async_block_till_done()
    # Both on the plan now: no candidates left
    await client.send_json_auto_id({"type": WS_CANDIDATES})
    msg = await client.receive_json()
    assert msg["result"]["trackers"] == []

    for message, code in (
        ({"address": KEYS, "name": "Keys again"}, "invalid_format"),
        ({"device_id": devices, "name": "Watch again"}, "invalid_format"),
        ({"name": "Nothing"}, "invalid_format"),
        ({"address": "nonsense", "name": "Bad"}, "invalid_format"),
    ):
        await client.send_json_auto_id({"type": WS_ADD_TRACKER, **message})
        msg = await client.receive_json()
        assert msg["error"]["code"] == code, message

    await client.send_json_auto_id({"type": WS_REMOVE_TRACKER, "key": "keys"})
    msg = await client.receive_json()
    assert msg["success"]
    await hass.async_block_till_done()
    assert hass.states.get("sensor.keys_room") is None
    await client.send_json_auto_id({"type": WS_REMOVE_TRACKER, "key": "keys"})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "not_found"


async def test_layout_commands(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """Read and write the rooms and openings as YAML; mistakes come back as messages."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_GET_LAYOUT})
    msg = await client.receive_json()
    assert "Living room" in msg["result"]["yaml"]
    await client.send_json_auto_id(
        {"type": WS_SET_LAYOUT, "yaml": "rooms:\n  - {name: Studio, x: 0, y: 0, w: 4, h: 3}\n"}
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert "Studio" in msg["result"]["yaml"]
    assert [r.name for r in entry.runtime_data.store.plan.rooms] == ["Studio"]
    await client.send_json_auto_id({"type": WS_SET_LAYOUT, "yaml": "rooms: ["})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "invalid_format"
    assert "not YAML" in msg["error"]["message"]
