"""Diagnostics: what helps with a wrong position, without what tells who lives where.

Scanners and trackers appear as "Scanner 1", "Tracker 1" in the order of the
plan: no names, Bluetooth addresses, device ids, room or area names, and no
timeline. Positions are coordinates on the plan, which says nothing about the
home without the room names.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from .catalog import alive_sources

if TYPE_CHECKING:
    from . import FloorplanConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FloorplanConfigEntry
) -> dict[str, Any]:
    """Return the settings, the scanners, the trackers and their readings, anonymised."""
    runtime = entry.runtime_data
    plan = runtime.store.plan
    scanner_names = {s.key: f"Scanner {i}" for i, s in enumerate(plan.scanners, 1)}
    tracker_names = {t.key: f"Tracker {i}" for i, t in enumerate(plan.trackers, 1)}
    alive = alive_sources(hass)
    positions = runtime.coordinator.data or {}

    def _tracker(index: int) -> dict[str, Any]:
        tracker = plan.trackers[index]
        position = positions.get(tracker.key)
        pairs = {
            scanner_names.get(scanner, "Scanner ?"): by_tracker[tracker.key]
            for scanner, by_tracker in plan.pair_offsets.items()
            if tracker.key in by_tracker
        }
        info: dict[str, Any] = {
            "kind": "fixed address" if tracker.address else "Private BLE Device",
            "height": tracker.height,
            "ref_power": tracker.ref_power,
            "pair_offsets": pairs,
        }
        if position is not None:
            info |= {
                "address_known": position.address is not None,
                "seen": position.seen,
                "present": position.present,
                "x": position.x,
                "y": position.y,
                "in_a_room": bool(position.room),
                "scanner_count": position.scanner_count,
                "readings": {
                    scanner_names.get(key, "Scanner ?"): reading.as_dict()
                    for key, reading in position.readings.items()
                },
            }
        return info

    runs: dict[str, int] = {}
    for run in runtime.calibration.runs:
        name = tracker_names.get(run.tracker, "Tracker ?")
        runs[name] = runs.get(name, 0) + 1
    return {
        "version": runtime.about["version"],
        "options": dict(entry.options),
        "settings": plan.settings.as_dict(),
        "floor_plan": {
            "rooms": sum(1 for r in plan.rooms if not r.zone),
            "zones": sum(1 for r in plan.rooms if r.zone),
            "outdoor": sum(1 for r in plan.rooms if r.outdoor),
            "linked_to_areas": sum(1 for r in plan.rooms if r.area),
            "openings": len(plan.openings),
            "extent": list(plan.extent),
        },
        "scanners": {
            scanner_names[s.key]: {
                "x": s.x,
                "y": s.y,
                "z": s.z,
                "rssi_offset": s.rssi_offset,
                "active": s.source in alive,
            }
            for s in plan.scanners
        },
        "trackers": {tracker_names[t.key]: _tracker(i) for i, t in enumerate(plan.trackers)},
        "calibration": {"running": runtime.calibration.active is not None, "runs": runs},
        "timeline_days": len(runtime.history.days),
    }
