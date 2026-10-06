"""Race review pages: every award has a home page, the newer awards (errors, overtaking ratings, race pace,
driving style), each page's endpoint carrying only its own awards, and the Driving style page."""
import json
import threading
import urllib.request

import pytest

from ams2season.app import App, _make_server, make_handler
from ams2season.awards import PAGE, RACE_CATALOG, race_awards
from ams2season.race import analyze_race
from ams2season.simulate import RaceScript, run_race

HUMANS = ["Jax", "Mason", "Eli", "Theo"]
PAGES = {"report", "pace", "overtakes", "errors", "style", "cars"}


@pytest.fixture(scope="module")
def race(tmp_path_factory):
    root = tmp_path_factory.mktemp("rp")
    dirs = run_race(root / "recordings", HUMANS, RaceScript(laps=8, n_ai=10, spin=("Theo", 3, 1320.0), local_collision_lap=None), seed=7)
    return root, next(d for d in dirs if d.name.endswith("_race"))


def test_every_award_has_a_page(race):
    assert set(PAGE.values()) <= PAGES and set(PAGE) <= set(RACE_CATALOG)
    _, path = race
    aw = race_awards(analyze_race(path, humans=set(HUMANS)))
    assert all(a["page"] in PAGES for a in aw)
    ids = {a["id"] for a in aw}
    assert {"spin_doctor", "error_free"} <= ids                                     # Theo spun; someone drove clean
    assert {"smooth_power", "apex_hunter"} <= ids and ids & {"clinical", "immovable"}
    spin = next(a for a in aw if a["id"] == "spin_doctor")
    assert spin["winner"] == "Theo" and spin["page"] == "errors"
    assert not any(a["id"] == "costliest_moment" and "spin" in a["detail"] for a in aw)   # spins are "Costliest moment"'s
    assert len({a["title"] for a in aw}) == len(aw)                                 # no two awards with the same name


def test_pages_carry_their_own_awards(race):
    root, path = race
    app = App(root)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    get = lambda p: json.loads(urllib.request.urlopen(base + p.lstrip("/")).read())
    try:
        for endpoint, page in (("errors", "errors"), ("overtakes", "overtakes"), ("pace", "pace"), ("race-cars", "cars"), ("style", "style")):
            d = get(f"/api/{endpoint}?recording={path.name}")
            assert d["awards"] and all(a["page"] == page for a in d["awards"]), endpoint
        st = get(f"/api/style?recording={path.name}")
        assert len(st["drivers"]) >= 10 and st["racing_mode"] == "reduced" and st["meta"]["track"]
        d0 = st["drivers"][0]
        assert d0["pos"] == 1 and all(f"brake_consistency_{m}" in d0 for m in ("equal", "reduced", "excluded"))
        page = urllib.request.urlopen(base + f"report?recording={path.name}").read().decode()
        assert 'id="style"' not in page and "pageLink" in page                       # the report links awards to their pages
    finally:
        srv.shutdown()
