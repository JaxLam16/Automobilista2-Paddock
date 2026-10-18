"""Queued stale snapshots must not erase usable live native history."""
import queue,time
from types import SimpleNamespace
from ams2season.coach.service import CoachService
from ams2season.coach.crew_core import Core
from ams2season.coach.telemetry import from_snapshot
from test_crew_chief_damage import raw_state


def choose(first,*pending):
    worker=SimpleNamespace(inbox=queue.Queue(),dropped_snapshots=0)
    for item in pending:worker.inbox.put_nowait(item)
    return worker,CoachService._skip_stale_snapshots(worker,*first)


def test_superseded_stale_frames_do_not_reset_native_history_when_fresh_data_is_queued():
    calls=[]
    core=Core(host=lambda p:calls.append(p) or {'mapped':True,'events':{'valid':[],'calls':[]}})
    raw=raw_state();now=time.perf_counter();tick=from_snapshot(raw,0,'race')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),now-.02)
    assert core.latest and not core._needs_reset
    stale=raw_state();stale.mParticipantInfo[0].mCurrentLapDistance=900
    fresh=raw_state();fresh.mParticipantInfo[0].mCurrentLapDistance=1100
    worker,(selected,stamp)=choose((stale,now-1),(stale,now-.5),(fresh,time.perf_counter()-.01))
    tick=from_snapshot(selected,.1,'race')
    core.feed_snapshot(selected,tick,tick.player('Jax_Lam'),stamp)
    assert selected is fresh and worker.dropped_snapshots==2
    assert len(calls)==2 and all(p['op']=='map' for p in calls)
    assert core.latest and not core._needs_reset and core.timings_available


def test_a_real_unavailable_gap_still_invalidates_native_state():
    core=Core(host=lambda p:{'mapped':True,'events':{'valid':[],'calls':[]}})
    raw=raw_state();tick=from_snapshot(raw,0,'race')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter()-.01)
    worker,(selected,stamp)=choose((raw,time.perf_counter()-1))
    core.feed_snapshot(selected,tick,tick.player('Jax_Lam'),stamp)
    assert not core.latest and core._needs_reset
    assert core.state=='withheld_stale_or_wrong_player'
    assert worker.dropped_snapshots==0


def test_fresh_samples_keep_their_order_and_are_not_skipped():
    first,next_sample=object(),object();now=time.perf_counter()
    worker,(selected,stamp)=choose((first,now-.01),(next_sample,now))
    assert selected is first and stamp==now-.01
    assert worker.dropped_snapshots==0 and worker.inbox.get_nowait()==(next_sample,now)
