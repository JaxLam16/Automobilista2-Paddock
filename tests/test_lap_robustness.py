"""Regression for 'fastest lap 0.000': real recordings can contain things the clean simulator didn't.
Each scenario must still give real lap times, correct lap counts and the true finishing order."""
import pytest

from ams2season.race import analyze_race
from ams2season.awards import race_awards
from ams2season.simulate import RaceScript, run_race

HUMANS = ["Jax", "Mason", "Eli", "Theo"]
SCENARIOS = {
    "lap distance flickers to 0": dict(glitch_rate=0.003),
    "wrong reported track length": dict(report_track_length=1500.0),
    "grid run counted as a lap": dict(count_grid_lap=True),
    "all of the above": dict(glitch_rate=0.003, report_track_length=1500.0, count_grid_lap=True),
}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_lap_times_survive_real_world_quirks(name, tmp_path):
    script = RaceScript(laps=4, n_ai=6, local_collision_lap=None, **SCENARIOS[name])
    dirs = run_race(tmp_path, HUMANS, script, seed=31)
    race = next(d for d in dirs if d.name.endswith("_race"))
    import json
    truth = json.loads((race / "truth.json").read_text())
    ra = analyze_race(race, humans=set(HUMANS))

    assert list(ra.classification.name) == truth["classification"], name
    fin = ra.classification[ra.classification.status == "finished"]
    assert (fin.laps == 4).all(), name
    valid = ra.laps[ra.laps.valid]
    assert valid.time.min() > 50, f"{name}: implausible lap {valid.time.min():.3f}s"
    assert ra.laps.time.max() < 200, name
    st = ra.stats.dropna(subset=["median_clean"])
    assert (st.median_clean > 50).all(), name
    for a in race_awards(ra):
        if a["id"] in ("fastest_lap", "race_pace", "ultimate_lap", "final_lap_flyer"):
            assert not a["value"].startswith("0."), f"{name}: {a['title']} = {a['value']}"
