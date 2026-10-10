"""Parse a Madness .vhf render model: which .meb each LOD uses and where the part sits on the car."""
import xml.etree.ElementTree as ET


def read(path):
    root = ET.fromstring(open(path, 'rb').read())
    mats = {m.get('id'): m for m in root.iter('MATRIX')}
    parts = []
    for lod in root.iter('NODE'):
        if lod.get('type') != 'LOD':
            continue
        m = mats.get(lod.get('MatrixNumber'))
        parts.append(dict(
            lod=lod.get('Name') or '',
            offset=[float(v) for v in m.get('Offset', '0 0 0').split()] if m is not None else [0.0, 0.0, 0.0],
            quat=[float(v) for v in m.get('Orientation', '0 0 0 1').split()] if m is not None else [0, 0, 0, 1.0],
            resources=[r.get('Filename') for r in lod.iter('RESOURCE')]))
    return parts
