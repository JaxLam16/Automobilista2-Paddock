# AMS2 Season: handoff notes

The essentials for continuing development: how the app is put together, facts about AMS2's data that were
verified on real telemetry (several contradict the official header), conventions that prevent bugs that
already happened once, and what's unfinished. README.md is the user-facing feature guide.

## Running and testing

- Windows: `AMS2 Season.bat`. Anywhere: `pip install -e .` then `python -m ams2season app`.
- Tests: `python -m pytest -q` (about 120 tests, around 5 minutes). The shared-memory layout test needs the
  AMS2 `SharedMemory.h` and is skipped without it; point `AMS2_SHM_HEADER` at the file to run it.
- Python 3.10+, pandas/numpy/pyarrow, Pillow. The UI is plain HTML/JS served by a local stdlib HTTP server.
- Recording needs Windows and AMS2 running (shared memory). Everything else runs anywhere; `simulate.py`
  generates realistic sessions for tests and demos.

## Layout

```
ams2season/
  app.py            Library (data access, caching, page payloads), App.route (JSON API), HTTP server, launcher
  app_ui.html       the whole UI in one file: h() builds elements, api() fetches, setView() renders, routes at the bottom
  recorder.py       shared memory -> recordings (session.json, frames.parquet = every car, local.parquet = your car's telemetry, events.jsonl)
  shm.py            ctypes mirror of AMS2's SharedMemory.h (v14)
  derive.py         sessions, distance, laps, corners, classification, track geometry helpers
  race.py           analyze_race(): the race analysis everything else builds on (RaceAnalysis)
  report.py         the race report page (served as an iframe), its data and its own JS
  awards.py         race and season awards; PAGE maps each award to its race-review page
  metrics.py        driving metrics (braking/throttle consistency, track usage), car stats, race_pace()
  traffic.py        "racing corners" detection and weighting (equal / reduced / excluded)
  errors.py         driver errors (spin, off track, braked too late, slow corner) and their cost
  overtakes.py      pass rate / hold rate per driver
  tyres.py          tyre analysis page
  technique.py      Brake & throttle page (corner shapes, scores per racing-corner mode, lock-ups)
  quali.py, practice.py, practice_points.py   qualifying, live practice goals, practice awards for championships
  season.py         championship SQLite: rounds, results, standings (+ practice points), drivers, teams
  legends.py        F1 legend style fingerprints and matching for driver profiles
  engineer/         race engineer: catalog (settings), evidence + corners (measuring), engine (rules, colours,
                    race plan, quali variant, feedback merge), store (sessions, learning), live (tracker)
  liveries.py, bff.py, livery_editor.js/.css   livery editor (writes AMS2 package files; backups + undo)
  simulate.py       synthetic sessions (thermal tyre model, setups, spins, pit stops)
tests/              pytest; tests/data holds REAL AMS2 recordings used as fixtures (keep them)
```

User data lives next to the app and is git-ignored: recordings/, championships/, engineer/, livery_editor/,
tracks/, car_icons/, ams2season.json (settings), ams2season.log.

## AMS2 data facts (verified on real recordings, not the header)

- Tyre pressure (mAirPressure) arrives in kPa (about 186 for 1.86 bar), not PSI. Shown in bar. `tyres.to_bar()` handles kPa/PSI/bar.
- mTyreRPS is radians per second (rolling radius about 0.33 m front, 0.35 m rear for a GT3).
- mBrakeBias is the REAR share: 0.45 = 55/45 in the garage. Front share = 1 - value.
- mTurboBoostPressure is in pascals. Forward speed = -mLocalVelocity z.
- Turning right: steering > 0, yaw rate < 0, lateral accel > 0, left-side wheels loaded.
- Longitudinal accel > 0 under braking.
- Ride height in cm; suspension travel and tyre height above ground in m; damper velocity in m/s.
- AMS2 does NOT expose setup values (except brake bias, TC/ABS levels, fuel, compound, cold pressures and
  static ride heights). The engineer tracks the setup in ticks from the default through confirmed changes.
- Wheel slip must be calibrated while coasting (no pedals): driven wheels spin a few % fast under power.
- Positions at 20 Hz are too coarse to differentiate twice; use yaw rate / speed for path curvature.

## Conventions that prevent repeat bugs

- Never use a `<nav>` element in page content: the sidebar CSS styles every nav (full-height vertical list).
- The main scroll container is `#main`, not window. Preserve `mainEl.scrollTop` on in-page redraws; setView resets it.
- The app window is opened at `/?v=<stamp of app_ui.html>` and responses send `Cache-Control: no-store`, so
  updates always load. Keep both.
- Check the UI in light and dark mode; colours come from CSS variables (`--ink`, `--paper`, `--panel`, ...).
- Bump the analysis version constants when output shape changes so caches refresh: `TECHNIQUE_VERSION`,
  `TYRES_VERSION` (app.py), `ENGINE_VERSION` (engineer/engine.py, re-evaluates saved engineer sessions on open).
- Tables sort by clicking headings (global handler); rows with class `fieldrow` stay pinned; tables with
  class `nosort` opt out.
- Race recordings with no racing (left before the start) raise `race.NO_RACE`; the app shows a note and
  hides them from the home page.
- Friend imports write only session.json, frames.parquet, local.parquet and events.jsonl, by plain name.
- Pages under the race review link to each other with small header buttons (`raceButtons()` in app_ui.html).

## Race engineer design (engineer/)

- Evidence per run (`engine.measure_run`): corner balance (steering per curvature at each apex), fast-corner
  understeer gradient, countersteer by phase, tyre temps/pressures, platform (ride height, bottoming,
  clipped travel), gearing, braking/traction, thermals, fuel, tyre wear.
- Rules in `engine.recommend` fire only on evidence they can stand on; thresholds live in `TARGETS`;
  `targets(prefs)` moves them by the driver's preference sliders. One remedy per symptom.
- `store.EngineerStore`: sessions per car+track; `_learn` measures what one tick did (rejects implausibly
  small effects); learns a ride-height floor when lowering causes bottoming.
- Driver feedback (`engine.merge_feedback`) folds feel into the advice: agree raises confidence, the data
  wins on disagreement, feel-only changes are low confidence; the ARBs are one balance axis.
- Validated on two real Road America runs (tests/data/engineer): +2 rear wing and +2 front ARB read as
  about 20% more steering for the same curvature at 9 of 10 corners.

## Unfinished / next steps

- Engineer thresholds are first estimates: tune them with more real runs (one change at a time, 6+ laps).
- Engineer settings marked `analysed=False` in engineer/catalog.py (slow dampers, fast rebound, caster,
  front toe, 3rd springs, individual gears, diff preload/ramps, weight bias/jacker, boost, compound) are
  tracked but have no rules yet.
- "Traction-limited time" (rear slip over 15%) needs a run with TC changed to decide where real wheelspin starts.
- Practice award thresholds (5 laps for Metronome/Clean sheet, 3 for Iron man/Mileage) need checking in real sessions.
- Livery editor: verify on Windows with the real game (apply, check in AMS2, undo).
- The user asked for a Cordoba practice recording to be checked (ride heights); it never arrived as a zip.
