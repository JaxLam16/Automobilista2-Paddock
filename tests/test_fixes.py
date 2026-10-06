"""Regression tests for reported bugs: empty-roster championships, the window lifecycle, corner detection,
battle gaps, lap-1 'gifted' passes, jagged mapped edges and navigation back to the race."""
import json
from pathlib import Path
import math
import sqlite3
import threading
import time
import urllib.request

import numpy as np
import pandas as pd
import pytest

from ams2season.app import App, _make_server, make_handler
from ams2season.derive import curvature_profile, detect_corners
from ams2season.race import analyze_race
from ams2season.season import connect
from ams2season.simulate import TRACK, RaceScript, _build_centreline, mapping_drive, run_race, v_ref
from ams2season.trackmap import LiveMapper, Ref, track_geometry

HUMANS = ["Jax", "Mason", "Eli", "Theo"]


def _server(root):
    app = App(root)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"

    def call(method, path, body=None):
        req = urllib.request.Request(base + path.lstrip("/"), method=method, headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers.get_content_type() == "application/json" else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    return app, srv, call


def test_championship_with_no_matching_drivers(tmp_path):
    """Filing a race before the roster matches used to break the championship page and home ("points")."""
    run_race(tmp_path / "recordings", ["Jax", "Mason"], RaceScript(laps=3, n_ai=5, local_collision_lap=None), seed=3)
    app, srv, call = _server(tmp_path)
    try:
        race = next(r["id"] for r in call("GET", "/api/recordings")[1]["recordings"] if r["type"] == "race")
        for name, drivers in (("No roster", []), ("Wrong names", [{"display": "Somebody", "aliases": []}])):
            cid = call("POST", "/api/championships", {"name": name})[1]["id"]
            if drivers:
                call("PUT", f"/api/championships/{cid}", {"drivers": drivers, "teams": [{"name": "T", "members": ["somebody"]}]})
            assert call("POST", f"/api/championships/{cid}/rounds", {"recording": race, "round": 1})[0] == 200
            status, d = call("GET", f"/api/championships/{cid}")
            assert status == 200 and d["standings"]["humans_only"]["rows"] == []
            assert call("GET", f"/api/replay?recording={race}&champ={cid}")[0] == 200
            assert call("GET", f"/report?recording={race}&champ={cid}")[0] == 200
        assert call("GET", "/api/home")[0] == 200
        assert call("GET", "/api/championships/does-not-exist")[0] == 404  # real "not found" still is
    finally:
        srv.shutdown()


def test_window_lifecycle(tmp_path):
    """Quit when the window closes; never because the browser throttled or slept a background window."""
    a = App(tmp_path)
    now = time.monotonic()
    a.last_heartbeat, a.closing_at = now - 600, None
    assert not a.should_quit()                       # hidden and throttled for 10 minutes
    a.last_heartbeat, a.closing_at = now - 21, now - 20
    assert a.should_quit()                           # closed 20 s ago
    a.last_heartbeat, a.closing_at = now - 5, now - 20
    assert not a.should_quit()                       # reloaded: heartbeat after the close signal
    a.last_heartbeat, a.closing_at = now - 4 * 3600, None
    assert a.should_quit()                           # silent for hours (crash fallback)
    a.recorder.status = lambda: {"state": "recording"}
    assert not a.should_quit()                       # never mid-recording


def _synthetic_track():
    segs = [(400, 0), (0, 1 / 40, 120), (300, 0), (0, 1 / 60, 50), (0, -1 / 60, 50), (200, 0), (0, -1 / 90, 80),
            (0, 1 / 90, 80), (0, -1 / 90, 80), (350, 0), (0, 1 / 300, 60), (300, 0), (0, 1 / 70, 70), (40, 0), (0, 1 / 70, 70), (500, 0)]
    kap = []
    for sg in segs:
        kap += [0.0] * sg[0] if len(sg) == 2 else [sg[1]] * sg[2]
    kap = np.array(kap)
    kap[-300:] += (2 * math.pi - kap.sum()) / 300
    th = np.cumsum(kap)
    X, Z, n = np.cumsum(np.cos(th)), np.cumsum(np.sin(th)), len(kap)
    spd = 70 - 45 * np.minimum(1, np.abs(np.convolve(kap, np.ones(60) / 60, "same")) * 40)
    prof = np.array([spd[min(n - 1, i * 10 + 5)] for i in range(int(n / 10))])
    return prof, curvature_profile(np.arange(n), X, Z, float(n))


def test_corners_from_track_shape():
    """Kinks, chicanes and esses are separate turns (speed alone found only 6 here)."""
    prof, kap = _synthetic_track()
    cs = detect_corners(prof, curvature=kap)
    dirs = [c["dir"][0] for c in cs]
    assert len(cs) >= 10 and len(cs) >= len(detect_corners(prof)) + 3  # speed alone misses kinks and merges chicanes
    assert dirs[:9] == ["l", "l", "r", "r", "l", "r", "l", "l", "l"]  # hairpin, chicane, esses, kink, double apex
    assert cs[2]["apex"] - cs[1]["apex"] >= 40                        # chicane halves have their own apexes
    assert cs[6]["radius"] > 250                                      # the flat-out kink
    s, x, z, h, k = _build_centreline()
    prof2 = np.array([v_ref(i * 10 + 5) for i in range(int(TRACK["length"] / 10))])
    sim = detect_corners(prof2, curvature=curvature_profile(s, x, z, TRACK["length"]))
    assert [round(c["apex"] / 10) * 10 for c in sim] == [280, 820, 1300, 1900, 2350, 2750] or \
        all(abs(c["apex"] - a) <= 10 for c, (a, _) in zip(sim, TRACK["corners"]))
    assert [c["dir"] for c in sim] == ["left", "left", "right", "left", "left", "left"]


@pytest.fixture(scope="module")
def raced(tmp_path_factory):
    d = tmp_path_factory.mktemp("fx")
    out = {}
    for label, kw in (("normal", {}), ("mass", {"mass_invalid_at_start": True}),
                      ("spin", {"spin": ("Theo", 2, 1320.0)})):
        dirs = run_race(d / label, HUMANS, RaceScript(laps=4, n_ai=12, local_collision_lap=None, **kw), seed=4)
        out[label] = analyze_race(next(x for x in dirs if x.name.endswith("_race")), humans=set(HUMANS))
    return out


def test_lap_one_passes_are_not_gifted(raced):
    for label in ("normal", "mass"):  # also when the game invalidates the whole field's first lap at once
        lap1 = raced[label].passes[raced[label].passes.lap == 1]
        assert len(lap1) > 5 and (lap1.kind == "clean").all(), label
    spun = raced["spin"].passes
    on_theo = spun[(spun.passed == "Theo") & (spun.lap == 2)]
    assert len(on_theo) and (on_theo.kind == "gifted").all()  # a real spin still counts as gifted


def test_battles_report_average_gap(raced, tmp_path):
    b = raced["normal"].battles
    assert len(b) and (b.avg_gap_s >= b.min_gap_s).all() and (b.avg_gap_s > 0.05).all()
    old = tmp_path / "old.db"  # a season database from before battles had an average gap
    con = sqlite3.connect(old)
    con.execute("CREATE TABLE battle(session_id INTEGER, a_id INTEGER, b_id INTEGER, start_lap INTEGER, end_lap INTEGER, "
                "laps REAL, duration_s REAL, min_gap_s REAL, swaps INTEGER, winner_id INTEGER)")
    con.commit()
    con.close()
    assert "avg_gap_s" in {r["name"] for r in connect(old).execute("PRAGMA table_info(battle)")}


def test_mapped_edges_smooth_despite_gaps_and_strays(raced):
    """~96% coverage plus stray points used to leave notches; edges must stay smooth and accurate."""
    s_, cx, cz, _, _ = _build_centreline()
    truth = Ref(s_, cx, cz, TRACK["length"])
    m = LiveMapper()
    for snap, t in mapping_drive():
        m.feed(snap, t)
    samples, _ = m.samples()
    L = TRACK["length"]
    keep = np.ones(len(samples), bool)
    for a, b, side in ((400, 470, "left"), (1500, 1540, "right"), (2200, 2235, "left")):
        keep &= ~((samples.lap_dist % L >= a) & (samples.lap_dist % L <= b) & (samples.side == side))
    noisy = samples[keep].copy()
    stray = noisy.sample(frac=0.08, random_state=1).copy()
    nx, nz = truth.at(stray.lap_dist.to_numpy() % L)[2:]
    push = np.random.default_rng(3).choice([-1, 1], len(stray)) * np.random.default_rng(4).uniform(2, 3, len(stray))
    stray["x"] += push * nx
    stray["z"] += push * nz
    noisy = pd.concat([noisy, stray], ignore_index=True)
    ra = raced["normal"]
    fr, laps = ra.frames, ra.laps
    clean = laps[laps.clean]
    name = clean.groupby("name").size().idxmax()
    lp = clean[clean.name == name].iloc[1]
    prev = laps[(laps.name == name) & (laps.lap == lp.lap - 1)]
    seg = fr[(fr.name == name) & (fr.t >= float(prev.t_end.iat[0])) & (fr.t <= float(lp.t_end))]
    g = track_geometry(fr, seg.lap_dist, seg.x, seg.z, L, normal={(r.name, int(r.lap) - 1) for r in clean.itertuples()}, samples=noisy)
    c = (np.arange(len(g["left"])) + 0.5) * 5.0
    for side, target in (("left", 5.0), ("right", -5.0)):
        off = truth.offset(c, *np.array(g[side]).T)
        assert np.abs(np.diff(np.r_[off, off[:1]])).max() < 0.4, side
        assert np.abs(off - target).max() < 0.7 and np.median(np.abs(off - target)) < 0.1, side


def test_back_to_the_race_links(tmp_path):
    run_race(tmp_path / "recordings", HUMANS, RaceScript(laps=3, n_ai=5, with_qualifying=True, local_collision_lap=None), seed=6)
    app, srv, call = _server(tmp_path)
    try:
        recs = call("GET", "/api/recordings")[1]["recordings"]
        q = next(r["id"] for r in recs if r["type"] == "qualify")
        race = next(r["id"] for r in recs if r["type"] == "race")
        assert call("GET", f"/api/quali?recording={q}")[1]["race"]["id"] == race
        tq = call("GET", f"/api/technique?recording={q}")[1]
        assert tq["race"]["id"] == race
        tr = call("GET", f"/api/technique?recording={race}")[1]
        assert tr["race"]["id"] == race
        jax = next(d for d in tr["drivers"] if d.get("available"))
        assert jax["map"]["points"] and len(jax["map"]["corners"]) == len(jax["corners"])  # turn map data
    finally:
        srv.shutdown()


def test_no_skinny_stretches_from_false_edges(raced):
    """Surface changes inside the road (paint, patches) give false edge points that used to pull the edges in
    and make the track skinny for no reason. Width must stay close to the real width everywhere."""
    s_, cx, cz, _, _ = _build_centreline()
    truth = Ref(s_, cx, cz, TRACK["length"])
    L = TRACK["length"]
    m = LiveMapper()
    for snap, t in mapping_drive():
        m.feed(snap, t)
    samples, _ = m.samples()
    rng = np.random.default_rng(5)
    fake = []
    for a, b, side in ((700, 820, "left"), (1650, 1800, "right"), (2400, 2480, "left"), (150, 230, "right")):
        sel = samples[(samples.side == side) & (samples.lap_dist % L >= a) & (samples.lap_dist % L <= b)]
        f = pd.concat([sel] * 3, ignore_index=True).copy()
        nx, nz = truth.at(f.lap_dist.to_numpy() % L)[2:]
        push = rng.uniform(2, 5, len(f)) * (-1 if side == "left" else 1)
        f["x"] += push * nx
        f["z"] += push * nz
        fake.append(f)
    ra = raced["normal"]
    fr, laps = ra.frames, ra.laps
    clean = laps[laps.clean]
    name = clean.groupby("name").size().idxmax()
    lp = clean[clean.name == name].iloc[1]
    prev = laps[(laps.name == name) & (laps.lap == lp.lap - 1)]
    seg = fr[(fr.name == name) & (fr.t >= float(prev.t_end.iat[0])) & (fr.t <= float(lp.t_end))]
    g = track_geometry(fr, seg.lap_dist, seg.x, seg.z, L, normal={(r.name, int(r.lap) - 1) for r in clean.itertuples()},
                       samples=pd.concat([samples] + fake, ignore_index=True))
    c = (np.arange(len(g["left"])) + 0.5) * 5.0
    lo, ro = truth.offset(c, *np.array(g["left"]).T), truth.offset(c, *np.array(g["right"]).T)
    assert (lo - ro).min() > 0.9 * 2 * 5.0
    assert np.abs(lo - 5).max() < 0.8 and np.abs(ro + 5).max() < 0.8


def _apex_setup(raced):
    s_, cx, cz, _, _ = _build_centreline()
    truth = Ref(s_, cx, cz, TRACK["length"])
    m = LiveMapper()
    for snap, t in mapping_drive():
        m.feed(snap, t)
    mapped, _ = m.samples()
    ra = raced["normal"]
    fr, laps = ra.frames, ra.laps
    clean = laps[laps.clean]
    name = clean.groupby("name").size().idxmax()
    lp = clean[clean.name == name].iloc[1]
    prev = laps[(laps.name == name) & (laps.lap == lp.lap - 1)]
    seg = fr[(fr.name == name) & (fr.t >= float(prev.t_end.iat[0])) & (fr.t <= float(lp.t_end))]
    normal = {(r.name, int(r.lap) - 1) for r in clean.itertuples()}
    return truth, mapped, fr, seg, normal


def _pushed(truth, df, a, b, side, lo, hi, rng):
    L = TRACK["length"]
    sel = df[(df.side == side) & (df.lap_dist % L >= a) & (df.lap_dist % L <= b)]
    f = pd.concat([sel] * 3, ignore_index=True).copy()
    nx, nz = truth.at(f.lap_dist.to_numpy() % L)[2:]
    k = rng.uniform(lo, hi, len(f)) * (1 if side == "left" else -1)  # outward, past the real edge
    f["x"] += k * nx
    f["z"] += k * nz
    return f


def _worst_near(truth, g, apex):
    c = (np.arange(len(g["left"])) + 0.5) * 5.0
    lo, ro = truth.offset(c, *np.array(g["left"]).T), truth.offset(c, *np.array(g["right"]).T)
    w = slice(max(0, int(apex / 5) - 30), int(apex / 5) + 30)
    return max(np.abs(lo[w] - 5).max(), np.abs(ro[w] + 5).max())


def test_corners_by_the_line_keep_their_apexes(raced):
    """T1 and the last turn sit either side of the start/finish line. Racing laps that cut them, and a mapping
    recorded with a slightly different lap length, must still leave the apex at the inside edge."""
    truth, mapped, fr, seg, normal = _apex_setup(raced)
    L = TRACK["length"]
    rng = np.random.default_rng(1)
    corners = (280, 2750)
    geo = lambda **kw: track_geometry(fr, seg.lap_dist, seg.x, seg.z, L, normal=normal, **kw)
    clean = {a: _worst_near(truth, geo(samples=mapped), a) for a in corners}
    assert max(clean.values()) < 0.8  # the simulated mapping drive jumps edges right after the line
    racing = pd.concat([mapped.sample(frac=0.3, random_state=2)] + [_pushed(truth, mapped, a - 60, a + 80, "left", 4, 6, rng) for a in corners],
                       ignore_index=True)
    g = geo(samples=mapped, extra_samples=racing)          # racing laps only fill gaps in a mapping
    assert all(_worst_near(truth, g, a) < clean[a] + 0.1 for a in corners)
    stretched = mapped.assign(lap_dist=mapped.lap_dist * 1.01)
    stretched.attrs["length"] = L * 1.01
    g = geo(samples=stretched)                              # rescaled to this lap's length
    assert all(_worst_near(truth, g, a) < clean[a] + 0.1 for a in corners)



RBR = Path(__file__).parent / "data" / "rbr"


@pytest.mark.skipif(not RBR.exists(), reason="real Red Bull Ring recording not present")
def test_real_red_bull_ring_apexes():
    """Real data (a mapped Red Bull Ring and a 21-car qualifying session): at every corner the cars must get
    close to the drawn inside edge at the apex. Used to be 11 m away at T1 and 9 m at the final turn."""
    from ams2season.quali import analyze_qualifying
    from ams2season.trackmap import load_track_samples
    rec = RBR / "recordings" / "20261003-152233_Spielberg_qualify"
    qa = analyze_qualifying(rec, humans={"Jax_Lam"}, track_samples=load_track_samples(RBR, "Spielberg", "Spielberg_Modern"),
                            track_width=12.0)
    g, L = qa.geometry, qa.L
    pole = qa.best[qa.classification.name.iat[0]]
    ref = Ref(np.arange(0, L, 2.0), pole["x"], pole["z"], L)
    fr = qa.session.frames
    fr = fr[(fr.speed > 20) & (fr.pit_mode == 0)]
    off = ref.offset(fr.lap_dist.to_numpy() % L, fr.x, fr.z)
    assert len(qa.corners) == 8
    for c in qa.corners:
        closest = []
        for d0 in range(-40, 41, 5):  # the geometric apex: where the cars get closest to the inside edge
            a = (c["apex"] + d0) % L
            near = np.abs(((fr.lap_dist.to_numpy() - a) + L / 2) % L - L / 2) < 3
            if not near.any():
                continue
            b = int(a / 5) % len(g["offsets"]["left"])
            inside = g["offsets"]["right"][b] if c["dir"] == "right" else g["offsets"]["left"][b]
            closest.append(abs(np.median(off[near]) - inside))
        assert min(closest) < 3.0, (c["name"], round(min(closest), 1))
