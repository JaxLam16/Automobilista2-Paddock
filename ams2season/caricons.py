"""Top-down car icons: normalising images, matching them to in-game car names, and real lengths.

An icon is a top-down image on a transparent background, nose pointing up, painted neutral grey so the
replay can tint the bodywork in each driver's colour while glass, tyres and the wing stay dark. Images
dropped in are cropped to the car and turned nose-up automatically (a rear wing is a straight bar that
fills the full width at its end; a nose is rounded), with a manual flip if that ever guesses wrong.
"""
from __future__ import annotations

import base64
import io
import json
import re
import shutil
from pathlib import Path

BUILTIN_DIR = Path(__file__).parent / "assets" / "car_icons"
EXTS = (".png", ".webp")

# Overall length in metres, used to draw each car at its real size (width follows the image's shape).
# "published" = from a cited spec sheet; "estimate" = a best guess within GT3's usual 4.4-4.95 m range,
# editable on the Car icons page.
CAR_SPECS = {
    "astonmartinv12vantagegt3": (4.50, "estimate"),
    "audir8lmsgt3": (4.583, "published"),
    "bentleycontinentalgt3": (4.86, "estimate"),
    "bmwm6gt3": (4.94, "estimate"),
    "bmwz4gt3": (4.39, "estimate"),
    "cadillacatsvrgt3": (4.75, "estimate"),
    "chevroletcorvettec7rgt3": (4.64, "estimate"),
    "ferrari488gt3": (4.73, "estimate"),
    "hondansxgt3": (4.61, "estimate"),
    "lamborghinihuracangt3": (4.55, "estimate"),
    "mclaren650sgt3": (4.53, "estimate"),
    "mercedesamggt3": (4.75, "estimate"),
    "nissangtrnismor35": (4.78, "estimate"),
    "porsche911gt3r": (4.60, "estimate"),
}


def _plain(s: str) -> str:
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(ch)).lower()


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _plain(s))


GENERIC = {"gt3", "gt", "evo", "evo2", "ii", "2", "car", "the", "r"}


def _tokens(s: str) -> set:
    return {t for t in re.split(r"[^a-z0-9]+", _plain(s)) if t}


def _token_match(car: str, icon_stem: str) -> float:
    """How well an icon name fits a car name, word by word (0 = no). A model number in both that
    differs (M4 vs M6, C8 vs C7R) rules it out."""
    a, b = _tokens(car), _tokens(icon_stem)
    nums_a = {t for t in a - GENERIC if any(ch.isdigit() for ch in t)}
    nums_b = {t for t in b - GENERIC if any(ch.isdigit() for ch in t)}
    if nums_a and nums_b and not (nums_a & nums_b) and not any(x in y or y in x for x in nums_a for y in nums_b):
        return 0.0
    core_b = b - GENERIC
    if not core_b:
        return 0.0
    shared = (a - GENERIC) & core_b
    if len(shared) < 2:
        return 0.0
    frac = len(shared) / len(core_b)
    return frac if frac >= 0.6 else 0.0


def _pil():
    try:
        from PIL import Image
        return Image
    except Exception:  # Pillow missing: icons are used exactly as supplied
        return None


def wing_at_top(im) -> bool:
    """True if the rear wing is at the top of the image (so the car points nose-down)."""
    import numpy as np
    a = np.asarray(im.convert("RGBA"))[..., 3] > 128
    h = a.shape[0]
    k = max(2, int(h * 0.025))
    return float(a[:k].mean()) > float(a[-k:].mean())


def normalise(data: bytes, dst: Path, flip: bool | None = None) -> dict:
    """Crop to the car, turn it nose-up, save as PNG. Returns what was done."""
    Image = _pil()
    if Image is None:
        dst.write_bytes(data)
        return {"processed": False}
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    box = im.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox()
    if box:
        im = im.crop(box)
    turned = wing_at_top(im) if flip is None else flip
    if turned:
        im = im.rotate(180)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "PNG")
    return {"processed": True, "rotated": bool(turned), "size": list(im.size)}


def import_upload(icons_dir: Path, name: str, b64: str) -> dict:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem).strip("_") or "car"
    raw = base64.b64decode(b64.split(",")[-1])
    dst = icons_dir / f"{stem}.png"
    info = normalise(raw, dst)
    return {"file": dst.name, **info}


def flip_icon(path: Path) -> None:
    Image = _pil()
    if Image is None:
        raise ValueError("Flipping needs the Pillow package (pip install pillow).")
    im = Image.open(path).convert("RGBA").rotate(180)
    im.save(path, "PNG")


def available(icons_dir: Path) -> dict:
    """compact key -> {"file", "url", "builtin"}; your own icons replace built-in ones of the same name."""
    out = {}
    for folder, builtin in ((BUILTIN_DIR, True), (icons_dir, False)):
        if folder.exists():
            for f in sorted(folder.iterdir()):
                if f.suffix.lower() in EXTS:
                    out[compact(f.stem)] = {"file": f.name, "url": f"/car-icons/{f.name}", "builtin": builtin}
    return out


def match(car: str, icons: dict, overrides: dict | None = None) -> str | None:
    """The icon key for an in-game car name: your choice first, then an exact match ignoring spaces and
    punctuation, then the longest icon name contained in the car's name (or the other way round)."""
    if overrides and car in overrides:
        chosen = overrides[car]
        return compact(Path(chosen).stem) if chosen else None
    c = compact(car)
    if c in icons:
        return c
    hits = [k for k in icons if (k in c or c in k) and min(len(k), len(c)) >= 6
            and _token_match(car, Path(icons[k]["file"]).stem) > 0 or (k in c and min(len(k), len(c)) >= 6
            and not _conflicting_numbers(car, Path(icons[k]["file"]).stem))]
    if hits:
        return max(hits, key=len)
    scored = sorted(((_token_match(car, Path(v["file"]).stem), k) for k, v in icons.items()), reverse=True)
    return scored[0][1] if scored and scored[0][0] > 0 else None


def _conflicting_numbers(car: str, icon_stem: str) -> bool:
    a = {t for t in _tokens(car) - GENERIC if any(ch.isdigit() for ch in t)}
    b = {t for t in _tokens(icon_stem) - GENERIC if any(ch.isdigit() for ch in t)}
    return bool(a and b and not (a & b) and not any(x in y or y in x for x in a for y in b))


def length_for(key: str | None, lengths: dict | None = None) -> tuple[float | None, str | None]:
    if not key:
        return None, None
    if lengths and key in lengths:
        return float(lengths[key]), "yours"
    spec = CAR_SPECS.get(key)
    return (spec[0], spec[1]) if spec else (None, None)


_CLASS_CACHE: dict = {}


def _classes_from_frames(p: Path) -> dict:
    """car -> class for older recordings whose summary didn't store the class (reads two columns only)."""
    f = p / "frames.parquet"
    if not f.exists():
        return {}
    key = (str(f), f.stat().st_mtime)
    if key not in _CLASS_CACHE:
        try:
            import pyarrow.parquet as pq
            t = pq.read_table(f, columns=["car", "car_class"]).to_pandas().drop_duplicates()
            _CLASS_CACHE[key] = dict(zip(t.car, t.car_class))
        except Exception:
            _CLASS_CACHE[key] = {}
    return _CLASS_CACHE[key]


def seen_cars(recordings_dir: Path) -> list[dict]:
    """Every car (and class) that appears in your recordings, with how many sessions it was in."""
    seen = {}
    for p in recordings_dir.iterdir() if recordings_dir.exists() else []:
        f = p / "session.json"
        if not f.exists():
            continue
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        final = m.get("final") or []
        classes = None
        for x in final:
            car = x.get("car")
            if not car:
                continue
            cls = x.get("car_class")
            if cls is None:
                classes = classes if classes is not None else _classes_from_frames(p)
                cls = classes.get(car, "")
            e = seen.setdefault(car, {"car": car, "class": cls or "", "sessions": set()})
            if cls and not e["class"]:
                e["class"] = cls
            e["sessions"].add(p.name)
    return sorted(({"car": e["car"], "class": e["class"], "sessions": len(e["sessions"])} for e in seen.values()),
                  key=lambda e: e["car"].lower())


def install_builtins(src_dir: Path) -> list[str]:
    """Normalise a folder of images into the built-in icon set (used once, to bundle the defaults)."""
    done = []
    for f in sorted(src_dir.iterdir()):
        if f.suffix.lower() in EXTS:
            normalise(f.read_bytes(), BUILTIN_DIR / f"{f.stem}.png")
            done.append(f.stem)
    return done


__all__ = ["CAR_SPECS", "available", "compact", "flip_icon", "import_upload", "install_builtins", "length_for", "match",
           "normalise", "seen_cars", "shutil"]
