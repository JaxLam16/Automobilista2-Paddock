"""The race engineer's evidence, checked against real AMS2 telemetry: two Road America runs in the Ferrari
488 GT3, the second with 2 more ticks of rear wing and 2 more of front anti-roll bar."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ams2season.engineer.corners import corner_balance, find_corners, laps_of
from ams2season.engineer.evidence import braking_traction

DATA = Path(__file__).parent / "data" / "engineer"
L = 6440.41


@pytest.fixture(scope="module")
def runs():
    if not DATA.exists():
        pytest.skip("real engineer test data not present")
    return {k: pd.read_parquet(DATA / f"{k}.parquet").sort_values("t") for k in ("ra_ferrari_baseline", "ra_ferrari_wing2_frontarb2")}


def test_sign_conventions(runs):
    lo = runs["ra_ferrari_baseline"]
    mv = lo[lo.speed > 20]
    assert np.corrcoef(mv.steering, mv.yaw_rate)[0, 1] < -0.7      # turning right: steering +, yaw -
    assert mv.acc_long[mv.brake > 0.5].median() > 8                   # braking shows as positive longitudinal g
    assert abs(1 - lo.brake_bias.median() - 0.55) < 1e-6              # AMS2 reports the rear share: garage 55/45


def test_stiffer_front_and_more_rear_wing_read_as_understeer(runs):
    """At the same corners, the second run needs more steering for the curvature it achieves."""
    ref = laps_of(runs["ra_ferrari_baseline"])[0]
    corners = find_corners(ref, L)
    assert 8 <= len(corners) <= 14
    per = {}
    for key, lo in runs.items():
        vals = {}
        for n, g in lo.groupby("local_lap"):
            if n == 0 or len(g) < 200:
                continue
            g = g.sort_values("t")
            inv, d = g.local_lap_invalid.to_numpy(bool), g.lap_dist.to_numpy(float)
            bad = d[np.argmax(inv)] if inv.any() else 1e9
            for name, b in corner_balance(g, corners).items():
                apex = next(c["apex"] for c in corners if c["name"] == name)
                if not (bad - 300 < apex < bad + 600):
                    vals.setdefault(name, []).append(b["steer_per_curv"])
        per[key] = {k: float(np.median(v)) for k, v in vals.items()}
    common = sorted(set(per["ra_ferrari_baseline"]) & set(per["ra_ferrari_wing2_frontarb2"]))
    change = np.array([per["ra_ferrari_wing2_frontarb2"][c] / per["ra_ferrari_baseline"][c] - 1 for c in common])
    assert len(common) >= 8 and np.median(change) > 0.10 and (change > 0).mean() >= 0.7


def test_wheel_slip_calibration(runs):
    for lo in runs.values():
        b = braking_traction(lo)
        r = [b[f"radius_{w}_m"] for w in ("fl", "fr", "rl", "rr")]
        assert all(0.30 < x < 0.38 for x in r) and r[2] > r[0]       # realistic radii, bigger rear tyres
        assert all(b[f"lock_{w}_s"] < 1.0 for w in ("fl", "fr", "rl", "rr"))   # ABS 8: no real lock-ups
        assert b["brake_bias_front"] == 0.55
