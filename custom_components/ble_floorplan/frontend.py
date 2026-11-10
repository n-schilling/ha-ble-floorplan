"""Serves the card and the panel and registers them with the frontend and the dashboards."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from homeassistant.components import panel_custom
from homeassistant.components.frontend import (
    DATA_EXTRA_MODULE_URL,
    add_extra_js_url,
    async_panel_exists,
    async_remove_panel,
)
from homeassistant.components.http.server import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.core import HomeAssistant, callback
from homeassistant.loader import async_get_integration
from homeassistant.util.hass_dict import HassKey

from .const import (
    BUILD_FILE,
    CARD_FILENAME,
    DOMAIN,
    FRONTEND_URL_BASE,
    NAME,
    PANEL_ELEMENT,
    PANEL_FILENAME,
    PANEL_ICON,
    PANEL_URL_PATH,
)

_LOGGER = logging.getLogger(__name__)

DATA_FRONTEND: HassKey[str] = HassKey(f"{DOMAIN}_frontend")
CARD_PATH = f"{FRONTEND_URL_BASE}/{CARD_FILENAME}"
PANEL_PATH = f"{FRONTEND_URL_BASE}/{PANEL_FILENAME}"
RESOURCE_TYPE = "module"


async def async_card_url(hass: HomeAssistant) -> str:
    """Return the URL of the card, with a hash of the scripts so browsers fetch every change."""
    return f"{CARD_PATH}?v={await _async_digest(hass)}"


async def _async_digest(hass: HomeAssistant) -> str:
    """A short hash over the card, the page and the module they share."""
    return await hass.async_add_executor_job(_digest, Path(__file__).parent / "frontend")


def _digest(folder: Path) -> str:
    digest = hashlib.sha256()
    for script in sorted(folder.glob("*.js")):
        digest.update(script.name.encode())
        digest.update(script.read_bytes())
    return digest.hexdigest()[:12]


async def async_register_panel(hass: HomeAssistant) -> None:
    """Add the panel to the sidebar of administrators, unless it is there.

    It stays through a reload of the entry, so a page that shows it is not
    thrown out while a change reloads the entry; removing the entry removes it.
    """
    if async_panel_exists(hass, PANEL_URL_PATH):
        return
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        sidebar_title=NAME,
        sidebar_icon=PANEL_ICON,
        # The content hash makes browsers fetch every changed page, also within a version
        module_url=f"{PANEL_PATH}?v={await _async_digest(hass)}",
        require_admin=True,
    )


@callback
def async_unregister_panel(hass: HomeAssistant) -> None:
    """Take the panel off the sidebar."""
    async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the card, load it on every page and register it as a dashboard resource.

    Serving and loading happen once per run of Home Assistant: the card cannot
    be unregistered. The resource is checked on every setup, so an entry added
    again after a removal gets it back.
    """
    if (url := hass.data.get(DATA_FRONTEND)) is None:
        url = hass.data[DATA_FRONTEND] = await async_card_url(hass)
        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL_BASE, str(Path(__file__).parent / "frontend"), False)]
        )
        # The frontend is an after-dependency: present in every normal installation
        if DATA_EXTRA_MODULE_URL in hass.data:
            add_extra_js_url(hass, url)
    await _async_ensure_resource(hass, url)


async def async_about(hass: HomeAssistant) -> dict[str, str | None]:
    """The version the page shows at the bottom, and the commit of a test deployment."""
    integration = await async_get_integration(hass, DOMAIN)
    commit = await hass.async_add_executor_job(_read_commit)
    return {"version": str(integration.version), "commit": commit}


def _read_commit() -> str | None:
    """The commit the integration was deployed from, written by scripts/deploy.sh."""
    try:
        return (Path(__file__).parent / BUILD_FILE).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


async def _async_card_resources(
    hass: HomeAssistant,
) -> tuple[ResourceStorageCollection, list[dict[str, Any]]] | None:
    """Return the dashboard resources and the card's entries among them.

    None in YAML mode: resources in YAML are the user's.
    """
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None or lovelace.resource_mode != MODE_STORAGE:
        return None
    resources = lovelace.resources
    if not isinstance(resources, ResourceStorageCollection):
        return None
    # Loads the collection when nothing did so far
    await resources.async_get_info()
    return resources, [
        item
        for item in resources.async_items()
        if str(item.get("url", "")).split("?", 1)[0] == CARD_PATH
    ]


async def async_remove_resource(hass: HomeAssistant) -> None:
    """Remove the card from the dashboard resources, with the entry."""
    if (found := await _async_card_resources(hass)) is None:
        return
    resources, items = found
    for item in items:
        await resources.async_delete_item(item["id"])
        _LOGGER.debug("Dashboard resource %s removed", item["url"])


async def _async_ensure_resource(hass: HomeAssistant, url: str) -> None:
    """Add the card to the dashboard resources, or point an old entry to this version."""
    if (found := await _async_card_resources(hass)) is None:
        return
    resources, items = found
    for item in items:
        if item["url"] != url:
            await resources.async_update_item(item["id"], {"url": url})
            _LOGGER.debug("Dashboard resource updated to %s", url)
        return
    await resources.async_create_item({"res_type": RESOURCE_TYPE, "url": url})
    _LOGGER.debug("Dashboard resource %s added", url)
