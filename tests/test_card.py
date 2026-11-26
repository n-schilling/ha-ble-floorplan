"""The card and the panel that the integration ships.

The card (STANDARD §7, the dashboard card): served, loaded on every page and
kept as a dashboard resource; what its script may read and call.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant.common import MockConfigEntry

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE, MODE_YAML
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.core import HomeAssistant

from custom_components.ble_floorplan import frontend
from custom_components.ble_floorplan.const import DOMAIN
from custom_components.ble_floorplan.frontend import (
    CARD_PATH,
    DATA_FRONTEND,
    async_card_url,
    async_register_frontend,
)

from .conftest import ScannerDevices

PACKAGE = Path(__file__).resolve().parent.parent / "custom_components" / "ble_floorplan"
FRONTEND = PACKAGE / "frontend"
CARD = FRONTEND / "ble-floorplan-card.js"

# The actions the card's controls may call, as "domain.action" (STANDARD §7).
# The card only reads: none.
ACTIONS: set[str] = set()
# The subscriptions the card may open (STANDARD §7): the plan view's one, open to
# every user, changing nothing, without readings for users who are no administrators
SUBSCRIPTIONS = {"ble_floorplan/subscribe"}


def _version() -> str:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    return str(manifest["version"])


def test_shared_module_version_matches_manifest() -> None:
    """The shared module logs the version of the integration it came with."""
    shared = (FRONTEND / "ble-floorplan-plan.js").read_text(encoding="utf-8")
    match = re.search(r'export const VERSION = "([^"]+)"', shared)
    assert match is not None
    assert match.group(1) == _version()


def test_imports_carry_the_version() -> None:
    """Every module names the release it loads, so a browser that cached the last one fetches anew."""
    version = _version()
    for name in ("ble-floorplan-card.js", "ble-floorplan-panel.js", "ble-floorplan-editor.js"):
        code = (FRONTEND / name).read_text(encoding="utf-8")
        loaded = re.findall(r'"(\./ble-floorplan-[^"]+)"', code)
        assert loaded, name
        for target in loaded:
            assert re.fullmatch(
                rf"\./ble-floorplan-(plan|editor)\.js\?v={re.escape(version)}", target
            ), (name, target)


def test_card_reads_and_calls_only_what_is_listed() -> None:
    """The card reads entities: no command, no fetch, no action; the plan view its one subscription."""
    card = CARD.read_text(encoding="utf-8")
    assert "customElements.define(TAG" in card
    # The overview is the card's own script and reads entities only
    for call in ("subscribeMessage", "navigate(", "is_admin", '"ble_floorplan/'):
        assert call not in card, call
    # The plan view loads one module, and only when a card is in that mode
    assert re.findall(r'"\./(ble-floorplan-[a-z]+\.js)\?v=', card) == ["ble-floorplan-plan.js"]
    assert card.count("import(") == 1
    assert not re.search(r"^import ", card, re.MULTILINE)
    code = card + (FRONTEND / "ble-floorplan-plan.js").read_text(encoding="utf-8")
    for call in ("callWS", "callApi", "fetch(", "sendMessage"):
        assert call not in code, call
    listed = re.search(r"const ACTIONS = \[(.*?)\];", code, re.DOTALL)
    assert set(re.findall(r'"([a-z_]+\.[a-z_]+)"', listed.group(1)) if listed else []) == ACTIONS
    # One place calls, with an entry of the list; a card without controls calls nothing
    assert code.count("callService") == (1 if ACTIONS else 0)
    subscribed = re.findall(r'subscribeMessage\([^;]*?\{ type: "([^"]+)" \}', code, re.DOTALL)
    assert code.count("subscribeMessage(") == len(subscribed)
    assert set(subscribed) == SUBSCRIPTIONS
    # Every option the card reads has a field in its editor
    options = set(re.findall(r"\bc\.(\w+)", card))
    assert len(options) > 8
    for option in options - {"title", "size"}:
        assert f'"{option}"' in card, option
    # The card picker lists it once, with a preview
    assert card.count("window.customCards.push(") == 1
    assert "preview: true" in card


def _card_keys(code: str, language: str) -> list[str]:
    """The keys of one language of the card's texts, in order."""
    start = code.index(f"\n    {language}: {{\n")
    end = code.index("\n    },", start)
    return re.findall(r'^\s+([A-Za-z_][A-Za-z0-9_]*): "', code[start:end], re.MULTILINE)


def test_card_texts_have_each_key_once_in_both_languages() -> None:
    """A key written twice silently takes the later text; both languages have the same keys."""
    code = CARD.read_text(encoding="utf-8")
    english = _card_keys(code, "en")
    german = _card_keys(code, "de")
    assert len(english) > 20
    for keys in (english, german):
        twice = sorted({key for key in keys if keys.count(key) > 1})
        assert not twice, twice
    assert english == german


def test_panel_uses_the_commands() -> None:
    """The panel sets up, calibrates and plays back through the WebSocket commands."""
    panel = (FRONTEND / "ble-floorplan-panel.js").read_text(encoding="utf-8")
    assert 'customElements.define("ble-floorplan-panel"' in panel
    assert "new LiveSubscription(" in panel
    for command in (
        "get_layout",
        "set_layout",
        "candidates",
        "add_scanner",
        "add_tracker",
        "set_scanner",
        "set_tracker",
        "set_settings",
        "history",
        "calibration/start",
        "calibration/stop",
        "calibration/delete",
        "calibration/solve",
        "calibration/apply",
        "scanner_system",
    ):
        assert f'"ble_floorplan/{command}"' in panel, command
    # Removing is built from the action name
    assert "`ble_floorplan/${c.act.replace" in panel


def test_card_and_page_share_the_subscription() -> None:
    """One subscription helper: retries after a failure, drops what arrives for a page that left."""
    shared = (FRONTEND / "ble-floorplan-plan.js").read_text(encoding="utf-8")
    assert '{ type: "ble_floorplan/subscribe" }' in shared
    assert "RETRY_MS" in shared
    assert "this._host.isConnected" in shared


def test_panel_is_built_from_home_assistant_elements() -> None:
    """The page uses Home Assistant's elements, not look-alikes: its frame with tabs, tabs, rows, tooltips."""
    panel = (FRONTEND / "ble-floorplan-panel.js").read_text(encoding="utf-8")
    for element in (
        "hass-tabs-subpage",
        "ha-tab-group",
        "ha-tab-group-tab",
        "ha-settings-row",
        "ha-tooltip",
        "ha-icon-button",
        "ha-card",
        "ha-button",
        "ha-alert",
        "ha-form",
        "ha-expansion-panel",
        "ha-assist-chip",
    ):
        assert f"<{element}" in panel or f'"{element}"' in panel, element
    # The look-alikes of before are gone: own header, own tabs, own dialog
    for gone in ("ha-top-app-bar-fixed", "bottom-tabs", "qdialog", 'class="tab'):
        assert gone not in panel, gone
    assert "height: 100dvh" in panel
    assert "<button" not in panel
    assert panel.count("<select") == 1  # only the speed of the timeline
    assert "window.confirm" not in panel
    assert 'class="about"' in panel


def _language_keys(shared: str, language: str) -> list[str]:
    """The keys of one language of the texts, in order, each as often as it is written."""
    start = shared.index(f"\n  {language}: {{\n")
    end = shared.index("\n  },", start)
    body = shared[start:end]
    return re.findall(r'(?:^|", |\{ )\s*([A-Za-z_][A-Za-z0-9_]*): "', body, re.MULTILINE)


def test_texts_have_each_key_once_in_both_languages() -> None:
    """A key written twice silently takes the later text (Pause became Anhalten); both languages alike."""
    shared = (FRONTEND / "ble-floorplan-plan.js").read_text(encoding="utf-8")
    english = _language_keys(shared, "en")
    german = _language_keys(shared, "de")
    assert len(english) > 300
    for keys in (english, german):
        twice = sorted({k for k in keys if keys.count(k) > 1})
        assert not twice, twice
    assert set(english) == set(german)


def _lovelace(mode: str, resources: Any) -> MagicMock:
    data = MagicMock()
    data.resource_mode = mode
    data.resources = resources
    return data


def _collection(items: list[dict[str, Any]]) -> MagicMock:
    collection = MagicMock(spec=ResourceStorageCollection)
    collection.async_get_info = AsyncMock()
    collection.async_items = MagicMock(return_value=items)
    collection.async_create_item = AsyncMock()
    collection.async_update_item = AsyncMock()
    collection.async_delete_item = AsyncMock()
    return collection


async def test_frontend_extra_js_and_resource_created(
    hass: HomeAssistant,
    bluetooth: None,
    storage: dict[str, Any],
    clock: Callable[[float], None],
    scanner_devices: ScannerDevices,
    config_entry: MockConfigEntry,
) -> None:
    """With the frontend loaded the card is added to every page and to the dashboard resources."""
    collection = _collection([{"id": "1", "url": "/local/other.js", "type": "module"}])
    hass.data[LOVELACE_DATA] = _lovelace(MODE_STORAGE, collection)
    hass.data[DATA_EXTRA_MODULE_URL] = MagicMock()
    config_entry.add_to_hass(hass)
    with patch("custom_components.ble_floorplan.frontend.add_extra_js_url") as add_url:
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    url = hass.data[DATA_FRONTEND]
    add_url.assert_called_once_with(hass, url)
    collection.async_get_info.assert_awaited_once()
    collection.async_create_item.assert_awaited_once_with({"res_type": "module", "url": url})
    collection.async_update_item.assert_not_awaited()


async def test_frontend_resource_updated(hass: HomeAssistant, bluetooth: None) -> None:
    """An entry of an earlier version is pointed to this one; a current one is left alone."""
    url = await async_card_url(hass)
    collection = _collection([{"id": "7", "url": f"{CARD_PATH}?v=0.0.1", "type": "module"}])
    hass.data[LOVELACE_DATA] = _lovelace(MODE_STORAGE, collection)
    await async_register_frontend(hass)
    collection.async_update_item.assert_awaited_once_with("7", {"url": url})
    collection.async_create_item.assert_not_awaited()

    hass.data.pop(DATA_FRONTEND)
    collection = _collection([{"id": "7", "url": url, "type": "module"}])
    hass.data[LOVELACE_DATA] = _lovelace(MODE_STORAGE, collection)
    await async_register_frontend(hass)
    collection.async_update_item.assert_not_awaited()
    collection.async_create_item.assert_not_awaited()


async def test_frontend_resource_skipped(hass: HomeAssistant, bluetooth: None) -> None:
    """Resources in YAML are the user's; a collection of another kind is left alone."""
    collection = _collection([])
    hass.data[LOVELACE_DATA] = _lovelace(MODE_YAML, collection)
    await async_register_frontend(hass)
    collection.async_create_item.assert_not_awaited()

    hass.data.pop(DATA_FRONTEND)
    hass.data[LOVELACE_DATA] = _lovelace(MODE_STORAGE, MagicMock())
    await async_register_frontend(hass)
    assert DATA_FRONTEND in hass.data
    assert DOMAIN in hass.data[DATA_FRONTEND]


async def test_remove_takes_the_resource_away_and_a_new_entry_brings_it_back(
    hass: HomeAssistant,
    bluetooth: None,
    storage: dict[str, Any],
    clock: Callable[[float], None],
    scanner_devices: ScannerDevices,
    config_entry: MockConfigEntry,
) -> None:
    """Removing the entry removes the card's dashboard resource; a new entry adds it again."""
    items: list[dict[str, Any]] = [{"id": "1", "url": "/local/other.js", "type": "module"}]
    collection = _collection(items)
    hass.data[LOVELACE_DATA] = _lovelace(MODE_STORAGE, collection)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    url = hass.data[DATA_FRONTEND]
    items.append({"id": "2", "url": url, "type": "module"})
    assert await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    collection.async_delete_item.assert_awaited_once_with("2")

    items.pop()
    collection.async_create_item.reset_mock()
    again = MockConfigEntry(domain=DOMAIN, title="BLE Floorplan", unique_id=DOMAIN, data={})
    again.add_to_hass(hass)
    assert await hass.config_entries.async_setup(again.entry_id)
    await hass.async_block_till_done()
    collection.async_create_item.assert_awaited_once_with({"res_type": "module", "url": url})


async def test_remove_leaves_yaml_resources_alone(hass: HomeAssistant, bluetooth: None) -> None:
    """Resources in YAML are the user's, also when the entry goes."""
    collection = _collection([{"id": "2", "url": f"{CARD_PATH}?v=1", "type": "module"}])
    hass.data[LOVELACE_DATA] = _lovelace(MODE_YAML, collection)
    await frontend.async_remove_resource(hass)
    collection.async_delete_item.assert_not_awaited()
