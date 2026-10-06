"""Racing corners: detecting passes made fighting another car, and weighting them in braking / throttle consistency."""
import json
import threading
import urllib.request

import numpy as np
import pandas as pd
import pytest

from ams2season.app import App, _make_server, make_handler
from ams2season.race import analyze_race
from ams2season.simulate import RaceScript, run_race
from ams2season.traffic import racing_flags, weights, wstd

L = 3000.0


def _frames(gap_s, pit_other=False):
    """Two cars at 50 m/s, B `gap_s` behind A, for 60 s."""
    t = np.arange(0, 60, 0.05)
    rows = []
    for name, lag in (("A", 0.0), ("B", gap_s)):
        rows.append(pd.DataFrame({"t": t, "name": name, "dist": 50 * (t - lag) + 500, "speed": 50.0,
                                  "pit_mode": 1 if (pit_other and name == "A") else 0}))
    return pd.concat(rows, ignore_index=True)


def test_racing_flags():
    q = [10.0, 20.0, 30.0]
    assert racing_flags(_frames(0.6), "B", q, L).all()            # following 0.6 s behind
    assert racing_flags(_frames(0.5), "A", q, L).all()            # defending, 0.5 s ahead
    assert not racing_flags(_frames(0.9), "A", q, L).any()        # 0.9 s behind you isn't close enough to defend
    assert not racing_flags(_frames(3.0), "B", q, L).any()        # clear air
    assert not racing_flags(_frames(0.6, pit_other=True), "B", q, L).any()   # a car in the pits doesn't count
    lapped = _frames(0.0)
    lapped.loc[lapped.name == "A", "dist"] += L + 25              # a lap ahead, 25 m up the road: still traffic
    assert racing_flags(lapped, "B", q, L).all()


def test_weights_and_spread():
    flags = [False, False, False, True, True]
    assert list(weights(flags, "equal")) == [1, 1, 1, 1, 1]
    assert list(weights(flags, "reduced")) == [1, 1, 1, 0.25, 0.25]
    assert list(weights(flags, "excluded")) == [1, 1, 1, 0, 0]
    assert list(weights([False, True, True, True], "excluded")) == [1, 1, 1, 1]   # too few clear laps: count them all
    v = [100, 101, 99, 130, 70]                                    # two wild braking points, both in traffic
    assert wstd(v, weights(flags, "excluded")) < 1 < wstd(v, weights(flags, "reduced")) < wstd(v, weights(flags, "equal"))


@pytest.fixture(scope="module")
def race(tmp_path_factory):
    root = tmp_path_factory.mktemp("rc")
    dirs = run_race(root / "recordings", ["Jax", "Mason", "Eli", "Theo"], RaceScript(laps=8, n_ai=12, local_collision_lap=None), seed=7)
    return root, next(d for d in dirs if d.name.endswith("_race"))


def test_driving_metrics_carry_all_three_modes(race):
    _, path = race
    st = analyze_race(path, humans={"Jax", "Mason", "Eli", "Theo"}).stats.set_index("name")
    for m in ("equal", "reduced", "excluded"):
        assert st[f"brake_consistency_{m}"].notna().sum() > 10 and st[f"throttle_consistency_{m}"].notna().sum() > 10
    assert st.racing_share.between(0, 100).all() and st.racing_share.max() > 20
    assert (st.brake_consistency == st.brake_consistency_reduced).all()          # the default mode
    some = st[(st.racing_share > 20) & (st.racing_share < 80)]
    assert len(some) and (some.brake_consistency_excluded != some.brake_consistency_equal).any()
    ex = analyze_race(path, humans={"Jax"}, racing_mode="excluded").stats.set_index("name")
    assert (ex.brake_consistency == ex.brake_consistency_excluded).all()


def test_technique_page_and_setting(race):
    root, path = race
    app = App(root)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"

    def call(m, p, body=None):
        req = urllib.request.Request(base + p.lstrip("/"), method=m, headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    try:
        _, tq = call("GET", f"/api/technique?recording={path.name}")
        d = next(x for x in tq["drivers"] if x.get("available"))
        assert d["racing_mode"] == "reduced" and set(d["summary_by_mode"]) == {"equal", "reduced", "excluded"}
        assert d["racing_passes"] > 0 and d["passes"] >= d["racing_passes"]
        c = d["corners"][0]
        assert set(c["scores_by_mode"]) == {"equal", "reduced", "excluded"} and all("racing" in l for l in c["laps"])
        assert call("POST", "/api/settings", {"racing_corners": "sideways"})[0] == 400
        assert call("POST", "/api/settings", {"racing_corners": "excluded"})[0] == 200
        _, tq2 = call("GET", f"/api/technique?recording={path.name}")
        assert next(x for x in tq2["drivers"] if x.get("available"))["racing_mode"] == "excluded"   # re-analysed with the new setting
    finally:
        srv.shutdown()
