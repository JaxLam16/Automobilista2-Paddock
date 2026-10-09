"""BOP-only package patches and staged, journalled game-file transactions.

The existing livery reader/editor is not changed. BOP uses its tested BFF index,
hash and encryption routines, with a separate writer restricted to physics/CRD.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path

from .bff import BffArchive, UnsupportedBff, checksum, path_uid, rc4
from .liveries import _game_running, _json_write, _relative


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def value_patches(archive: BffArchive, replacements: dict[str, bytes], *, allow_relocation=False):
    """Replace physics entries; full donors may grow documented BFF layouts.

    PCarsTools PakFileHeader.cs/PAK.bt describe the alignment and TOC registers.
    CRC/section tables are not guessed. A render-only DHSA preservation attempt
    passed readback tests but hung the Mustang in live AMS2. All relocation with
    section metadata remains blocked until game-compatible handling is proven.
    """
    patches, verify = [], {}
    toc = bytearray(archive.toc)
    append_offset = archive.file_size
    allowed = {'.crd', '.cdfbin', '.edfbin', '.gdfbin', '.vdfm', '.cdf', '.edf', '.gdf'}
    for name, raw in replacements.items():
        if Path(name).suffix.lower() not in allowed:
            raise ValueError('Only decoded physics and class-definition files can be edited here.')
        entry = archive.by_uid.get(path_uid(name))
        if entry is None:
            raise ValueError('A physics stream is missing from ' + archive.path.name)
        existing = archive.read(name)
        if existing == raw:
            continue
        if name.lower().endswith('.crd'):
            if len(raw) > entry.size:
                # A shorter class name leaves padding at the end of the packed
                # XML. Reclaim it before restoring a longer original name;
                # padding is allocation, not part of any property value.
                raw = raw.rstrip(b' ')
            if len(raw) > entry.size:
                # Reclaim formatting only BETWEEN consecutive self-closing prop
                # tags. Property values/order and every other XML byte survive.
                from .bop_physics import crd_properties
                properties = crd_properties(raw)
                raw = re.sub(rb'(<prop\b[^>]*?/>)[\t\r\n ]+(?=<prop\b)', rb'\1', raw, flags=re.I)
                if crd_properties(raw) != properties: raise ValueError('CRD whitespace compaction changed a property.')
            if len(raw) > entry.size:
                raise ValueError('The new class text is longer than the allocated CRD in ' + archive.path.name +
                                 '. This package needs rebuilding with the mod author’s tools; nothing was applied.')
            raw = raw.ljust(entry.size, b' ')
        if len(raw) != entry.size:
            # Normal coefficient widening retains its allocation. Whole donor
            # streams may resize, with bounded relocation checked below.
            if not allow_relocation and (entry.compression != 1 or Path(name).suffix.lower() not in {'.cdfbin', '.cdf'}):
                raise ValueError('This edit would resize an unsupported binary physics stream; nothing was applied.')
            from .bop_physics import shcb_region, vdfm_references
            validator = vdfm_references if name.lower().endswith('.vdfm') else shcb_region
            validator(existing); validator(raw)
            if len(raw) > 8 * 1024 * 1024: raise ValueError('Chassis physics exceeds 8 MB.')
        if entry.compression == 0:
            payload = raw
        elif entry.compression == 1:
            # Match the existing stream wrapper (zlib vs raw Deflate).
            with archive.path.open('rb') as f:
                f.seek(entry.offset)
                encoded = f.read(entry.packed_size)
            original = rc4(archive.key, encoded) if archive.key else encoded
            window = 15
            try: zlib.decompress(original)
            except zlib.error: window = -15
            candidates = []
            for level in (9, 6, 1):
                compressor = zlib.compressobj(level, zlib.DEFLATED, window)
                candidates.append(compressor.compress(raw) + compressor.flush())
            payload = min(candidates, key=len)
            if len(payload) > entry.packed_size and not allow_relocation:
                raise ValueError('The edited physics stream cannot fit in ' + archive.path.name +
                                 '. This package needs rebuilding; no game files were changed.')
            if len(payload) <= entry.packed_size: payload = payload.ljust(entry.packed_size, b'\0')
        else:
            raise UnsupportedBff('Writing this package compression is unsupported: ' + archive.path.name)
        offset = entry.offset
        if len(payload) > entry.packed_size or (entry.compression == 0 and len(payload) != entry.packed_size):
            if not allow_relocation: raise ValueError('A replacement physics stream has an invalid size.')
            with archive.path.open('rb') as f: header = f.read(0x130)
            crc_size = struct.unpack_from('<I', header, 0x11C)[0]
            section_pos, section_size = struct.unpack_from('<II', header, 0x124)
            sector = struct.unpack_from('<I', header, 20)[0]
            if (crc_size or section_pos or section_size or header[300] & ~2 or
                    not 1 <= sector <= 65536 or sector & (sector - 1)):
                raise ValueError(archive.path.name + ' :: ' + name + ': replacement needs ' + str(len(payload)) +
                                 ' packed bytes but its slot has ' + str(entry.packed_size) +
                                 '. This package has unsupported CRC/section metadata or alignment' +
                                 ' (CRC bytes=' + str(crc_size) + ', section position=' + str(section_pos) +
                                 ', section bytes=' + str(section_size) + ', sector=' + str(sector) +
                                 '). Section-table relocation is disabled after a live AMS2 loading failure.' +
                                 ' Donor transfer requires a game-compatible package rebuild; nothing was applied.')
            offset = (append_offset + sector - 1) // sector * sector
            append_offset = offset + len(payload)
        encoded = rc4(archive.key, payload) if archive.key else payload
        patches.append((offset, encoded))
        struct.pack_into('<Q', toc, entry.index * 42 + 8, offset)
        struct.pack_into('<I', toc, entry.index * 42 + 16, len(encoded))
        struct.pack_into('<I', toc, entry.index * 42 + 20, len(raw))
        struct.pack_into('<I', toc, entry.index * 42 + 34, checksum(encoded))
        verify[name] = raw
    if patches:
        patches.append((0x130, rc4(archive.key, bytes(toc)) if archive.key else bytes(toc)))
    return patches, verify


def _temporary(target):
    return target.with_name('.' + target.name + '.bop-' + uuid.uuid4().hex + '.tmp')


def apply_files(game: Path, backups: Path, files: list[dict], changes: list[dict], guards=None) -> dict:
    if _game_running():
        raise ValueError('Close Automobilista 2 before applying Balance of Performance changes.')
    if not files:
        return {'ok': True, 'changed': 0, 'message': 'These values are already installed.'}
    guards = guards or {}
    for path, expected in guards.items():
        _relative(game, path)
        if sha(path) != expected:
            raise ValueError('A referenced game file changed after preview. Scan and preview again.')
    for item in files:
        _relative(game, item['path'])
        if sha(item['path']) != item['before']:
            raise ValueError('Game files changed after preview. Scan and preview again.')
    ident = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
    directory = backups / ident
    directory.mkdir(parents=True)
    record = {'id': ident, 'created': datetime.now(timezone.utc).isoformat(), 'game_path': str(game),
              'changes': changes, 'files': [], 'status': 'prepared'}
    staged, committed = [], []
    try:
        for index, item in enumerate(files):
            target = item['path']
            original = directory / (str(index) + '.original')
            shutil.copy2(target, original)
            if sha(original) != item['before']:
                raise ValueError('A game file changed while backing it up.')
            tmp = _temporary(target)
            staged.append(tmp)
            if item.get('patches') is None:
                tmp.write_bytes(item['raw'])
                if tmp.read_bytes() != item['raw']:
                    raise ValueError('Staged file verification failed.')
            else:
                shutil.copy2(original, tmp)
                with tmp.open('r+b') as f:
                    for offset, data in item['patches']:
                        f.seek(offset)
                        f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                check = BffArchive(tmp)
                for name, raw in item['verify'].items():
                    if check.read(name) != raw:
                        raise ValueError('Staged package verification failed: ' + name)
            record['files'].append({'path': _relative(game, target), 'backup': original.name,
                                    'before': item['before'], 'after': sha(tmp)})
        _json_write(directory / 'transaction.json', record)
        for path, expected in guards.items():
            if sha(path) != expected:
                raise ValueError('A referenced game file changed during preparation.')
        for item in files:
            if sha(item['path']) != item['before']:
                raise ValueError('Game files changed during preparation.')
        for index, (item, tmp) in enumerate(zip(files, staged)):
            if sha(item['path']) != item['before']:
                raise ValueError('A game file changed just before applying.')
            os.replace(tmp, item['path'])
            committed.append((index, item['path']))
        record['status'] = 'applied'
        _json_write(directory / 'transaction.json', record)
    except Exception as exc:
        errors = []
        for index, target in reversed(committed):
            restore = _temporary(target)
            try:
                shutil.copy2(directory / (str(index) + '.original'), restore)
                os.replace(restore, target)
            except OSError as problem:
                errors.append(str(problem))
            finally:
                restore.unlink(missing_ok=True)
        record['status'] = 'rollback_failed' if errors else 'rolled_back'
        record['error'] = str(exc)
        _json_write(directory / 'transaction.json', record)
        if errors:
            raise ValueError('Apply failed and some files need restoring from ' + str(directory)) from exc
        raise ValueError('No BOP changes were kept. ' + str(exc)) from exc
    finally:
        for tmp in staged:
            tmp.unlink(missing_ok=True)
    return {'ok': True, 'changed': len(files), 'backup': str(directory), 'transaction': ident}


def transactions(backups: Path) -> list[tuple[Path, dict]]:
    result = []
    for file in sorted(backups.glob('*/transaction.json'), reverse=True):
        try:
            record = json.loads(file.read_text(encoding='utf-8'))
            if isinstance(record, dict): result.append((file, record))
        except (ValueError, OSError):
            continue
    # IDs have second resolution plus a random suffix. Use the full journal
    # timestamp so rapid successive applies undo in the actual commit order.
    result.sort(key=lambda pair: (str(pair[1].get('created', '')), str(pair[0])), reverse=True)
    return result


def undo_files(game: Path, backups: Path) -> dict:
    if _game_running():
        raise ValueError('Close Automobilista 2 before restoring Balance of Performance changes.')
    pair = next(((p, r) for p, r in transactions(backups) if r.get('status') == 'applied'), None)
    if pair is None:
        raise ValueError('There is no BOP apply to undo.')
    journal, record = pair
    staged, committed, targets = [], [], []
    current = journal.parent / 'undo-current'
    current.mkdir(exist_ok=True)
    try:
        for index, item in enumerate(record['files']):
            target = game / item['path']
            _relative(game, target)
            original = journal.parent / item['backup']
            _relative(journal.parent, original)
            if sha(target) != item['after'] or sha(original) != item['before']:
                raise ValueError('Files changed since this apply. Undo stopped to preserve those changes.')
            shutil.copy2(target, current / str(index))
            tmp = _temporary(target)
            staged.append(tmp)
            shutil.copy2(original, tmp)
            if sha(tmp) != item['before']:
                raise ValueError('The restore copy failed verification.')
            targets.append(target)
        for target, item in zip(targets, record['files']):
            if sha(target) != item['after']:
                raise ValueError('Game files changed during restore.')
        for index, (target, tmp) in enumerate(zip(targets, staged)):
            if sha(target) != record['files'][index]['after']:
                raise ValueError('A game file changed just before restoring.')
            os.replace(tmp, target)
            committed.append((index, target))
        record['status'] = 'undone'
        _json_write(journal, record)
    except Exception as exc:
        errors = []
        for index, target in reversed(committed):
            restore = _temporary(target)
            try:
                shutil.copy2(current / str(index), restore)
                os.replace(restore, target)
            except OSError as problem:
                errors.append(str(problem))
            finally:
                restore.unlink(missing_ok=True)
        if errors:
            raise ValueError('Restore failed; recover current files from ' + str(current)) from exc
        raise
    finally:
        for tmp in staged:
            tmp.unlink(missing_ok=True)
    return {'ok': True, 'restored': len(committed)}
