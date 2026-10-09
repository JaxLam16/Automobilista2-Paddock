"""Physics conversion: synthetic known layouts, package guards and reversibility."""
from pathlib import Path
import struct

import pytest

from ams2season.bff import BffArchive
from ams2season.bop import BopEditor
from ams2season.bop_physics import decode, edit, metrics, shcb_region
from ams2season.conversion import MODULES, information, propose
from test_bop import chassis, engine, gearbox, hashes, pack, request, setup_game, shcb, vdfm


def rich_chassis(mass, reference=False):
    original = chassis(mass)
    start, end = shcb_region(original)
    data = original[start:end]
    data += bytes.fromhex('24bbb39f0ba302') + struct.pack('<fff', *(2400, 2600, 600) if reference else (3000, 3200, 650))
    # A legacy byte-encoded diffuser needs a documented float widening to
    # accept the reference model. These are synthetic, not shipped game data.
    data += bytes.fromhex('24be0f2899a300') + struct.pack('<ffB', -.95, -2, 10) if reference else bytes.fromhex('24be0f28992300') + struct.pack('<fBB', -1.3, 252, 35)
    data += bytes.fromhex('2447d0b1de21') + struct.pack('<f', 1 if reference else .5)
    data += bytes.fromhex('2420b98dffa302') + struct.pack('<fff', .02, 0, 0)
    data += bytes.fromhex('24ff5946c8a302') + struct.pack('<fff', .05, .3, .3)
    data += bytes.fromhex('24e0a125dea2') + struct.pack('<ff', -.2, .3)
    data += bytes.fromhex('24e176322421') + struct.pack('<f', .6)
    for hx, value in [('67caa092', .4), ('1f13c185', -.1), ('56e0a3ab', .2), ('06f458ac', .3), ('96d38a17', .7), ('7a8f77c8', 1)]:
        data += bytes.fromhex('24' + hx + '21') + struct.pack('<f', value)
    data += bytes.fromhex('2409a852d921') + struct.pack('<f', .2) if reference else bytes.fromhex('2409a852d90101')
    for hx in ['2cfb70da', '67dcb6b3']:
        data += bytes.fromhex('24' + hx + 'a302') + struct.pack('<fff', .025, .001, .0001)
    for corner in ['e07d16e29f','e0d6537908','e0bf9f5ba2','e0cff2c932']:
        data += bytes.fromhex(corner + '2244495d88') + struct.pack('<f', 1 if reference else .75)
        data += bytes.fromhex('2251374153') + struct.pack('<f', 1 if reference else .8)
        data += bytes.fromhex('24a5123d0d5300') + struct.pack('<iiB', 165000 if reference else 270000, 4000, 10)
        data += bytes.fromhex('20ceaa7a9705')
        data += bytes.fromhex('24d7c60d7aa300') + struct.pack('<ffB', .055 if reference else .05, .001, 10)
        data += bytes.fromhex('206d04940505')
        for hx, setting in [('0c43d9d0','d19e2c0a'),('3089ec3d','38382587'),('bcc0a291','2273d781'),('bc6d0ef7','b8b0022e')]:
            data += bytes.fromhex('24' + hx + '5300') + struct.pack('<iiB', 13000 if reference else 14000, 400, 20)
            data += bytes.fromhex('20' + setting + '05')
    return shcb(data)


def rich_game(tmp_path):
    game = setup_game(tmp_path)
    persistent = {'unrelated/foo.xml': b'<keep/>'}
    for name, mass in [('car_a',1470),('car_b',1300),('car_c',1400)]:
        files = {f'vehicles/physics/chassis/{name}.cdfbin':rich_chassis(mass,name!='car_a'),
                 f'vehicles/physics/engines/{name}.edfbin':engine(),
                 f'vehicles/physics/gearbox/{name}.gdfbin':gearbox(),
                 f'vehicles/physics/vehicles/{name}.vdfm':vdfm(name,'tyre_'+name)}
        for canonical, raw in files.items():
            (game / 'Vehicles' / Path(canonical).relative_to('vehicles')).write_bytes(raw)
        persistent.update(files)
        pack(game / f'Pakfiles/Vehicles/{name}.bff',files | {f'vehicles/{name}/body.meb':b'geometry stays untouched'},1,256)
    pack(game/'Pakfiles/PHYSICSPERSISTENT.bff',persistent,1,256)
    return game


def conversion_request(**changes):
    return dict(car='car_a',target_class='GT3_Gen0',reference='car_b',strength=1) | changes


def test_conversion_updates_real_fields_across_copies_and_undo_is_byte_exact(tmp_path):
    game=rich_game(tmp_path); editor=BopEditor(tmp_path/'app');editor.scan(str(game))
    original=hashes(game)
    proposal=propose(editor,conversion_request())
    assert not [m for m in proposal['modules'] if m['status']=='skipped']
    assert proposal['after']['mass']==1350
    assert proposal['edit']['tyres']=='tyre_car_b'
    assert proposal['after']['yaw_inertia']==pytest.approx(3200*1350/1470)
    old_cdf=(game/'Vehicles/physics/chassis/car_a.cdfbin').read_bytes()
    old_footer=old_cdf[shcb_region(old_cdf)[1]:]
    plan=editor.preview([proposal['edit']]);assert hashes(game)==original
    editor.apply(plan['token'])
    detail=editor.detail('car_a')
    assert detail['class']=='GT3_Gen0' and detail['tyres']=='tyre_car_b'
    changed_cdf=(game/'Vehicles/physics/chassis/car_a.cdfbin').read_bytes()
    assert len(changed_cdf)>len(old_cdf)
    assert changed_cdf[shcb_region(changed_cdf)[1]:]==old_footer
    fields={p.id:p.value for p in decode('cdf',changed_cdf)}
    assert fields['cdf.diffuser.0.1']==-2
    assert fields['cdf.fw_max_height.0.0']==pytest.approx(.2)
    for path in [game/'Pakfiles/Vehicles/car_a.bff',game/'Pakfiles/PHYSICSPERSISTENT.bff']:
        archive=BffArchive(path)
        assert archive.read('vehicles/physics/chassis/car_a.cdfbin')==changed_cdf
        for entry in archive.entries:archive.read_entry(entry)
    assert BffArchive(game/'Pakfiles/Vehicles/car_a.bff').read('vehicles/car_a/body.meb')==b'geometry stays untouched'
    for path, digest in original.items():
        if any(s in path for s in ('engines/', 'gearbox/', 'car_b.', 'car_c.')):assert hashes(game)[path]==digest
    editor.undo();assert hashes(game)==original


def test_suspension_scales_for_candidate_axle_load_and_preserves_geometry_multipliers(tmp_path):
    game=rich_game(tmp_path);editor=BopEditor(tmp_path/'app');editor.scan(str(game))
    proposal=propose(editor,conversion_request(modules=['mass','suspension']))
    own=editor.cars['car_a'];reference=editor.cars['car_b']
    edited=decode('cdf',edit('cdf',own.sources['cdf'][0].raw,proposal['edit']['parameters']))
    after=metrics(edited)[0];ref=metrics(reference.parameters)[0]
    assert after['front_spring_proxy']/after['mass']==pytest.approx(ref['front_spring_proxy']/ref['mass'])
    assert after['rear_spring_proxy']/after['mass']==pytest.approx(ref['rear_spring_proxy']/ref['mass'])
    assert not any('multiplier' in k or 'cg_' in k for k in proposal['edit']['parameters'])


def test_inertia_uses_original_backup_after_previous_mass_only_bop(tmp_path):
    game=rich_game(tmp_path);editor=BopEditor(tmp_path/'app');editor.scan(str(game))
    editor.apply(editor.preview([request(editor,parameters={'cdf.mass.0.0':1300})])['token'])
    info=information(editor,'car_a','GT3_Gen0')
    assert info['baseline']['mass']==1470 and 'history' in info['baseline']['source']
    proposal=propose(editor,conversion_request(modules=['inertia'],move_class=False))
    assert proposal['after']['yaw_inertia']==pytest.approx(3200*1300/1470)
    editor.apply(editor.preview([proposal['edit']])['token'])
    again=propose(editor,conversion_request(modules=['inertia'],move_class=False))
    assert not again['edit']['parameters']
    assert editor.detail('car_a')['class']=='World_GT_Challenge'


def test_bop_proposal_can_compare_another_class_without_reassigning_it(tmp_path):
    game=rich_game(tmp_path);editor=BopEditor(tmp_path/'app');editor.scan(str(game))
    proposal=editor.propose(dict(car='car_a',target_class='GT3_Gen0',strength=1,axes=['mass'],reassign_class=False))
    assert 'target_class' not in proposal['edit']
    editor.apply(editor.preview([proposal['edit']])['token'])
    assert editor.detail('car_a')['class']=='World_GT_Challenge'


def test_missing_conversion_module_is_reported_without_partial_physics_changes(tmp_path):
    game=setup_game(tmp_path);editor=BopEditor(tmp_path/'app');editor.scan(str(game))
    p=propose(editor,conversion_request(modules=['underbody','suspension','inertia']))
    assert all(m['status']=='skipped' for m in p['modules'])
    assert p['edit']['parameters']=={}
    assert p['edit']['target_class']=='GT3_Gen0'


def test_reference_changes_are_guarded_after_review(tmp_path):
    game=rich_game(tmp_path);editor=BopEditor(tmp_path/'app');editor.scan(str(game))
    p=propose(editor,conversion_request(modules=['tyres']))
    plan=editor.preview([p['edit']])
    path=game/'Vehicles/physics/chassis/car_b.cdfbin'
    path.write_bytes(edit('cdf',path.read_bytes(),{'cdf.mass.0.0':1310}))
    before=hashes(game)
    with pytest.raises(ValueError,match='referenced game file changed'):editor.apply(plan['token'])
    assert hashes(game)==before


def test_shared_and_readonly_chassis_are_not_partially_converted(tmp_path):
    game=rich_game(tmp_path);editor=BopEditor(tmp_path/'app');editor.scan(str(game))
    editor.cars['car_a'].blocked['cdf']='Shared chassis'
    p=propose(editor,conversion_request(modules=['underbody','suspension','mass','inertia']))
    assert all(m['status']=='skipped' for m in p['modules'])
    assert p['edit']['parameters']=={}


@pytest.mark.parametrize('change',[{'modules':['guess_grip']},{'strength':float('nan')},{'move_class':'yes'},{'performance_target':'magic'},{'reference':'car_a'}])
def test_invalid_conversion_requests_do_not_write(tmp_path,change):
    game=rich_game(tmp_path);editor=BopEditor(tmp_path/'app');editor.scan(str(game));before=hashes(game)
    with pytest.raises(ValueError):propose(editor,conversion_request(**change))
    assert hashes(game)==before


def test_custom_class_and_physics_conversion_share_one_reviewed_transaction(tmp_path):
    game=rich_game(tmp_path);editor=BopEditor(tmp_path/'app');editor.scan(str(game))
    p=propose(editor,conversion_request(target_class='League_GT3',group='GT3',grid='10',performance_target='reference',modules=['mass','tyres']))
    assert p['after']['mass']==1300
    editor.apply(editor.preview([p['edit']])['token'])
    assert editor.detail('car_a')['class']=='League_GT3' and editor.detail('car_a')['tyres']=='tyre_car_b'


def test_conversion_profile_retains_reference_validation(tmp_path):
    game=rich_game(tmp_path);editor=BopEditor(tmp_path/'app');editor.scan(str(game))
    p=propose(editor,conversion_request(modules=['tyres','underbody']))
    value={'format':'ams2season-bop','version':1,'name':'GT3 conversion','edits':[p['edit']]}
    profile=editor.import_profile(value,save=False)
    assert profile['edits'][0]['conversion_reference']==p['edit']['conversion_reference']
    editor.cars['car_b'].metadata['Vehicle Class']='Different'
    # Alter a source, which is what the installed-version fingerprint covers.
    source=editor.cars['car_b'].sources['cdf'][0];source.raw=edit('cdf',source.raw,{'cdf.mass.0.0':1310})
    with pytest.raises(ValueError,match='conversion reference changed'):editor.import_profile(profile,save=False)


def test_widening_updates_registers_and_cannot_guess_ambiguous_coefficients():
    raw=rich_chassis(1470)
    with pytest.raises(ValueError,match='complete coefficient tuple'):
        edit('cdf',raw,{'cdf.diffuser.0.2':10.5})
    out=edit('cdf',raw,{'cdf.diffuser.0.0':-.95,'cdf.diffuser.0.1':-2,'cdf.diffuser.0.2':10.5})
    assert shcb_region(out)[1]-shcb_region(raw)[1]==len(out)-len(raw)
    assert struct.unpack_from('<I',out,8)[0]==len(out)
    assert {p.id:p.value for p in decode('cdf',out)}['cdf.diffuser.0.2']==pytest.approx(10.5)


def test_new_api_and_ui_route_are_integrated(tmp_path):
    game=rich_game(tmp_path);editor=BopEditor(tmp_path/'app');editor.scan(str(game))
    info=editor.route('GET','/api/bop/conversion/info',{'car':'car_a','class':'GT3_Gen0'}, {})
    assert info['recommended'] in ('car_b','car_c') and len(info['modules'])==len(MODULES)
    p=editor.route('POST','/api/bop/conversion/propose',{},conversion_request(modules=['mass','inertia']))
    assert p['after']['mass']==1350
