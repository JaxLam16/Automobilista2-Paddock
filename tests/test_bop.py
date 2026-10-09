"""BOP modifies real game files: verify whole-file reversibility and failure paths.

Fixtures use documented binary layouts, with synthetic values/assets. No game
physics or proprietary DDS data is distributed with the test suite.
"""
import hashlib
import http.client
import json
import math
import os
import struct
import threading
import zlib
from pathlib import Path

import pytest

from ams2season.bff import BffArchive, _KEYS, checksum, path_uid, rc4
from ams2season.bop import BopEditor
from ams2season.bop_physics import (change_crd, crd_properties, decode, edit,
                                   edit_tyres, metrics, vdfm_references)


def shcb(data, version=2):
    start = 40 if version == 2 else 28
    footer = b'\x01\x02\x03' if version == 2 else b''
    header = bytearray(start)
    header[:8] = bytes.fromhex('53684342e60fdd53')
    struct.pack_into('<II', header, 8, start + len(data) + len(footer), version)
    header[16:20] = bytes.fromhex('baba1010')
    struct.pack_into('<II', header, 20, len(data), start)
    if version == 2:
        header[28:32] = bytes.fromhex('52498655')
        struct.pack_into('<II', header, 32, len(footer), start + len(data))
    return bytes(header) + data + footer


def chassis(mass=1470, multiplier=1.035):
    data = bytes.fromhex('21670b57ab') + struct.pack('<i', mass)
    data += bytes.fromhex('22a3bf1e60') + struct.pack('<f', multiplier)
    data += bytes.fromhex('241824eaa821') + struct.pack('<f', 0.27)
    data += bytes.fromhex('24beba677b2300') + struct.pack('<fBB', 0.466, 0, 0)
    data += bytes.fromhex('243363edfd21') + struct.pack('<f', 0.33)
    data += bytes.fromhex('24ad3c20138300') + struct.pack('<BfB', 0, 1, 4)
    data += bytes.fromhex('2006a31f94') + b'\x01'
    data += bytes.fromhex('2423ec212aa302') + struct.pack('<fff', -0.26, -0.02, 0.0002)
    data += bytes.fromhex('24157654868300') + struct.pack('<BfB', 0, 1, 8)
    data += bytes.fromhex('208a98eb35') + b'\x03'
    data += bytes.fromhex('2483d385b9a302') + struct.pack('<fff', -0.22, -0.024, 0.0004)
    data += bytes.fromhex('20ff0c2207') + b'\x03'
    data += bytes.fromhex('208d69c2da') + b'\x01'
    data += bytes.fromhex('20c1ebdc28') + b'\x00'
    for marker, torque in [('e07d16e29f', 5300), ('e0d6537908', 5300), ('e0bf9f5ba2', 4400), ('e0cff2c932', 4400)]:
        data += bytes.fromhex(marker + '214ba4817a') + struct.pack('<i', torque)
    return shcb(data)


def engine(factor=1, maps=1):
    data = b''
    for map_index in range(maps):
        data += bytes.fromhex('248b0ab7718302') + struct.pack('<Bff', 0, -30, -20)
        for rpm, torque in [(1000, 300), (3000, 500), (6000, 550), (7500, 450)]:
            data += bytes.fromhex('248b0ab7719302') + struct.pack('<iff', rpm, -100, torque * factor * (1 - .1 * map_index))
    data += bytes.fromhex('24dea72eb71300') + struct.pack('<iBB', 6500, 0, 0)
    data += bytes.fromhex('28a55cc1c4')
    data += bytes.fromhex('224665ae87') + struct.pack('<f', .25)
    data += bytes.fromhex('2292c7cd7c') + struct.pack('<f', 6.16)
    return shcb(data)


def gearbox():
    data = bytes.fromhex('6088de240f')
    for driver, driven in [(10, 30), (15, 30), (25, 30)]:
        data += bytes.fromhex('249d58f96402') + bytes([driver, driven])
    data += bytes.fromhex('e09765b7af243c5bef6202') + bytes([1, 1])
    data += bytes.fromhex('249d58f96402') + bytes([10, 35])
    return shcb(data, version=1)


def vdfm(model, tyres):
    data = bytearray(96)
    pool = model.encode() + b'\0' + tyres.encode() + b'\0'
    for offset in (8, 24, 64): struct.pack_into('<I', data, offset, 0)
    struct.pack_into('<I', data, 88, len(model) + 1)
    header = bytearray(48)
    header[:8] = bytes.fromhex('5102010400000104')
    struct.pack_into('<I', header, 16, len(data))
    struct.pack_into('<I', header, 24, len(pool))
    header[29] = 32
    mapping = b''.join(struct.pack('<Q', n) for n in (8, 24, 64, 88))
    struct.pack_into('<I', header, 32, len(mapping))
    return bytes(header) + data + pool + b'\0' * 32 + mapping


def crd(name, cls='World_GT_Challenge', model=None):
    props = {'Name': name, 'Vehicle Name': name.upper(), 'Vehicle Physics Model': model or name,
             'Vehicle Class': cls, 'Vehicle Group': 'GT3' if cls == 'GT3_Gen0' else cls,
             'Grid Grouping': '10' if cls == 'GT3_Gen0' else '15', 'Vehicle Initial Performance Index': '107'}
    return ('<data>\n' + '\n'.join('<prop name="' + k + '" data="' + v + '"/>' for k, v in props.items()) + '\n/>\n</data>\n').encode()


def pack(path, mapping, compression=0, reserve=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    count = len(mapping)
    data_offset = (304 + count * 42 + 15) // 16 * 16
    toc, data = bytearray(), bytearray()
    for name, raw in mapping.items():
        payload = zlib.compress(raw) if compression == 1 else raw
        payload = payload + b'\0' * reserve if compression else payload
        encoded = rc4(_KEYS[4], payload)
        toc += struct.pack('<QQIIQBBI4s', path_uid(name), data_offset + len(data), len(encoded), len(raw),
                           0, compression, 4, checksum(encoded), Path(name).suffix[1:5].encode().ljust(4, b'\0'))
        data += encoded
        data += b'\0' * ((-len(data)) % 16)
    header = bytearray(304)
    header[:4] = b' KAP'
    struct.pack_into('<IIQI', header, 4, 0x10400004, count, data_offset, 16)
    struct.pack_into('<I', header, 280, len(toc))
    header[301] = 2
    path.write_bytes(bytes(header) + rc4(_KEYS[4], bytes(toc)) + b'\0' * (data_offset - 304 - len(toc)) + data)


def setup_game(tmp_path, compression=1):
    game = tmp_path / 'game'
    physics, boot = {}, {}
    for name, mass, multiplier, factor, cls in [('car_a', 1470, 1.035, 1, 'World_GT_Challenge'),
                                               ('car_b', 1300, 1.1, 1.05, 'GT3_Gen0'),
                                               ('car_c', 1400, 1.05, 1.1, 'GT3_Gen0')]:
        definition = crd(name, cls)
        loose = game / 'Vehicles' / name / (name + '.crd')
        loose.parent.mkdir(parents=True)
        loose.write_bytes(definition)
        boot['vehicles/' + name + '/' + name + '.crd'] = definition.ljust(1200, b' ')
        files = {f'vehicles/physics/chassis/{name}.cdfbin': chassis(mass, multiplier),
                 f'vehicles/physics/engines/{name}.edfbin': engine(factor),
                 f'vehicles/physics/gearbox/{name}.gdfbin': gearbox(),
                 f'vehicles/physics/vehicles/{name}.vdfm': vdfm(name, 'tyre_' + name)}
        for canonical, raw in files.items():
            target = game / 'Vehicles' / Path(canonical).relative_to('vehicles')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        physics.update(files)
        pack(game / 'Pakfiles/Vehicles' / (name + '.bff'), files | {'vehicles/' + name + '/body.meb': b'geometry stays untouched'}, compression, 256)
    pack(game / 'Pakfiles/PHYSICSPERSISTENT.bff', physics | {'unrelated/foo.xml': b'<keep/>'}, compression, 256)
    pack(game / 'Pakfiles/BOOTPERSISTENT.bff', boot, compression, 256)
    return game


def hashes(game):
    return {p.relative_to(game).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in game.rglob('*') if p.is_file()}


def request(editor, car='car_a', **changes):
    return {'car': car, 'fingerprint': editor.cars[car if isinstance(car, str) else 'car_a'].fingerprint, 'parameters': {}} | changes


def test_decoder_edits_only_parameter_bytes_and_respects_binary_types():
    raw = chassis()
    params = decode('cdf', raw)
    mass = next(p for p in params if p.id == 'cdf.mass.0.0')
    out = edit('cdf', raw, {mass.id: 1350})
    assert out[:mass.offset] == raw[:mass.offset] and out[mass.offset + 4:] == raw[mass.offset + 4:]
    assert struct.unpack_from('<i', out, mass.offset)[0] == 1350
    with pytest.raises(ValueError, match='integer'): edit('cdf', raw, {mass.id: 1350.5})
    with pytest.raises(ValueError, match='finite'): edit('cdf', raw, {mass.id: float('nan')})
    with pytest.raises(ValueError): edit('cdf', raw, {'cdf.forward_gears.0.0': 0})


def test_power_proxy_caps_at_limiter_instead_of_overrev():
    params = decode('cdf', chassis()) + decode('edf', engine())
    values, curves = metrics(params)
    expected_torque = 550 + (450 - 550) * (6500 - 6000) / 1500
    expected_kw = expected_torque * 6500 * math.pi / 30000 * struct.unpack('<f', struct.pack('<f', 1.035))[0]
    assert values['power_kw'] == pytest.approx(expected_kw)
    assert values['rev_limit'] == 6500 and curves[0]['rows'][-1]['rpm'] == 7500
    assert values['front_brake_torque'] == 5300 and values['rear_brake_torque'] == 4400


def test_multiple_torque_maps_preserve_compression_and_curve_shape():
    raw = engine(maps=2)
    fields = decode('edf', raw)
    changes = {p.id: p.value * 1.1 for p in fields if p.id.startswith('edf.torque.') and p.value > 0}
    out = edit('edf', raw, changes)
    decoded = {p.id: p.value for p in decode('edf', out)}
    for p in fields:
        assert decoded[p.id] == pytest.approx(p.value * (1.1 if p.id in changes else 1))
    assert len(metrics(decode('edf', out))[1]) == 2
    with pytest.raises(ValueError): edit('edf', raw, {'edf.rpm.0.1': 1001})


def test_tyres_header_driven_slot_edit():
    raw = vdfm('car_a', 'gt4_305')
    out = edit_tyres(raw, 'gt3_315_front_325_rear')
    assert len(out) == len(raw)
    assert vdfm_references(out) == vdfm_references(raw) | {'tyres': 'gt3_315_front_325_rear'}
    with pytest.raises(ValueError, match='does not fit'): edit_tyres(raw, 'x' * 100)


def test_batch_apply_patches_all_copies_and_undo_restores_entire_files(tmp_path):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app')
    data = editor.scan(str(game)); before = hashes(game)
    assert len(data['cars']) == 3
    assert editor.detail('car_a')['metrics']['mass'] == 1470
    changes = [request(editor, parameters={'cdf.mass.0.0': 1350, 'cdf.power_multiplier.0.0': 1.12}, target_class='GT3_Gen0', tyres='tyre_car_b'),
               request(editor, 'car_b', parameters={'cdf.mass.0.0': 1320})]
    plan = editor.preview(changes)
    assert hashes(game) == before
    assert plan['files'].count('Pakfiles/PHYSICSPERSISTENT.bff') == 1
    editor.apply(plan['token'])
    assert editor.detail('car_a')['class'] == 'GT3_Gen0'
    assert editor.detail('car_a')['metrics']['mass'] == 1350
    assert editor.detail('car_a')['tyres'] == 'tyre_car_b'
    assert crd_properties((game / 'Vehicles/car_a/car_a.crd').read_bytes())['Vehicle Initial Performance Index'] == '107'
    for packed in (game / 'Pakfiles/Vehicles/car_a.bff', game / 'Pakfiles/PHYSICSPERSISTENT.bff'):
        archive = BffArchive(packed)
        p = decode('cdf', archive.read('vehicles/physics/chassis/car_a.cdfbin'))
        assert metrics(p)[0]['mass'] == 1350
        for entry in archive.entries: archive.read_entry(entry)
    archive = BffArchive(game / 'Pakfiles/Vehicles/car_a.bff')
    assert archive.read('vehicles/car_a/body.meb') == b'geometry stays untouched'
    assert hashes(game)['Pakfiles/Vehicles/car_c.bff'] == before['Pakfiles/Vehicles/car_c.bff']
    fresh = BopEditor(tmp_path / 'app'); fresh.scan(str(game))
    fresh.undo()
    assert hashes(game) == before


def test_proposal_uses_class_medians_and_keeps_own_curve_gearing(tmp_path):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    original_engine = (game / 'Vehicles/physics/engines/car_a.edfbin').read_bytes()
    proposal = editor.propose({'car': 'car_a', 'target_class': 'GT3_Gen0', 'strength': 1, 'axes': ['mass', 'power_to_weight']})
    assert proposal['after']['mass'] == 1350
    assert proposal['after']['power_to_weight'] == pytest.approx(proposal['comparison']['power_to_weight']['median'], rel=1e-6)
    assert all(key.startswith(('cdf.mass.', 'cdf.power_multiplier.')) for key in proposal['edit']['parameters'])
    assert 'edf' not in {key.split('.')[0] for key in proposal['edit']['parameters']}
    editor.apply(editor.preview([proposal['edit']])['token'])
    assert (game / 'Vehicles/physics/engines/car_a.edfbin').read_bytes() == original_engine


def test_proportional_aero_and_brakes_retain_front_rear_relationships(tmp_path):
    game = setup_game(tmp_path)
    # Alter a reference's wing and brake values across ALL copies via the editor.
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    reference = editor.detail('car_b')
    values = {p['id']: p['value'] * 1.2 for p in reference['parameters'] if p['id'].startswith(('cdf.fw_lift.', 'cdf.rw_lift.', 'cdf.brake_torque.'))}
    editor.apply(editor.preview([request(editor, 'car_b', parameters=values)])['token'])
    proposal = editor.propose({'car': 'car_a', 'target_class': 'GT3_Gen0', 'strength': 1, 'axes': ['wing_lift', 'brakes']})
    before, after = proposal['before'], proposal['after']
    assert after['fw_lift'] / after['rw_lift'] == pytest.approx(before['fw_lift'] / before['rw_lift'])
    assert after['front_brake_torque'] / after['rear_brake_torque'] == pytest.approx(before['front_brake_torque'] / before['rear_brake_torque'], rel=.001)


def test_scan_and_review_staleness_prevent_writes(tmp_path):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    change = request(editor, parameters={'cdf.mass.0.0': 1350})
    target = game / 'Vehicles/physics/vehicles/car_a.vdfm'
    target.write_bytes(edit_tyres(target.read_bytes(), 'tyre_car_b'))
    before = hashes(game)
    with pytest.raises(ValueError, match='changed since'): editor.preview([change])
    assert hashes(game) == before
    # Restore VDFM consistency, then change an unrelated package byte after preview.
    target.write_bytes(BffArchive(game / 'Pakfiles/Vehicles/car_a.bff').read('vehicles/physics/vehicles/car_a.vdfm'))
    editor.scan(str(game))
    plan = editor.preview([request(editor, parameters={'cdf.mass.0.0': 1350})])
    packed = game / 'Pakfiles/Vehicles/car_a.bff'; raw = bytearray(packed.read_bytes()); raw[100] ^= 1; packed.write_bytes(raw)
    changed = hashes(game)
    with pytest.raises(ValueError, match='after preview'): editor.apply(plan['token'])
    assert hashes(game) == changed


def test_apply_rolls_back_every_replacement_when_one_file_is_locked(tmp_path, monkeypatch):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    plan = editor.preview([request(editor, parameters={'cdf.mass.0.0': 1350}, target_class='GT3_Gen0')])
    before = hashes(game); replace = os.replace; calls = 0
    def fail_second(src, dst):
        nonlocal calls
        if Path(dst).is_relative_to(game) and '.bop-' in Path(src).name:
            calls += 1
            if calls == 2: raise PermissionError('file is locked')
        return replace(src, dst)
    monkeypatch.setattr('ams2season.bop_files.os.replace', fail_second)
    with pytest.raises(ValueError, match='No BOP changes were kept'): editor.apply(plan['token'])
    assert hashes(game) == before
    assert not list(game.rglob('*.tmp'))


def test_undo_rolls_back_partial_restore_and_refuses_external_changes(tmp_path, monkeypatch):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    editor.apply(editor.preview([request(editor, parameters={'cdf.mass.0.0': 1350})])['token'])
    applied = hashes(game); replace = os.replace; calls = 0
    def fail_second(src, dst):
        nonlocal calls
        if Path(dst).is_relative_to(game) and '.bop-' in Path(src).name:
            calls += 1
            if calls == 2: raise PermissionError('file is locked')
        return replace(src, dst)
    with monkeypatch.context() as context:
        context.setattr('ams2season.bop_files.os.replace', fail_second)
        with pytest.raises(PermissionError): editor.undo()
    assert hashes(game) == applied
    packed = game / 'Pakfiles/Vehicles/car_a.bff'; data = bytearray(packed.read_bytes()); data[101] ^= 1; packed.write_bytes(data)
    external = hashes(game)
    with pytest.raises(ValueError, match='changed since'): editor.undo()
    assert hashes(game) == external


def test_running_game_and_expired_review_are_blocked(tmp_path, monkeypatch):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    plan = editor.preview([request(editor, parameters={'cdf.mass.0.0': 1350})]); before = hashes(game)
    monkeypatch.setattr('ams2season.bop_files._game_running', lambda: True)
    with pytest.raises(ValueError, match='Close Automobilista'): editor.apply(plan['token'])
    assert hashes(game) == before
    plan = editor.preview([request(editor, parameters={'cdf.mass.0.0': 1350})]); editor.prepared[plan['token']]['created'] -= 601
    with pytest.raises(ValueError, match='expired'): editor.apply(plan['token'])


def test_shared_physics_blocks_individual_tuning_but_allows_class_move(tmp_path):
    game = setup_game(tmp_path)
    loose = game / 'Vehicles/car_b/car_b.crd'
    shared = crd('car_b', 'GT3_Gen0', model='car_a'); loose.write_bytes(shared)
    boot = {f'vehicles/{name}/{name}.crd': ((game / f'Vehicles/{name}/{name}.crd').read_bytes()).ljust(1200, b' ') for name in ('car_a', 'car_b', 'car_c')}
    pack(game / 'Pakfiles/BOOTPERSISTENT.bff', boot, 1, 256)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    assert editor.detail('car_a')['editable_parameters'] == 0
    with pytest.raises(ValueError, match='shared with'): editor.preview([request(editor, parameters={'cdf.mass.0.0': 1350})])
    editor.apply(editor.preview([request(editor, target_class='GT3_Gen0')])['token'])
    assert editor.detail('car_a')['class'] == 'GT3_Gen0'
    assert editor.detail('car_b')['metrics']['mass'] == 1470


def test_profiles_validate_starting_version_and_never_apply_on_import(tmp_path):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    data = {'format': 'ams2season-bop', 'version': 1, 'name': 'League round 1',
            'edits': [request(editor, parameters={'cdf.mass.0.0': 1350})]}
    before = hashes(game)
    saved = editor.import_profile(data)
    assert editor.profile(saved['id']) == data
    assert hashes(game) == before
    editor.apply(editor.preview(data['edits'])['token'])
    with pytest.raises(ValueError, match='differs'): editor.import_profile(data)
    editor.undo(); assert editor.import_profile(data, save=False) == data


@pytest.mark.parametrize('changes', [
    {'parameters': {'cdf.mass.0.0': True}}, {'parameters': {'cdf.mass.0.0': -10}},
    {'parameters': {'unknown.hex.0': 1}}, {'parameters': {'cdf.mass.0.0': float('inf')}},
    {'parameters': {'gdf.gear.0.0': 0}}, {'parameters': {'cdf.gear2_setting.0.0': 250}},
    {'parameters': {'cdf.forward_gears.0.0': 5}}, {'target_class': '../../outside'},
    {'tyres': 'unknown_tyre_model'}, {'car': []},
])
def test_invalid_manual_values_are_rejected_without_writes(tmp_path, changes):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game)); before = hashes(game)
    with pytest.raises(ValueError): editor.preview([request(editor, **changes)])
    assert hashes(game) == before


def test_malformed_binary_missing_metrics_and_inconsistent_copies(tmp_path):
    game = setup_game(tmp_path)
    target = game / 'Vehicles/physics/chassis/car_a.cdfbin'
    target.write_bytes(target.read_bytes()[:-1])
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    assert editor.detail('car_a')['metrics']['mass'] is None
    assert editor.detail('car_a')['errors']['cdf']
    target.write_bytes(edit('cdf', BffArchive(game / 'Pakfiles/Vehicles/car_a.bff').read('vehicles/physics/chassis/car_a.cdfbin'), {'cdf.mass.0.0': 1400}))
    editor.scan(str(game))
    with pytest.raises(ValueError, match='copies disagree'): editor.preview([request(editor, parameters={'cdf.mass.0.0': 1350})])


def test_oversize_class_does_not_relocate_archives(tmp_path):
    game = setup_game(tmp_path)
    definition = crd('car_a').ljust(1200, b' ')
    # A package with no trailing XML slack for an artificially long replacement.
    pack(game / 'Pakfiles/BOOTPERSISTENT.bff', {'vehicles/car_a/car_a.crd': crd('car_a', 'A')}, 1, 256)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game)); before = hashes(game)
    with pytest.raises(ValueError, match='allocated CRD'):
        editor.preview([request(editor, target_class='X' * 80, group='G', grid='10')])
    assert hashes(game) == before


def test_crd_edit_preserves_other_metadata_and_stray_tag():
    raw = crd('car_a')
    out = change_crd(raw, {'Vehicle Class': 'GT3_Gen0', 'Vehicle Group': 'GT3', 'Grid Grouping': '10'})
    assert b'\n/>\n' in out
    props = crd_properties(out)
    assert props['Vehicle Initial Performance Index'] == '107'
    assert props['Vehicle Physics Model'] == 'car_a'


def test_http_assets_existing_routes_and_mutation_origin(tmp_path):
    from ams2season.app import App, _make_server, make_handler
    (tmp_path / 'app').mkdir()
    app = App(tmp_path / 'app')
    server = _make_server(0, make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    def call(method, path, body=None, **headers):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=20)
        conn.request(method, path, json.dumps(body) if body is not None else None,
                     headers={'Content-Type': 'application/json'} | headers)
        response = conn.getresponse(); content = response.read(); conn.close()
        return response.status, content
    try:
        assert call('GET', '/api/ping')[0] == 200
        assert b'Balance of Performance' in call('GET', '/')[1]
        assert call('GET', '/bop-editor.js')[0] == 200
        assert call('GET', '/bop-editor.css')[0] == 200
        assert call('GET', '/api/liveries/config')[0] == 200
        assert call('POST', '/api/bop/scan', {}, Origin='https://outside.example')[0] == 403
        assert call('POST', '/api/bop/scan', {}, **{'Content-Type': 'text/plain'})[0] == 415
        assert call('POST', '/api/bop/scan', [1, 2])[0] == 400
    finally:
        server.shutdown(); server.server_close()


def test_recorded_data_reuses_the_existing_car_analysis(tmp_path):
    class Library:
        def recordings(self):
            return [{'id': 'race1', 'type': 'race', 'status': 'complete', 'raced': True},
                    {'id': 'empty', 'type': 'race', 'status': 'complete', 'raced': False},
                    {'id': 'quali', 'type': 'qualify', 'status': 'complete'}]
        def race_cars_page(self, recording, champ):
            assert recording == 'race1' and champ is None
            return {'meta': {'track': 'Simtown'}, 'cars': [{'car': 'CAR_A', 'pace': 92.2}], 'car_extra': {'turns': []}, 'awards': []}
    editor = BopEditor(tmp_path, Library())
    assert [r['id'] for r in editor.route('GET', '/api/bop/recordings', {}, {})['recordings']] == ['race1']
    result = editor.route('GET', '/api/bop/measured', {'recording': 'race1'}, {})
    assert result['cars'][0]['pace'] == 92.2 and 'awards' not in result


def test_profile_compatibility_ignores_identical_copies_and_crd_whitespace(tmp_path):
    import shutil
    first = setup_game(tmp_path / 'first')
    second = tmp_path / 'second/game'; second.parent.mkdir(parents=True)
    shutil.copytree(first, second)
    # Same car/mod inputs, different content-manager duplication/layout.
    shutil.rmtree(second / 'Vehicles/physics')
    p = second / 'Vehicles/car_a/car_a.crd'; p.write_bytes(p.read_bytes().replace(b'\n', b'\n    '))
    a = BopEditor(tmp_path / 'app_a'); a.scan(str(first))
    b = BopEditor(tmp_path / 'app_b'); b.scan(str(second))
    profile = {'format': 'ams2season-bop', 'version': 1, 'name': 'Portable league settings',
               'edits': [request(a, parameters={'cdf.mass.0.0': 1350})]}
    assert b.import_profile(profile, save=False) == profile


def test_referenced_engine_change_after_review_is_detected(tmp_path):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    plan = editor.preview([request(editor, parameters={'cdf.mass.0.0': 1350})])
    p = game / 'Vehicles/physics/engines/car_a.edfbin'
    p.write_bytes(edit('edf', p.read_bytes(), {'edf.torque.0.2': 510}))
    before = hashes(game)
    with pytest.raises(ValueError, match='referenced game file changed'): editor.apply(plan['token'])
    assert hashes(game) == before


def test_longer_class_can_reclaim_prop_formatting_without_archive_resize(tmp_path):
    from ams2season.bop_files import value_patches
    raw = crd('car_a', 'A').replace(b'\n<prop', b'\n    <prop')
    p = tmp_path / 'class.bff'; name = 'vehicles/car_a/car_a.crd'
    pack(p, {name: raw}, 1, 256)
    before_size = p.stat().st_size
    replacement = change_crd(raw, {'Vehicle Class': 'League_GT3_0', 'Vehicle Group': 'GT3'})
    assert len(replacement) > len(raw)
    patches, verify = value_patches(BffArchive(p), {name: replacement})
    with p.open('r+b') as f:
        for offset, data in patches: f.seek(offset); f.write(data)
    restored = BffArchive(p).read(name)
    assert len(restored) == len(raw) and p.stat().st_size == before_size
    assert crd_properties(restored) == crd_properties(replacement)


def test_zero_default_gear_encoding_is_read_only_and_used_for_ratio_metrics():
    raw = chassis()
    start, end = 40, struct.unpack_from('<I', raw, 36)[0]
    data = raw[start:end] + bytes.fromhex('28f4cc2f1d205f2ba9ee') + b'\x02'
    # Three forward gears: highest gear selector is gear3, not gear6.
    data += bytes.fromhex('20c02593c3') + b'\x02'
    raw = shcb(data)
    fields = decode('cdf', raw)
    first = next(p for p in fields if p.id == 'cdf.gear1_setting.0.0')
    assert first.value == 0 and not first.public()['editable']
    with pytest.raises(ValueError): edit('cdf', raw, {first.id: 1})
    values, _ = metrics(fields + decode('gdf', gearbox()))
    assert values['first_gear_ratio'] == 3 and values['top_gear_ratio'] == 1.2
    assert values['final_drive_ratio'] == 3.5
