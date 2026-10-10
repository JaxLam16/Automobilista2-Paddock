"""Install a PNG as a livery slot (DDS + .rcf entries), always backing up what it changes."""
import datetime
import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from .transaction import track_write

from PIL import Image

from . import dds, rcf
from .template import reference_size

BACKUP_DIR = '_livery_tool_backups'


class Backup:
    def __init__(self, game, label):
        stamp = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
        self.game, self.dir = game, os.path.join(game.root, BACKUP_DIR, f'{stamp}_{label}_{uuid.uuid4().hex[:8]}')
        self.saved = []

    def save(self, path, move=False):
        if not path or not os.path.exists(path):
            return
        if not Path(path).resolve().is_relative_to(Path(self.game.root)):
            raise ValueError('Backup source must be inside the selected game folder.')
        if move:
            track_write(path)
        dst = os.path.join(self.dir, os.path.relpath(path, self.game.root))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        digest = hashlib.sha256(open(path, 'rb').read()).hexdigest()
        (shutil.move if move else shutil.copy2)(path, dst)
        if hashlib.sha256(open(dst, 'rb').read()).hexdigest() != digest:
            raise IOError(f'backup of {path} does not match the original - nothing was changed')
        self.saved.append(self.game.rel(path))

    def put_back(self, path):
        """Copy the backed-up version of `path` back (after a failed change)."""
        src = os.path.join(self.dir, os.path.relpath(path, self.game.root))
        if os.path.exists(src):
            shutil.copy2(src, path)


def read_rcfs(car):
    """{path: text} of every livery list the car has, checked first so a broken one stops us before anything changes."""
    out = {}
    for f in car.rcfs:
        text = open(f, 'rb').read().decode('utf-8', 'replace')
        try:
            rcf.check(text)
        except ValueError as e:
            raise ValueError(f'can\'t read {os.path.basename(f)}: {str(e).replace("the car\'s livery list (.rcf) ", "it ")}. Nothing was changed. '
                             f'Copy it back from the newest folder in {BACKUP_DIR} or verify the car mod\'s files.')
        out[f] = text
    return out


def write_rcfs(new, old):
    """Write the changed livery lists all-or-nothing: temp files first, then swap them in, undoing on any error."""
    new = {f: t for f, t in new.items() if t != old.get(f)}
    for f, text in new.items():
        rcf.check(text)                                    # never write a list we can't read back
    tmps, done = {}, []
    try:
        for f, text in new.items():
            tmps[f] = f + '.livery_tool.tmp'
            with open(tmps[f], 'wb') as fh:
                fh.write(text.encode('utf-8'))
        for f, tmp in tmps.items():
            track_write(f)
            os.replace(tmp, f)
            done.append(f)
    except Exception:
        for f in done:                                     # put back the ones already swapped in
            with open(f, 'wb') as fh:
                fh.write(old[f].encode('utf-8'))
        raise
    finally:
        for tmp in tmps.values():
            if os.path.exists(tmp):
                os.remove(tmp)


def _repair_note(old):
    fixed = [f'{os.path.basename(f)} line {", ".join(map(str, rcf.repairs(t)))}' for f, t in old.items() if rcf.repairs(t)]
    return f' (also fixed a typo the car mod shipped in {"; ".join(fixed)})' if fixed else ''


def _texture_name(table, new_id):
    """Follow the car's own naming: <dir>\\<prefix><id>.dds, taken from its highest existing livery."""
    for lid in sorted(table, reverse=True):
        tex = table[lid]['texture']
        m = tex and re.match(r'(.*[\\/])([^\\/]*?)(\d+)\.dds$', tex, re.I)
        if m:
            return f'{m.group(1)}{m.group(2)}{new_id}.dds', lid
    raise ValueError('could not work out where this car keeps its liveries')


def _fit(game, car, img):
    (W, H), _ = reference_size(game, car)
    note = ''
    if img.size != (W, H):
        if abs(img.size[0] / img.size[1] - W / H) > 0.01:
            note = f' (warning: your image is {img.size[0]}x{img.size[1]}, this car expects {W}x{H}; it was stretched)'
        img = img.resize((W, H), Image.LANCZOS)
    return img, note


def _write_dds(dest_abs, img, fourcc):
    os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
    track_write(dest_abs)
    tmp = dest_abs + '.tmp'
    dds.write(tmp, img, fourcc)
    os.replace(tmp, dest_abs)


def _norm(path):
    p = path.replace('/', '\\').lower()
    return p[:-4] if p.endswith('.mtx') else p


def _reads_spec(game, material):
    """The finish-map texture a material reads (if it is common_paint_spec), else None."""
    path = game.resolve(material if material.lower().endswith('.mtx') else material + '.mtx')
    if not path:
        return None
    m = re.search(r'name="specularTexture".*?<value v="([^"]+)"', open(path, 'rb').read().decode('utf-8', 'replace'), re.S)
    return m.group(1) if m and 'common_paint_spec' in m.group(1).lower() else None


def finish_support(game, car, paint_materials=None):
    """Can this car show a finish (spec) map from a livery?  -> dict(supported, source, reason, swaps)

    Works if the car's own liveries already swap common_paint_spec.dds, if the paint material a new livery
    ends up with (after the template livery's material swaps) reads common_paint_spec.dds, or if some of the
    car's liveries switch the paint to such a material (we borrow those swap lines).
    """
    text = car.rcf_text()
    m = re.search(r'REPLACE\s+TEXTURE="([^"]*common_paint_spec\.dds)"', text, re.I)
    if m:
        return dict(supported=True, source=m.group(1), reason='', swaps=[])
    table = rcf.liveries(text)
    blocks = rcf.conditions(text)
    try:
        _, template = _texture_name(table, max(table) + 1)
    except ValueError:
        template = None
    swaps_re = r'<REPLACE\s+MATERIAL="([^"]+)"\s+NEWMATERIAL="([^"]+)"\s*/>'
    tswaps = {_norm(a): b for a, b in re.findall(swaps_re, blocks.get(template, ''), re.I)}
    if paint_materials is None:
        from . import model
        paint_materials = {sm.material for _, mesh in model.parts(game, car) for sm in mesh.submeshes if 'PAINT' in sm.material.upper()}
    for mat in paint_materials:
        src = _reads_spec(game, tswaps.get(_norm(mat), mat))
        if src:
            return dict(supported=True, source=src, reason='', swaps=[])
    paint = {_norm(m) for m in paint_materials}
    for lid in sorted(blocks, reverse=True):
        lines = [mm for mm in re.finditer(swaps_re, blocks[lid], re.I) if _norm(mm.group(1)) in paint]
        srcs = [_reads_spec(game, mm.group(2)) for mm in lines]
        if lines and any(srcs):
            return dict(supported=True, source=next(x for x in srcs if x), reason='', swaps=[mm.group(0) for mm in lines])
    return dict(supported=False, source=None, reason="this car's paint material doesn't read a finish map", swaps=[])


def _spec_name(tex_rel):
    return re.sub(r'\.dds$', '_spec.dds', tex_rel, flags=re.I)


def install(game, car, image, name=None, slot=None, alpha=False, spec=None):
    """Install `image` (a path or a PIL image) as a livery. spec: optional PIL image (RGB = gloss, A = reflection)."""
    if isinstance(image, (str, os.PathLike)):
        name = name or os.path.splitext(os.path.basename(image))[0]
        image = Image.open(image)
    name = name or 'My livery'
    texts = read_rcfs(car)                                 # stops here, changing nothing, if a livery list is unreadable
    img, note = _fit(game, car, image)
    img = img.convert('RGBA' if alpha else 'RGB')
    spec_src = None
    if spec is not None:
        fs = finish_support(game, car)
        if fs['supported']:
            spec_src = (fs['source'], fs['swaps'])
            spec, _ = _fit(game, car, spec)
        else:
            note += f' (finish not saved: {fs["reason"]})'
            spec = None
    table = rcf.liveries(texts[car.rcfs[0]])
    backup = Backup(game, f'{car.id}_install')
    if slot is not None and slot in table:                     # update an existing slot in place
        dest_rel = table[slot]['texture']
        if not dest_rel:
            raise ValueError(f'livery {slot} has no paint texture to replace')
        shared = [l for l, v in table.items() if l != slot and (v['texture'] or '').lower() == dest_rel.lower()]
        if shared:
            raise ValueError(f'livery {slot} shares its texture with livery {shared[0]}; add a new livery instead')
        dest = game.resolve(dest_rel) or os.path.join(game.root, *re.split(r'[\\/]', dest_rel))
        old_spec = rcf.spec_of(texts[car.rcfs[0]], slot)
        new_spec_rel = _spec_name(dest_rel) if spec is not None else None
        new_texts = {}
        for f, text in texts.items():                      # work out every change before touching any file
            new = rcf.repair(text)
            if name != table[slot]['name']:
                new = rcf.rename_slot(new, slot, name)
            if (new_spec_rel or None) != (old_spec or None):
                new = rcf.set_spec(new, slot, (spec_src[0], new_spec_rel, spec_src[1]) if new_spec_rel else None)
            new_texts[f] = new
        backup.save(dest)
        if spec is not None:
            backup.save(game.resolve(new_spec_rel) or '')
        for f in car.rcfs:
            backup.save(f)
        spec_abs = os.path.join(os.path.dirname(dest), os.path.basename(new_spec_rel.replace('\\', '/'))) if spec is not None else None
        had_spec = bool(spec_abs and os.path.exists(spec_abs))
        try:
            _write_dds(dest, img, 'DXT5' if alpha else 'DXT1')
            if spec is not None:
                _write_dds(spec_abs, spec, 'DXT5')
            write_rcfs(new_texts, texts)
        except Exception:                                  # leave the livery exactly as it was
            backup.put_back(dest)
            if spec_abs:
                backup.put_back(spec_abs) if had_spec else (os.path.exists(spec_abs) and os.remove(spec_abs))
            raise
        game.refresh()
        return dict(action='updated', slot=slot, name=name, texture=dest, size=img.size, note=note + _repair_note(texts),
                    backup=backup.dir, finish=spec is not None)

    new_id = max(table) + 1
    if slot is not None and slot != new_id:
        raise ValueError(f'livery {slot} does not exist; the next free number on this car is {new_id} '
                         f'(use --slot with an existing number to update that livery instead)')
    tex_rel, template_id = _texture_name(table, new_id)
    dest_dir = game.resolve(os.path.dirname(tex_rel.replace('\\', '/')).replace('/', '\\'))
    if not dest_dir:
        raise FileNotFoundError(f'livery folder {os.path.dirname(tex_rel)} not found')
    dest = os.path.join(dest_dir, os.path.basename(tex_rel.replace('\\', '/')))
    k = 1
    while os.path.exists(dest):          # a leftover file from another livery pack: never overwrite it, use a new name
        k += 1
        tex_rel = re.sub(r'(_le\d*)?\.dds$', f'_le{k if k > 2 else ""}.dds', tex_rel, flags=re.I)
        dest = os.path.join(dest_dir, os.path.basename(tex_rel.replace('\\', '/')))
    spec_rel = _spec_name(tex_rel) if spec is not None else None
    new_texts = {f: rcf.add_slot(t, new_id, name, tex_rel, template_id,               # all of them, before writing anything
                                 spec=(spec_src[0], spec_rel, spec_src[1]) if spec is not None else None)
                 for f, t in texts.items()}
    for f in car.rcfs:
        backup.save(f)
    spec_abs = os.path.join(dest_dir, os.path.basename(spec_rel.replace('\\', '/'))) if spec is not None else None
    try:
        _write_dds(dest, img, 'DXT5' if alpha else 'DXT1')
        if spec_abs:
            _write_dds(spec_abs, spec, 'DXT5')
        write_rcfs(new_texts, texts)
    except Exception:                                      # no half-installed livery: take the new files away again
        for p in (dest, spec_abs):
            if p and os.path.exists(p):
                os.remove(p)
        raise
    note += _repair_note(texts)
    stale = game.resolve(preview_rel(car, new_id))
    if stale:                            # a picture left over from another pack would show the wrong livery
        backup.save(stale, move=True)
    _manifest(game, add=dict(car=car.id, slot=new_id, texture=tex_rel, name=name, spec=spec_rel))
    game.refresh()
    return dict(action='added', slot=new_id, name=name, texture=dest, size=img.size, note=note, backup=backup.dir, finish=spec is not None)


def install_pixels(game, car, rgba, width, height, name, slot=None, spec_rgba=None):
    """Install raw RGBA bytes from the editor (rows top-down). spec_rgba: R = gloss, G = reflection."""
    img = Image.frombuffer('RGBA', (width, height), rgba, 'raw', 'RGBA', 0, 1).convert('RGB')
    spec = None
    if spec_rgba is not None:
        r, g, _, _ = Image.frombuffer('RGBA', (width, height), spec_rgba, 'raw', 'RGBA', 0, 1).split()
        spec = Image.merge('RGBA', (r, r, r, g))
    return install(game, car, img, name, slot, spec=spec)


def ours(game):
    """{(car id, slot)} installed by this tool, from the manifest."""
    try:
        data = json.load(open(os.path.join(game.root, BACKUP_DIR, 'manifest.json')))
        return {(e['car'], e['slot']) for e in data.get('installed', [])}
    except (OSError, ValueError, KeyError):
        return set()


def remove(game, car, slot):
    texts = read_rcfs(car)
    table = rcf.liveries(texts[car.rcfs[0]])
    if slot not in table:
        raise KeyError(f'{car.id} has no livery {slot}')
    if slot != max(table):
        raise ValueError(f'only the last slot ({max(table)}) can be removed, so the numbering stays continuous')
    backup = Backup(game, f'{car.id}_remove{slot}')
    for f in car.rcfs:
        backup.save(f)
    tex = game.resolve(table[slot]['texture']) if table[slot]['texture'] else None
    shared = [l for l, v in table.items() if l != slot and v['texture'] == table[slot]['texture']]
    text0 = texts[car.rcfs[0]]
    spec_rel = rcf.spec_of(text0, slot)
    spec_shared = spec_rel and any(rcf.spec_of(text0, l) == spec_rel for l in table if l != slot)
    write_rcfs({f: rcf.remove_slot(t, slot) for f, t in texts.items()}, texts)
    if tex and not shared:
        backup.save(tex, move=True)                             # moved into the backup, not deleted
    if spec_rel and not spec_shared and game.resolve(spec_rel):
        backup.save(game.resolve(spec_rel), move=True)
    if game.resolve(preview_rel(car, slot)):
        backup.save(game.resolve(preview_rel(car, slot)), move=True)
    _manifest(game, remove=dict(car=car.id, slot=slot))
    game.refresh()
    return dict(slot=slot, name=table[slot]['name'], backup=backup.dir)


def _manifest_load(game):
    try:
        return json.load(open(os.path.join(game.root, BACKUP_DIR, 'manifest.json')))
    except (OSError, ValueError):
        return {'installed': []}


def _manifest(game, add=None, remove=None, update=None):
    path = os.path.join(game.root, BACKUP_DIR, 'manifest.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = _manifest_load(game)
    if update:                                         # (car, slot, {changes})
        car_id, slot, changes = update
        for e in data['installed']:
            if e['car'] == car_id and e['slot'] == slot:
                e.update(changes)
    if add:
        data['installed'].append(dict(add, time=datetime.datetime.now().isoformat(timespec='seconds')))
    if remove:
        data['installed'] = [e for e in data['installed'] if not (e['car'] == remove['car'] and e['slot'] == remove['slot'])]
    track_write(path)
    temp = path + '.tmp'
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
    os.replace(temp, path)


# ---- livery pictures for the in-game livery list --------------------------------------------------------
PREVIEW_SIZE = (2048, 768)                             # what the game's own pictures use (DXT5, transparent background)


def preview_rel(car, slot):
    return f'GUI\\vehicleimages\\vehicleimages_{car.id}\\{car.id}_livery_{slot}.dds'


def _preview_abs(game, car, slot):
    hit = game.resolve(preview_rel(car, slot))
    if hit:
        return hit
    folder = game.resolve(f'GUI\\vehicleimages\\vehicleimages_{car.id}')
    if not folder:
        base = game.resolve('GUI\\vehicleimages') or os.path.join(game.resolve('GUI') or os.path.join(game.root, 'GUI'), 'vehicleimages')
        folder = os.path.join(base, f'vehicleimages_{car.id}')
    return os.path.join(folder, f'{car.id}_livery_{slot}.dds')


def write_preview(game, car, slot, rgba, width, height):
    """Write the picture the livery list shows: GUI/vehicleimages/vehicleimages_<car>/<car>_livery_<N>.dds"""
    if slot not in car.liveries():
        raise KeyError(f'{car.id} has no livery {slot}')
    img = Image.frombuffer('RGBA', (width, height), rgba, 'raw', 'RGBA', 0, 1)
    if img.size != PREVIEW_SIZE:
        img = img.resize(PREVIEW_SIZE, Image.LANCZOS)
    path = _preview_abs(game, car, slot)
    Backup(game, f'{car.id}_picture{slot}').save(path)
    _write_dds(path, img, 'DXT5')
    _manifest(game, update=(car.id, slot, {'preview': game.rel(path)}))
    game.refresh()
    return path


# ---- put back liveries that a mod update removed from a car's livery list ------------------------------
def _listed(car, texture):
    return any((v['texture'] or '').lower() == texture.lower() for v in car.liveries().values())


def missing(game):
    """Liveries this tool installed whose files are still there but which the car's .rcf no longer lists."""
    cars = {c.id: c for c in game.cars()}
    out = []
    for e in _manifest_load(game).get('installed', []):
        car = cars.get(e['car'])
        try:
            if car and game.resolve(e['texture']) and not _listed(car, e['texture']):
                out.append(dict(e, carName=car.name))
        except ValueError:                                 # that car's livery list is unreadable: nothing to offer
            pass
    return out


def restore(game, entries):
    cars = {c.id: c for c in game.cars()}
    restored, skipped = [], []
    for e in entries:
        car = cars.get(e.get('car'))
        if not car:
            skipped.append(dict(name=e.get('name'), reason='car not found')); continue
        if not game.resolve(e['texture']):
            skipped.append(dict(name=e['name'], reason='its texture file is gone')); continue
        try:
            read_rcfs(car)
        except ValueError as err:
            skipped.append(dict(name=e['name'], reason=str(err))); continue
        if _listed(car, e['texture']):
            skipped.append(dict(name=e['name'], reason='already in the list')); continue
        table = car.liveries()
        new_id = max(table) + 1
        _, template = _texture_name(table, new_id)
        spec = None
        if e.get('spec') and game.resolve(e['spec']):
            fs = finish_support(game, car)
            if fs['supported']:
                spec = (fs['source'], e['spec'], fs['swaps'])
        backup = Backup(game, f'{car.id}_restore')
        for f in car.rcfs:
            backup.save(f)
        texts = read_rcfs(car)
        write_rcfs({f: rcf.add_slot(t, new_id, e['name'], e['texture'], template, spec=spec) for f, t in texts.items()}, texts)
        game.refresh()
        old_pic = game.resolve(e['preview']) if e.get('preview') else None
        target = _preview_abs(game, car, new_id)
        if old_pic and os.path.normcase(old_pic) != os.path.normcase(target):
            backup.save(target)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            track_write(target)
            shutil.copy2(old_pic, target)
        elif not old_pic and os.path.exists(target):
            backup.save(target, move=True)               # a picture of some other livery would be misleading
        _manifest(game, update=(car.id, e['slot'], {'slot': new_id, 'preview': game.rel(target) if old_pic else None}))
        restored.append(dict(name=e['name'], car=car.id, carName=car.name, old=e['slot'], slot=new_id))
        game.refresh()
    return dict(restored=restored, skipped=skipped)
