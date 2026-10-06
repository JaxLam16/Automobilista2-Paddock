"""Teams: validation, team standings (all / best N), colours and teammate battles."""
from ams2season.app import _clean_teams
from ams2season.season import SeasonConfig, connect, driver_colors, ingest, team_standings, teammate_battles
from ams2season.simulate import RaceScript, run_race

HUMANS = ["Jax", "Mason", "Eli", "Theo"]


def test_clean_teams():
    teams = _clean_teams([{"name": "Red", "color": "#ff0000", "icon": "bolt", "members": ["jax", "eli", "ghost"]},
                          {"name": "Blue", "color": "nope", "icon": "unknown", "members": ["jax", "mason"]},
                          {"name": "", "members": ["theo"]}, {"name": "Red", "members": []}],
                         {"jax", "mason", "eli", "theo"})
    assert [t["name"] for t in teams] == ["Red", "Blue", "Red"] and teams[2]["key"] == "red-2"
    assert teams[0]["members"] == ["jax", "eli"] and teams[0]["color"] == "#FF0000"
    assert teams[1]["members"] == ["mason"] and teams[1]["icon"] == "shield" and teams[1]["color"] == "#2E86DE"


def test_team_standings_and_colours(tmp_path):
    cfg = SeasonConfig(drivers=[{"key": h.lower(), "display": h, "aliases": []} for h in HUMANS],
                       teams=[{"key": "a", "name": "A", "color": "#7B2CBF", "icon": "bolt", "members": ["jax", "eli"]},
                              {"key": "b", "name": "B", "color": "#2E86DE", "icon": "shield", "members": ["mason", "theo"]}])
    db = tmp_path / "s.db"
    for rnd in (1, 2):
        dirs = run_race(tmp_path / f"r{rnd}", HUMANS, RaceScript(laps=3, n_ai=4, local_collision_lap=None), seed=rnd)
        ingest(db, cfg, next(d for d in dirs if d.name.endswith("_race")), rnd)
    con = connect(db)
    allpts = team_standings(con, cfg)
    assert set(allpts.name) == {"A", "B"} and allpts.points.sum() == 2 * (25 + 18 + 15 + 12)
    cfg.team_count = 1
    best1 = team_standings(con, cfg)
    assert best1.points.sum() < allpts.points.sum() and all(best1[lab].max() <= 25 for lab in best1.attrs["labels"])
    battles = teammate_battles(con, cfg)
    assert len(battles) == 2 and all(sum(d["ahead"] for d in b["drivers"]) == 2 for b in battles)
    assert driver_colors(cfg)["jax"] != "#7B2CBF"
    cfg.team_colors_for_drivers = True
    c = driver_colors(cfg)
    assert c["jax"] == "#7B2CBF" and c["eli"] != c["jax"] and c["mason"] == "#2E86DE"
