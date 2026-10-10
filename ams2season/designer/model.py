"""Assemble a car's LOD-A parts (placed via its .vhf) for the viewer and the template exporter."""
import base64
import os

import numpy as np

from . import meb, vhf

SKIP = ('CPIT', 'SHADOW', 'BLUR', 'LIGHTGLOWS', 'SUSPENSION', 'ENGINE')
LIVERY_UV = 'TEXCOORD2'


def parts(game, car, skip=SKIP):
    """Yield (vhf part dict, Meb) for every LOD-A mesh the car's render model uses."""
    for p in vhf.read(car.vhf):
        if any(s in p['lod'].upper() for s in skip):
            continue
        res = next((r for r in p['resources'] if r and r.lower().endswith('loda.meb')), None)
        if not res:
            continue
        path = game.resolve(res) or car.local(res.replace('/', '\\').split('\\')[-1])
        if not path:
            continue
        try:
            yield p, meb.read(path)
        except (ValueError, KeyError, IndexError):
            continue


def paint_triangles(game, car):
    """Yield (uv (T,3,2), positions (T,3,3)) for every PAINT submesh, in car space."""
    for p, m in parts(game, car):
        if not m.has(LIVERY_UV):
            continue
        uv = m.stream(LIVERY_UV)[:, :2]
        pos = m.stream('POSITION0') + np.asarray(p['offset'], np.float32)
        for sm in m.submeshes:
            if 'PAINT' in sm.material.upper():
                tri = m.indices(sm)
                yield uv[tri], pos[tri], tri


def _b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def viewer_json(game, car):
    out = []
    for p, m in parts(game, car):
        if not m.has('POSITION0') or not m.has('NORMAL0'):
            continue
        uv0 = m.stream('TEXCOORD0')[:, :2] if m.has('TEXCOORD0') else np.zeros((m.nv, 2), np.float32)
        uv2 = m.stream(LIVERY_UV)[:, :2] if m.has(LIVERY_UV) else uv0
        groups = [dict(material=os.path.basename(sm.material.replace('\\', '/')).rsplit('.', 1)[0].upper(),
                       index=_b64(m.indices(sm).astype(np.uint32))) for sm in m.submeshes if sm.tri_count]
        out.append(dict(name=m.name, offset=p['offset'], quat=p['quat'],
                        pos=_b64(m.stream('POSITION0')), nrm=_b64(m.stream('NORMAL0')[:, :3]),
                        uv0=_b64(uv0), uv2=_b64(uv2), groups=groups))
    return dict(car=car.id, name=car.name, parts=out)
