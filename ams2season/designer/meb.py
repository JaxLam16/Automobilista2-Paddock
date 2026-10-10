"""Reader for Madness-engine .meb meshes as found loose in AMS2 mod cars.

Verified on all 14 cars of the GT3 Gen0 pack (versions 0x01000000 and 0x01400000).

Layout
  header   : u32 version, u8 flags[4] (flags[0] == 1 -> skinned), name (null-terminated, padded to 4),
             u32 vertex count, u32 stream count, u32 submesh count, bounding sphere (4f) + AABB (6f)
  skinned  : u32 bone count, u32 name-blob size, name blob, bone count x 3x4 f32 rest transforms
  streams  : per stream u32 type, u32 semantic, u32 set index, then vertex count x element
  submeshes: .mtx path (null-terminated, padded to 4), u32 flags, u32 triangle count,
             [skinned: u32 palette count + u16 bone ids, padded to 4], u16 indices (padded to 4),
             u16 min/max vertex, bounding sphere + AABB

The livery texture is mapped with TEXCOORD2. Skinned meshes (tyres, wipers) are stored in rest pose.
"""
import struct
from dataclasses import dataclass, field

import numpy as np

TYPE_SIZE = {0: 4, 1: 8, 2: 12, 3: 16, 4: 4, 5: 4}      # f32, f32x2, f32x3, f32x4, u8x4 colour, u8x4 bone ids
SEM_NAME = {0: 'POSITION', 1: 'BLENDWEIGHT', 2: 'NORMAL', 3: 'TEXCOORD', 4: 'TANGENT',
            5: 'BINORMAL', 6: 'COLOR', 8: 'BLENDINDICES'}
VERSIONS = (0x01000000, 0x01400000)


@dataclass
class Stream:
    type: int
    sem: int
    idx: int
    off: int
    size: int

    @property
    def key(self):
        return f"{SEM_NAME.get(self.sem, 'SEM%d' % self.sem)}{self.idx}"


@dataclass
class Submesh:
    material: str
    tri_count: int
    idx_off: int
    vmin: int
    vmax: int


@dataclass
class Meb:
    name: str
    nv: int
    streams: list
    submeshes: list
    data: bytes
    bones: list = field(default_factory=list)

    def has(self, key):
        return any(s.key == key for s in self.streams)

    def stream(self, key):
        s = next(s for s in self.streams if s.key == key)
        if s.type in (4, 5):
            return np.frombuffer(self.data, np.uint8, self.nv * 4, s.off).reshape(-1, 4)
        n = s.size // 4
        return np.frombuffer(self.data, np.float32, self.nv * n, s.off).reshape(-1, n)

    def indices(self, sm):
        return np.frombuffer(self.data, np.uint16, sm.tri_count * 3, sm.idx_off).reshape(-1, 3)


def read(path):
    b = open(path, 'rb').read()
    u32 = lambda o: struct.unpack_from('<I', b, o)[0]
    if u32(0) not in VERSIONS:
        raise ValueError(f'{path}: unknown meb version {u32(0):#x}')
    end = b.index(b'\0', 8)
    name = b[8:end].decode('ascii')
    o = (end + 1 + 3) & ~3
    nv, nstreams, nsub = u32(o), u32(o + 4), u32(o + 8)
    o += 12 + 40
    bones = []
    if b[4] == 1:
        nb, blob = u32(o), u32(o + 4)
        names = b[o + 8:o + 8 + blob].split(b'\0')[:nb]
        o += 8 + blob
        for i in range(nb):
            bones.append((names[i].decode('ascii', 'replace'), struct.unpack_from('<12f', b, o)))
            o += 48
    streams = []
    for _ in range(nstreams):
        t, sem, idx = u32(o), u32(o + 4), u32(o + 8)
        size = TYPE_SIZE[t]
        streams.append(Stream(t, sem, idx, o + 12, size))
        o += 12 + nv * size
    subs = []
    for _ in range(nsub):
        end = b.index(b'\0', o)
        mat = b[o:end].decode('ascii')
        o = (end + 1 + 3) & ~3
        _flags, tris = u32(o), u32(o + 4)
        idx_off = o + 8
        if bones:
            npal = u32(idx_off)
            idx_off = (idx_off + 4 + 2 * npal + 3) & ~3
        o = (idx_off + tris * 6 + 3) & ~3
        vmin, vmax = struct.unpack_from('<HH', b, o)
        o += 4 + 40
        subs.append(Submesh(mat, tris, idx_off, vmin, vmax))
    if o != len(b):
        raise ValueError(f'{path}: parsed to {o:#x} but file is {len(b):#x}')
    return Meb(name, nv, streams, subs, b, bones)
