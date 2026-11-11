"""The quality scale file names every rule up to Platinum, each done or exempt with a reason."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

FILE = Path(__file__).parents[1] / "custom_components" / "ble_floorplan" / "quality_scale.yaml"

# The rules of the quality scale in Home Assistant 2026.11, Bronze to Platinum
RULES = {
    "action-setup",
    "appropriate-polling",
    "brands",
    "common-modules",
    "config-flow",
    "config-flow-test-coverage",
    "dependency-transparency",
    "docs-actions",
    "docs-conditions",
    "docs-triggers",
    "docs-high-level-description",
    "docs-installation-instructions",
    "docs-removal-instructions",
    "entity-event-setup",
    "entity-unique-id",
    "has-entity-name",
    "runtime-data",
    "test-before-configure",
    "test-before-setup",
    "unique-config-entry",
    "action-exceptions",
    "config-entry-unloading",
    "docs-configuration-parameters",
    "docs-installation-parameters",
    "entity-unavailable",
    "integration-owner",
    "log-when-unavailable",
    "parallel-updates",
    "reauthentication-flow",
    "test-coverage",
    "devices",
    "diagnostics",
    "discovery",
    "discovery-update-info",
    "docs-data-update",
    "docs-examples",
    "docs-known-limitations",
    "docs-supported-devices",
    "docs-supported-functions",
    "docs-troubleshooting",
    "docs-use-cases",
    "dynamic-devices",
    "entity-category",
    "entity-device-class",
    "entity-disabled-by-default",
    "entity-translations",
    "exception-translations",
    "icon-translations",
    "reconfiguration-flow",
    "repair-issues",
    "stale-devices",
    "async-dependency",
    "inject-websession",
    "strict-typing",
}


def test_platinum() -> None:
    """Every rule is there, done or exempt, and an exemption says why."""
    rules: dict[str, Any] = yaml.safe_load(FILE.read_text(encoding="utf-8"))["rules"]
    assert set(rules) == RULES
    for name, value in rules.items():
        status = value if isinstance(value, str) else value["status"]
        assert status in ("done", "exempt"), name
        if status == "exempt":
            assert isinstance(value, dict) and value.get("comment"), name


PACKAGE = FILE.parent


def test_rules_that_files_show() -> None:
    """What the files can prove: parallel updates, icons and translations of every entity."""
    import json

    for platform in ("sensor.py", "device_tracker.py"):
        assert "PARALLEL_UPDATES = 0" in (PACKAGE / platform).read_text(encoding="utf-8")
    strings = json.loads((PACKAGE / "strings.json").read_text(encoding="utf-8"))
    icons = json.loads((PACKAGE / "icons.json").read_text(encoding="utf-8"))
    for domain, keys in strings["entity"].items():
        assert set(keys) == set(icons["entity"][domain]), domain
    assert strings["exceptions"]
    assert strings["issues"]
    for module in ("diagnostics.py", "entity.py", "coordinator.py", "issues.py"):
        assert (PACKAGE / module).exists(), module
