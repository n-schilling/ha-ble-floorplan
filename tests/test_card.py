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
    assert '"ble_floorplan/subscribe"' in card
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
    for command in (
        "subscribe",
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
    assert "`ble_floorplan/${act.replace" in panel
