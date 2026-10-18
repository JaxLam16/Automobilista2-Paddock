"""Speech readiness must distinguish cached words from implemented analysis."""
from ams2season.coach.engine import CoachEngine
from ams2season.coach.voice import VoiceCache,text_key
from ams2season.coach.replay import run_replay
from test_coach_voice import voice_batch
from test_coach_replay import write_recording

def test_coverage_reports_holes_and_never_claims_all_dynamic_slots(tmp_path):
    voice_batch(tmp_path,["The car ahead is pitting.","You're missing the apex at turn nine."])
    rows={r['id']:r for r in VoiceCache(tmp_path).coverage(CoachEngine.capabilities()['implemented_rules'])}
    assert rows['X-15']['matching_clips']==1 and rows['X-15']['coverage']=='partial'
    assert rows['X-15']['missing_relations']==['car behind','class leader']
    assert rows['C-10']['matching_clips']==1 and rows['C-10']['coverage']=='partial'
    assert all(rows[k]['coverage']=='none' for k in ('G-01','G-18','S-16','C-09','C-05'))

def test_cached_voice_replay_uses_pinned_inventory_and_reports_missing_phrases(tmp_path):
    path=tmp_path/'race';write_recording(path)
    text=run_replay(path,tmp_path)
    missing=run_replay(path,tmp_path,voice_durations={},voice_id='empty-test')
    cached=run_replay(path,tmp_path,voice_durations={text_key('The car ahead is pitting.'):1.5},voice_id='test')
    assert text['counts']['would_say']==cached['counts']['would_say']==1
    assert missing['counts'].get('would_say',0)==0 and missing['reasons']['voice_clip_missing']>0
    assert missing['speech_simulation']=='cached_voice' and missing['voice_id']=='empty-test'
    assert text['speech_simulation']=='text_preview' and text['voice_id'] is None
    assert text['inputs_unchanged'] and missing['inputs_unchanged'] and cached['inputs_unchanged']
