"""DDS helpers: read a texture's size/format, write DXT1/DXT5 with a full mip chain."""
import io
import struct

from PIL import Image

BLOCK = {'DXT1': 8, 'DXT3': 16, 'DXT5': 16}


def info(path):
    with open(path, 'rb') as f:
        h = f.read(148)
    if h[:4] != b'DDS ':
        raise ValueError(f'{path} is not a DDS file')
    height, width = struct.unpack_from('<II', h, 12)
    mips = struct.unpack_from('<I', h, 28)[0]
    fourcc = h[84:88].decode('ascii', 'replace')
    return dict(width=width, height=height, mips=max(1, mips), format=fourcc)


def load(path):
    """Decode the top mip level with Pillow (handles DXT1/3/5 and BC7)."""
    return Image.open(path)


def _encode_level(im, fourcc):
    w, h = im.size
    if not _encode_level.checked:
        try:
            Image.new('RGB', (4, 4)).save(io.BytesIO(), 'DDS', pixel_format=fourcc)
        except Exception:
            raise RuntimeError('Your Pillow version cannot write compressed DDS. Run: pip install --upgrade pillow')
        _encode_level.checked = True
    if w < 4 or h < 4:
        im = im.resize((max(4, w), max(4, h)), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, 'DDS', pixel_format=fourcc)
    data = buf.getvalue()[128:]
    expect = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * BLOCK[fourcc]
    if len(data) < expect:
        raise ValueError(f'encoder returned {len(data)} bytes for {w}x{h}, expected {expect}')
    return data[:expect]


_encode_level.checked = False


def write(path, img, fourcc='DXT1'):
    """Write `img` as a DXT1 (no alpha) or DXT5 (alpha) DDS with mips down to 1x1. Returns mip count."""
    img = img.convert('RGBA' if fourcc == 'DXT5' else 'RGB')
    w, h = img.size
    levels, level = [], img
    while True:
        levels.append(_encode_level(level, fourcc))
        if level.size == (1, 1):
            break
        level = level.resize((max(1, level.size[0] // 2), max(1, level.size[1] // 2)), Image.BOX)
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000          # caps|height|width|pixelformat|mipcount|linearsize
    pf = struct.pack('<II4sIIIII', 32, 0x4, fourcc.encode(), 0, 0, 0, 0, 0)
    caps = 0x8 | 0x1000 | 0x400000                                  # complex|texture|mipmap
    hdr = b'DDS ' + struct.pack('<IIIIIII', 124, flags, h, w, len(levels[0]), 0, len(levels)) + b'\0' * 44 + pf \
        + struct.pack('<IIIII', caps, 0, 0, 0, 0)
    with open(path, 'wb') as f:
        f.write(hdr)
        for lv in levels:
            f.write(lv)
    return len(levels)
