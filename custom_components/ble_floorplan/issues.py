"""Repair issues: a tracker whose Private BLE Device no longer exists is never seen again."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN
from .model import Floorplan

ISSUE_DEVICE_MISSING = "tracker_device_missing"
# The issues that are raised: the ones a later check may find settled
DATA_ISSUES: HassKey[set[str]] = HassKey(f"{DOMAIN}_issues")


@callback
def async_check_trackers(hass: HomeAssistant, entry_id: str, plan: Floorplan) -> None:
    """Raise an issue for every tracker whose device is gone, and drop the issues that are settled.

    The page fixes it: take the tracker off the plan, or add the device again.
    The issues belong to the config entry: Home Assistant removes them with it.
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
            config_entry_id=entry_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_DEVICE_MISSING,
            translation_placeholders={"name": tracker.name},
        )
    for issue_id in hass.data.get(DATA_ISSUES, set()) - wanted:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    hass.data[DATA_ISSUES] = wanted
