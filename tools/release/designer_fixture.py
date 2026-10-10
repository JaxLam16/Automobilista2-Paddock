"""Authored synthetic car used only by designer tests and portable verification."""
from pathlib import Path
import struct
from PIL import Image
from ams2season.designer import dds
from ams2season.designer.game import Game


def synthetic_game(root):
    """A tiny authored mesh and texture; contains no AMS2 or mod content."""
    folder = root / 'Vehicles' / 'sample'
    folder.mkdir(parents=True)
    (folder / 'sample.crd').write_text('<root><prop name="Vehicle Name" data="Synthetic car"/><prop name="Vehicle Render Model" data="sample.vhf"/></root>')
    (folder / 'sample.vhf').write_text('<root><NODE type="LOD" Name="BODY"><RESOURCE Filename="vehicles/sample/body_loda.meb"/></NODE></root>')
    positions = [(-1, 0, -2), (1, 0, -2), (1, 0, 2), (-1, 0, 2)]
    # A paintable quad in the same binary layout used by loose mod meshes.
    data = bytearray(struct.pack('<I4s', 0x01000000, b'\0'*4) + b'Body\0')
    data += b'\0' * (-len(data) % 4)
    data += struct.pack('<III10f', 4, 3, 1, *([0]*10))
    for typ, semantic, index, values in [(2, 0, 0, positions), (2, 2, 0, [(0, 1, 0)]*4), (1, 3, 2, [(0, 0), (1, 0), (1, 1), (0, 1)])]:
        data += struct.pack('<III', typ, semantic, index)
        flat = [v for row in values for v in row]
        data += struct.pack('<' + 'f'*len(flat), *flat)
    data += b'vehicles/sample/PAINT.mtx\0'
    data += b'\0' * (-len(data) % 4)
    data += struct.pack('<II6H', 0, 2, 0, 2, 1, 0, 3, 2)
    data += b'\0' * (-len(data) % 4)
    data += struct.pack('<HH10f', 0, 3, *([0]*10))
    (folder / 'body_loda.meb').write_bytes(data)
    text = '''<REPLACEMENT_SYSTEM>
<INPUTS><INPUT NAME="LIVERY" OPTIONS="1"/></INPUTS>
<NAMES INPUT="LIVERY">
<NAME LIVERY="1" NAME="Original" />
</NAMES>
<CONDITION LIVERY="1">
<REPLACE TEXTURE="vehicles/textures/common_paint.dds" NEWTEXTURE="vehicles/sample/paint_1.dds" />
</CONDITION>
<CONDITION TIRE="1"><REPLACE TEXTURE="tyre.dds" NEWTEXTURE="unchanged.dds" /></CONDITION>
</REPLACEMENT_SYSTEM>'''
    for name in ('sample.rcf', 'sample_hr.rcf'):
        (folder / name).write_text(text)
    dds.write(folder / 'paint_1.dds', Image.new('RGB', (64, 64), 'blue'))
    return Game(str(root))
