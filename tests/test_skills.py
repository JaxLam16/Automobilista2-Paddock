import copy
import json
from pathlib import Path
import numpy as np
import pytest

from ams2season.skills import measure, report, CATALOG
from ams2season.skill_references import match,compare


def lap(hz=20):
    t=np.arange(0,12+1/hz/2,1/hz);ld=t*50
    interp=lambda pairs:np.interp(ld,*zip(*pairs))
    brake=interp([(0,0),(130,0),(160,90),(190,90),(290,0),(600,0)])
    steer=interp([(0,0),(180,0),(220,20),(310,25),(390,0),(600,0)])
    n=len(t);const=lambda v:np.full(n,float(v))
    return {'n':1,'valid':True,'time':12.,'t':t,'ld':ld,'brake':brake,
        'throttle':interp([(0,100),(130,0),(290,0),(380,100),(600,100)]),
        'speed':interp([(0,190),(280,90),(320,90),(600,190)]),'steer':steer,
        'gear':const(3),'yaw_rate':const(-.5),'acc_lat':const(5),'acc_vert':const(9.8),
        'acc_long':const(0),'vel_lat':const(1),'vel_long':const(-35),
        'rpm':const(6000),'max_rpm':const(8000)}


def measured(lp=None,**kw):return measure(lp or lap(),{'name':'T1','apex':300},1000,before=180,after=170,**kw)


def test_one_clean_lap_supports_all_measurements_without_claiming_optimality():
    r=report([lap()],[{'name':'T1','apex':300}],1000)
    assert r['clean_laps']==1 and len(r['passes'])==1 and not r['optimality_scored']
    m=measured()['metrics'];assert set(m)=={k for k,_ in CATALOG}
    assert m['peak_brake']['value']==90 and m['minimum_speed']['value']==90
    assert m['apex']['value'] is None and m['exits']['value'] is None
    assert 'measured track edges' in m['exits']['detail']
    assert all('score' not in a for a in m.values())


def test_trail_brake_is_release_shape_and_location_not_only_overlap():
    m=measured()['metrics']['trail_braking'];r=m['release']
    assert r['seconds']>1 and r['largest_drop_per_0_1s']<10
    assert r['reapplication_points']==0 and r['distance_m']<0 and r['overlap_s']>0
    lp=lap();lp['brake']=np.where((lp['ld']>=150)&(lp['ld']<=270),90.,0.)
    abrupt=measured(lp)['metrics']['trail_braking']
    assert abrupt['status']=='caution' and abrupt['release']['largest_drop_per_0_1s']>35


def test_sampling_rate_does_not_change_smoothness_or_event_duration():
    a,b=(measured(lap(hz))['metrics'] for hz in (20,60))
    assert a['steering']['value']==pytest.approx(b['steering']['value'],abs=1)
    assert a['trail_braking']['value']==pytest.approx(b['trail_braking']['value'],abs=.06)


@pytest.mark.parametrize('bad',['invalid','gap','reverse','missing','late_entry','incomplete_exit'])
def test_unsafe_passes_withhold_measurements(bad):
    p=lap()
    if bad=='invalid':p['valid']=False
    if bad=='gap':p['t'][100:]+=2
    if bad=='reverse':p['ld'][100]-=20
    if bad=='missing':p['brake'][100]=np.nan
    if bad=='late_entry':
        keep=p['ld']>280
        for k,v in list(p.items()):
            if isinstance(v,np.ndarray):p[k]=v[keep]
    if bad=='incomplete_exit':
        keep=p['ld']<310
        for k,v in list(p.items()):
            if isinstance(v,np.ndarray):p[k]=v[keep]
    assert all(m['value'] is None for m in measured(p)['metrics'].values())


def test_small_rotation_not_flagged_and_sustained_correction_requires_motion():
    p=lap();normal=measured(p)['metrics']['oversteer'];assert normal['value']==0 and normal['status']=='measured'
    m=(p['ld']>300)&(p['ld']<420);p['steer'][m]=-15;p['vel_lat'][m]=5;p['throttle'][m]=90
    event=measured(p)['metrics']['oversteer'];assert event['status']=='caution' and event['value']>1
    del p['vel_lat'];assert measured(p)['metrics']['oversteer']['value'] is None


def test_shift_or_large_vertical_acceleration_does_not_become_throttle_blame():
    p=lap();m=(p['ld']>320)&(p['ld']<345);p['steer'][m]=-15;p['vel_lat'][m]=5;p['throttle'][m]=90
    p['gear'][p['ld']>330]=4
    assert measured(p)['metrics']['oversteer']['value']==0
    p['gear'][:]=3;p['acc_vert'][m]=30
    assert measured(p)['metrics']['oversteer']['value']==0


def test_no_distinct_throttle_pickup_or_trail_brake_in_flatout_corner():
    p=lap();p['throttle'][:]=80;p['brake'][:]=0
    m=measured(p)['metrics'];assert m['throttle_onset']['value'] is None and m['trail_braking']['value'] is None


def test_small_early_brake_touch_is_not_the_main_braking_point():
    p=lap()
    run=lambda:measure(p,{'name':'T1','apex':300},1000,before=240,after=170)
    main=run()['metrics']['brake_point']['value']
    p['brake'][(p['ld']>80)&(p['ld']<110)]=8
    assert run()['metrics']['brake_point']['value']==pytest.approx(main,abs=3)


def test_one_long_withdrawal_is_not_counted_as_multiple_new_lifts():
    p=lap();p['throttle']=np.interp(p['ld'],[0,300,320,430,600],[100,100,100,10,10])
    assert measured(p)['metrics']['throttle_application']['value']==1


def test_measured_edge_clearance_is_observation_not_wide_exit_penalty():
    from types import SimpleNamespace
    p=lap();p['x']=p['ld'].copy();p['z']=p['ld']*0
    geometry=SimpleNamespace(corners=[{'name':'T1','sections':[{'d':260,'width':12},{'d':340,'width':12}]}],gap=lambda *args:1.2)
    m=measured(p,geometry=geometry)['metrics']
    assert m['apex']['value']==.35 and m['exits']['value']==9.95
    assert m['exits']['status']=='measured' and 'not penalized' in m['exits']['detail']


def test_reference_exact_car_then_class_never_unrelated_layout_or_ai():
    a={'track_location':'Track','track_variation':'GP','track_length':1000,
       'local':{'name':'A','car':'Mustang','car_class':'GT3 Gen 0'}}
    b=copy.deepcopy(a);b['local']['name']='B'
    assert match(a,b)=='exact_car'
    b['local']['car']='GT-R';assert match(a,b)=='same_class'
    b['local']['car_class']='GT4';assert match(a,b) is None
    b=copy.deepcopy(a);b['track_variation']='Short';assert match(a,b) is None
    b=copy.deepcopy(a);b['final']=[{'name':'A','is_ai':True}];assert match(a,b) is None


def test_reference_deltas_are_not_cross_car_scores():
    current=report([lap()],[{'name':'T1','apex':300}],1000)
    ref=copy.deepcopy(current);ref['passes'][0]['metrics']['minimum_speed']['value']=100
    r=compare(current,ref,'same_class');assert not r['quality_scores']
    assert r['differences'][0]['metrics']['minimum_speed']['difference']==-10
    assert 'do not prove a mistake' in r['note']
    for target in ref['targets']['T1'].values():target['apex']=330
    assert not compare(current,ref,'same_class')['differences']


def test_corner_targets_use_best_corner_not_whole_best_lap_and_keep_metric_provenance():
    from ams2season.skill_references import corner_targets
    a=measured();a.update(lap=1,ranking_time_s=8.,group_racing=False,linked_corners=['T1'])
    b=copy.deepcopy(a);b.update(lap=2,ranking_time_s=7.9)
    a['metrics']['trail_braking']['release']['reapplication_points']=0
    b['metrics']['trail_braking']['release']['reapplication_points']=20
    targets=corner_targets([a,b])['T1']
    assert targets['minimum_speed']['lap']==2
    assert targets['trail_braking']['lap']==1
    assert targets['trail_braking']['ranking_time_s']<=targets['minimum_speed']['ranking_time_s']+.2
    b['group_racing']=True
    assert corner_targets([a,b])['T1']['minimum_speed']['lap']==1


def test_linked_sequence_timing_keeps_both_corners_from_same_lap():
    p=lap();p['n']=3
    corners=[{'name':'T1','apex':300,'dir':'left','exit_policy':'compromise'},
             {'name':'T2','apex':420,'dir':'right'}]
    r=report([p],corners,1000,racing={(3,'T1'):False,(3,'T2'):False})
    passes=r['passes'];assert passes[0]['linked_corners']==['T1','T2']
    assert all(p['ranking_time_s']==pytest.approx(sum(q['elapsed_s'] for q in passes)) for p in passes)
    assert r['targets']['T1']['minimum_speed']['linked_corners']==['T1','T2']
