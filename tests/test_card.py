"""The card and the panel that the integration ships."""

from __future__ import annotations

import json
from pathlib import Path
import re

PACKAGE = Path(__file__).resolve().parent.parent / "custom_components" / "ble_floorplan"
FRONTEND = PACKAGE / "frontend"


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
    """Every import names the release, so a browser that cached the last one fetches anew."""
    version = _version()
    for name in ("ble-floorplan-card.js", "ble-floorplan-panel.js"):
        code = (FRONTEND / name).read_text(encoding="utf-8")
        imports = re.findall(r'from "([^"]+)"', code)
        assert imports, name
        for target in imports:
            assert target == f"./ble-floorplan-plan.js?v={version}", (name, target)


def test_card_only_shows() -> None:
    """The card draws the live plan; it neither sets up nor leads to the panel."""
    card = (FRONTEND / "ble-floorplan-card.js").read_text(encoding="utf-8")
    assert 'customElements.define("ble-floorplan-card"' in card
    assert "new LiveSubscription(" in card
    assert "navigate(" not in card
    assert "is_admin" not in card
    # Setting up, calibrating and the timeline are the panel's
    assert '"ble_floorplan/set_' not in card
    assert '"ble_floorplan/calibration/' not in card
    assert '"ble_floorplan/history"' not in card


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
    """The page uses Home Assistant's elements, not look-alikes, and shows the version at the bottom."""
    panel = (FRONTEND / "ble-floorplan-panel.js").read_text(encoding="utf-8")
    for element in (
        "ha-top-app-bar-fixed",
        "ha-menu-button",
        "ha-card",
        "ha-button",
        "ha-alert",
        "ha-form",
    ):
        assert f"<{element}" in panel or f'"{element}"' in panel, element
    # Home Assistant's header: the sidebar's colour with a line, and the height fix
    assert "--app-header-background-color: var(--sidebar-background-color" in panel
    assert "height: 100dvh" in panel
    assert "<button" not in panel
    assert "<select" in panel  # only the speed of the timeline
    assert panel.count("<select") == 1
    assert "window.confirm" not in panel
    assert 'class="about"' in panel
