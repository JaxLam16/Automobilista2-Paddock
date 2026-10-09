"""Complete component transfers, absolute offsets, guarded writes and exact Undo."""
import json
import hashlib
import struct
import pytest

from ams2season.bff import BffArchive, path_uid
from ams2season.bop import BopEditor
from ams2season.bop_physics import decode, edit, private_donor_vdf, vdfm_references
from ams2season.donor import capture, information, propose
from test_bop import hashes, pack, vdfm
from test_conversion import rich_game


def donor_game(tmp_path, compression=1):
    game = rich_game(tmp_path); persistent = {'unrelated/foo.xml': b'<keep/>'}
    for name in ('car_a', 'car_b', 'car_c'):
        old = vdfm(name, 'tyre_' + name)
        data = bytearray(old[48:144]) + b'geometry-and-unknown-settings!!'.ljust(64, b'X')
        pool = name.encode() + b'\0tyre_' + name.encode() + b'\0clutch\0'
        for offset in (8, 24, 64, 72): struct.pack_into('<I', data, offset, 0)
        struct.pack_into('<I', data, 32, len(name) + 1 + len('tyre_' + name) + 1)
        struct.pack_into('<I', data, 88, len(name) + 1)
        header = bytearray(old[:48]); struct.pack_into('<I', header, 16, len(data)); struct.pack_into('<I', header, 24, len(pool)); header[29] = 1
        mapping = b''.join(struct.pack('<Q', n) for n in (8, 24, 32, 64, 72, 88)); struct.pack_into('<I', header, 32, len(mapping))
        full = bytes(header) + data + pool + b'\x04' + mapping + b'unknown-end-section'
        payload = {}
        for role, folder, ext in [('cdf', 'chassis', 'cdfbin'), ('edf', 'engines', 'edfbin'), ('gdf', 'gearbox', 'gdfbin')]:
            raw = (game / f'Vehicles/physics/{folder}/{name}.{ext}').read_bytes()
            if name == 'car_b' and role == 'edf':
                torque = next(p for p in decode('edf', raw) if p.id.startswith('edf.torque.') and p.value > 0)
                raw = edit('edf', raw, {torque.id: 570})
            if name == 'car_b' and role == 'gdf': raw = edit('gdf', raw, {'gdf.gear.0.1': 33})
            payload[f'vehicles/physics/{folder}/{name}.{ext}'] = raw
        payload[f'vehicles/physics/vehicles/{name}.vdfm'] = full
        payload[f'vehicles/physics/suspension/{name}.sdfbin'] = (name + ' entire suspension').encode()
        payload[f'vehicles/physics/tyres/tyre_{name}.hdtbin'] = (name + ' entire tyre model').encode()
        payload['vehicles/physics/clutches/clutch.cmfbin'] = b'whole clutch'
        for canonical, raw in payload.items():
            target = game / 'Vehicles' / canonical.removeprefix('vehicles/'); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        persistent.update(payload)
        pack(game / f'Pakfiles/Vehicles/{name}.bff', payload | {f'vehicles/{name}/body.meb': b'original body ' + name.encode()}, compression, 0)
    pack(game / 'Pakfiles/PHYSICSPERSISTENT.bff', persistent, compression, 0)
    return game


def ready(tmp_path, **kwargs):
    game = donor_game(tmp_path, **kwargs); editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    result = capture(editor, {'car': 'car_a', 'donor': 'car_b', 'fingerprint': editor.cars['car_a'].fingerprint,
                             'donor_fingerprint': editor.cars['car_b'].fingerprint})
    return game, editor, result['baseline']


def test_native_hdt_tag_with_hdtbin_path_is_pinned_and_guarded(tmp_path):
    from ams2season.bff import rc4
    game = donor_game(tmp_path)
    canonical = 'vehicles/physics/tyres/tyre_car_b.hdtbin'
    raw = (game / canonical).read_bytes()
    # The donor tyre exists only in a native-style persistent entry. Its TOC
    # type is HDT, not the first four letters of its .hdtbin path suffix.
    (game / canonical).unlink()
    vehicle = game / 'Pakfiles/Vehicles/car_b.bff'
    archive = BffArchive(vehicle)
    pack(vehicle, {c: archive.read(c) for c in (
        'vehicles/physics/chassis/car_b.cdfbin',
        'vehicles/physics/engines/car_b.edfbin',
        'vehicles/physics/gearbox/car_b.gdfbin',
        'vehicles/physics/vehicles/car_b.vdfm',
        'vehicles/physics/suspension/car_b.sdfbin',
        'vehicles/physics/clutches/clutch.cmfbin')})
    persistent = game / 'Pakfiles/PHYSICSPERSISTENT.bff'
    pack(persistent, {canonical: raw})
    archive = BffArchive(persistent)
    data = bytearray(persistent.read_bytes())
    toc = bytearray(archive.toc); toc[38:42] = b'hdt\0'
    data[304:304 + len(toc)] = rc4(archive.key, bytes(toc))
    persistent.write_bytes(data)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    assert next(d for d in information(editor, 'car_a')['donors'] if d['id'] == 'car_b')['available']
    result = capture(editor, {'car': 'car_a', 'donor': 'car_b',
                             'fingerprint': editor.cars['car_a'].fingerprint,
                             'donor_fingerprint': editor.cars['car_b'].fingerprint})
    assert 'tyres' in result['baseline']['pinned_components']
    preview = editor.preview([draft(editor, result['baseline'])])
    pack(persistent, {canonical: b'changed tyre bytes'})
    with pytest.raises(ValueError, match='referenced game file changed'):
        editor.apply(preview['token'])


def draft(editor, baseline, **offsets):
    return propose(editor, {'car': 'car_a', 'baseline': baseline['id'], 'offsets': offsets})['edit']


@pytest.mark.parametrize('compression', [0, 1])
def test_complete_transfer_all_copies_engine_gearing_geometry_and_undo(tmp_path, compression):
    game, editor, baseline = ready(tmp_path, compression=compression); before = hashes(game)
    own, donor = editor.cars['car_a'], editor.cars['car_b']
    expected = {role: donor.sources[role][0].raw for role in ('cdf', 'edf', 'gdf')}
    expected['vdf'] = private_donor_vdf(donor.sources['vdf'][0].raw, {role: own.references[role] for role in ('cdf', 'edf', 'gdf')})
    assert all(c['available'] for c in baseline['controls'])
    assert set(baseline['pinned_components']) == {'sdf', 'tyres', 'cmf'}
    preview = editor.preview([draft(editor, baseline)]); assert hashes(game) == before
    editor.apply(preview['token']); current = editor.cars['car_a']
    for role, raw in expected.items():
        assert all(s.raw == raw for s in current.sources[role]); assert raw != own.sources[role][0].raw
    assert current.references['sdf'] == donor.references['sdf']; assert current.references['tyres'] == donor.references['tyres']
    assert current.metadata['Vehicle Physics Model'] == own.metadata['Vehicle Physics Model']; assert current.name == own.name
    assert current.metadata['Vehicle Class'] == donor.metadata['Vehicle Class']
    for name in ('car_b', 'car_c'):
        assert hashes(game)[f'Pakfiles/Vehicles/{name}.bff'] == before[f'Pakfiles/Vehicles/{name}.bff']
        for folder, ext in [('chassis', 'cdfbin'), ('engines', 'edfbin'), ('gearbox', 'gdfbin')]:
            relative = f'Vehicles/physics/{folder}/{name}.{ext}'; assert hashes(game)[relative] == before[relative]
    for package in game.rglob('*.bff'):
        archive = BffArchive(package)
        for entry in archive.entries: archive.read_entry(entry)
    assert BffArchive(game / 'Pakfiles/Vehicles/car_a.bff').read('vehicles/car_a/body.meb') == b'original body car_a'
    assert information(editor, 'car_a')['active']['id'] == baseline['id']
    editor.undo(); assert hashes(game) == before


def test_absolute_tuning_restart_repeat_zero_restore_and_undo(tmp_path):
    game, editor, baseline = ready(tmp_path); original = hashes(game)
    values = {p.id: p.value for p in editor.cars['car_b'].parameters}
    proposal = draft(editor, baseline, power=1, aero=.5, braking=1.5, cornering=2); first = editor._evaluate(proposal)
    editor.apply(editor.preview([proposal])['token']); installed = hashes(game)
    assert first['after']['power_multiplier'] == pytest.approx(values['cdf.power_multiplier.0.0'] * 1.01)
    assert first['after']['cg_height'] == pytest.approx(values['cdf.cg_height.0.0'] * .98)
    again = BopEditor(tmp_path / 'app'); again.scan(str(game))
    repeated = draft(again, baseline, power=1, aero=.5, braking=1.5, cornering=2)
    preview = again.preview([repeated]); assert preview['count'] == 0
    again.apply(preview['token']); assert hashes(game) == installed
    assert again._evaluate(draft(again, baseline, power=2))['after']['power_multiplier'] == pytest.approx(values['cdf.power_multiplier.0.0'] * 1.02)
    again.apply(again.preview([draft(again, baseline)])['token'])
    assert all(s.raw == again.cars['car_b'].sources['cdf'][0].raw for s in again.cars['car_a'].sources['cdf'])
    again.undo(); assert hashes(game) == installed
    again.undo(); assert hashes(game) == original


@pytest.mark.parametrize('bad', [True, float('nan'), float('inf'), -1, 10.5, .25, '1'])
def test_invalid_offsets_cannot_write(tmp_path, bad):
    game, editor, baseline = ready(tmp_path); before = hashes(game)
    with pytest.raises(ValueError, match='0.5% steps'): draft(editor, baseline, power=bad)
    assert hashes(game) == before


def test_changed_snapshot_and_dependency_rejected(tmp_path):
    game, editor, baseline = ready(tmp_path); dependency = game / 'Vehicles/physics/suspension/car_b.sdfbin'
    dependency.write_bytes(b'external replacement'); before = hashes(game)
    with pytest.raises(ValueError, match='pinned donor component changed'): draft(editor, baseline)
    assert hashes(game) == before
    dependency.write_bytes(b'car_b entire suspension')
    snapshot = editor.install_dir / 'donor_baselines' / baseline['id'] / 'cdf.bin'
    snapshot.write_bytes(edit('cdf', snapshot.read_bytes(), {'cdf.mass.0.0': 1200}))
    with pytest.raises(ValueError, match='baseline bytes changed'): draft(editor, baseline)


def test_linked_change_after_preview_blocks_apply(tmp_path):
    game, editor, baseline = ready(tmp_path); preview = editor.preview([draft(editor, baseline)])
    (game / 'Vehicles/physics/suspension/car_b.sdfbin').write_bytes(b'changed after review'); before = hashes(game)
    with pytest.raises(ValueError, match='referenced game file changed'): editor.apply(preview['token'])
    assert hashes(game) == before


def test_private_vdf_preserves_unknown_pool_geometry_and_footer():
    raw = vdfm('donor', 'tyres'); start = 144; old_map = start + struct.unpack_from('<I', raw, 24)[0] + raw[29]
    raw = raw[:old_map - 1] + b'\x04' + raw[old_map:] + b'extra footer'
    out = private_donor_vdf(raw, {role: 'much_longer_private_component_' + role for role in ('cdf', 'edf', 'gdf')})
    new_map = start + struct.unpack_from('<I', out, 24)[0] + out[29]
    assert out[48:56] == raw[48:56]; assert out[start:old_map] == raw[start:old_map]
    assert out[new_map:] == raw[old_map:]; assert vdfm_references(out)['tyres'] == 'tyres'


def test_shared_candidate_and_incomplete_donor_blocked(tmp_path):
    _, editor, baseline = ready(tmp_path); editor.cars['car_a'].blocked['cdf'] = 'Shared with another car'
    with pytest.raises(ValueError, match='Shared with another car'): draft(editor, baseline)
    editor.cars['car_b'].linked_sources['sdf'] = []
    assert not next(d for d in information(editor, 'car_a')['donors'] if d['id'] == 'car_b')['available']


def test_unsupported_section_metadata_rejected_before_writes(tmp_path):
    game, editor, baseline = ready(tmp_path); path = game / 'Pakfiles/Vehicles/car_a.bff'
    raw = bytearray(path.read_bytes()); struct.pack_into('<I', raw, 0x128, 16); path.write_bytes(raw)
    editor.scan(str(game)); before = hashes(game)
    with pytest.raises(ValueError, match='unsupported CRC/section') as error:
        editor.preview([draft(editor, baseline)])
    assert path.name in str(error.value) and 'vehicles/physics/' in str(error.value)
    assert 'packed bytes' in str(error.value) and 'section bytes=16' in str(error.value)
    assert hashes(game) == before


def add_dhsa(path, index, *, sections=1, version=0x10000000):
    """Native-style single-record render section table before the data area."""
    from ams2season.bff import rc4
    archive = BffArchive(path); old = path.read_bytes()
    old_start = struct.unpack_from('<Q', old, 12)[0]
    pos = 304 + len(archive.toc)
    table = struct.pack('<4sIII', b'DHSA', version, 1, 0)
    table += struct.pack('<IIQ', index, sections, archive.entries[index].packed_size)
    start = (pos + len(table) + 15) // 16 * 16
    shift = start - old_start
    toc = bytearray(archive.toc)
    for entry in archive.entries:
        struct.pack_into('<Q', toc, entry.index * 42 + 8, entry.offset + shift)
    header = bytearray(old[:304])
    struct.pack_into('<Q', header, 12, start)
    struct.pack_into('<II', header, 0x124, pos, len(table))
    path.write_bytes(bytes(header) + rc4(archive.key, bytes(toc)) + table +
                     b'\0' * (start - pos - len(table)) + old[old_start:])


def dhsa_game(tmp_path):
    game, editor, baseline = ready(tmp_path)
    path = game / 'Pakfiles/Vehicles/car_a.bff'; archive = BffArchive(path)
    car = editor.cars['car_a']
    names = {s.canonical for found in list(car.sources.values()) + list(car.linked_sources.values()) for s in found}
    names.add('vehicles/car_a/body.meb')
    payload = {name: archive.read(name) for name in sorted(names) if archive.has(name)}
    payload['vehicles/car_a/render.dds'] = b'preserve this render payload'
    pack(path, payload, 1, 0)
    archive = BffArchive(path)
    add_dhsa(path, archive.by_uid[path_uid('vehicles/car_a/render.dds')].index)
    editor.scan(str(game))
    return game, editor, baseline, path


def test_render_only_sections_still_block_growth_after_live_loading_failure(tmp_path):
    game, editor, baseline, path = dhsa_game(tmp_path); before = hashes(game)
    old = path.read_bytes(); pos, size = struct.unpack_from('<II', old, 0x124)
    with pytest.raises(ValueError, match='disabled after a live AMS2 loading failure'):
        editor.preview([draft(editor, baseline, power=.5)])
    assert path.read_bytes()[pos:pos + size] == old[pos:pos + size]
    assert hashes(game) == before
    assert not editor.prepared


@pytest.mark.parametrize('bad', ['edited', 'version', 'sections', 'bounds', 'count'])
def test_unknown_or_affected_dhsa_is_rejected_without_writes(tmp_path, bad):
    game, editor, baseline, path = dhsa_game(tmp_path)
    raw = bytearray(path.read_bytes()); pos, size = struct.unpack_from('<II', raw, 0x124)
    if bad == 'edited':
        engine_index = BffArchive(path).by_uid[path_uid('vehicles/physics/engines/car_a.edfbin')].index
        struct.pack_into('<I', raw, pos + 16, engine_index)
    elif bad == 'version': struct.pack_into('<I', raw, pos + 4, 123)
    elif bad == 'sections': struct.pack_into('<I', raw, pos + 20, 2)
    elif bad == 'bounds': struct.pack_into('<I', raw, 0x124, len(raw) - 5)
    else: struct.pack_into('<I', raw, pos + 8, 2)
    path.write_bytes(raw); editor.scan(str(game)); before = hashes(game)
    with pytest.raises(ValueError, match='unsupported CRC/section'):
        editor.preview([draft(editor, baseline)])
    assert hashes(game) == before


def test_profile_and_api_keep_baseline_and_reject_manual_mix(tmp_path):
    _, editor, baseline = ready(tmp_path); request = draft(editor, baseline, power=.5)
    profile = editor.import_profile({'format': 'ams2season-bop', 'version': 1, 'name': 'Whole donor', 'edits': [request]}, save=False)
    assert profile['edits'][0]['donor_baseline'] == request['donor_baseline']
    with pytest.raises(ValueError, match='cannot be mixed'): editor._evaluate(request | {'parameters': {'cdf.mass.0.0': 1310}})
    assert editor.route('GET', '/api/bop/donor/info', {'car': 'car_a'}, {})['baselines'][0]['id'] == baseline['id']


def test_tampered_baseline_metadata_rejected(tmp_path):
    _, editor, baseline = ready(tmp_path); path = editor.install_dir / 'donor_baselines' / baseline['id'] / 'baseline.json'
    record = json.loads(path.read_text()); record['aliases']['edf'] = 'car_c'; path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='metadata changed'): draft(editor, baseline)


def capture_request(editor, **extra):
    return {'car': 'car_a', 'donor': 'car_b', 'fingerprint': editor.cars['car_a'].fingerprint,
            'donor_fingerprint': editor.cars['car_b'].fingerprint} | extra


@pytest.mark.parametrize('role', ['cdf', 'edf', 'gdf', 'vdf'])
def test_different_readable_donor_versions_require_explicit_choice(tmp_path, role):
    game, editor, _ = ready(tmp_path)
    source = next(s for s in editor.cars['car_b'].sources[role] if not s.packed)
    if role == 'vdf':
        changed = bytearray(source.raw); changed[48 + 96] ^= 1; changed = bytes(changed)
    else:
        key, value = {'cdf': ('cdf.mass.0.0', 1510), 'edf': ('edf.engine_inertia.0.0', .31),
                      'gdf': ('gdf.gear.0.1', 34)}[role]
        changed = edit(role, source.raw, {key: value})
    source.file.write_bytes(changed); editor.scan(str(game)); before = hashes(game)
    info = next(d for d in information(editor, 'car_a')['donors'] if d['id'] == 'car_b')
    assert info['available'] and info['requires_selection']
    component = next(c for c in info['components'] if c['role'] == role)
    assert len(component['versions']) == 2
    assert {s['packed'] for v in component['versions'] for s in v['sources']} == {True, False}
    with pytest.raises(ValueError, match='Choose a ' + role.upper() + ' donor version'):
        capture(editor, capture_request(editor))
    ident = hashlib.sha256(changed).hexdigest()
    result = capture(editor, capture_request(editor, sources={role: ident}))['baseline']
    assert hashes(game) == before
    assert (editor.install_dir / 'donor_baselines' / result['id'] / (role + '.bin')).read_bytes() == changed
    assert next(s for s in result['sources'] if s['role'] == role)['sha'] == ident
    editor.apply(editor.preview([draft(editor, result)])['token'])
    expected = changed
    if role == 'vdf': expected = private_donor_vdf(changed, {k: 'car_a' for k in ('cdf', 'edf', 'gdf')})
    assert all(s.raw == expected for s in editor.cars['car_a'].sources[role])
    assert source.file.read_bytes() == changed
    editor.undo(); assert hashes(game) == before


def test_readable_donor_with_unsupported_packed_copy_can_be_captured(tmp_path):
    game, editor, _ = ready(tmp_path); source = editor.cars['car_b'].sources['cdf'][0]
    archive = game / 'Pakfiles/Vehicles/native_sources.bff'
    pack(archive, {source.canonical: source.raw}, 2, 0)
    editor.scan(str(game)); before = hashes(game)
    assert 'unsupported compression' in ';'.join(editor.cars['car_b'].errors['cdf'])
    info = next(d for d in information(editor, 'car_a')['donors'] if d['id'] == 'car_b')
    assert info['available'] and not info['requires_selection']
    assert any('native_sources.bff' in n and source.canonical in n for n in info['source_notes'])
    result = capture(editor, capture_request(editor))['baseline']
    assert hashes(game) == before
    editor.apply(editor.preview([draft(editor, result)])['token'])
    assert editor.cars['car_a'].public()['metrics']['mass'] == 1300
    assert hashes(game)['Pakfiles/Vehicles/native_sources.bff'] == before['Pakfiles/Vehicles/native_sources.bff']
    editor.undo(); assert hashes(game) == before


def test_invalid_first_copy_does_not_hide_valid_donor_archive(tmp_path):
    game, editor, _ = ready(tmp_path)
    source = next(s for s in editor.cars['car_b'].sources['cdf'] if not s.packed)
    source.file.write_bytes(b'not a physics stream'); editor.scan(str(game))
    info = next(d for d in information(editor, 'car_a')['donors'] if d['id'] == 'car_b')
    assert info['available'] and not info['requires_selection']
    result = capture(editor, capture_request(editor))['baseline']
    assert result['metrics']['mass'] == 1300
    assert all(s['packed'] for s in next(c for c in result['sources'] if c['role'] == 'cdf')['copies'])
    with pytest.raises(ValueError, match='selected CDF donor version is unavailable'):
        capture(editor, capture_request(editor, sources={'cdf': hashlib.sha256(b'not a physics stream').hexdigest()}))


def test_source_selection_and_capture_guard_against_stale_changes(tmp_path):
    game, editor, _ = ready(tmp_path); source = editor.cars['car_b'].sources['cdf'][0]
    with pytest.raises(ValueError, match='Invalid donor component selections'):
        capture(editor, capture_request(editor, sources={'sdf': 'fake'}))
    source.file.write_bytes(edit('cdf', source.raw, {'cdf.mass.0.0': 1500})); before = hashes(game)
    with pytest.raises(ValueError, match='Game files changed since scanning'):
        capture(editor, capture_request(editor))
    assert hashes(game) == before


@pytest.mark.parametrize('problem', ['missing', 'mismatched', 'unreadable'])
def test_candidate_write_guards_are_not_relaxed(tmp_path, problem):
    game, editor, _ = ready(tmp_path); car = editor.cars['car_a']
    if problem == 'missing':
        car.sources['cdf'] = []; car.errors['cdf'] = ['CDF missing']
    elif problem == 'mismatched':
        source = next(s for s in car.sources['cdf'] if not s.packed)
        source.file.write_bytes(edit('cdf', source.raw, {'cdf.mass.0.0': 1500})); editor.scan(str(game))
    else:
        pack(game / 'Pakfiles/Vehicles/native_sources.bff', {car.sources['cdf'][0].canonical: car.sources['cdf'][0].raw}, 2, 0)
        editor.scan(str(game))
    before = hashes(game)
    assert information(editor, 'car_a')['reason']
    with pytest.raises(ValueError, match='CDF|cdf'):
        capture(editor, capture_request(editor))
    assert hashes(game) == before


def test_linked_disagreement_still_blocks_read_only_donor(tmp_path):
    game, editor, _ = ready(tmp_path)
    source = next(s for s in editor.cars['car_b'].linked_sources['sdf'] if not s.packed)
    source.file.write_bytes(b'different installed suspension'); editor.scan(str(game)); before = hashes(game)
    info = next(d for d in information(editor, 'car_a')['donors'] if d['id'] == 'car_b')
    assert not info['available'] and 'SDF' in info['reason']
    with pytest.raises(ValueError, match='SDF copies'):
        capture(editor, capture_request(editor))
    assert hashes(game) == before


def test_missing_donor_cdf_reports_the_component_and_scan_cause(tmp_path):
    _, editor, _ = ready(tmp_path); donor = editor.cars['car_b']
    donor.sources['cdf'] = []; donor.errors['cdf'] = ['Pakfiles/Vehicles/Nissan.bff: checksum mismatch']
    info = next(d for d in information(editor, 'car_a')['donors'] if d['id'] == 'car_b')
    assert not info['available'] and 'no usable CDF' in info['reason'] and 'Nissan.bff' in info['reason']


def test_baselines_captured_before_source_selection_remain_compatible(tmp_path):
    _, editor, baseline = ready(tmp_path)
    path = editor.install_dir / 'donor_baselines' / baseline['id'] / 'baseline.json'
    record = json.loads(path.read_text()); record.pop('sources'); path.write_text(json.dumps(record))
    assert information(editor, 'car_a')['baselines'][0]['id'] == baseline['id']
    assert draft(editor, baseline)['donor_baseline']['id'] == baseline['id']
