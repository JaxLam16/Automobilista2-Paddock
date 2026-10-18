"""Persisted windows are hints until a fresh clean lap confirms current driving."""
from dataclasses import replace
import json

import pytest

from ams2season.coach.engine import CoachEngine
from ams2season.coach.windows import WindowLearner, WindowStore
from test_coach_replay import tick


def learned():
    learner=WindowLearner(1000)
    for i in range(401):
        frame=tick(i*.1)
        learner.feed(frame,frame.cars[0])
    return learner


def test_saved_windows_need_a_fresh_clean_lap_and_preserve_track_geometry(tmp_path):
    track=tmp_path/'tracks/track.json'; track.parent.mkdir()
    track.write_bytes(b'original-track-geometry')
    store=WindowStore(tmp_path,clock=lambda:1000)
    frame=tick(40)
    identity=store.identity(frame,frame.cars[0])
    store.save(identity,learned())
    restored=WindowLearner(1000)
    assert store.load(identity,restored)
    assert restored.needs_current_lap and restored.seconds(50,50) is None
    # Out-lap, invalid lap and pit lap cannot validate old references.
    for i in range(201):
        frame=tick(i*.1,invalid=(i==100))
        restored.feed(frame,frame.cars[0])
    assert restored.needs_current_lap
    for i in range(201,401):
        frame=tick(i*.1)
        # Current driver brakes earlier; that portion must no longer be a window.
        if frame.cars[0].distance>=650:
            frame=replace(frame,local={**frame.local,'brake':.4})
        restored.feed(frame,frame.cars[0])
    assert not restored.needs_current_lap
    assert restored.seconds(700,50)==0
    assert restored.seconds(50,50)>0
    assert restored.provenance[-1]['completed_at_t']==40
    assert track.read_bytes()==b'original-track-geometry'


@pytest.mark.parametrize('change', ['car','driver','layout','length','weather','unknown_weather'])
def test_cached_windows_do_not_cross_identity_or_condition_boundaries(tmp_path,change):
    store=WindowStore(tmp_path,clock=lambda:1000)
    frame=tick(40)
    identity=store.identity(frame,frame.cars[0]); store.save(identity,learned())
    player=frame.cars[0]
    if change=='car':player=replace(player,car='Other car')
    if change=='driver':player=replace(player,name='Other driver')
    if change=='layout':frame=replace(frame,layout='Other layout')
    if change=='length':frame=replace(frame,length=1001)
    if change in ('weather','unknown_weather'):
        frame=replace(frame,local={**frame.local,'rain_density':.7 if change=='weather' else None})
    assert not store.load(store.identity(frame,player),WindowLearner(frame.length))


@pytest.mark.parametrize('fault',['schema','nan_speed','bad_safe','short','future','stale','array'])
def test_bad_or_stale_cache_cannot_authorize_speech(tmp_path,fault):
    store=WindowStore(tmp_path,clock=lambda:1000)
    frame=tick(40);identity=store.identity(frame,frame.cars[0]);store.save(identity,learned())
    path=store.path(identity);data=json.loads(path.read_text())
    if fault=='schema':data['schema']=2
    if fault=='nan_speed':data['laps'][0]['cells'][0][2]=float('nan')
    if fault=='bad_safe':data['laps'][0]['cells'][0][1]='true'
    if fault=='short':data['laps'][0]['cells']=[]
    if fault=='future':data['saved_at']=1001
    if fault=='stale':data['saved_at']=1000-31*86400
    if fault=='array':data=[]
    path.write_text(json.dumps(data))
    engine=CoachEngine('Player',window_store=store)
    assert engine.feed(tick(0),radio_busy=False) is None
    assert engine.context.window_s is None
    assert len(engine.windows.laps)==0 and engine.windows.completed==0
    assert bool(engine.window_cache_error)==(fault not in ('future','stale'))


def test_live_engine_saves_but_standalone_replay_engine_cannot_load_future_cache(tmp_path):
    store=WindowStore(tmp_path,clock=lambda:1000)
    live=CoachEngine('Player',window_store=store)
    for i in range(401):live.feed(tick(i*.1),radio_busy=False)
    paths=list(store.directory.glob('*.json'))
    assert len(paths)==1
    saved=paths[0].read_bytes()
    later=CoachEngine('Player',window_store=store)
    later.feed(tick(0),radio_busy=False)
    assert later.status()['window_validation_pending'] and len(later.windows.laps)==2
    replay=CoachEngine('Player')
    for i in range(200):
        replay.feed(tick(i*.1),radio_busy=False)
        assert replay.context.window_s is None
    assert not replay.windows.laps
    assert paths[0].read_bytes()==saved


def test_live_weather_change_discards_incompatible_current_windows():
    engine=CoachEngine('Player')
    for i in range(401):engine.feed(tick(i*.1),radio_busy=False)
    assert len(engine.windows.laps)==2
    wet=tick(40.1)
    wet=replace(wet,local={**wet.local,'rain_density':.6})
    engine.feed(wet,radio_busy=False)
    assert not engine.windows.laps and engine.context.window_s is None
