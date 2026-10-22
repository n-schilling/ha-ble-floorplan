"""The adjustment gets known parameters back from synthetic runs."""

from __future__ import annotations

import math

import pytest

from custom_components.ble_floorplan.calibration import CalibrationRun
from custom_components.ble_floorplan.solver import CalibrationError, observations, solve

from . import make_plan, synthetic_run

PLAN = make_plan()
# Offsets that sum to zero, as the solver reports them
OFFSETS = {"living": 2.0, "kitchen": -3.0, "bedroom": 1.0}


def _runs(
    attenuation: float = 3.0, pairs: dict[str, dict[str, float]] | None = None
) -> list[CalibrationRun]:
    """Two runs per tracker at different places."""
    pairs = pairs or {}
    return [
        synthetic_run(PLAN, "r1", "tag", 2.0, 2.0, -58.0, OFFSETS, attenuation, pairs.get("tag")),
        synthetic_run(PLAN, "r2", "tag", 7.0, 3.0, -58.0, OFFSETS, attenuation, pairs.get("tag")),
        synthetic_run(
            PLAN, "r3", "phone", 3.0, 7.0, -66.0, OFFSETS, attenuation, pairs.get("phone")
        ),
        synthetic_run(
            PLAN, "r4", "phone", 8.0, 7.0, -66.0, OFFSETS, attenuation, pairs.get("phone")
        ),
    ]


def test_recovers_reference_power_and_offsets() -> None:
    """Reference power per tracker and offset per scanner come back; pairs are zero."""
    proposal = solve(PLAN, _runs(), fit_attenuation=False)
    assert proposal["attenuation"] is None
    assert proposal["trackers"] == {
        "tag": {"old": -60.0, "new": -58.0, "runs": 2, "samples": 30},
        "phone": {"old": -55.0, "new": -66.0, "runs": 2, "samples": 30},
    }
    assert proposal["scanners"] == {
        "living": {"old": 0.0, "new": 2.0, "runs": 4, "samples": 20},
        "kitchen": {"old": 0.0, "new": -3.0, "runs": 4, "samples": 20},
        "bedroom": {"old": 0.0, "new": 1.0, "runs": 4, "samples": 20},
    }
    assert proposal["pairs"]["kitchen"]["phone"] == {
        "old": 0.0,
        "new": 0.0,
        "runs": 2,
        "samples": 10,
    }
    assert all(p["new"] == 0.0 for s in proposal["pairs"].values() for p in s.values())
    assert proposal["rms"]["new"] == 0.0
    assert proposal["rms"]["old"] > 5
    assert proposal["observations"] == 12


def test_recovers_exponent() -> None:
    """With runs at different distances the exponent is fitted as well."""
    proposal = solve(PLAN, _runs(attenuation=2.6), fit_attenuation=True)
    assert proposal["attenuation"] == {"old": 3.0, "new": 2.6}
    assert proposal["trackers"]["tag"]["new"] == -58.0
    assert proposal["scanners"]["kitchen"]["new"] == -3.0
    assert proposal["rms"]["new"] == 0.0


def test_pairs_take_what_the_fit_leaves() -> None:
    """A scanner that hears one tracker louder than the model: the pair gets the rest."""
    runs = _runs(pairs={"phone": {"kitchen": 6.0}})
    proposal = solve(PLAN, runs, fit_attenuation=False)
    # The additive fit of the 2 x 3 table takes a third of the 6 dB into the
    # phone's reference power and half into the kitchen's offset; the pairs
    # carry the interaction that is left, and with it the fit is exact
    assert proposal["trackers"]["tag"]["new"] == -58.0
    assert proposal["trackers"]["phone"]["new"] == -64.0
    assert {k: v["new"] for k, v in proposal["scanners"].items()} == {
        "living": 1.0,
        "kitchen": -1.0,
        "bedroom": 0.0,
    }
    assert {s: {t: p["new"] for t, p in ps.items()} for s, ps in proposal["pairs"].items()} == {
        "living": {"tag": 1.0, "phone": -1.0},
        "kitchen": {"tag": -2.0, "phone": 2.0},
        "bedroom": {"tag": 1.0, "phone": -1.0},
    }
    assert proposal["rms"]["new"] == 0.0
    assert proposal["rms"]["old"] > 0


def test_current_values_are_the_old_ones() -> None:
    """Old values are the plan's, including the default reference power and existing pairs."""
    plan = make_plan(
        scanners=[{**s, "rssi_offset": 1.5} for s in PLAN.as_dict()["scanners"]],
        settings={"attenuation": 2.5, "ref_power_default": -50},
        pair_offsets={"living": {"tag": -2.0}},
    )
    runs = [synthetic_run(plan, "r1", "tag", 2.0, 2.0, -58.0, OFFSETS, 2.5)]
    proposal = solve(plan, runs, fit_attenuation=False)
    assert proposal["trackers"]["tag"]["old"] == -60.0
    assert proposal["scanners"]["living"]["old"] == 1.5
    assert proposal["pairs"]["living"]["tag"]["old"] == -2.0
    assert proposal["pairs"]["living"]["tag"]["new"] == 0.0
    assert proposal["trackers"]["tag"]["new"] == -58.0
    phone_runs = [synthetic_run(plan, "r2", "phone", 3.0, 7.0, -66.0, OFFSETS, 2.5)]
    assert solve(plan, phone_runs, fit_attenuation=False)["trackers"]["phone"]["old"] == -50.0


def test_nothing_usable() -> None:
    """No runs, a run still going, too few samples or unknown keys: nothing to solve."""
    with pytest.raises(CalibrationError, match="no finished run"):
        solve(PLAN, [], fit_attenuation=False)
    running = synthetic_run(PLAN, "r1", "tag", 2.0, 2.0, -58.0, OFFSETS)
    running.duration = None
    few = synthetic_run(PLAN, "r2", "tag", 2.0, 2.0, -58.0, OFFSETS, count=2)
    unknown_tracker = synthetic_run(PLAN, "r3", "tag", 2.0, 2.0, -58.0, OFFSETS)
    unknown_tracker.tracker = "gone"
    unknown_scanner = synthetic_run(PLAN, "r4", "tag", 2.0, 2.0, -58.0, OFFSETS)
    unknown_scanner.samples = {"nowhere": unknown_scanner.samples["living"]}
    assert observations(PLAN, [running, few, unknown_tracker, unknown_scanner]) == []
    with pytest.raises(CalibrationError, match="no finished run"):
        solve(PLAN, [running, few, unknown_tracker, unknown_scanner], fit_attenuation=False)


def test_exponent_needs_different_distances() -> None:
    """One run of one tracker: every scanner at one distance, the exponent is free."""
    runs = [synthetic_run(PLAN, "r1", "tag", 2.0, 2.0, -58.0, OFFSETS)]
    with pytest.raises(CalibrationError, match="different distances"):
        solve(PLAN, runs, fit_attenuation=True)
    proposal = solve(PLAN, runs, fit_attenuation=False)
    assert proposal["trackers"]["tag"]["new"] == -58.0
    assert proposal["scanners"]["living"]["new"] == 2.0


def test_runs_must_connect_trackers_and_scanners() -> None:
    """A tracker heard by one set of scanners and another by a disjoint set: no common gauge."""
    runs = [
        synthetic_run(PLAN, "r1", "tag", 2.0, 2.0, -58.0, OFFSETS, scanners=["living"]),
        synthetic_run(PLAN, "r2", "phone", 8.0, 7.0, -66.0, OFFSETS, scanners=["kitchen"]),
    ]
    with pytest.raises(CalibrationError, match="connect"):
        solve(PLAN, runs, fit_attenuation=False)
    with pytest.raises(CalibrationError, match="connect"):
        solve(PLAN, runs, fit_attenuation=True)


def test_run_at_the_scanner() -> None:
    """A run right at a scanner's place and height counts as 5 cm away: the logarithm is finite."""
    runs = [
        synthetic_run(PLAN, "r1", "tag", 1.0, 1.0, -58.0, OFFSETS, height=0.8),
        synthetic_run(PLAN, "r2", "tag", 5.0, 3.0, -58.0, OFFSETS, height=0.8),
    ]
    obs = observations(PLAN, runs)
    assert min(o.distance for o in obs) == 0.05
    proposal = solve(PLAN, runs, fit_attenuation=True)
    assert proposal["attenuation"]["new"] == 3.0
    assert proposal["trackers"]["tag"]["new"] == -58.0


def test_observation_median_and_height() -> None:
    """The observation is the median of the run; the run's height replaces the tracker's."""
    run = synthetic_run(PLAN, "r1", "tag", 2.0, 2.0, -58.0, OFFSETS, height=1.3, count=4)
    obs = {o.scanner: o for o in observations(PLAN, [run])}
    assert run.height == 1.3
    assert obs["living"].samples == 4
    # 1.3 m above the floor, living's scanner at 0.8 m: the line is a little longer than the floor
    assert obs["living"].distance == pytest.approx((1.0**2 + 1.0**2 + 0.5**2) ** 0.5)
    assert obs["living"].rssi == pytest.approx(
        -58.0 + 2.0 - 30 * math.log10(obs["living"].distance), abs=0.5
    )
