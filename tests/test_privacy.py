"""Privacy: nothing personal in the repository, nothing leaves the house."""

from __future__ import annotations

import ast
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "custom_components" / "ble_floorplan"
SKIPPED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
TEXT_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".md", ".txt", ".toml", ".ini", ".sh", ".js"}

MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# Only made-up addresses belong in the repository: the test prefix and the
# documentation ranges of RFC 5737
ALLOWED_MAC_PREFIX = "AA:BB:CC:DD:EE:"
ALLOWED_IPV4_PREFIXES = ("192.0.2.", "198.51.100.", "203.0.113.")
ALLOWED_MAIL_DOMAINS = ("users.noreply.github.com", "example.com")
# File names that merely look like an address
NOT_MAILS = ("icon@2x.png",)

# The integration talks to Home Assistant's Bluetooth stack only: no network
# library, directly or through Home Assistant's helpers
NETWORK_MODULES = {"aiohttp", "httpx", "requests", "urllib", "socket", "ssl"}
NETWORK_PATHS = (
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.httpx_client",
    "homeassistant.components.webhook",
    "homeassistant.components.cloud",
)


def _scanned() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix in TEXT_SUFFIXES
        and not SKIPPED_DIRS & set(path.relative_to(ROOT).parts)
    ]


def _imports(path: Path) -> list[str]:
    """Every imported module path, with the names of a from-import appended."""
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_no_real_addresses() -> None:
    """No Bluetooth or IP address of a real device, no personal e-mail address, anywhere."""
    files = _scanned()
    assert any(path.name == "ci.yaml" for path in files), "the workflow files are scanned"
    assert any(path.suffix == ".js" for path in files), "the card is scanned"
    for path in files:
        text = path.read_text(encoding="utf-8")
        for mac in MAC.findall(text):
            assert mac.upper().startswith(ALLOWED_MAC_PREFIX), f"{path}: {mac}"
        for ip in IPV4.findall(text):
            assert ip.startswith(ALLOWED_IPV4_PREFIXES), f"{path}: {ip}"
        for mail in EMAIL.findall(text):
            assert mail in NOT_MAILS or mail.endswith(ALLOWED_MAIL_DOMAINS), f"{path}: {mail}"


def test_no_network_libraries() -> None:
    """Nothing is sent anywhere: the package imports no network library."""
    for path in PACKAGE.rglob("*.py"):
        for name in _imports(path):
            assert name.split(".")[0] not in NETWORK_MODULES, f"{path}: {name}"
            assert not name.startswith(NETWORK_PATHS), f"{path}: {name}"


def test_card_talks_to_home_assistant_only() -> None:
    """The card uses the WebSocket connection of the page, no other URL."""
    card = (PACKAGE / "frontend" / "ble-floorplan-card.js").read_text(encoding="utf-8")
    assert "fetch(" not in card
    assert "XMLHttpRequest" not in card
    assert "http://" not in card
    assert "https://" not in card


def test_no_diagnostics() -> None:
    """There is nothing to download: the integration offers no diagnostics."""
    assert not (PACKAGE / "diagnostics.py").exists()


# Images carry pixels only: no text chunks, no EXIF, no colour profile with a name
IMAGE_CHUNKS = {b"IHDR", b"PLTE", b"IDAT", b"IEND"}


def test_images_carry_no_metadata() -> None:
    """The screenshots are rendered from the example flat and keep no metadata."""
    images = [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        and not SKIPPED_DIRS & set(path.relative_to(ROOT).parts)
    ]
    assert any(p.parent.name == "images" for p in images), "the screenshots are checked"
    for path in images:
        data = path.read_bytes()
        assert path.suffix == ".png", f"{path}: only PNG, so the chunks can be checked"
        assert data[:8] == b"\x89PNG\r\n\x1a\n", path
        i = 8
        while i < len(data):
            length = struct.unpack(">I", data[i : i + 4])[0]
            kind = data[i + 4 : i + 8]
            assert kind in IMAGE_CHUNKS, f"{path}: chunk {kind!r}"
            i += 12 + length
