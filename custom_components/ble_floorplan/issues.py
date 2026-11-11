"""Repair issues: a tracker whose Private BLE Device no longer exists is never seen again."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, issue_registry as ir

from .const import DOMAIN
from .model import Floorplan

ISSUE_DEVICE_MISSING = "tracker_device_missing"


@callback
def async_check_trackers(hass: HomeAssistant, plan: Floorplan) -> None:
    """Raise an issue for every tracker whose device is gone, and drop the issues that are settled.

    The page fixes it: take the tracker off the plan, or add the device again.
    """
    devices = dr.async_get(hass)
    wanted: set[str] = set()
    for tracker in plan.trackers:
        if tracker.device_id is None or devices.async_get(tracker.device_id) is not None:
            continue
        issue_id = f"{ISSUE_DEVICE_MISSING}_{tracker.key}"
        wanted.add(issue_id)
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_DEVICE_MISSING,
            translation_placeholders={"name": tracker.name},
        )
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain == DOMAIN and issue_id not in wanted:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


@callback
def async_clear_issues(hass: HomeAssistant) -> None:
    """Remove every issue of the integration, with the entry."""
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain == DOMAIN:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
