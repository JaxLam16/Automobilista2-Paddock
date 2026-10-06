"""Track edges: mapping laps (wheel surfaces) and the racing-line model, checked against the simulated
circuit's real road (asphalt 5 m either side of the centre line)."""
import numpy as np
import pytest

from ams2season.race import analyze_race
from ams2season.simulate import TRACK, RaceScript, _build_centreline, mapping_drive, run_race
from ams2season.trackmap import (LiveMapper, Ref, list_track_files, load_track_file, load_track_samples,
                                 save_track_samples, save_track_width, track_geometry)

HUMANS = ["Jax", "Mason", "Eli", "Theo"]
HALF = TRACK["asphalt_half"]


@pytest.fixture(scope="module")
def truth():
    s, x, z, h, k = _build_centreline()
    return Ref(s, x, z, TRACK["length"])


@pytest.fixture(scope="module")
def mapped():
    m = LiveMapper()
    for snap, t in mapping_drive():
        m.feed(snap, t)
    return m


@pytest.fixture(scope="module")
def race(tmp_path_factory):
    out = tmp_path_factory.mktemp("tm")
    dirs = run_race(out, HUMANS, RaceScript(laps=5, n_ai=12, spin=("Theo", 2, 1320.0), local_collision_lap=None), seed=12)
    ra = analyze_race(next(d for d in dirs if d.name.endswith("_race")), humans=set(HUMANS))
    laps, fr = ra.laps, ra.frames
    clean = laps[laps.clean]
    name = clean.groupby("name").size().idxmax()
    lp = clean[clean.name == name].iloc[1]
    prev = laps[(laps.name == name) & (laps.lap == lp.lap - 1)]
    seg = fr[(fr.name == name) & (fr.t >= float(prev.t_end.iat[0])) & (fr.t <= float(lp.t_end))]
    normal = {(r.name, int(r.lap) - 1) for r in clean.itertuples()}
    return {"ra": ra, "seg": seg, "normal": normal}


def _errors(g, truth):
    c = (np.arange(len(g["left"])) + 0.5) * 5.0
    lo = truth.offset(c, *np.array(g["left"]).T)
    ro = truth.offset(c, *np.array(g["right"]).T)
    return np.abs(lo - HALF), np.abs(ro + HALF), lo, ro


def test_mapping_laps_find_the_white_lines(mapped, truth):
    st = mapped.status()
    assert st["track"] == "Simtown" and st["coverage"]["left"] >= 95 and st["coverage"]["right"] >= 95
    assert st["calibration"]["left_sign"] == 1.0  # worked out which side is the car's left from steering
    s, _ = mapped.samples()
    for side, target in (("left", HALF), ("right", -HALF)):
        p = s[s.side == side]
        off = truth.offset(p.lap_dist.to_numpy() % TRACK["length"], p.x, p.z)
        assert np.percentile(np.abs(off - target), 95) < 0.25, side


def test_mapped_edges_in_the_replay_geometry(race, mapped, truth):
    s, _ = mapped.samples()
    seg = race["seg"]
    g = track_geometry(race["ra"].frames, seg.lap_dist, seg.x, seg.z, TRACK["length"], normal=race["normal"], samples=s)
    le, re_, _, _ = _errors(g, truth)
    assert g["edges"]["source"] == "mapped"
    assert np.median(le) < 0.1 and np.median(re_) < 0.1 and np.percentile(le, 95) < 0.3 and np.percentile(re_, 95) < 0.3


def test_racing_line_model(race, truth):
    """Without a map: normal laps averaged, apexes on the inside edge, turn-in and exit on the outside."""
    seg = race["seg"]
    g = track_geometry(race["ra"].frames, seg.lap_dist, seg.x, seg.z, TRACK["length"], normal=race["normal"], width=2 * HALF)
    info = g["edges"]["model"]
    assert g["edges"]["source"] == "model" and info["corners"] == 6
    le, re_, lo, ro = _errors(g, truth)
    assert np.median(le) < 0.3 and np.median(re_) < 0.3
    assert np.percentile(le, 95) < 1.2 and np.percentile(re_, 95) < 1.2
    assert np.abs(np.diff(lo, 2)).mean() < 0.06  # smooth, not jagged
    # the right-hander (T3, apex 1300 m) has its inside on the right
    i = int(1300 / 5)
    assert abs(ro[i] + HALF) < 1.0


def test_track_files_round_trip(tmp_path, mapped):
    s, _ = mapped.samples()
    res = save_track_samples(tmp_path, "Simtown", "GP", TRACK["length"], s)
    assert res["coverage"]["left"] >= 95
    save_track_width(tmp_path, "Simtown", "GP", 11.5)
    again = save_track_samples(tmp_path, "Simtown", "GP", TRACK["length"], s.iloc[:10])
    assert load_track_file(tmp_path, "Simtown", "GP")["width"] == 11.5 and again["coverage"]["left"] >= 95
    back = load_track_samples(tmp_path, "Simtown", "GP")
    assert set(back.side) == {"left", "right"} and len(back) > 100
    assert list_track_files(tmp_path)[0]["track"] == "Simtown"
