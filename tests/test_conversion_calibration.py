"""Automatic targets and roll-control transactions use complete, auditable sources."""
import json
import struct

import pytest

from ams2season.bop import BopEditor
from ams2season.bop_physics import decode, edit, metrics, shcb_region
from ams2season.conversion import propose
from test_bop import hashes, pack, request, setup_game, shcb
from test_conversion import conversion_request, rich_chassis


def replace_component(game, name, role, raw):
    extension = {'cdf': 'cdfbin', 'edf': 'edfbin'}[role]
    folder = {'cdf': 'chassis', 'edf': 'engines'}[role]
    canonical = f'vehicles/physics/{folder}/{name}.{extension}'
    (game / 'Vehicles' / 'physics' / folder / f'{name}.{extension}').write_bytes(raw)
    from ams2season.bff import BffArchive
    from ams2season.bff import path_uid
    names = ['unrelated/foo.xml']
    for car in ('car_a', 'car_b', 'car_c'):
        names.append(f'vehicles/{car}/body.meb')
        names.extend(f'vehicles/physics/{folder}/{car}.{ext}' for folder, ext in
                     [('chassis', 'cdfbin'), ('engines', 'edfbin'), ('gearbox', 'gdfbin'), ('vehicles', 'vdfm')])
    for path in (game / f'Pakfiles/Vehicles/{name}.bff', game / 'Pakfiles/PHYSICSPERSISTENT.bff'):
        archive = BffArchive(path)
        mapping = {n: archive.read(n) for n in names if path_uid(n) in archive.by_uid}
        assert len(mapping) == len(archive.entries)
        mapping[canonical] = raw
        pack(path, mapping, 1, 1024)


def with_boost(raw):
    start, end = shcb_region(raw)
    return shcb(raw[start:end] + bytes.fromhex('24d774451a8300') + struct.pack('<BfB', 0, .01, 100)
                + bytes.fromhex('20ca2fd13464'))


def bars_chassis(mass, reference=False, rear=True, mode=1):
    raw = rich_chassis(mass, reference)
    start, end = shcb_region(raw)
    data = raw[start:end] + bytes.fromhex('2026e982b6') + bytes([mode])
    for axle, marker, setting_marker, base, step, setting in [
        ('front', 'e5b9a9d6', '7fc758d5', 50000 if reference else 60000, 4000 if reference else 2500, 10),
        ('rear', '66001e25', '0478e991', 10000, 5000 if reference else 2500, 3 if reference else 7),
    ]:
        if axle == 'rear' and not rear: continue
        data += bytes.fromhex('24' + marker + '6300') + struct.pack('<fiB', base, step, 20)
        data += bytes.fromhex('20' + setting_marker) + bytes([setting])
    return shcb(data)


def bars_game(tmp_path):
    game = setup_game(tmp_path)
    for name, mass in [('car_a', 1470), ('car_b', 1300), ('car_c', 1400)]:
        replace_component(game, name, 'cdf', bars_chassis(mass, name != 'car_a'))
    return game


def test_low_unboosted_turbo_curves_do_not_pull_automatic_power_target_down(tmp_path):
    game = setup_game(tmp_path)
    path = game / 'Vehicles/physics/engines/car_c.edfbin'
    replace_component(game, 'car_c', 'edf', with_boost(path.read_bytes()))
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    comparison = editor.comparison('GT3_Gen0', exclude='car_a')
    assert {c['car'] for c in comparison['power_target']['used']} == {'car_b'}
    assert comparison['summary']['power_to_weight']['count'] == 2
    assert comparison['reference_summary']['mass']['count'] == 2
    assert 'boost' in comparison['power_target']['excluded'][0]['reason'].lower()
    p = editor.propose(dict(car='car_a', target_class='GT3_Gen0', strength=1, axes=['power_to_weight']))
    assert p['after']['power_to_weight'] == pytest.approx(editor.detail('car_b')['metrics']['power_to_weight'])


def test_active_changes_are_excluded_but_undo_restores_the_class_baseline(tmp_path):
    game = setup_game(tmp_path); editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    editor.apply(editor.preview([request(editor, 'car_b', parameters={'cdf.mass.0.0': 2500})])['token'])
    c = editor.comparison('GT3_Gen0', exclude='car_a')
    assert c['summary']['mass']['median'] == 1950
    assert c['reference_summary']['mass']['median'] == 1400
    assert {x['car'] for x in c['power_target']['used']} == {'car_c'}
    editor.undo()
    assert editor.comparison('GT3_Gen0', exclude='car_a')['reference_summary']['mass']['median'] == 1350


def test_turbo_candidate_skips_power_without_skipping_mass(tmp_path):
    game = setup_game(tmp_path)
    path = game / 'Vehicles/physics/engines/car_a.edfbin'
    replace_component(game, 'car_a', 'edf', with_boost(path.read_bytes()))
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    p = propose(editor, conversion_request(modules=['mass', 'power']))
    assert p['after']['mass'] == 1350
    assert 'cdf.power_multiplier.0.0' not in p['edit']['parameters']
    assert next(m for m in p['modules'] if m['id'] == 'power')['status'] == 'skipped'
    assert editor.propose(dict(car='car_a', target_class='GT3_Gen0', axes=['power_to_weight']))['edit']['parameters'] == {}


def test_missing_boost_status_is_not_treated_as_verified_nonboosted_power(tmp_path):
    game = setup_game(tmp_path); editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    editor.cars['car_b'].turbo_model = editor.cars['car_c'].turbo_model = None
    p = propose(editor, conversion_request(modules=['power']))
    assert p['modules'][0]['status'] == 'skipped' and not p['edit']['parameters']
    assert p['power_target']['summary']['power_to_weight']['median'] is None


def test_target_provenance_survives_profiles_journals_and_guards_used_sources(tmp_path):
    game = setup_game(tmp_path); editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    p = propose(editor, conversion_request(modules=['mass', 'power']))
    profile = editor.import_profile({'format': 'ams2season-bop', 'version': 1, 'name': 'Calibration', 'edits': [p['edit']]}, save=False)
    assert profile['edits'][0]['reference_basis'] == p['edit']['reference_basis']
    assert {r['car'] for r in p['edit']['reference_basis']['references']} == {'car_b', 'car_c'}
    plan = editor.preview(profile['edits'])
    path = game / 'Vehicles/physics/engines/car_c.edfbin'
    path.write_bytes(path.read_bytes() + b'external change')
    before = hashes(game)
    with pytest.raises(ValueError, match='referenced game file changed'): editor.apply(plan['token'])
    assert hashes(game) == before
    path.write_bytes(path.read_bytes()[:-len(b'external change')])
    editor.scan(str(game))
    result = editor.apply(editor.preview(profile['edits'])['token'])
    records = [json.loads(p.read_text()) for p in (editor.install_dir / 'backups').glob('*/transaction.json')]
    record = next(r for r in records if r['status'] == 'applied')
    assert record['changes'][0]['reference_basis'] == p['edit']['reference_basis']


def test_reference_fingerprint_is_checked_when_reloading_a_profile(tmp_path):
    game = setup_game(tmp_path); editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    p = editor.propose(dict(car='car_a', target_class='GT3_Gen0', axes=['mass']))
    source = editor.cars['car_c'].sources['cdf'][0]
    source.raw = edit('cdf', source.raw, {'cdf.mass.0.0': 1500})
    with pytest.raises(ValueError, match='automatic target reference changed'): editor._evaluate(p['edit'])


def test_optional_roll_control_scales_both_axles_preserves_settings_and_undo(tmp_path):
    game = bars_game(tmp_path); editor = BopEditor(tmp_path / 'app'); editor.scan(str(game)); before = hashes(game)
    p = propose(editor, conversion_request(modules=['roll_control'], move_class=False))
    assert p['modules'][0]['status'] == 'ready'
    assert set(p['edit']['parameters']) == {f'cdf.{axle}_arb_range.0.{i}' for axle in ('front', 'rear') for i in range(2)}
    ref = editor.detail('car_b')['metrics']
    assert p['after']['mass'] == 1470 and p['after']['power_hp'] == p['before']['power_hp']
    for axle in ('front', 'rear'):
        assert p['after'][axle + '_arb_proxy'] / p['after']['mass'] == pytest.approx(ref[axle + '_arb_proxy'] / ref['mass'])
    editor.apply(editor.preview([p['edit']])['token'])
    values = {x.id: x.value for x in editor.cars['car_a'].parameters}
    assert values['cdf.front_arb_setting.0.0'] == 10 and values['cdf.rear_arb_setting.0.0'] == 7
    assert values['cdf.front_arb_range.0.2'] == values['cdf.rear_arb_range.0.2'] == 20
    assert values['cdf.rear_arb_range.0.1'] != round(values['cdf.rear_arb_range.0.1'])
    editor.undo(); assert hashes(game) == before
    default = propose(editor, conversion_request())
    assert not any(m['id'] == 'roll_control' for m in default['modules'])


@pytest.mark.parametrize('rear, mode', [(False, 1), (True, 0)])
def test_incomplete_or_diameter_based_bars_do_not_apply_a_partial_module(tmp_path, rear, mode):
    game = bars_game(tmp_path)
    replace_component(game, 'car_a', 'cdf', bars_chassis(1470, rear=rear, mode=mode))
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    p = propose(editor, conversion_request(modules=['roll_control'], move_class=False))
    assert p['modules'][0]['status'] == 'skipped' and not p['edit']['parameters']


def test_travel_coordinates_and_unknown_progression_are_not_zero_or_usable_droop():
    data = b''
    for corner in ['e07d16e29f', 'e0d6537908', 'e0bf9f5ba2', 'e0cff2c932']:
        data += bytes.fromhex(corner + '22b3d821f7') + struct.pack('<f', -.02)
        data += bytes.fromhex('22177b8a89') + struct.pack('<f', -.088)
        data += bytes.fromhex('217fc6f841') + struct.pack('<i', 16000)
        # Unverified double encoding must remain unavailable, never zero.
        data += bytes.fromhex('23cb91f163') + struct.pack('<d', 6944444.4)
    values = metrics(decode('cdf', shcb(data)))[0]
    assert values['rear_rebound_travel'] == pytest.approx(-.088)
    assert values['rear_bumpstop_spring'] == 16000
    assert values['rear_bumpstop_rising'] is None
