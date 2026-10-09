"""Custom grids must restore assignments without reverting later car tuning."""
import os
from pathlib import Path

import pytest

from ams2season.bff import BffArchive
from ams2season.bop import BopEditor
from ams2season.bop_files import transactions
from ams2season.bop_physics import crd_properties
from ams2season.class_sets import catalog_path
from test_bop import crd, hashes, pack, request, setup_game


def route(editor, method='GET', endpoint='', body=None):
    return editor.route(method, '/api/bop/class-sets' + endpoint, {}, body or {})


def new_class(editor, name='Testing'):
    return route(editor, 'POST', body={'name': name, 'base_class': 'GT3_Gen0'})['id']


def preview(editor, ident, members):
    return route(editor, 'POST', '/preview', {'id': ident, 'members': members, 'revision': route(editor)['revision']})


def apply(editor, ident, members):
    return editor.apply(preview(editor, ident, members)['token'])


def members(editor, ident):
    return next(c['members'] for c in route(editor)['classes'] if c['id'] == ident)


def test_create_and_review_are_app_only_until_apply(tmp_path):
    game = setup_game(tmp_path)
    app = tmp_path / 'app'
    for folder in ('recordings', 'championships', 'old_backups'):
        (app / folder).mkdir(parents=True)
        (app / folder / 'keep').write_bytes(b'important user data')
    editor = BopEditor(app)
    editor.scan(str(game))
    before = hashes(game)
    ident = new_class(editor)
    assert members(editor, ident) == []
    plan = preview(editor, ident, ['car_a', 'car_b'])
    assert hashes(game) == before
    assert members(editor, ident) == []
    assert len(plan['changes']) == 2 and plan['count'] == 3
    assert set(plan['files']) == {'Vehicles/car_a/car_a.crd', 'Vehicles/car_b/car_b.crd', 'Pakfiles/BOOTPERSISTENT.bff'}
    assert all(c['before'] == c['after'] for c in plan['changes'])
    editor.apply(plan['token'])
    assert members(editor, ident) == ['car_a', 'car_b']
    for car in ('car_a', 'car_b'):
        metadata = crd_properties((game / f'Vehicles/{car}/{car}.crd').read_bytes())
        packed = crd_properties(BffArchive(game / 'Pakfiles/BOOTPERSISTENT.bff').read(f'vehicles/{car}/{car}.crd'))
        assert metadata == packed
        assert metadata['Vehicle Class'] == 'Testing' and metadata['Vehicle Group'] == 'GT3'
        assert metadata['Vehicle Physics Model'] == car
    after = hashes(game)
    assert {p for p in before if before[p] != after[p]} == set(plan['files'])
    for folder in ('recordings', 'championships', 'old_backups'):
        assert (app / folder / 'keep').read_bytes() == b'important user data'


def test_remove_restores_each_original_and_keeps_later_tuning_with_restart_and_undo(tmp_path):
    game = setup_game(tmp_path)
    app = tmp_path / 'app'
    editor = BopEditor(app); editor.scan(str(game))
    before = hashes(game)
    original_boot = BffArchive(game / 'Pakfiles/BOOTPERSISTENT.bff')
    original_crds = {c: original_boot.read(f'vehicles/{c}/{c}.crd') for c in ('car_a', 'car_b', 'car_c')}
    ident = new_class(editor)
    apply(editor, ident, ['car_a', 'car_b'])
    added = hashes(game)
    editor.apply(editor.preview([request(editor, parameters={'cdf.mass.0.0': 1350})])['token'])
    tuned = hashes(game)
    editor = BopEditor(app); editor.scan(str(game))
    apply(editor, ident, [])
    assert members(editor, ident) == []
    assert editor.cars['car_a'].metadata['Vehicle Class'] == 'World_GT_Challenge'
    assert editor.cars['car_a'].metadata['Vehicle Group'] == 'World_GT_Challenge'
    assert editor.cars['car_a'].metadata['Grid Grouping'] == '15'
    assert editor.cars['car_b'].metadata['Vehicle Class'] == 'GT3_Gen0'
    assert editor.detail('car_a')['metrics']['mass'] == 1350
    restored_boot = BffArchive(game / 'Pakfiles/BOOTPERSISTENT.bff')
    assert {c: restored_boot.read(f'vehicles/{c}/{c}.crd') for c in original_crds} == original_crds
    assert restored_boot.file_size == original_boot.file_size
    editor.undo()
    assert members(editor, ident) == ['car_a', 'car_b'] and hashes(game) == tuned
    editor.undo()
    assert hashes(game) == added
    editor.undo()
    assert members(editor, ident) == [] and hashes(game) == before
    assert catalog_path(editor).exists()


def test_transfer_between_custom_classes_retains_first_original(tmp_path):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    first, second = new_class(editor), new_class(editor, 'Testing_2')
    apply(editor, first, ['car_a', 'car_b'])
    apply(editor, second, ['car_a', 'car_c'])
    assert members(editor, first) == ['car_b']
    assert members(editor, second) == ['car_a', 'car_c']
    apply(editor, second, [])
    assert editor.cars['car_a'].metadata['Vehicle Class'] == 'World_GT_Challenge'
    assert editor.cars['car_c'].metadata['Vehicle Class'] == 'GT3_Gen0'
    editor.undo()
    assert members(editor, second) == ['car_a', 'car_c']
    editor.undo()
    assert members(editor, first) == ['car_a', 'car_b'] and members(editor, second) == []


def test_class_only_moves_keep_stock_physics_eligible_as_references(tmp_path):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    ident = new_class(editor)
    apply(editor, ident, ['car_a', 'car_b', 'car_c'])
    comparison = editor.comparison('Testing')
    assert {r['car'] for r in comparison['reference_cars']} == {'car_a', 'car_b', 'car_c'}
    assert {r['car'] for r in comparison['power_target']['used']} == {'car_a', 'car_b', 'car_c'}
    editor.apply(editor.preview([request(editor, parameters={'cdf.mass.0.0': 1350})])['token'])
    comparison = editor.comparison('Testing')
    assert {r['car'] for r in comparison['reference_cars']} == {'car_b', 'car_c'}
    assert {r['car'] for r in comparison['power_target']['used']} == {'car_b', 'car_c'}


def test_failed_apply_never_commits_membership(tmp_path, monkeypatch):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    ident = new_class(editor)
    plan = preview(editor, ident, ['car_a', 'car_b'])
    before, replace, calls = hashes(game), os.replace, 0
    def fail_second(src, dst):
        nonlocal calls
        if Path(dst).is_relative_to(game) and '.bop-' in Path(src).name:
            calls += 1
            if calls == 2: raise PermissionError('locked')
        return replace(src, dst)
    monkeypatch.setattr('ams2season.bop_files.os.replace', fail_second)
    with pytest.raises(ValueError, match='No BOP changes were kept'):
        editor.apply(plan['token'])
    assert hashes(game) == before and members(editor, ident) == []
    assert transactions(editor.install_dir / 'backups')[0][1]['status'] == 'rolled_back'


def test_external_assignment_conflict_is_read_only(tmp_path):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    ident = new_class(editor)
    apply(editor, ident, ['car_a'])
    # A separately reviewed class edit must not be silently overwritten on removal.
    editor.apply(editor.preview([request(editor, target_class='GT3_Gen0')])['token'])
    before = hashes(game)
    assert next(c['reason'] for c in route(editor)['cars'] if c['id'] == 'car_a')
    with pytest.raises(ValueError, match='outside this manager'):
        preview(editor, ident, [])
    assert hashes(game) == before
    editor.undo()
    apply(editor, ident, [])
    assert editor.cars['car_a'].metadata['Vehicle Class'] == 'World_GT_Challenge'


def test_oversize_class_review_does_not_relocate_or_partially_write(tmp_path):
    game = setup_game(tmp_path)
    pack(game / 'Pakfiles/BOOTPERSISTENT.bff', {'vehicles/car_a/car_a.crd': crd('car_a')}, 1, 256)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    ident = new_class(editor, 'T' * 80)
    before = hashes(game)
    with pytest.raises(ValueError, match='allocated CRD'):
        preview(editor, ident, ['car_a'])
    assert hashes(game) == before and members(editor, ident) == []


def test_stale_picker_catalog_and_game_file_guards(tmp_path):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    ident = new_class(editor)
    old = route(editor)['revision']
    new_class(editor, 'Testing_2')
    with pytest.raises(ValueError, match='Reopen Manage classes'):
        route(editor, 'POST', '/preview', {'id': ident, 'members': ['car_a'], 'revision': old})
    plan = preview(editor, ident, ['car_a'])
    new_class(editor, 'Testing_3')
    with pytest.raises(ValueError, match='changed after preview'):
        editor.apply(plan['token'])
    plan = preview(editor, ident, ['car_a'])
    path = game / 'Vehicles/car_a/car_a.crd'
    path.write_bytes(path.read_bytes() + b' ')
    before = hashes(game)
    with pytest.raises(ValueError, match='after preview'):
        editor.apply(plan['token'])
    assert hashes(game) == before and members(editor, ident) == []


@pytest.mark.parametrize('name', ['GT3_Gen0', 'gt3_gen0', 'Testing', 'testing', '../../outside', '<script>', '', 7])
def test_invalid_or_duplicate_names_preserve_catalog(tmp_path, name):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    new_class(editor)
    path = catalog_path(editor); saved = path.read_bytes()
    with pytest.raises(ValueError):
        new_class(editor, name)
    assert path.read_bytes() == saved


@pytest.mark.parametrize('desired', [[], ['missing'], ['car_a', 'car_a'], 'car_a', [1]])
def test_invalid_or_unchanged_selection_does_not_apply(tmp_path, desired):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    ident = new_class(editor); before = hashes(game)
    with pytest.raises(ValueError): preview(editor, ident, desired)
    assert hashes(game) == before


def test_bad_catalog_is_preserved_and_another_game_has_separate_classes(tmp_path):
    game = setup_game(tmp_path)
    editor = BopEditor(tmp_path / 'app'); editor.scan(str(game))
    new_class(editor)
    path = catalog_path(editor); path.write_text('{broken', encoding='utf-8')
    with pytest.raises(ValueError, match='invalid'): new_class(editor, 'Other')
    assert path.read_text(encoding='utf-8') == '{broken'
    other = setup_game(tmp_path / 'other')
    editor.scan(str(other))
    assert route(editor)['classes'] == []
