"""The adjustment over the calibration runs.

The path loss model `rssi = ref_t + off_s - 10 n log10(d)` is linear in the
reference power of every tracker, the offset of every scanner and the exponent
n, once the true distance d of a run is known. One observation per run and
scanner (the median RSSI of the run) goes into a least-squares fit; the
scanners' offsets are made to average zero, because only the sum of a
tracker's reference power and a scanner's offset is observable. What the fit
leaves per pair scanner x tracker is the pair's correction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
import statistics
from typing import Any

from .calibration import CalibrationRun
from .const import CALIBRATION_MIN_DISTANCE, CALIBRATION_MIN_SAMPLES
from .model import Floorplan

# Pivots below this share of the largest entry count as zero
_SINGULAR = 1e-9


class CalibrationError(Exception):
    """The runs do not determine the parameters."""


@dataclass(frozen=True, slots=True)
class Observation:
    """What one run says about one scanner."""

    tracker: str
    scanner: str
    run_id: str
    # Median RSSI of the run at this scanner in dBm
    rssi: float
    # Line-of-sight distance between the tracker and the scanner in metres
    distance: float
    samples: int

    @property
    def path(self) -> float:
        """Return the path loss term 10 log10(d), without the exponent."""
        return 10 * math.log10(self.distance)


def observations(plan: Floorplan, runs: Sequence[CalibrationRun]) -> list[Observation]:
    """Return one observation per finished run and scanner with enough samples."""
    result: list[Observation] = []
    for run in runs:
        if run.running or (tracker := plan.tracker(run.tracker)) is None:
            continue
        for scanner_key, samples in run.samples.items():
            if (scanner := plan.scanner(scanner_key)) is None:
                continue
            if len(samples) < CALIBRATION_MIN_SAMPLES:
                continue
            distance = max(
                math.sqrt(
                    (run.x - scanner.x) ** 2
                    + (run.y - scanner.y) ** 2
                    + (scanner.z - run.height) ** 2
                ),
                CALIBRATION_MIN_DISTANCE,
            )
            rssi = float(statistics.median(s[1] for s in samples))
            result.append(
                Observation(tracker.key, scanner.key, run.id, rssi, distance, len(samples))
            )
    return result


def _solve_linear(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Solve the square system by Gauss-Jordan elimination with partial pivoting."""
    n = len(rhs)
    a = [[*row, rhs[i]] for i, row in enumerate(matrix)]
    scale = max(abs(v) for row in matrix for v in row)
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) <= _SINGULAR * scale:
            raise CalibrationError("underdetermined")
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(n):
            if r == col or a[r][col] == 0.0:
                continue
            f = a[r][col] / a[col][col]
            for c in range(col, n + 1):
                a[r][c] -= f * a[col][c]
    return [a[i][n] / a[i][i] for i in range(n)]


def _fit(
    obs: Sequence[Observation],
    trackers: Sequence[str],
    scanners: Sequence[str],
    attenuation: float | None,
) -> tuple[dict[str, float], dict[str, float], float]:
    """Least squares over the observations; attenuation None fits the exponent as well.

    Returns the reference power per tracker, the offset per scanner (summing to
    zero) and the exponent.
    """
    t_index = {key: i for i, key in enumerate(trackers)}
    s_index = {key: len(trackers) + i for i, key in enumerate(scanners)}
    fit_n = attenuation is None
    size = len(trackers) + len(scanners) + (1 if fit_n else 0)
    # Normal equations A^T A x = A^T b, plus the constraint sum(off) = 0 as a
    # Lagrange multiplier in the last row and column
    normal = [[0.0] * (size + 1) for _ in range(size + 1)]
    rhs = [0.0] * (size + 1)
    for o in obs:
        row = [0.0] * size
        row[t_index[o.tracker]] = 1.0
        row[s_index[o.scanner]] = 1.0
        if attenuation is None:
            row[size - 1] = -o.path
            value = o.rssi
        else:
            value = o.rssi + attenuation * o.path
        for i in range(size):
            if row[i] == 0.0:
                continue
            rhs[i] += row[i] * value
            for j in range(size):
                normal[i][j] += row[i] * row[j]
    for key in scanners:
        normal[s_index[key]][size] = 1.0
        normal[size][s_index[key]] = 1.0
    x = _solve_linear(normal, rhs)
    ref = {key: x[t_index[key]] for key in trackers}
    off = {key: x[s_index[key]] for key in scanners}
    n = x[size - 1] if fit_n else attenuation
    assert n is not None
    return ref, off, n


def _residual(
    o: Observation,
    ref: float,
    off: float,
    pair: float,
    attenuation: float,
) -> float:
    """Return measured minus modelled RSSI."""
    return o.rssi - (ref + off + pair - attenuation * o.path)


def _rms(values: Sequence[float]) -> float:
    return math.sqrt(sum(v * v for v in values) / len(values))


def solve(plan: Floorplan, runs: Sequence[CalibrationRun], fit_attenuation: bool) -> dict[str, Any]:
    """Return the proposal: old and new value of every parameter the runs determine.

    Raises CalibrationError without usable runs or when the runs leave the
    parameters undetermined.
    """
    obs = observations(plan, runs)
    if not obs:
        raise CalibrationError(
            f"no finished run with at least {CALIBRATION_MIN_SAMPLES} samples of a scanner"
        )
    trackers = [t.key for t in plan.trackers if any(o.tracker == t.key for o in obs)]
    scanners = [s.key for s in plan.scanners if any(o.scanner == s.key for o in obs)]
    current_n = plan.settings.attenuation
    try:
        ref, off, n = _fit(obs, trackers, scanners, None if fit_attenuation else current_n)
    except CalibrationError:
        if fit_attenuation:
            try:
                _fit(obs, trackers, scanners, current_n)
            except CalibrationError:
                pass
            else:
                raise CalibrationError(
                    "the exponent needs runs at different distances from a scanner"
                ) from None
        raise CalibrationError("the runs do not connect every tracker with every scanner") from None
    n = round(n, 2)
    ref = {key: round(v, 1) for key, v in ref.items()}
    off = {key: round(v, 1) for key, v in off.items()}

    # What the fit leaves per pair is the pair's correction
    pair_residuals: dict[tuple[str, str], list[float]] = {}
    pair_samples: dict[tuple[str, str], int] = {}
    for o in obs:
        r = _residual(o, ref[o.tracker], off[o.scanner], 0.0, n)
        pair_residuals.setdefault((o.scanner, o.tracker), []).append(r)
        pair_samples[(o.scanner, o.tracker)] = (
            pair_samples.get((o.scanner, o.tracker), 0) + o.samples
        )
    pairs: dict[str, dict[str, dict[str, Any]]] = {}
    new_pair: dict[tuple[str, str], float] = {}
    for (scanner, tracker), values in pair_residuals.items():
        new_pair[(scanner, tracker)] = round(sum(values) / len(values), 1)
        pairs.setdefault(scanner, {})[tracker] = {
            "old": plan.pair_offset(scanner, tracker),
            "new": new_pair[(scanner, tracker)],
            "runs": len(values),
            "samples": pair_samples[(scanner, tracker)],
        }

    old_residuals = []
    new_residuals = []
    for o in obs:
        t = plan.tracker(o.tracker)
        s = plan.scanner(o.scanner)
        assert t is not None and s is not None
        old_residuals.append(
            _residual(
                o,
                plan.ref_power(t),
                s.rssi_offset,
                plan.pair_offset(o.scanner, o.tracker),
                current_n,
            )
        )
        new_residuals.append(
            _residual(o, ref[o.tracker], off[o.scanner], new_pair[(o.scanner, o.tracker)], n)
        )

    def _counts(select: str) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {}
        seen: dict[str, set[str]] = {}
        for o in obs:
            key = getattr(o, select)
            entry = counts.setdefault(key, {"runs": 0, "samples": 0})
            entry["samples"] += o.samples
            seen.setdefault(key, set()).add(o.run_id)
        for key, entry in counts.items():
            entry["runs"] = len(seen[key])
        return counts

    tracker_counts = _counts("tracker")
    scanner_counts = _counts("scanner")
    return {
        "attenuation": {"old": current_n, "new": n} if fit_attenuation else None,
        "trackers": {
            t.key: {"old": plan.ref_power(t), "new": ref[t.key], **tracker_counts[t.key]}
            for t in plan.trackers
            if t.key in ref
        },
        "scanners": {
            s.key: {"old": s.rssi_offset, "new": off[s.key], **scanner_counts[s.key]}
            for s in plan.scanners
            if s.key in off
        },
        "pairs": pairs,
        "rms": {"old": round(_rms(old_residuals), 2), "new": round(_rms(new_residuals), 2)},
        "observations": len(obs),
    }
