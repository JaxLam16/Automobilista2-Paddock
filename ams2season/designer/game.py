"""Find the AMS2 install and the mod cars in it (cars that ship loose .meb meshes)."""
import os
import re
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from . import rcf as rcf_mod

SKIP_DIRS = {'textures', '_data', 'physics', '_generic_materials', '_296_'}


def find_game():
    """Best-effort Steam lookup on Windows; returns the AMS2 folder or None."""
    candidates = []
    if sys.platform.startswith('win'):
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam'),
                              (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam')):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for val in ('SteamPath', 'InstallPath'):
                            try:
                                candidates.append(winreg.QueryValueEx(k, val)[0])
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        candidates += [r'C:\Program Files (x86)\Steam', r'C:\Program Files\Steam']
    libs = []
    for steam in candidates:
        vdf = os.path.join(steam, 'steamapps', 'libraryfolders.vdf')
        libs.append(steam)
        if os.path.isfile(vdf):
            libs += re.findall(r'"path"\s+"([^"]+)"', open(vdf, encoding='utf-8', errors='replace').read())
    for lib in libs:
        p = os.path.join(lib.replace('\\\\', '\\'), 'steamapps', 'common', 'Automobilista 2')
        if os.path.isfile(os.path.join(p, 'AMS2.exe')) or os.path.isdir(os.path.join(p, 'Vehicles')):
            return p
    return None


@dataclass
class Car:
    id: str            # crd base name, e.g. porsche991gt3r
    name: str          # display name from the crd
    folder: str        # absolute path of the Vehicles/<car> folder
    vhf: str           # absolute path
    rcfs: list         # absolute paths: main .rcf first, then _hr variant if present
    pack: str = ''
    _files: dict = field(default_factory=dict, repr=False)

    @property
    def folder_name(self):
        return os.path.basename(self.folder)

    def local(self, filename):
        """Find a file inside the car folder case-insensitively."""
        if not self._files:
            self._files = {f.lower(): f for f in os.listdir(self.folder)}
        f = self._files.get(filename.lower())
        return os.path.join(self.folder, f) if f else None

    def rcf_text(self):
        return open(self.rcfs[0], 'rb').read().decode('utf-8')

    def liveries(self):
        return rcf_mod.liveries(self.rcf_text())


class Game:
    def __init__(self, root):
        if not os.path.isdir(os.path.join(root, 'Vehicles')):
            raise FileNotFoundError(f'{root} does not look like an Automobilista 2 folder (no Vehicles folder)')
        self.root = str(Path(root).resolve())
        self._dir_cache = {}

    def _listdir(self, d):
        if d not in self._dir_cache:
            names = {}
            try:
                for f in os.listdir(d):
                    names.setdefault(f.lower(), []).append(f)
            except OSError:
                pass
            self._dir_cache[d] = names
        return self._dir_cache[d]

    def resolve(self, rel):
        """Resolve a game-relative path like 'vehicles\\textures\\X.dds' case-insensitively; None if missing."""
        parts = [p for p in re.split(r'[\\/]+', rel) if p]
        if any(p in ('.', '..') or ':' in p for p in parts) or rel.startswith(('/', '\\')):
            raise ValueError('Game references must stay inside the selected game folder.')

        def walk(cur, i):
            if not Path(cur).resolve().is_relative_to(Path(self.root)):
                raise ValueError('Game reference resolves outside the selected game folder.')
            if i == len(parts):
                return cur
            for hit in self._listdir(cur).get(parts[i].lower(), []):
                found = walk(os.path.join(cur, hit), i + 1)
                if found:
                    return found
            return None
        return walk(self.root, 0)

    def refresh(self):
        """Forget cached folder listings (after files were written)."""
        self._dir_cache.clear()

    def rel(self, path):
        return os.path.relpath(path, self.root).replace('/', '\\')

    def packs(self):
        """Map crd path (lower, game-relative) -> mod pack name from UserData/Mods/*/vehiclelist.lst."""
        out = {}
        mods = self.resolve('UserData\\Mods')
        if mods:
            for mod in os.listdir(mods):
                lst = os.path.join(mods, mod, 'vehiclelist.lst')
                if os.path.isfile(lst):
                    for line in open(lst, encoding='utf-8', errors='replace'):
                        if line.strip():
                            out[line.strip().replace('/', '\\').lower()] = mod
        return out

    def cars(self):
        vehicles = self.resolve('Vehicles')
        packs = self.packs()
        cars = []
        for d in sorted(os.listdir(vehicles), key=str.lower):
            folder = os.path.join(vehicles, d)
            if not Path(folder).resolve().is_relative_to(Path(self.root)):
                continue
            if d.lower() in SKIP_DIRS or not os.path.isdir(folder):
                continue
            files = {f.lower(): f for f in os.listdir(folder) if (Path(folder)/f).resolve().is_relative_to(Path(self.root))}
            if not any(f.endswith('.meb') for f in files):
                continue                                  # base-game cars live in the archives
            entries = []
            for crd in [f for f in files if f.endswith('.crd')]:
                try:
                    root = ET.fromstring(open(os.path.join(folder, files[crd]), 'rb').read())
                    props = {p.get('name'): p.get('data') for p in root.iter('prop') if p.get('data') is not None}
                except ET.ParseError:
                    props = {}
                base = crd[:-4]
                entries.append((files[crd][:-4], props.get('Vehicle Name') or base,
                                (props.get('Vehicle Render Model') or base + '.vhf').lower(), packs.get(f'vehicles\\{d}\\{files[crd]}'.lower(), '')))
            if not entries:                               # no crd (partial copies): fall back to the vhf/rcf pair
                for vhf in [f for f in files if f.endswith('.vhf') and not f.endswith('_cockpit.vhf')]:
                    entries.append((files[vhf][:-4], d, vhf, ''))
            for cid, name, vhf, pack in entries:
                base = vhf[:-4]
                rcfs = [os.path.join(folder, files[f]) for f in (base + '.rcf', base + '_hr.rcf') if f in files]
                if vhf not in files or not rcfs:
                    continue
                cars.append(Car(cid, name, folder, os.path.join(folder, files[vhf]), rcfs, pack))
        return cars

    def car(self, query):
        cars = self.cars()
        q = query.lower()
        for test in (lambda c: c.id.lower() == q or c.folder_name.lower() == q,
                     lambda c: q in c.id.lower() or q in c.folder_name.lower() or q in c.name.lower()):
            hits = [c for c in cars if test(c)]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                raise LookupError(f'"{query}" matches several cars: ' + ', '.join(f'{c.id} ({c.name})' for c in hits))
        raise LookupError(f'no mod car matches "{query}" - run "list" to see them')

    def livery_file(self, car, livery_id):
        tex = car.liveries().get(livery_id, {}).get('texture')
        return self.resolve(tex) if tex else None
