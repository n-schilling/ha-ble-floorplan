"""The card that the integration ships."""

from __future__ import annotations

import json
from pathlib import Path
import re

PACKAGE = Path(__file__).resolve().parent.parent / "custom_components" / "ble_floorplan"


def test_card_version_matches_manifest() -> None:
    """The card logs the version of the integration it came with."""
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    card = (PACKAGE / "frontend" / "ble-floorplan-card.js").read_text(encoding="utf-8")
    match = re.search(r'const VERSION = "([^"]+)"', card)
    assert match is not None
    assert match.group(1) == manifest["version"]
    assert 'customElements.define("ble-floorplan-card"' in card
    assert '"ble_floorplan/subscribe"' in card
    assert '"ble_floorplan/set_scanner"' in card
    for command in ("start", "stop", "delete", "solve", "apply"):
        assert f'"ble_floorplan/calibration/{command}"' in card, command
    assert '"ble_floorplan/set_tracker"' in card
    assert '"ble_floorplan/set_settings"' in card
