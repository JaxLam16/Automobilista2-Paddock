"""Small, lossless BFF reader/editor for installed AMS2 livery configurations.

RC4 keys and format details adapted from Nenkai/PCarsTools (MIT).
See LIVERY_EDITOR_NOTICES.txt. No textures are removed or repacked.
"""
from __future__ import annotations

import base64
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

# Populated from the MIT-licensed PCarsTools PC2AndAbove keyset.
_KEYS_B64 = (
    'TjVbWilYRF53ezF1X2JdPzJASFRBNA==',
    'VmJVNEghR1pmWVZkWEFZKzYobXVTNA==',
    'dk52YTZpTSFDajNEV2JWZjBPS0Ewdg==',
    'NUJ7N05VRX4pUS1lKzhWJUhBMjQqaQ==',
    'T2RjZXJ4UXRRSklieG9MQktWN3BQZQ==',
    'ZEdmT2lDZGZTMk1sSFZVenl6Y0hJZQ==',
    'UGpyNipiNiMqP3F3e0xxek8/MUhTJA==',
    'RWtrdWcyQ3dBaFlRSjJodm5wRnNCMQ==',
    'WnVnVGt6a09YV29ZVHZxWHBETEp0bg==',
    'NVJIRkhFUjlHNzJlUUdsa3hoRk1sbg==',
    'MGh3RFoxJHMoeVBaXXRAQkxESlZxOA==',
    'fVouYytsayUzalk4cDRRQzBfMmB4Ng==',
    'NEFtUnlMNGxKSmNCVnM3cjZ2ak92Vw==',
    'V0s4d1FYUnFXcFN3R1laQ1N4eEl2bw==',
    'eVgjamtIRGV0XXQ/KjNTTW5pTDY4IQ==',
    'OXgrUTB4Zyt2NjkuZnxiLVBLRDJrRA==',
    'Rmt8P21SWzFRRGZLNihyJC0qeV17Yg==',
    'RVZqbzZGRns2UWRwW3d8XyxmYEtWJA==',
    'k5X01LqS5NmGxLqv+ujK9PKSsv7N9fmk4Yg=',
    'osbe5fKm6v7NvOOks/PYvLu17ZvN9eOjpc0=',
    'h8bZ6OOzqc3B9OaypMmV9OuGs83N4+b47c0=',
    'ktzE4byit83Z48T6tfvu8OSVh5v7wunq5M0=',
    '7MjZsPCgj9zfrPSzr9zP8PKSssTe8uKihPk=',
    'otveteX/st7cwsWmppubxfWCtM2b5sG0t80=',
    'r4fspKaypo3Epub+ppTN0vS2ptXet+WypM0=',
    'tfzY1NCv48fJ+sPyv83I5NS1suft//CRgs4=',
    'st3N5qb4s+zb9PT/pt7psMOkh+nK5Nfssv4=',
    '7cbN4PClst2bsvey8N6R6OOzpfn8sPCHoso=',
    '8u6f5MKGopr5wOOwntmTt+TmtYGY0OXt8ck=',
    'l9+f1OT1pp6NwuuivunH8OamjNmb1PmytMk=',
    'tcruo8Gmrdnb5PqitM2I8KSit83Yu6Oiv80=',
    'stjE5bfx+t7b4umi8cnv5PWipc2P4/Sxpso=',
)
_KEYS = tuple(base64.b64decode(k) for k in _KEYS_B64)
_TOC = struct.Struct('<QQIIQBBI4s')
_MASK = (1 << 64) - 1
MAX_RCF_BYTES = 8 * 1024 * 1024


class UnsupportedBff(ValueError):
    pass


def rc4(key: bytes, data: bytes) -> bytes:
    box = list(range(256))
    j = 0
    for i in range(256):
        j = (j + box[i] + key[i % len(key)]) & 255
        box[i], box[j] = box[j], box[i]
    result = bytearray(data)
    i = j = 0
    for n in range(len(result)):
        i = (i + 1) & 255
        j = (j + box[i]) & 255
        box[i], box[j] = box[j], box[i]
        result[n] ^= box[(box[i] + box[j]) & 255]
    return bytes(result)


def _mix(a: int, b: int, c: int) -> tuple[int, int, int]:
    for cr, al, br in ((43, 9, 8), (38, 23, 5), (35, 49, 11), (12, 18, 22)):
        a = ((a - b - c) & _MASK) ^ (c >> cr)
        b = ((b - c - a) & _MASK) ^ ((a << al) & _MASK)
        c = ((c - a - b) & _MASK) ^ (b >> br)
    return a, b, c


def path_uid(path: str) -> int:
    """Madness' case-insensitive 64-bit path identifier."""
    if not path:
        return 0x8DB63936938575BF
    data = path.lower().replace('/', '\\').encode('ascii', errors='replace')
    a = b = 0
    c = 0x9E3779B97F4A7C13
    cursor = 0
    while len(data) - cursor >= 24:
        a = (a + int.from_bytes(data[cursor:cursor + 8], 'big')) & _MASK
        b = (b + int.from_bytes(data[cursor + 8:cursor + 16], 'big')) & _MASK
        c = (c + int.from_bytes(data[cursor + 16:cursor + 24], 'big')) & _MASK
        a, b, c = _mix(a, b, c)
        cursor += 24
    tail = data[cursor:]
    c = (c + len(data)) & _MASK
    a = (a + int.from_bytes(tail[:8], 'little')) & _MASK
    b = (b + int.from_bytes(tail[8:16], 'little')) & _MASK
    c = (c + (int.from_bytes(tail[16:], 'little') << 8)) & _MASK
    return _mix(a, b, c)[2]


def checksum(data: bytes) -> int:
    return zlib.crc32(data) ^ 0xFFFFFFFF


@dataclass(frozen=True)
class Entry:
    index: int
    uid: int
    offset: int
    packed_size: int
    size: int
    modified: int
    compression: int
    flag: int
    crc: int
    extension: bytes


class BffArchive:
    """Reads just the index and requested entries, even for large car packages."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self.file_size = self.path.stat().st_size
        with self.path.open('rb') as f:
            header = f.read(0x130)
            if len(header) != 0x130 or header[:4] != b' KAP':
                raise UnsupportedBff('Unrecognized BFF format: ' + self.path.name)
            count = struct.unpack_from('<I', header, 8)[0]
            toc_size = struct.unpack_from('<I', header, 0x118)[0]
            self.encryption = header[0x12D]
            if not count or count > 100_000 or toc_size != count * 42 or 0x130 + toc_size > self.file_size:
                raise ValueError('Invalid BFF index: ' + self.path.name)
            if self.encryption not in (0, 2):
                raise UnsupportedBff('This BFF encryption variant is not supported: ' + self.path.name)
            encrypted = f.read(toc_size)
        hint = 3 if 'persistent' in self.path.stem.lower() else 4
        indices = [hint] + [i for i in range(len(_KEYS)) if i != hint]
        for index in (indices if self.encryption else [0]):
            key = _KEYS[index] if self.encryption else b''
            toc = rc4(key, encrypted) if key else encrypted
            records = [_TOC.unpack_from(toc, i * 42) for i in range(count)]
            if all(0x130 + toc_size <= r[1] <= self.file_size and
                   r[1] + r[2] <= self.file_size and r[5] in (0, 1, 2, 3, 4)
                   for r in records):
                self.key, self.toc = key, toc
                self.entries = [Entry(i, *r) for i, r in enumerate(records)]
                self.by_uid = {e.uid: e for e in self.entries}
                break
        else:
            raise UnsupportedBff('Could not read the BFF index: ' + self.path.name)
        if len(self.by_uid) != len(self.entries):
            raise ValueError('Duplicate paths in BFF: ' + self.path.name)

    def has(self, path: str) -> bool:
        return path_uid(path) in self.by_uid

    def read(self, path: str, limit: int = MAX_RCF_BYTES) -> bytes:
        entry = self.by_uid.get(path_uid(path))
        if entry is None:
            raise LookupError('Not found in ' + self.path.name + ': ' + path)
        return self.read_entry(entry, limit)

    def read_entry(self, entry: Entry, limit: int = MAX_RCF_BYTES) -> bytes:
        if entry.size > limit or entry.packed_size > max(limit * 2, 1024):
            raise ValueError('Packed entry exceeds the size limit: ' + self.path.name)
        with self.path.open('rb') as f:
            f.seek(entry.offset)
            packed = f.read(entry.packed_size)
        if len(packed) != entry.packed_size or checksum(packed) != entry.crc:
            raise ValueError('BFF entry checksum mismatch: ' + self.path.name)
        data = rc4(self.key, packed) if self.key else packed
        if entry.compression == 1:
            # Some engine archives use raw Deflate, others have the zlib header.
            for window in (15, -15):
                try:
                    decoder = zlib.decompressobj(window)
                    raw = decoder.decompress(data, entry.size + 1)
                    if not decoder.eof or len(raw) != entry.size:
                        raise ValueError('Invalid compressed entry in ' + self.path.name)
                    return raw
                except zlib.error:
                    continue
            raise ValueError('Could not decompress an entry in ' + self.path.name)
        if entry.compression == 0:
            if len(data) != entry.size:
                raise ValueError('Invalid uncompressed entry in ' + self.path.name)
            return data
        raise UnsupportedBff('This entry uses unsupported compression in ' + self.path.name)

    def patches(self, replacements: dict[str, bytes]) -> list[tuple[int, bytes]]:
        """Replace RCF streams in their existing slots; preserve every other asset.

        Retaining the original expanded size allows later re-enabling every
        saved livery without relocating streams or changing section metadata.
        """
        patches = []
        toc = bytearray(self.toc)
        for name, raw in replacements.items():
            entry = self.by_uid.get(path_uid(name))
            if entry is None or entry.extension.rstrip(b'\0') != b'rcf':
                raise ValueError('The requested RCF is missing in ' + self.path.name)
            existing = self.read_entry(entry)
            if existing == raw or existing.rstrip() == raw.rstrip():
                continue
            if len(raw) > entry.size:
                raise ValueError('The saved RCF no longer fits in ' + self.path.name + '. Rescan after restoring the original mod.')
            padded = raw + b' ' * (entry.size - len(raw))
            if entry.compression == 0:
                payload = padded
            elif entry.compression == 1:
                candidates = [zlib.compress(padded, level) for level in (9, 6, 1)]
                payload = min(candidates, key=len)
                if len(payload) > entry.packed_size:
                    raise ValueError('The edited RCF cannot fit in ' + self.path.name + '; no files were changed.')
                payload += b'\0' * (entry.packed_size - len(payload))
            else:
                raise UnsupportedBff('Editing this compression variant is unsupported: ' + self.path.name)
            encoded = rc4(self.key, payload) if self.key else payload
            if len(encoded) != entry.packed_size:
                raise ValueError('Invalid replacement size for ' + self.path.name)
            patches.append((entry.offset, encoded))
            struct.pack_into('<I', toc, entry.index * 42 + 34, checksum(encoded))
        if patches:
            patches.append((0x130, rc4(self.key, bytes(toc)) if self.key else bytes(toc)))
        return patches
