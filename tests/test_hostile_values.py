"""Regression for the first live run: the game sent unsigned values >= 2**31, which crashed the
flush (OverflowError on Windows, ArrowInvalid elsewhere). Feed a whole race of such values."""
import json
from datetime import datetime, timedelta

from ams2season import shm as S
from ams2season.race import analyze_race
from ams2season.recorder import Recorder
from ams2season.simulate import DT, RaceScript, RaceSim

HUMANS = ["Jax", "Mason", "Eli", "Theo"]
U32_UNSET = 0xFFFFFFFF


def _poison(m: S.SharedMemory) -> None:
    for i in range(m.mNumParticipants):
        p = m.mParticipantInfo[i]
        if m.mLapsInvalidated[i]:  # flag packed into the top bit of the lap counter
            p.mLapsCompleted |= 0x80000000
            p.mCurrentLap |= 0x80000000
        m.mNationalities[i] = U32_UNSET
        m.mPitSchedules[i] = U32_UNSET
        m.mHighestFlagReasons[i] = U32_UNSET
    if m.mNumParticipants > 3 and int(m.mSequenceNumber) % 40 == 0:
        m.mParticipantInfo[3].mRacePosition = U32_UNSET  # occasional bogus position


def test_recorder_survives_out_of_range_values(tmp_path):
    start = datetime(2026, 10, 3, 20, 0)
    clock = {"now": 0.0}
    logs = []
    rec = Recorder(tmp_path, hz=20, flush_s=10, log=logs.append,
                   wallclock=lambda: start + timedelta(seconds=clock["now"]))
    sim = RaceSim(HUMANS, RaceScript(laps=4, n_ai=8, spin=("Mason", 2, 1320.0)), seed=5)

    def tick(snap):
        clock["now"] += DT
        rec.step(snap, clock["now"])

    while sim.done_t is None or sim.t < sim.done_t + 5:
        sim.advance(t_green=4.0)
        snap = sim.snapshot(S.GAME_INGAME_PLAYING, S.SESSION_RACE)
        _poison(snap)
        tick(snap)
    for _ in range(int(12 / DT)):
        tick(sim.snapshot(S.GAME_FRONT_END, S.SESSION_INVALID))

    assert len(rec.completed) == 1, "bogus lap counters must not trigger restart detection"
    meta = json.loads((rec.completed[0] / "session.json").read_text())
    assert meta["status"] == "complete"
    oor = meta["out_of_range"]
    assert {"nationality"}.isdisjoint(oor)  # stored losslessly as int64
    assert {"pit_schedule", "flag_reason", "laps_completed", "race_pos"} <= set(oor)
    assert oor["laps_completed"]["stored_as"] >= 0  # top bit masked, real count kept
    assert sum("[warn]" in line for line in logs) == len(oor)  # one warning per field, not per frame

    ra = analyze_race(rec.completed[0], humans=set(HUMANS))
    truth_order = [c.name for c in sim._order()]
    assert list(ra.classification.name) == truth_order
    assert (ra.classification.laps[ra.classification.status == "finished"] == 4).all()
    assert len(ra.pits) == 0  # unset pit schedule must not invent pit stops
