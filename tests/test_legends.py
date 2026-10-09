"""F1 legend fingerprints, style matching, driver profiles across a championship, and table sorting."""
import json
import shutil
import tempfile
import threading
import urllib.request
from pathlib import Path


from ams2season.app import App, _make_server, make_handler
from ams2season.legends import DIMENSIONS, LEGENDS, match, scores_from_raw
from ams2season.simulate import RaceScript, run_race

HUMANS = ["Jax", "Mason", "Eli", "Theo"]


def test_twenty_distinct_legends():
    assert len(LEGENDS) == 20 and len({l["key"] for l in LEGENDS}) == 20
    keys = {k for k, _, _ in DIMENSIONS}
    for l in LEGENDS:
        assert set(l["style"]) == keys and all(0 <= v <= 10 for v in l["style"].values()) and l["blurb"]
    shapes = {tuple(l["style"][k] for k, _, _ in DIMENSIONS) for l in LEGENDS}
    assert len(shapes) == 20                                     # no two legends share a fingerprint


def test_matching_is_about_shape_not_level():
    prost = next(l for l in LEGENDS if l["key"] == "prost")["style"]
    # a mid-pack driver with Prost's pattern (smooth, consistent, easy on tyres) at a much lower level
    you = {k: 25 + 4 * v for k, v in prost.items()}
    ms = match(you)
    assert ms[0]["key"] == "prost" and ms[0]["similarity"] > 95
    assert {"Consistency", "Clean driving", "Tyre management", "Throttle control"} & {x["label"] for x in ms[0]["shared_strengths"]}
    villeneuve = next(m for m in ms if m["key"] == "villeneuve")
    assert villeneuve["similarity"] < 30                         # the opposite style
    assert match({"qualifying": 60, "race_pace": 50}) == []       # too little data to say


def test_scores_from_raw_scales():
    s = scores_from_raw({"grid_pct": 0.8, "pace_rel_pct": -1.0, "lap_cv_pct": 0.5, "pass_rate": 30, "hold_rate": 75,
                         "lap1_gain": 1.0, "clean_share": 85, "trend_pct": -0.1, "brake_consistency": 120})
    assert s["qualifying"] == 80 and s["race_pace"] == 75 and round(s["consistency"]) == 94 and s["overtaking"] == 50
    assert s["defending"] == 50 and round(s["starts"]) == 62 and s["clean"] == 85 and s["late_race"] == 80
    assert s["braking"] == 100 and s["tyres"] is None             # clipped, and missing stays missing


def test_driver_profiles_across_a_championship(tmp_path):
    root = tmp_path
    (root / "recordings").mkdir()
    for i, seed in enumerate((7, 8)):
        tmp = Path(tempfile.mkdtemp())
        for d in run_race(tmp, HUMANS, RaceScript(laps=5, n_ai=8, local_collision_lap=None, spin=("Theo", 3, 1320.0) if seed == 8 else None), seed=seed):
            new = root / "recordings" / (f"2026100{i + 1}" + d.name[8:])
            shutil.copytree(d, new)
            m = json.loads((new / "session.json").read_text())
            m["started_at"] = f"2026-10-0{i + 1}" + m["started_at"][10:]
            (new / "session.json").write_text(json.dumps(m))
    app = App(root)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"

    def call(m, path, body=None):
        req = urllib.request.Request(base + path.lstrip("/"), method=m, headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        return json.loads(urllib.request.urlopen(req).read())
    try:
        cid = call("POST", "/api/championships", {"name": "Legends Cup"})["id"]
        call("PUT", f"/api/championships/{cid}", {"drivers": [{"display": n} for n in HUMANS]})
        races = sorted(r["id"] for r in call("GET", "/api/recordings")["recordings"] if r["type"] == "race")
        for i, r in enumerate(races):
            call("POST", f"/api/championships/{cid}/rounds", {"recording": r, "round": i + 1})
        P = call("GET", f"/api/championships/{cid}/profiles")
        assert len(P["legends"]) == 20 and len(P["dimensions"]) == 12
        prof = {p["driver"]: p for p in P["profiles"]}
        assert set(prof) == set(HUMANS)
        for p in prof.values():
            assert p["races"] == 2 and len(p["matches"]) == 20 and p["matches"][0]["similarity"] >= p["matches"][-1]["similarity"]
            assert sum(v is not None for v in p["scores"].values()) >= 8
        assert prof["Theo"]["scores"]["clean"] < prof["Eli"]["scores"]["clean"]   # his spin shows up
        assert prof["Jax"]["scores"]["tyres"] is not None                         # tyre data: the recording car only
    finally:
        srv.shutdown()
