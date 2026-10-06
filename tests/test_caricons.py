"""Car icons: normalising images, matching in-game names, real lengths, and the Car icons endpoints."""
import base64
import io
import json
import threading
import urllib.request

from PIL import Image

from ams2season.app import App, _make_server, make_handler
from ams2season.caricons import BUILTIN_DIR, CAR_SPECS, available, compact, match, normalise, wing_at_top
from ams2season.simulate import RaceScript, run_race

PORSCHE = BUILTIN_DIR / "Porsche_911_GT3R.png"


def test_builtin_icons_are_nose_up_and_cropped():
    files = sorted(BUILTIN_DIR.glob("*.png"))
    assert len(files) == 14
    for f in files:
        im = Image.open(f)
        assert not wing_at_top(im), f.name                 # wing at the bottom = nose up
        assert im.getchannel("A").getbbox() == (0, 0) + im.size or im.getchannel("A").getbbox()[0] <= 1
        assert compact(f.stem) in CAR_SPECS and 3.8 < CAR_SPECS[compact(f.stem)][0] < 5.2


def test_normalise_turns_and_crops(tmp_path):
    im = Image.open(PORSCHE).convert("RGBA")
    padded = Image.new("RGBA", (im.width + 80, im.height + 60), (0, 0, 0, 0))
    padded.paste(im.rotate(180), (40, 30))                 # nose down, with empty margins
    buf = io.BytesIO(); padded.save(buf, "PNG")
    info = normalise(buf.getvalue(), tmp_path / "x.png")
    out = Image.open(tmp_path / "x.png")
    assert info["rotated"] and out.size == im.size and not wing_at_top(out)


def test_matching_in_game_names():
    icons = available(BUILTIN_DIR.parent / "nowhere")
    expect = {"Porsche 911 GT3 R": "Porsche_911_GT3R.png", "Mercedes-AMG GT3 Evo": "Mercedes_AMG_GT3.png",
              "Lamborghini Huracán GT3": "Lamborghini_Huracan_GT3.png", "Nissan GT-R Nismo GT3": "Nissan_GT-R_Nismo_R35.png",
              "Chevrolet Corvette C7.R": "Chevrolet_Corvette_C7R_GT3.png", "Cadillac ATS-V.R GT3": "Cadillac_ATS-VR_GT3.png",
              "BMW M4 GT3": None, "McLaren 720S GT3 Evo": None, "Chevrolet Corvette C8.R": None}
    for car, want in expect.items():
        k = match(car, icons)
        assert (icons[k]["file"] if k else None) == want, car
    assert match("BMW M4 GT3", icons, {"BMW M4 GT3": "BMW_M6_GT3.png"}) == "bmwm6gt3"   # your choice wins
    assert match("Porsche 911 GT3 R", icons, {"Porsche 911 GT3 R": ""}) is None          # "no icon"


def test_car_icon_endpoints_and_replay(tmp_path):
    dirs = run_race(tmp_path / "recordings", ["Jax", "Mason"], RaceScript(laps=2, n_ai=6, local_collision_lap=None), seed=2)
    app = App(tmp_path)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"

    def call(m, path, body=None):
        req = urllib.request.Request(base + path.lstrip("/"), method=m, headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read()
                return r.status, json.loads(raw) if "json" in r.headers.get("Content-Type", "") else raw
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    try:
        _, page = call("GET", "/api/car-icons")
        assert len(page["icons"]) == 14 and page["cars"]
        matched = [c for c in page["cars"] if c["how"] == "auto"]
        unmatched = [c for c in page["cars"] if c["how"] == "none"]
        assert matched, page["cars"]
        car = matched[0]
        key = compact(car["icon"].rsplit(".", 1)[0])
        assert car["length"] == CAR_SPECS[key][0]
        assert call("GET", "/car-icons/" + car["icon"])[0] == 200
        race = next(d for d in dirs if d.name.endswith("_race")).name
        _, rp = call("GET", f"/api/replay?recording={race}")
        on_track = [d for d in rp["drivers"] if d["car"] == car["car"]]
        assert on_track and on_track[0]["icon"] == "/car-icons/" + car["icon"] and on_track[0]["length"] == CAR_SPECS[key][0]
        # your length and your icon choice flow through to the replay
        call("POST", "/api/car-icons/length", {"file": car["icon"], "length": 4.629})
        _, rp = call("GET", f"/api/replay?recording={race}")
        assert next(d for d in rp["drivers"] if d["car"] == car["car"])["length"] == 4.629
        _, page = call("GET", "/api/car-icons")
        assert next(i for i in page["icons"] if i["file"] == car["icon"])["length_source"] == "yours"
        if unmatched:
            call("POST", "/api/car-icons/assign", {"car": unmatched[0]["car"], "file": "BMW_M6_GT3.png"})
            _, page = call("GET", "/api/car-icons")
            c2 = next(c for c in page["cars"] if c["car"] == unmatched[0]["car"])
            assert c2["icon"] == "BMW_M6_GT3.png" and c2["how"] == "chosen"
        # upload: turned nose-up and cropped; flipping a built-in makes your own copy; built-ins can't be deleted
        im = Image.open(PORSCHE).rotate(180)
        buf = io.BytesIO(); im.save(buf, "PNG")
        status, up = call("POST", "/api/car-icons/upload", {"name": "My Car GT3.png", "data": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()})
        assert status == 200 and up["rotated"] and (app.lib.icons_dir / up["file"]).exists()
        assert call("POST", "/api/car-icons/flip", {"file": "Audi_R8_LMS_GT3.png"})[0] == 200
        assert (app.lib.icons_dir / "Audi_R8_LMS_GT3.png").exists()
        assert call("DELETE", "/api/car-icons?file=Bentley_Continental_GT3.png")[0] == 400
        assert call("DELETE", f"/api/car-icons?file={up['file']}")[0] == 200
        assert call("GET", "/car-icons/..%2F..%2Fams2season.json")[0] == 404
    finally:
        srv.shutdown()
