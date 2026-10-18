"""Practice telemetry shares applicable pages without inventing a race."""
import shutil
import numpy as np
import pytest
from tests.test_development import practices
from ams2season.app import App
from ams2season.technique import corner_shapes
from tests.test_throttle_technique import _lap

def test_aligned_inputs_keep_signed_steering_all_laps_and_raw_pedals():
    laps=[]
    for n in range(1,16):
        lp=_lap(np.full(500,50.+n),n=n)
        lp['steer']=np.full(500,-20.+n)
        laps.append(lp)
    corner=corner_shapes(laps,[{'name':'Turn','apex':400.}],1000)[0]
    data=corner['inputs']
    assert len(data['laps'])==15 and [r['lap'] for r in data['laps']]==list(range(1,16))
    assert len(data['x'])==len(data['mean']['brake'])==len(data['mean']['steering'])
    assert data['mean']['steering'][20]==pytest.approx(-12)
    assert data['laps'][0]['steering'][20]==-19 and data['laps'][-1]['throttle'][20]==65
    assert laps[0]['steer'][0]==-19

def test_practice_has_style_pace_errors_cars_without_race_awards_or_gaps(tmp_path,practices):
    path=tmp_path/'recordings'/'practice';shutil.copytree(practices[0],path)
    app=App(tmp_path)
    try:
        for page in ('style','pace','errors','race-cars'):
            result=app.route('GET','/api/'+page,{'recording':'practice'},{})
            assert result['meta']['session_type']=='practice' and result['awards']==[]
            if page=='pace':
                assert result['drivers'][0]['representative_laps']>0
                assert all(l['gap_ahead'] is None for d in result['drivers'] for l in d['laps'])
                assert all(d['traffic_cost'] is None for d in result['drivers'])
            if page=='race-cars':
                assert result['cars'] and all(c['best_finish'] is None and c['wins']==0 for c in result['cars'])
        assert not list(path.glob('analysis/no_race.flag'))
        assert not list((tmp_path/'championships').glob('*.db'))
    finally:
        if app._development:app._development.stop.set()
