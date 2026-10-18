# 0.1.0 alpha 8

Alpha 8 is a testing release for recording, championship and practice workflows.
It adds the latest corner-by-corner traces, telemetry skill measurements, minimal
live skill overlay, private reference-pack export/import, garage setup checklist,
practice/R&D improvements and championship fixes from the development build.
See [Corner skills](CORNER_SKILLS.md) for comparisons, configuration and limits.

**Engineer audio:** this ZIP contains no voice pack, Jim reference speech or
original Crew Chief recordings. Standalone radio and speech recognition remain
experimental; original baseline integration needs a compatible local Crew Chief
installation and sound pack. Cached Daniel audio is not included. Keep using
Crew Chief for your session if you need its established calls. Full Crew Chief
parity is incomplete; this release does not claim to replace every call.

Automatic league synchronization is not included. Reference packs can be shared
manually; they contain driver names and selected telemetry, so choose who receives
them. Physical in-game overlay, wheel and microphone compatibility still need
tester validation.

This portable Windows build of the current Paddock app bundles
the recorder, race and championship analysis, practice tools, race engineer,
livery editor, BOP tuning, individual car setups and custom classes.
The executable and dependencies are included; Python is not required on the tester's PC.

Recent telemetry work includes shift-aware throttle filtering, opportunity-aware
start ratings, exit track usage and pace comparison. Brake and throttle detail
appears above the "Where the lap time went" section.

Alpha 2 adds fictional championship AI drivers bound to car/livery, a saved
picture-based assignment review for each recording, and independent human-friends
filters. Registered AI can earn full-field points while remaining AI for human
rankings and awards. See [Championship liveries](CHAMPIONSHIP_LIVERIES.md).

Alpha 3 added optional human car/livery selections, a championship car-class
filter with per-picker exceptions, and livery pictures beside drivers in
standings, race results and replay. Replay car markers use estimated paint
colors with manual overrides. The race assignment button remains visible
before roster setup and provides a shortcut to the championship Settings.

Alpha 5 defaults Race engineer to the car and track currently detected by the
recorder. **Start live engineering** opens or resumes that setup and enables
live run analysis in one click. The selection refreshes while the page is open;
recorded practice remains an optional alternative. Stale or disconnected game
data cannot create a live session, and changing cars/layouts cannot mix run data.
Long track names wrap in the recording widget, race header and recordings table;
table controls remain inside their panel.

Alpha 6 adds an optional local connection to an installed Crew Chief: a separate
Paddock profile, original-file backups/restore, connection status and a spoken
radio check. Automatic corner coaching is not included in this first connection.
See [Crew Chief setup](CREW_CHIEF.md).

Alpha 7 requests immediate playback for radio checks instead of waiting in the
regular race-message queue. Crew Chief still requires a recognized active AMS2
session for custom MQTT speech. The latest source panel distinguishes connection
from session availability and disables the check when it observes game menus,
replay or no game. Delivery acknowledgement remains separate from confirmed hearing.

## Current limits

- **The Mustang/Nissan complete conversion is not validated.** That experiment
  caused event loading and car menu hangs. Native package relocation with section
  metadata remains blocked by the app. Class reassignment or matching power and
  aero does not guarantee GT3 handling. Do not treat these tools as a validated
  complete GT3 converter.
- Game file editing, BOP, liveries and the race engineer remain experimental.
  Support depends on the installed mod version and readable physics data.
  No game content or donor physics files are included in the release.
- Technique scores are heuristics. Fast-corner modulation, gear changes, traffic
  and changing conditions can still affect corner classification and consistency.
  Corner scores help identify patterns; they are not an objective driving grade.
- Pace comparison and racing line time loss are estimates based on available
  telemetry and geometry. They do not prove the cause of a pace gap or reproduce
  a physics simulation. Incomplete track boundaries and linked corners limit
  exit and racing line estimates.
- Shared memory provides detailed controls for the local driver. Other cars do
  not expose the same detailed brake/throttle telemetry for direct comparison.
- Recording requires Windows, AMS2 shared memory enabled and Paddock running.
  The local UI also requires a browser. This build is unsigned.

## First tester pass

1. Start from a fresh extraction and confirm the UI, recorder connection and settings.
2. Record a short practice and race; reopen Paddock and inspect both sessions.
3. Create a championship, add a race and check standings and race results.
   Also configure a fictional AI, review its livery, reopen the recording and
   compare full-field standings with the human-friends filter.
4. Inspect brake/throttle pages, replay, tyres and pace comparison on a clean lap.
5. For optional game editing tests, use a backed-up installation, close AMS2 and
   Content Manager, review/apply one supported change, verify in game and undo it.

The build environment is recorded in `BUILD_INFO.json`; the adjacent release
verification report records automated validation. A real game session and a
separate tester PC are still required to establish game and machine compatibility.

## Livery designer

New sidebar tool for painting supported loose mod meshes in 3D. Core graphics
libraries and starter decals are bundled; online fonts need internet. Projects
and imported decals live in the personal livery_designer folder. Close AMS2
before Save to game, enable all liveries in Livery editor first, then rescan that
editor after saving. Real-game material/loader compatibility still needs testing.
See LIVERY_DESIGNER.md.
