"""Livery edits must preserve unrelated car data and remain reversible."""
import hashlib
import http.client
import json
import struct
import threading
import zlib
from pathlib import Path

import pytest

from ams2season.bff import BffArchive, checksum, path_uid, rc4, _KEYS
from ams2season.liveries import LiveryEditor, rcf_liveries, select_rcf


def rcf(prefix='Team'):
    return ('''<?xml version="1.0" encoding="utf-8"?>
<REPLACEMENT_SYSTEM>
<INPUTS><INPUT NAME="LIVERY" OPTIONS="3"/><INPUT NAME="TIRE" OPTIONS="2"/></INPUTS>
<NAMES INPUT="LIVERY"><NAME LIVERY="71" NAME="%s Red #1"/><NAME LIVERY="72" NAME="%s Blue #2"/><NAME LIVERY="73" NAME="%s Green #3"/></NAMES>
<NAMES INPUT="TIRE"><NAME TIRE="1" NAME="Soft"/><NAME TIRE="2" NAME="Wet"/></NAMES>
<CONDITION LIVERY="71"><REPLACE TEXTURE="paint.dds" NEWTEXTURE="red.dds"/></CONDITION>
<CONDITION LIVERY="72"><REPLACE TEXTURE="paint.dds" NEWTEXTURE="blue.dds"/></CONDITION>
<CONDITION LIVERY="73"><REPLACE TEXTURE="paint.dds" NEWTEXTURE="green.dds"/></CONDITION>
<CONDITION TIRE="1"><REPLACE TEXTURE="tyres.dds" NEWTEXTURE="soft.dds"/></CONDITION>
<CONDITION DIRTTYPE="1"><REPLACE TEXTURE="dirt.dds" NEWTEXTURE="dust.dds"/></CONDITION>
</REPLACEMENT_SYSTEM>
''' % (prefix, prefix, prefix)).encode()


def pack(path, mapping, key_index=3):
    """Real BFF layout, RC4 encryption, and mixed-compression payloads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = len(mapping)
    data_offset = (0x130 + count * 42 + 15) // 16 * 16
    toc, chunks = bytearray(), bytearray()
    for name, raw in mapping.items():
        payload = rc4(_KEYS[key_index], zlib.compress(raw))
        toc.extend(struct.pack('<QQIIQBBI4s', path_uid(name), data_offset + len(chunks), len(payload), len(raw), 0,
                               1, 4, checksum(payload), Path(name).suffix[1:].encode().ljust(4, b'\0')))
        chunks.extend(payload)
        chunks.extend(b'\0' * ((-len(chunks)) % 16))
    header = bytearray(0x130)
    header[:4] = b' KAP'
    struct.pack_into('<IIQI', header, 4, 0x10400004, count, data_offset, 16)
    name = path.stem.encode(); header[24:24 + len(name)] = name
    struct.pack_into('<I', header, 0x118, len(toc))
    header[0x12D] = 2
    data = bytes(header) + rc4(_KEYS[key_index], bytes(toc))
    path.write_bytes(data + b'\0' * (data_offset - len(data)) + chunks)


def setup_game(tmp_path):
    game = tmp_path / 'Automobilista 2'
    pak = game / 'Pakfiles' / 'Vehicles'
    a, b = rcf('A'), rcf('B')
    names = {f'vehicles/{car}/{car}{suffix}.rcf': raw
             for car, raw in [('car_a', a), ('car_b', b)] for suffix in ['', '_hr']}
    persistent = pak / 'vehiclespersistent.bff'
    pack(persistent, {**names, 'vehicles/data/unrelated.xml': b'<anything>keep me</anything>'})
    for car, raw in [('car_a', a), ('car_b', b)]:
        pack(pak / (car + '.bff'), {f'vehicles/{car}/{car}.rcf': raw, f'vehicles/{car}/{car}_hr.rcf': raw,
                                  f'vehicles/{car}/mesh.meb': b'geometry must not change'}, key_index=4)
        folder = game / 'Vehicles' / car
        folder.mkdir(parents=True)
        (folder / (car + '.rcf')).write_bytes(raw)
        (folder / (car + '_hr.rcf')).write_bytes(raw)
        (folder / (car + '.crd')).write_text('<data><prop name="Vehicle Name" data="' + car.upper()
                                           + '"/><prop name="Vehicle Class" data="GT3_Gen_0"/></data>')
    return game, names, persistent


def hashes(game):
    return {p.relative_to(game).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in game.rglob('*') if p.is_file()}


def test_known_camaro_uid():
    # These IDs were verified against the actual uploaded installed packages.
    assert path_uid('vehicles/chevrolet_camaro_gt4r/chevrolet_camaro_gt4r.rcf') == 0x33156FBF3D312448
    assert path_uid('VEHICLES\\CHEVROLET_CAMARO_GT4R\\CHEVROLET_CAMARO_GT4R_HR.RCF') == 0x2D2921228BADC2C6


def test_rcf_selection_keeps_tire_and_dirt_data():
    import xml.etree.ElementTree as ET
    result = select_rcf(rcf(), ['72'])
    root = ET.fromstring(result)
    assert rcf_liveries(result) == [{'id': '72', 'name': 'Team Blue #2'}]
    assert root.find('./INPUTS/INPUT').get('OPTIONS') == '1'
    assert root.find('./NAMES[@INPUT="TIRE"]/NAME').get('NAME') == 'Soft'
    assert {x.get('LIVERY') for x in root.findall('CONDITION') if 'LIVERY' in x.attrib} == {'72'}
    assert b'NEWTEXTURE="soft.dds"' in result and b'NEWTEXTURE="dust.dds"' in result
    assert select_rcf(rcf(), ['71', '72', '73']).rstrip() == rcf().rstrip()


def test_apply_updates_every_copy_and_undo_is_byte_exact(tmp_path):
    game, names, persistent = setup_game(tmp_path)
    originals = hashes(game)
    editor = LiveryEditor(tmp_path / 'app')
    data = editor.scan(str(game))
    assert len(data['cars']) == 2
    assert all(c['class'] == 'GT3 Gen 0' for c in data['cars'])
    preview = editor.preview({'car_a': ['71', '73']})
    assert len(preview['files']) == 4
    assert hashes(game) == originals  # preview does not modify the game
    result = editor.apply(preview['token'])
    assert result['changed'] == 4
    for archive_path in [persistent, persistent.parent / 'car_a.bff']:
        archive = BffArchive(archive_path)
        for suffix in ['', '_hr']:
            assert [r['id'] for r in rcf_liveries(archive.read('vehicles/car_a/car_a' + suffix + '.rcf'))] == ['71', '73']
        for entry in archive.entries:
            archive.read_entry(entry)  # checks every entry checksum, including untouched assets
    shared = BffArchive(persistent)
    assert shared.read('vehicles/car_b/car_b.rcf') == names['vehicles/car_b/car_b.rcf']
    assert shared.read('vehicles/data/unrelated.xml') == b'<anything>keep me</anything>'
    assert hashes(game)['Pakfiles/Vehicles/car_b.bff'] == originals['Pakfiles/Vehicles/car_b.bff']
    # Persisted catalog makes hidden liveries available to a fresh app instance.
    fresh = LiveryEditor(tmp_path / 'app')
    rows = {c['id']: c for c in fresh.scan(str(game))['cars']}
    assert rows['car_a']['enabled'] == ['71', '73'] and rows['car_a']['total'] == 3
    fresh.undo()
    assert hashes(game) == originals


def test_reenable_and_two_cars_share_one_menu_write(tmp_path):
    game, _, persistent = setup_game(tmp_path)
    editor = LiveryEditor(tmp_path / 'app')
    editor.scan(str(game))
    p = editor.preview({'car_a': ['72'], 'car_b': ['73']})
    assert sum('vehiclespersistent' in f['path'] for f in p['files']) == 1
    editor.apply(p['token'])
    p = editor.preview({'car_a': ['71', '72', '73']})
    editor.apply(p['token'])
    archive = BffArchive(persistent)
    assert len(rcf_liveries(archive.read('vehicles/car_a/car_a.rcf'))) == 3
    assert [r['id'] for r in rcf_liveries(archive.read('vehicles/car_b/car_b.rcf'))] == ['73']


def test_rescan_refreshes_catalog_after_a_full_mod_update(tmp_path):
    game, names, persistent = setup_game(tmp_path)
    editor = LiveryEditor(tmp_path / 'app')
    editor.scan(str(game))
    updated = rcf('Updated A').replace(b'NAME="Soft"', b'NAME="New Soft"')
    for suffix in ['', '_hr']:
        names['vehicles/car_a/car_a' + suffix + '.rcf'] = updated
        (game / 'Vehicles/car_a' / ('car_a' + suffix + '.rcf')).write_bytes(updated)
    pack(persistent, names)
    pack(persistent.parent / 'car_a.bff', {name: raw for name, raw in names.items() if '/car_a/' in name}, key_index=4)
    rows = {c['id']: c for c in editor.scan(str(game))['cars']}
    assert rows['car_a']['liveries'][0]['name'].startswith('Updated A')
    editor.apply(editor.preview({'car_a': ['72']})['token'])
    raw = BffArchive(persistent).read('vehicles/car_a/car_a.rcf')
    assert rcf_liveries(raw)[0]['name'].startswith('Updated A')
    assert b'NAME="New Soft"' in raw


def test_stale_preview_and_invalid_selections_do_not_write(tmp_path):
    game, _, persistent = setup_game(tmp_path)
    editor = LiveryEditor(tmp_path / 'app'); editor.scan(str(game))
    original = hashes(game)
    for selection in [{'car_a': []}, {'car_a': ['999']}, {'../car_a': ['71']}, {'car_a': ['71', '71']}]:
        with pytest.raises(ValueError): editor.preview(selection)
        assert hashes(game) == original
    p = editor.preview({'car_a': ['71']})
    persistent.write_bytes(persistent.read_bytes() + b'external update')
    updated = hashes(game)
    with pytest.raises(ValueError, match='changed'): editor.apply(p['token'])
    assert hashes(game) == updated


def test_partial_apply_failure_rolls_back_all_committed_files(tmp_path, monkeypatch):
    import ams2season.liveries as module
    game, _, _ = setup_game(tmp_path)
    before = hashes(game)
    editor = LiveryEditor(tmp_path / 'app'); editor.scan(str(game))
    p = editor.preview({'car_a': ['71']})
    original_replace = module.os.replace
    count = 0
    def fail_second(source, target):
        nonlocal count
        if '.livery-' in str(source):
            count += 1
            if count == 2: raise PermissionError('test: a game file is locked')
        return original_replace(source, target)
    monkeypatch.setattr(module.os, 'replace', fail_second)
    with pytest.raises(ValueError, match='No livery changes were kept'): editor.apply(p['token'])
    assert hashes(game) == before
    assert not list(game.rglob('*.tmp'))


def test_presets_save_without_applying_and_reject_path_tricks(tmp_path):
    game, _, _ = setup_game(tmp_path)
    before = hashes(game)
    editor = LiveryEditor(tmp_path / 'app'); editor.scan(str(game))
    saved = editor.save_preset({'name': 'Friday GT3', 'selections': {'car_a': ['71', '72']}})
    assert editor.load_preset(saved['id'])['selections'] == {'car_a': ['71', '72']}
    assert hashes(game) == before
    with pytest.raises(LookupError): editor.load_preset('../../settings')


def test_livery_routes_and_legacy_routes_over_http(tmp_path):
    from ams2season.app import App, _make_server, make_handler
    game, _, _ = setup_game(tmp_path)
    root = tmp_path / 'app'; root.mkdir()
    app = App(root)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    def call(path, method='GET', body=None, origin=None):
        connection = http.client.HTTPConnection('127.0.0.1', srv.server_address[1])
        headers = {'Content-Type': 'application/json'}
        if origin: headers['Origin'] = origin
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = connection.getresponse(); data = response.read()
        return response.status, data
    try:
        for path in ['/', '/api/home', '/api/settings', '/api/liveries/config', '/livery-editor.js', '/livery-editor.css']:
            assert call(path)[0] == 200
        code, data = call('/api/liveries/scan', 'POST', {'game_path': str(game)})
        assert code == 200 and len(json.loads(data)['cars']) == 2
        code, _ = call('/api/liveries/undo', 'POST', {}, origin='https://example.invalid')
        assert code == 403
        assert call('/api/liveries/image?car=../../outside&livery=71')[0] == 404
        assert call('/api/recordings')[0] == 200
    finally:
        srv.shutdown(); srv.server_close()


def test_import_original_recovers_restrictions_made_before_the_editor(tmp_path):
    game, _, shared = setup_game(tmp_path)
    original = tmp_path / 'original-menu.bff'; original.write_bytes(shared.read_bytes())
    # A different installation tool already restricted all available copies.
    for path in game.rglob('*'):
        if not path.is_file(): continue
        if path.suffix == '.rcf': path.write_bytes(select_rcf(path.read_bytes(), ['71']))
        if path.suffix == '.bff':
            archive = BffArchive(path)
            names = [f'vehicles/{car}/{car}{suffix}.rcf' for car in ['car_a', 'car_b'] for suffix in ['', '_hr']]
            patches = archive.patches({name: select_rcf(archive.read(name), ['71']) for name in names if archive.has(name)})
            data = bytearray(path.read_bytes())
            for offset, patch in patches: data[offset:offset + len(patch)] = patch
            path.write_bytes(data)
    before = hashes(game)
    ed = LiveryEditor(tmp_path / 'new-app'); rows = ed.scan(str(game))['cars']
    assert all(c['total'] == 1 for c in rows)
    data = ed.import_catalog(str(original))
    assert data['imported_cars'] == 2 and all(c['total'] == 3 for c in data['cars'])
    assert all(c['enabled'] == ['71'] for c in data['cars']) and hashes(game) == before
    plan = ed.preview({'car_a': ['73']}); ed.apply(plan['token'])
    assert ed.overview()['cars'][0]['enabled'] == ['73']
