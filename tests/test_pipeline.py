"""Simulator -> real Recorder -> analysis -> season DB, checked against simulator ground truth."""
import json
from datetime import datetime

import numpy as np
import pytest

from ams2season import shm as S
from ams2season.derive import load_session
from ams2season.race import COUNTED, analyze_race
from ams2season.recorder import Recorder
from ams2season.season import SeasonConfig, add_correction, connect, ingest, standings
from ams2season.simulate import DT, RaceScript, RaceSim, run_race

HUMANS = ["Jax", "Mason", "Eli", "Theo"]
SCRIPT = RaceScript(laps=5, n_ai=12, spin=("Mason", 2, 1320.0), pit=(6, 3), retire=(9, 4, 1500.0),
                    disconnect=("Theo", 3, 900.0), with_qualifying=True)


@pytest.fixture(scope="module")
def weekend(tmp_path_factory):
    out = tmp_path_factory.mktemp("rec")
    dirs = run_race(out, HUMANS, SCRIPT, seed=3)
    race = next(d for d in dirs if d.name.endswith("_race"))
    truth = json.loads((race / "truth.json").read_text())
    return {"dirs": dirs, "race": race, "truth": truth, "ra": analyze_race(race, humans=set(HUMANS))}


def test_recorder_splits_and_closes_sessions(weekend):
    names = [d.name for d in weekend["dirs"]]
    assert [n.split("_")[-1] for n in names] == ["qualify", "race"]
    race = weekend["race"]
    assert (race / "frames.parquet").exists() and (race / "local.parquet").exists()
    assert not (race / "frames_parts").exists()
    meta = json.loads((race / "session.json").read_text())
    assert meta["status"] == "complete" and meta["green_t"] is not None
    events = [json.loads(x) for x in (race / "events.jsonl").read_text().splitlines()]
    green = [e for e in events if e["type"] == "green"]
    assert len(green) == 1 and not green[0]["late"] and len(green[0]["grid"]) == 16
    assert any(e["type"] == "leave" and e["name"] == "Theo" for e in events)


def test_classification_and_grid_match_truth(weekend):
    ra, truth = weekend["ra"], weekend["truth"]
    assert list(ra.classification.name) == truth["classification"]
    grid = ra.classification.set_index("name").grid.sort_values()
    assert list(grid.index) == truth["grid"]
    status = ra.classification.set_index("name").status
    assert status["Theo"] == "disconnected"
    assert status[truth["retired"][0]] == "dnf"
    assert (status.drop(["Theo", truth["retired"][0]]) == "finished").all()


def test_laps_and_sectors(weekend):
    ra = weekend["ra"]
    fin = ra.classification[ra.classification.status == "finished"]
    assert (fin.laps == SCRIPT.laps).all()
    laps = ra.laps
    assert laps.game_time.mean() > 0.95  # own timing reconciled with game lap times
    both = laps.dropna(subset=["s1", "s2", "s3"])
    assert len(both) / len(laps) > 0.95
    assert np.allclose(both.s1 + both.s2 + both.s3, both.time, atol=1e-3)
    mason_l2 = laps[(laps.name == "Mason") & (laps.lap == 2)].iloc[0]
    assert not mason_l2.valid and not mason_l2.clean  # the spin lap


def test_passes(weekend):
    ra = weekend["ra"]
    p = ra.passes
    spin_t = next(e["t"] for e in weekend["truth"]["events"] if e["type"] == "spin")
    on_spinner = p[(p.passed == "Mason") & p.t.between(spin_t - 1, spin_t + 8)]
    assert len(on_spinner) >= 5 and (on_spinner.kind == "gifted").all()
    assert set(on_spinner.corner) == {"T3"}  # spin at 1320 m, T3 apex ~1300 m
    pit_car = ra.session.frames.loc[ra.session.frames.pit_mode > 0, "name"].unique()
    assert len(pit_car) == 1
    pit_swaps = p[(p.passed == pit_car[0]) | (p.passer == pit_car[0])]
    assert (pit_swaps[pit_swaps.t.between(180, 245)].kind == "pit_cycle").all()
    counted = p[p.kind.isin(COUNTED)].copy()
    counted["pair"] = [tuple(sorted(x)) for x in zip(counted.passer, counted.passed)]
    assert (counted.groupby("pair").t.diff().dropna() >= 3.0).all()  # flicker never double counts
    # every counted pass is consistent with the stats table
    st = ra.stats.set_index("name")
    assert st.passes_made.sum() == st.passed_by.sum() == len(counted)


def test_pits_battles_corners(weekend):
    ra = weekend["ra"]
    assert len(ra.pits) == 1 and abs(ra.pits.stationary_time.iat[0] - 18.0) < 0.2
    apexes = [c["apex"] for c in ra.corners]
    assert len(apexes) == 6
    assert all(abs(a - b) < 20 for a, b in zip(apexes, [280, 820, 1300, 1900, 2350, 2750]))
    assert len(ra.battles) > 0 and (ra.battles.laps >= 2.0).all()


def test_season_ingest_standings_and_corrections(weekend, tmp_path):
    cfg = SeasonConfig(name="T", drivers=[{"key": h.lower(), "display": h, "aliases": [h]} for h in HUMANS],
                       points={"f1": [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]}, fastest_lap_bonus=0)
    db = tmp_path / "s.db"
    info = ingest(db, cfg, weekend["race"], round_no=1)
    assert sorted(info["humans"]) == sorted(HUMANS) and len(info["ai"]) == 12
    ingest(db, cfg, weekend["race"], round_no=1)  # idempotent re-ingest
    con = connect(db)
    assert con.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM entrant WHERE driver_id IS NULL").fetchone()[0] == 12

    st = standings(con, cfg, policy="humans_only").set_index("driver")
    hum_order = [n for n in weekend["truth"]["classification"] if n in HUMANS]
    finishers = [n for n in hum_order if n != "Theo"]  # disconnected: no points
    for rank, name in enumerate(finishers):
        assert st.loc[name, "points"] == cfg.points["f1"][rank]
    assert st.loc["Theo", "points"] == 0

    ff = standings(con, cfg, policy="full_field").set_index("driver")
    overall = {n: i + 1 for i, n in enumerate(weekend["truth"]["classification"])}
    for name in finishers:
        expect = cfg.points["f1"][overall[name] - 1] if overall[name] <= 10 else 0
        assert ff.loc[name, "points"] == expect

    winner = finishers[0]
    add_correction(db, 1, winner, "position_penalty", 30)
    st2 = standings(con, cfg, policy="humans_only").set_index("driver")
    assert st2.loc[winner, "points"] < st.loc[winner, "points"]
    add_correction(db, 1, finishers[1], "points", -3)
    st3 = standings(con, cfg, policy="humans_only").set_index("driver")
    assert st3.loc[finishers[1], "points"] == cfg.points["f1"][0] - 3  # promoted by the penalty, then docked


def _snapshots(sim: RaceSim, seconds: float, t_green: float = 1.0):
    for _ in range(int(seconds / DT)):
        sim.advance(t_green)
        yield sim.snapshot(S.GAME_INGAME_PLAYING, S.SESSION_RACE)


def test_restart_without_restarting_state_opens_new_session(tmp_path):
    rec = Recorder(tmp_path, hz=20, log=lambda *_: None, wallclock=lambda: datetime(2026, 10, 3, 20, 0))
    now = 0.0
    for snap in _snapshots(RaceSim(HUMANS, RaceScript(n_ai=4), seed=1), 30):
        now += DT
        rec.step(snap, now)
    for snap in _snapshots(RaceSim(HUMANS, RaceScript(n_ai=4), seed=2), 30, t_green=10.0):  # back on the grid
        now += DT
        rec.step(snap, now)
    rec.close(now)
    assert len(rec.completed) == 2
    assert json.loads((rec.completed[0] / "session.json").read_text())["end_reason"] == "restart"


def test_reads_parts_after_recorder_crash(tmp_path):
    rec = Recorder(tmp_path, hz=20, flush_s=5, log=lambda *_: None, wallclock=lambda: datetime(2026, 10, 3, 20, 0))
    now = 0.0
    for snap in _snapshots(RaceSim(HUMANS, RaceScript(n_ai=4), seed=1), 20):
        now += DT
        rec.step(snap, now)
    path = rec.active.path  # never closed: simulates a crash / power cut
    sess = load_session(path)
    assert len(sess.frames) > 8 * 20 * 10 and sess.green_t is not None
    assert sess.meta["status"] == "recording"


def test_menu_flicker_is_not_a_session(tmp_path):
    rec = Recorder(tmp_path, hz=20, grace_s=1.0, log=lambda *_: None)
    sim = RaceSim(HUMANS, RaceScript(n_ai=2), seed=1)
    now = 0.0
    for _ in range(10):  # half a second in-session, then gone
        now += DT
        rec.step(sim.snapshot(S.GAME_INGAME_PLAYING, S.SESSION_RACE), now)
    for _ in range(40):
        now += DT
        rec.step(None, now)
    assert rec.completed == [] and not any(tmp_path.iterdir())
