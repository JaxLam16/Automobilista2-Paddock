"""The HTML report renders from a simulated race with valid embedded data and no JS errors."""
import json
import re

import pytest

from ams2season.race import analyze_race
from ams2season.report import render_race_report, report_data
from ams2season.simulate import RaceScript, run_race

HUMANS = ["Jax", "Mason", "Eli", "Theo"]


@pytest.fixture(scope="module")
def race(tmp_path_factory):
    out = tmp_path_factory.mktemp("rep")
    dirs = run_race(out, HUMANS, RaceScript(laps=4, n_ai=8, spin=("Mason", 2, 1320.0), pit=(5, 2)), seed=9)
    return analyze_race(next(d for d in dirs if d.name.endswith("_race")), humans=set(HUMANS))


def test_report_data_is_complete(race):
    d = report_data(race)
    assert len(d["drivers"]) == 12 and sum(not x["is_ai"] for x in d["drivers"]) == 4
    assert all(x["color"] for x in d["drivers"] if not x["is_ai"])
    assert len(d["track"]["points"]) > 50 and len(d["track"]["corners"]) == 6
    assert d["summary"] and len(d["awards"]) >= 15 and d["top_n"] == 6
    groups = {a["group"] for a in d["awards"]}
    assert {"Battles", "Overtaking", "Pace"} <= groups
    assert all(p["x"] is not None for p in d["passes"])
    json.dumps(d, allow_nan=False)  # no NaN leaks into the page


def test_report_html_renders_without_errors(race, tmp_path):
    out = render_race_report(race, tmp_path / "report.html")
    page = out.read_text(encoding="utf-8")
    payload = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)
    json.loads(payload)
    playwright = pytest.importorskip("playwright.sync_api")
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch()
            pg = browser.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(out.resolve().as_uri())
            pg.click(".chip[data-name='Mason']")
            assert pg.locator(".fsbtn").count() == 2  # lap chart and gap chart (the pass map is on the Overtaking page)
            assert pg.locator("#lapchart .series.on").count() == 1
            assert pg.locator("#style").count() == 0                   # driving style has its own page now
            pg.locator("#results thead th").first.click(); pg.locator("#results thead th").first.click()   # sort by position, descending
            assert pg.locator("#results thead th[data-sort='desc']").count() == 1
            vals = [int(t) for t in pg.locator("#results tbody td:nth-child(1)").all_inner_texts() if t.strip().isdigit()]
            assert len(vals) > 3 and vals == sorted(vals, reverse=True)
            browser.close()
    except Exception as e:  # browser binaries not installed
        if "Executable doesn't exist" in str(e):
            pytest.skip("playwright browser not installed")
        raise
    assert not errors


def test_awards_ranking_and_pins(race):
    from ams2season.awards import RACE_CATALOG, race_awards
    aw = race_awards(race)
    assert all(a["id"] in RACE_CATALOG for a in aw)
    assert [a["rank_score"] for a in aw] == sorted((a["rank_score"] for a in aw), reverse=True)
    spin = [a for a in aw if a["id"] == "spin_cost"]
    gifted = race.passes[(race.passes.kind == "gifted") & (race.passes.passed == "Mason")]
    if len(gifted) >= 2:
        assert spin and spin[0]["winner"] == "Mason" and spin[0]["t"] is not None
    else:
        assert not spin  # losing a single place isn't a "costliest moment"
    last_id = aw[-1]["id"]
    pinned = race_awards(race, pinned=[last_id])
    assert pinned[0]["id"] == last_id and pinned[0]["pinned"]
    assert not any("passs" in a["detail"] or " 1 races" in a["detail"] for a in aw)


def test_replay_payload(race):
    from ams2season.replay import replay_data
    rp = replay_data(race)
    assert rp["t0"] <= rp["green_t"] < rp["end_t"]
    assert {d["name"] for d in rp["drivers"]} == set(rp["cars"])
    mason = next(d for d in rp["drivers"] if d["name"] == "Mason")
    assert not mason["is_ai"] and mason["color"]
    assert rp["heading_source"] == "orientation"  # yaw component, sign and offset found automatically
    assert rp["inputs"] and rp["inputs"]["name"] == "Jax" and len(rp["inputs"]["thr"]) == rp["n"]
    assert all(d["body"] == "gt" and d["length"] > 4 for d in rp["drivers"])
    assert all(len(rp["cars"][d["name"]]["h"]) == rp["n"] for d in rp["drivers"])
    assert all("apex" in c for c in rp["track"]["corners"])
    pit_car = next(iter(rp["pits"]))
    assert rp["pits"][pit_car][0][1] > rp["pits"][pit_car][0][0]
    json.dumps(rp, allow_nan=False)
