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
# A GIF may carry its frames, their timing and the loop count, nothing else
GIF_LOOP = b"NETSCAPE2.0"


def _png_problems(data: bytes) -> list[str]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return ["no PNG"]
    problems = []
    i = 8
    while i < len(data):
        length = struct.unpack(">I", data[i : i + 4])[0]
        kind = data[i + 4 : i + 8]
        if kind not in IMAGE_CHUNKS:
            problems.append(f"chunk {kind!r}")
        i += 12 + length
    return problems


def _skip_sub_blocks(data: bytes, i: int) -> int:
    while data[i]:
        i += data[i] + 1
    return i + 1


def _gif_problems(data: bytes) -> list[str]:
    if data[:6] not in (b"GIF87a", b"GIF89a"):
        return ["no GIF"]
    problems = []
    flags = data[10]
    i = 13 + (3 * 2 ** ((flags & 7) + 1) if flags & 0x80 else 0)
    while i < len(data):
        block = data[i]
        if block == 0x3B:  # trailer
            break
        if block == 0x2C:  # image: descriptor, local colour table, LZW data
            local = data[i + 9]
            i += 10 + (3 * 2 ** ((local & 7) + 1) if local & 0x80 else 0)
            i = _skip_sub_blocks(data, i + 1)
        elif block == 0x21:  # extension
            label = data[i + 1]
            if label == 0xFF:
                ident = data[i + 3 : i + 3 + data[i + 2]]
                if ident != GIF_LOOP:
                    problems.append(f"application block {ident!r}")
            elif label != 0xF9:  # anything but the graphic control (timing)
                problems.append(f"extension 0x{label:02x}")
            i = _skip_sub_blocks(data, i + 2)
        else:
            problems.append(f"block 0x{block:02x}")
            break
    return problems


def test_images_carry_no_metadata() -> None:
    """The screenshots are rendered from the example flat and keep no metadata."""
    images = [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        and not SKIPPED_DIRS & set(path.relative_to(ROOT).parts)
    ]
    assert any(p.suffix == ".gif" for p in images), "the animation is checked"
    for path in images:
        data = path.read_bytes()
        assert path.suffix in {".png", ".gif"}, f"{path}: only PNG and GIF, so they can be checked"
        problems = _png_problems(data) if path.suffix == ".png" else _gif_problems(data)
        assert not problems, f"{path}: {problems}"


def test_metadata_checks_catch_metadata() -> None:
    """The checks above find what they look for."""
    png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 0) + b"tEXt" + b"\0" * 4
    assert _png_problems(png) == ["chunk b'tEXt'"]
    assert _png_problems(b"nope") == ["no PNG"]
    header = b"GIF89a" + b"\0" * 4 + b"\0" + b"\0\0"
    comment = header + b"\x21\xfe\x03abc\x00" + b"\x3b"
    assert _gif_problems(comment) == ["extension 0xfe"]
    xmp = header + b"\x21\xff\x0bXMP DataXMP\x00" + b"\x3b"
    assert _gif_problems(xmp) == ["application block b'XMP DataXMP'"]
    assert _gif_problems(header + b"\x99") == ["block 0x99"]
    assert _gif_problems(b"nope") == ["no GIF"]
