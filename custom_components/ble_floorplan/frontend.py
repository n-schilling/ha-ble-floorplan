"""Serves the card and the panel and registers them with the frontend and the dashboards."""

from __future__ import annotations

import logging
from pathlib import Path

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
    """Return the URL of the card, with the version so browsers fetch a new release."""
    integration = await async_get_integration(hass, DOMAIN)
    return f"{CARD_PATH}?v={integration.version}"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Add the panel to the sidebar of administrators, unless it is there.

    It stays through a reload of the entry, so a page that shows it is not
    thrown out while a change reloads the entry; removing the entry removes it.
    """
    if async_panel_exists(hass, PANEL_URL_PATH):
        return
    integration = await async_get_integration(hass, DOMAIN)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        sidebar_title=NAME,
        sidebar_icon=PANEL_ICON,
        module_url=f"{PANEL_PATH}?v={integration.version}",
        require_admin=True,
    )


@callback
def async_unregister_panel(hass: HomeAssistant) -> None:
    """Take the panel off the sidebar."""
    async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the card, load it on every page and register it as a dashboard resource.

    Done once per run of Home Assistant: the card cannot be unregistered.
    """
    if DATA_FRONTEND in hass.data:
        return
    url = hass.data[DATA_FRONTEND] = await async_card_url(hass)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL_BASE, str(Path(__file__).parent / "frontend"), False)]
    )
    # The frontend is an after-dependency: present in every normal installation
    if DATA_EXTRA_MODULE_URL in hass.data:
        add_extra_js_url(hass, url)
    await _async_ensure_resource(hass, url)


async def _async_ensure_resource(hass: HomeAssistant, url: str) -> None:
    """Add the card to the dashboard resources, or point an old entry to this version.

    Only in storage mode; resources in YAML are the user's.
    """
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None or lovelace.resource_mode != MODE_STORAGE:
        return
    resources = lovelace.resources
    if not isinstance(resources, ResourceStorageCollection):
        return
    # Loads the collection when nothing did so far
    await resources.async_get_info()
    for item in resources.async_items():
        if str(item.get("url", "")).split("?", 1)[0] != CARD_PATH:
            continue
        if item["url"] != url:
            await resources.async_update_item(item["id"], {"url": url})
            _LOGGER.debug("Dashboard resource updated to %s", url)
        return
    await resources.async_create_item({"res_type": RESOURCE_TYPE, "url": url})
    _LOGGER.debug("Dashboard resource %s added", url)
