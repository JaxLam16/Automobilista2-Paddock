"""A race recording with no racing in it (the session was left before the start) gets a clear message instead
of an error, and the home page stops offering it."""
import json
import shutil
import tempfile
import threading
import urllib.request
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ams2season.app import App, _make_server, make_handler
from ams2season.simulate import RaceScript, run_race


def test_race_left_before_the_start(tmp_path):
    rec = tmp_path / "recordings"
    rec.mkdir()
    tmp = Path(tempfile.mkdtemp())
    src = next(d for d in run_race(tmp, ["Jax", "Mason"], RaceScript(laps=3, n_ai=3, local_collision_lap=None), seed=2) if d.name.endswith("_race"))
    good = rec / src.name
    shutil.copytree(src, good)
    bad = rec / ("20261004" + src.name[8:])
    shutil.copytree(src, bad)
    m = json.loads((bad / "session.json").read_text())
    green = m.get("green_t") or 5
    for f in ("frames.parquet", "local.parquet"):
        t = pq.read_table(bad / f).to_pandas()
        pq.write_table(pa.Table.from_pandas(t[t.t < green - 1], preserve_index=False), bad / f)
    m.update({"green_t": None, "started_at": "2026-10-04" + m["started_at"][10:]})
    for p in m.get("final") or []:
        p["laps_completed"] = 0
    (bad / "session.json").write_text(json.dumps(m))
    app = App(tmp_path)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    try:
        summary = {r["id"]: r for r in app.lib.recordings()}
        assert summary[bad.name]["raced"] is False and summary[good.name]["raced"] is True
        home = json.loads(urllib.request.urlopen(base + "api/home").read())
        assert home["latest"]["id"] == good.name and bad.name not in [r["id"] for r in home["inbox"]]
        page = urllib.request.urlopen(base + f"report?recording={bad.name}").read().decode()
        assert "No race to show" in page and "left before the green flag" in page
        assert len(urllib.request.urlopen(base + f"report?recording={good.name}").read()) > 50000
    finally:
        srv.shutdown()
