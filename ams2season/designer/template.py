"""Export a paint template kit for a car: UV outlines, paintable-area mask, current livery, preview."""
import os

import numpy as np
from PIL import Image, ImageDraw

from . import dds, model


def reference_size(game, car):
    """Size of the car's existing liveries (first one that exists), so new ones match."""
    for lid in car.liveries():
        f = game.livery_file(car, lid)
        if f:
            i = dds.info(f)
            return (i['width'], i['height']), lid
    return (4096, 4096), None


def build(game, car, out_dir, livery_id=None):
    (W, H), ref_id = reference_size(game, car)
    os.makedirs(out_dir, exist_ok=True)
    mask = Image.new('L', (W, H), 0)
    outline = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    dm, do = ImageDraw.Draw(mask), ImageDraw.Draw(outline)
    lw = max(1, W // 1024)
    scale = np.array([W, H], np.float32)
    for uv, _pos, tri in model.paint_triangles(game, car):
        px = uv * scale
        for t in px:
            dm.polygon([tuple(p) for p in t], fill=255)
        # island boundaries = edges used by exactly one triangle
        edges = np.sort(np.stack([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]], 1).reshape(-1, 2), 1)
        lines = np.stack([px[:, [0, 1]], px[:, [1, 2]], px[:, [2, 0]]], 1).reshape(-1, 2, 2)
        _, inv, counts = np.unique(edges, axis=0, return_inverse=True, return_counts=True)
        for a, b in lines[counts[inv.ravel()] == 1]:
            do.line([tuple(a), tuple(b)], fill=(255, 0, 200, 255), width=lw)
    mask.save(os.path.join(out_dir, 'mask.png'))
    outline.save(os.path.join(out_dir, 'uv_outlines.png'))
    base_id = livery_id if livery_id is not None else ref_id
    base_file = game.livery_file(car, base_id) if base_id is not None else None
    if base_file:
        base = dds.load(base_file).convert('RGB')
        if base.size != (W, H):
            base = base.resize((W, H), Image.LANCZOS)
    else:
        base = Image.new('RGB', (W, H), (200, 200, 200))
    base.save(os.path.join(out_dir, f'livery_{base_id}.png' if base_file else 'blank.png'))
    shade = Image.new('RGB', (W, H), (40, 42, 46))
    preview = Image.composite(base, shade, mask)
    preview.paste(outline, (0, 0), outline)
    preview.save(os.path.join(out_dir, 'template_preview.png'))
    return dict(size=(W, H), base=base_id if base_file else None, out=out_dir)
