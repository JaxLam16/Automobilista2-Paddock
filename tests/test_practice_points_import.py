"""Practice awards for the championship, importing a friend's recording, and practice goals from your history."""
import base64
import io
import json
import shutil
import tempfile
import threading
import urllib.request
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ams2season.app import App, _make_server, make_handler
from ams2season.practice_points import awards
from ams2season.simulate import RaceScript, run_race

H = ["Jax", "Mason", "Eli", "Theo"]


def test_award_rules():
    st = {"Jax": {"laps": 9, "valid": 9, "streak": 9, "best": 63.5, "consistency_s": 0.12, "improvement_pct": 0.5, "invalid_share": 0.0, "track_usage": 60.0},
          "Mason": {"laps": 9, "valid": 8, "streak": 6, "best": 63.2, "consistency_s": 0.30, "improvement_pct": 2.1, "invalid_share": 0.111, "track_usage": 75.0},
          "Eli": {"laps": 4, "valid": 4, "streak": 4, "best": 64.0, "consistency_s": None, "improvement_pct": None, "invalid_share": None, "track_usage": 50.0},
          "AI Bot": {"laps": 30, "valid": 30, "streak": 30, "best": 60.0, "consistency_s": 0.01, "improvement_pct": 5.0, "invalid_share": 0.0, "track_usage": 99.0}}
    won = {(a["award"], a["name"]) for a in awards(st, {"Jax": "jax", "Mason": "mason", "Eli": "eli"})}
    assert ("iron_man", "Jax") in won and ("metronome", "Jax") in won and ("every_inch", "Mason") in won and ("most_improved", "Mason") in won
    assert ("mileage", "Jax") in won and ("mileage", "Mason") in won                 # a tie: both get it
    assert ("clean_sheet", "Jax") in won and not any(n == "AI Bot" for _, n in won)  # AI never win practice points
    assert not any(k == "fastest" for k, _ in won)                                   # off by default
    assert ("fastest", "Mason") in {(a["award"], a["name"]) for a in awards(st, {"Jax": "jax", "Mason": "mason"}, ["fastest"])}


def _call(base, m, path, body=None):
    req = urllib.request.Request(base + path.lstrip("/"), method=m, headers={"Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, **json.loads(e.read())}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("pp")
    (root / "recordings").mkdir()
    tmp = Path(tempfile.mkdtemp())
    race = next(d for d in run_race(tmp, H, RaceScript(laps=6, n_ai=4, spin=("Theo", 3, 1320.0), local_collision_lap=None), seed=5) if d.name.endswith("_race"))
    shutil.copytree(race, root / "recordings" / race.name)
    prac = root / "recordings" / race.name.replace("20261003", "20261002").replace("_race", "_practice")
    shutil.copytree(race, prac)
    m = json.loads((prac / "session.json").read_text())
    m.update({"session_type": "practice", "green_t": None, "started_at": "2026-10-02" + m["started_at"][10:]})
    (prac / "session.json").write_text(json.dumps(m))
    app = App(root)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield root, race, prac, f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


def test_practice_points_in_the_championship(world):
    root, race, prac, base = world
    cid = _call(base, "POST", "/api/championships", {"name": "Practice Cup"})["id"]
    _call(base, "PUT", f"/api/championships/{cid}", {"drivers": [{"display": n} for n in H]})
    r = _call(base, "POST", f"/api/championships/{cid}/rounds", {"recording": prac.name})
    assert r["practice"] and r["round"] == 1 and r["awards"]
    d = _call(base, "GET", f"/api/championships/{cid}")
    rows = d["standings"]["humans_only"]["rows"]
    assert sum(x["practice"] for x in rows) == len(r["awards"]) and all(x["points"] == x["practice"] for x in rows)   # practice-only standings
    assert any(a["award"] == "every_inch" for a in d["practice"][0]["awards"])                                         # track usage measured
    _call(base, "POST", f"/api/championships/{cid}/rounds", {"recording": race.name, "round": 1})
    d = _call(base, "GET", f"/api/championships/{cid}")
    rows = {x["driver"]: x for x in d["standings"]["humans_only"]["rows"]}
    assert all(x["points"] == x["R1"] + x["practice"] for x in rows.values())                                         # race + practice
    _call(base, "PUT", f"/api/championships/{cid}", {"practice_points": 2, "practice_awards": ["iron_man"]})
    d = _call(base, "GET", f"/api/championships/{cid}")
    assert {a["award"] for a in d["practice"][0]["awards"]} == {"iron_man"} and all(a["points"] == 2 for a in d["practice"][0]["awards"])
    assert _call(base, "DELETE", f"/api/championships/{cid}/practice/{d['practice'][0]['id']}")["ok"]
    d = _call(base, "GET", f"/api/championships/{cid}")
    assert not d["practice"] and all(not x["practice"] for x in d["standings"]["humans_only"]["rows"])


def _friend_zip(race: Path, shift_hours: int, extra=None) -> bytes:
    friend = Path(tempfile.mkdtemp()) / "20261003-140002_Simtown_GP_race"
    shutil.copytree(race, friend)
    m = json.loads((friend / "session.json").read_text())
    m["local"] = {**m["local"], "name": "Mason"}
    m["label"] = "masons"
    m["started_at"] = (datetime.fromisoformat(m["started_at"]) - timedelta(hours=shift_hours)).isoformat(timespec="seconds")
    (friend / "session.json").write_text(json.dumps(m))
    # This synthetic import relabels the local driver rather than recording Mason's
    # real pedals. Model an older recording without verified viewed-slot identity;
    # modern Jax-slot telemetry must correctly be rejected when labelled Mason.
    import pandas as pd
    local = pd.read_parquet(friend / 'local.parquet').drop(columns=['viewed_slot'], errors='ignore')
    local.to_parquet(friend / 'local.parquet', index=False)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in friend.iterdir():
            z.write(f, f"{friend.name}/{f.name}")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def test_import_a_friends_recording(world):
    root, race, prac, base = world
    z = _friend_zip(race, 6, {"../evil.txt": "no", "20261003-140002_Simtown_GP_race/technique.json": "{}"})
    r = _call(base, "POST", "/api/recordings/import", {"zip": base64.b64encode(z).decode()})
    imp = r["imported"][0]
    assert imp["driver"] == "Mason" and not imp["already"]
    folder = root / "recordings" / imp["id"]
    assert sorted(p.name for p in folder.iterdir()) == ["events.jsonl", "frames.parquet", "import.json", "local.parquet", "session.json"]
    assert not (root / "evil.txt").exists() and not (root / "recordings" / "evil.txt").exists()
    assert _call(base, "POST", "/api/recordings/import", {"zip": base64.b64encode(z).decode()})["imported"][0]["already"]
    rec = {x["id"]: x for x in _call(base, "GET", "/api/recordings")["recordings"]}
    assert rec[imp["id"]]["imported_from"] == "Mason"
    drivers = [d["driver"] for d in _call(base, "GET", f"/api/technique?recording={race.name}")["drivers"] if d.get("available")]
    assert "Mason" in drivers and "Jax" in drivers                       # same session, despite a clock 6 hours off
    assert "zip" in _call(base, "POST", "/api/recordings/import", {"zip": base64.b64encode(b"nope").decode()})["error"]
    files = [{"path": "x/session.json", "data": base64.b64encode(b"{}").decode()}]
    assert "complete recording" in _call(base, "POST", "/api/recordings/import", {"files": files})["error"]


def test_goals_from_your_history(world):
    from ams2season.practice import suggest_objectives
    root, race, prac, base = world
    out = suggest_objectives(root / "recordings")
    goals = {o["id"]: o for o in out["objectives"]}
    assert set(goals) == {"clean_streak", "consistency", "target"} and goals["clean_streak"]["laps"] >= 5
    assert out["based_on"]["sessions"] >= 1 and out["reasons"]["clean_streak"]
    empty = suggest_objectives(Path(tempfile.mkdtemp()))
    assert empty["based_on"] is None and len(empty["objectives"]) == 3
