"""The decal library: import a zip of logos, and small thumbnails so big libraries load quickly."""
import hashlib
import io
import os
import re
import zipfile

from PIL import Image

IMAGE_EXT = {'.png', '.svg', '.jpg', '.jpeg', '.webp'}
MAX_FILE = 60 << 20            # per logo
MAX_TOTAL = 3 << 30            # whole zip, unpacked (guards against zip bombs)


def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name or '').strip(' .')
    return name[:100] or 'Untitled'


def _inside(base, path):
    base, path = os.path.realpath(base), os.path.realpath(path)
    return path == base or path.startswith(base + os.sep)


def _is_image(data, ext):
    if ext == '.svg':
        head = data[:4096].decode('utf-8', 'ignore').lower()
        return '<svg' in head
    try:
        Image.open(io.BytesIO(data)).verify()
        return True
    except Exception:
        return False


def import_zip(data, zip_name, decals_dir):
    """Unpack every logo in a zip into decals/<zip name>/..., named after its file (without the extension).

    Folders inside the zip become sub-categories. Returns a summary dict.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("that file isn't a zip archive")
    members = []
    for info in zf.infolist():
        name = info.filename.replace('\\', '/')
        comps = [c for c in name.split('/') if c not in ('', '.', '..')]
        if info.is_dir() or not comps or comps[0] == '__MACOSX' or any(c.startswith('.') for c in comps):
            continue
        members.append((info, comps))
    images = [(i, c) for i, c in members if os.path.splitext(c[-1])[1].lower() in IMAGE_EXT]
    skipped = [('/'.join(c), 'not an image') for i, c in members if os.path.splitext(c[-1])[1].lower() not in IMAGE_EXT]
    if not images:
        raise ValueError('no PNG, SVG, JPG or WEBP images in that zip')
    if sum(i.file_size for i, _ in images) > MAX_TOTAL:
        raise ValueError('that zip unpacks to more than 3 GB')
    # a zip usually wraps everything in one folder (Sponsors.zip -> Sponsors/...): don't repeat it
    if all(len(c) > 1 for _, c in images) and len({c[0] for _, c in images}) == 1:
        images = [(i, c[1:]) for i, c in images]
    folder = safe_name(os.path.splitext(os.path.basename(zip_name or 'Imported'))[0])
    root = os.path.join(decals_dir, folder)
    added = existing = 0
    for info, comps in images:
        if info.file_size > MAX_FILE:
            skipped.append(('/'.join(comps), 'bigger than 60 MB')); continue
        content = zf.read(info)
        stem, ext = os.path.splitext(comps[-1])
        ext = ext.lower()
        if not _is_image(content, ext):
            skipped.append(('/'.join(comps), 'not a readable image')); continue
        out_dir = os.path.join(root, *[safe_name(c) for c in comps[:-1]])
        target = os.path.join(out_dir, safe_name(stem) + ext)
        if not _inside(decals_dir, target):
            skipped.append(('/'.join(comps), 'bad path')); continue
        k = 1
        while os.path.exists(target):
            if open(target, 'rb').read() == content:
                break
            k += 1
            target = os.path.join(out_dir, f'{safe_name(stem)} ({k}){ext}')
        if os.path.exists(target):
            existing += 1
            continue
        os.makedirs(out_dir, exist_ok=True)
        with open(target, 'wb') as f:
            f.write(content)
        added += 1
    return dict(folder=folder, added=added, existing=existing, skipped=[dict(name=n, reason=r) for n, r in skipped])


def thumbnail(path, cache_dir, size=176):
    """A small PNG of a library image, cached by path and modification time."""
    st = os.stat(path)
    key = hashlib.sha1(f'{path}|{st.st_mtime_ns}|{st.st_size}|{size}'.encode()).hexdigest()[:20]
    out = os.path.join(cache_dir, 'thumb_' + key + '.png')
    if not os.path.exists(out):
        im = Image.open(path)
        im.draft('RGB', (size * 2, size * 2))            # fast JPEG downscale
        im = im.convert('RGBA')
        im.thumbnail((size, size), Image.LANCZOS)
        tmp = out + f'.{os.getpid()}.tmp.png'
        im.save(tmp)
        os.replace(tmp, out)
    return out
