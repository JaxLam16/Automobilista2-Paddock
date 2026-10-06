"""App backend: championship workflow over real HTTP, safety checks, and the recorder service."""
import http.client
import json
import threading
import time
from datetime import datetime, timedelta

import pytest

from ams2season import shm as S
from ams2season.app import App, make_handler, _make_server
from ams2season.simulate import RaceScript, RaceSim, run_race

HUMANS = ["Jax", "Mason", "Eli", "Theo"]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("app")
    rec = root / "recordings"
    for i in range(3):  # three race weekends, a week apart
        run_race(rec, HUMANS, RaceScript(laps=4, n_ai=6 + i, spin=("Mason", 2, 1320.0)), seed=20 + i,
                 start=datetime(2026, 10, 3, 20) + timedelta(days=7 * i))
    app = App(root)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield app, srv.server_address[1]
    srv.shutdown()


def call(port, method, path, body=None, host="127.0.0.1"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.request(method, path, body=json.dumps(body) if body is not None else None,
              headers={"Host": f"{host}:{port}", "Content-Type": "application/json"})
    r = c.getresponse()
    data = r.read()
    return r.status, (json.loads(data) if r.getheader("Content-Type", "").startswith("application/json") else data)


def test_championship_workflow(server):
    app, port = server
    status, recs = call(port, "GET", "/api/recordings")
    races = sorted((r for r in recs["recordings"] if r["type"] == "race"), key=lambda r: r["started_at"])
    assert status == 200 and len(races) == 3

    _, sug = call(port, "GET", "/api/suggestions")
    assert {s["name"] for s in sug["names"]} >= set(HUMANS)  # humans recur, random AI names don't

    _, created = call(port, "POST", "/api/championships", {"name": "Friday Night GT3"})
    cid = created["id"]
    status, res = call(port, "PUT", f"/api/championships/{cid}",
                       {"drivers": [{"display": h, "aliases": ""} for h in HUMANS]})
    assert status == 200 and res["reanalysed"]

    for i, r in enumerate(races):
        status, info = call(port, "POST", f"/api/championships/{cid}/rounds", {"recording": r["id"], "round": i + 1})
        assert status == 200 and sorted(info["humans"]) == sorted(HUMANS)

    _, d = call(port, "GET", f"/api/championships/{cid}")
    assert [r["round"] for r in d["rounds"]] == [1, 2, 3]
    st = d["standings"]["humans_only"]["rows"]
    assert len(st) == 4 and st[0]["points"] >= st[-1]["points"]
    assert set(d["progression"]["humans_only"]["series"]) == set(HUMANS)
    assert len(d["h2h"]["names"]) == 4 and len(d["awards"]) >= 10
    assert all(a["group"] and a["detail"] for a in d["awards"])

    # penalty changes standings, removing it restores them
    leader = st[0]["driver"]
    call(port, "POST", f"/api/championships/{cid}/corrections", {"round": 1, "driver": leader, "kind": "points", "value": -100})
    _, d2 = call(port, "GET", f"/api/championships/{cid}")
    assert d2["standings"]["humans_only"]["rows"][0]["driver"] != leader
    call(port, "DELETE", f"/api/championships/{cid}/corrections/{d2['corrections'][0]['id']}")

    # roster change re-analyses: drop Theo -> he becomes AI everywhere
    call(port, "PUT", f"/api/championships/{cid}", {"drivers": [{"display": h} for h in HUMANS[:3]]})
    _, d3 = call(port, "GET", f"/api/championships/{cid}")
    assert {r["driver"] for r in d3["standings"]["humans_only"]["rows"]} == set(HUMANS[:3])

    # race report renders inside the app, with Watch buttons enabled
    status, page = call(port, "GET", f"/report?recording={races[0]['id']}&champ={cid}")
    assert status == 200 and b'id="data"' in page and b'"embedded":true' in page

    # replay payload: every car on a shared timeline, pass events, track
    status, rp = call(port, "GET", f"/api/replay?recording={races[0]['id']}&champ={cid}")
    assert status == 200 and rp["n"] > 100 and len(rp["drivers"]) == len(rp["cars"])
    car = rp["cars"][rp["drivers"][0]["name"]]
    assert len(car["x"]) == rp["n"] and sum(v is not None for v in car["x"]) > rp["n"] * 0.9
    assert rp["passes"] and rp["track"]["points"] and rp["lap_marks"]

    # your own top-down car icons, matched by car name and served safely
    car = rp["drivers"][0]["car"]
    import re as _re
    (app.lib.icons_dir / (_re.sub(r"[^a-z0-9]+", "-", car.lower()).strip("-") + ".png")).write_bytes(b"\x89PNG\r\n\x1a\n")
    app.lib._report_cache.clear()
    _, rp2 = call(port, "GET", f"/api/replay?recording={races[0]['id']}&champ={cid}")
    icon = next(d["icon"] for d in rp2["drivers"] if d["car"] == car)
    assert icon and call(port, "GET", icon)[0] == 200
    assert call(port, "GET", "/car-icons/..%2F..%2Fams2season.json")[0] == 404

    # talking points + pins flow into the season page
    call(port, "POST", "/api/settings", {"talking_points": 3, "pinned_awards": ["s_iron_man"]})
    _, d4 = call(port, "GET", f"/api/championships/{cid}")
    assert d4["talking_points"] == 3
    if any(a["id"] == "s_iron_man" for a in d4["awards"]):
        assert d4["awards"][0]["id"] == "s_iron_man" and d4["awards"][0]["pinned"]
    _, catalog = call(port, "GET", "/api/awards-catalog")
    assert len(catalog["race"]) >= 35 and len(catalog["season"]) >= 20

    # filed races leave the inbox; removing a round puts it back
    _, home = call(port, "GET", "/api/home")
    assert home["inbox"] == [] and home["championships"][0]["races"] == 3
    call(port, "DELETE", f"/api/championships/{cid}/rounds?round=3&race_no=1")
    _, home = call(port, "GET", "/api/home")
    assert [r["id"] for r in home["inbox"]] == [races[2]["id"]]


def test_refuses_foreign_hosts_and_path_tricks(server):
    _, port = server
    status, _ = call(port, "GET", "/api/ping", host="evil.example")
    assert status == 403  # DNS-rebinding protection
    status, _ = call(port, "GET", "/report?recording=..%2F..%2Fetc")
    assert status == 404
    status, _ = call(port, "GET", "/api/championships/..%2Fsecrets")
    assert status == 404


def test_recorder_service_lifecycle(tmp_path):
    sim = RaceSim(HUMANS, RaceScript(n_ai=3), seed=4)

    class SimReader:
        calls = 0

        def snapshot(self):
            SimReader.calls += 1
            if SimReader.calls < 10:
                return None  # game not running yet
            sim.advance(t_green=1.0)
            return sim.snapshot(S.GAME_INGAME_PLAYING, S.SESSION_RACE)

    app = App(tmp_path, reader_factory=SimReader)
    svc = app.recorder
    assert svc.status()["state"] == "off"
    svc.start()
    deadline = time.time() + 15
    seen = set()
    while time.time() < deadline:
        st = svc.status()
        seen.add(st["state"])
        if st["session"] and st["session"]["green"]:
            break
        time.sleep(0.1)
    assert {"waiting", "recording"} <= seen
    st = svc.status()
    assert st["session"]["track"] == "Simtown" and st["session"]["cars"] == 7
    svc.stop()
    st = svc.status()
    assert st["state"] == "off" and len(st["completed"]) == 1
    rec = app.lib.recordings()
    assert rec[0]["type"] == "race" and rec[0]["status"] == "complete"


def test_quali_endpoint_merges_recordings(tmp_path):
    rec = tmp_path / "recordings"
    s = RaceScript(laps=3, n_ai=5, with_qualifying=True, local_collision_lap=None)
    run_race(rec, HUMANS, s, seed=5)
    run_race(rec, HUMANS, s, seed=5, local_human="Eli")
    app = App(tmp_path)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        recs = call(port, "GET", "/api/recordings")[1]["recordings"]
        q = sorted(r["id"] for r in recs if r["type"] == "qualify")[0]
        race = next(r for r in recs if r["type"] == "race")
        assert race["quali"] in {r["id"] for r in recs if r["type"] == "qualify"}  # race knows its qualifying
        status, d = call(port, "GET", f"/api/quali?recording={q}")
        assert status == 200 and len(d["merged_recordings"]) == 1
        has = {x["name"]: x["has_inputs"] for x in d["drivers"]}
        assert has["Jax"] and has["Eli"]
        assert all(len(d["laps"][x["name"]]["t"]) == d["n"] for x in d["drivers"])
        assert d["breakdown"]["drivers"] and d["breakdown"]["awards"] and d["track"]["left"]
    finally:
        srv.shutdown()


def test_mapping_session_saves_a_track_map(tmp_path):
    from ams2season.simulate import mapping_drive
    rec = tmp_path / "recordings"
    run_race(rec, HUMANS, RaceScript(laps=3, n_ai=5, local_collision_lap=None), seed=6)
    app = App(tmp_path)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        assert call(port, "POST", "/api/trackmap/start")[0] == 200
        for snap, t in mapping_drive():  # what the recorder thread would feed it from the game
            app.recorder.mapper.feed(snap, t)
        _, st = call(port, "GET", "/api/trackmap/status")
        assert st["mapping"] and st["track"] == "Simtown" and st["coverage"]["left"] >= 95
        status, saved = call(port, "POST", "/api/trackmap/save")
        assert status == 200 and saved["coverage"]["right"] >= 95
        _, tl = call(port, "GET", "/api/tracks")
        assert tl["tracks"][0]["track"] == "Simtown"
        race = next(r for r in call(port, "GET", "/api/recordings")[1]["recordings"] if r["type"] == "race")
        _, rp = call(port, "GET", f"/api/replay?recording={race['id']}")
        assert rp["track"]["edges"]["source"] == "mapped"
        call(port, "POST", "/api/tracks/width", {"track": "Simtown", "layout": "GP", "width": 11})
        assert call(port, "DELETE", "/api/tracks?key=" + tl["tracks"][0]["key"])[0] == 200
        _, rp2 = call(port, "GET", f"/api/replay?recording={race['id']}")
        # without the map: modelled, plus any edge points from the race itself (wheels touching kerbs)
        assert rp2["track"]["edges"]["source"] in ("model", "mixed")
        assert max(rp2["track"]["edges"]["mapped_pct"].values()) < 95
    finally:
        srv.shutdown()


def test_practice_technique_teams_endpoints(tmp_path):
    from ams2season.simulate import practice_drive
    rec = tmp_path / "recordings"
    style = {"tyre_wear": {"Jax": 0.8, "Mason": 1.4}}
    for pc in ("Jax", "Mason"):
        run_race(rec, HUMANS, RaceScript(laps=3, n_ai=4, local_collision_lap=None, extra=dict(style)), seed=9, local_human=pc)
    app = App(tmp_path)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        _, tpl = call(port, "GET", "/api/practice/templates")
        assert {t["id"] for t in tpl["templates"]} >= {"consistency", "brake_points", "smooth"}
        assert call(port, "POST", "/api/practice/start", {"objectives": [{"id": "clean_streak", "laps": 2}]})[0] == 200
        for snap, t in practice_drive(laps=6, seed=1, invalid_laps=()):
            app.recorder.practice.feed(snap, t)
        _, st = call(port, "GET", "/api/practice/status")
        assert st["active"] and st["track"] == "Simtown" and st["objectives"][0]["done"]
        import json as _json
        race_dir = next(p for p in rec.iterdir() if p.name.endswith("_race"))
        meta = _json.loads((race_dir / "session.json").read_text())
        jax = next(x for x in meta["final"] if x["name"] == "Jax")
        pb = app.lib.personal_best(meta["track_location"], meta["track_variation"], jax["car"], "Jax")
        assert pb and abs(pb - min(x["fastest_lap"] for x in [jax])) < 1e-6  # personal bests are per car and layout
        assert app.lib.personal_best(meta["track_location"], meta["track_variation"], "Some Other Car", "Jax") is None
        _, fin = call(port, "POST", "/api/practice/stop")
        assert fin["objectives"][0]["done"] and not call(port, "GET", "/api/practice/status")[1]["active"]

        races = sorted(r["id"] for r in call(port, "GET", "/api/recordings")[1]["recordings"] if r["type"] == "race")
        _, tq = call(port, "GET", f"/api/technique?recording={races[0]}")
        assert {d["driver"] for d in tq["drivers"] if d["available"]} == {"Jax", "Mason"}  # merged from both PCs

        cid = call(port, "POST", "/api/championships", {"name": "Teams"})[1]["id"]
        call(port, "PUT", f"/api/championships/{cid}", {"drivers": [{"display": n} for n in HUMANS],
             "teams": [{"name": "A", "color": "#E4572E", "icon": "bolt", "members": ["jax", "eli"]},
                       {"name": "B", "color": "#2E86DE", "icon": "flag", "members": ["mason", "theo", "jax"]}], "team_count": 2})
        call(port, "POST", f"/api/championships/{cid}/rounds", {"recording": races[0], "round": 1})
        _, d = call(port, "GET", f"/api/championships/{cid}")
        assert [t["members"] for t in d["config"]["teams"]] == [["jax", "eli"], ["mason", "theo"]]
        assert len(d["team_standings"]["humans_only"]) == 2 and d["driver_team"]["Jax"] == "a"
        care = {r["driver"]: r for r in d["tyre_care"]}
        assert care["Jax"]["wear_vs_field"] < 0 < care["Mason"]["wear_vs_field"] and care["Jax"]["score"] > care["Mason"]["score"]
    finally:
        srv.shutdown()
