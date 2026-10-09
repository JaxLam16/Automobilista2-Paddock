# Livery-based championship drivers — verified proposal

Status: implemented and tested on 2026-10-09. Usage: [Championship liveries](CHAMPIONSHIP_LIVERIES.md).
The user hosts multiplayer through AMS2's **Create Lobby** screen.

## What is actually available

The installed AMS2 SDK's `Support/SharedMemory/AMS2_SharedMemoryExampleApp/SharedMemory.h`
declares shared memory version 14 and 158 SharedMemory fields. Paddock mirrors all
158 field names: no omitted SDK field provides a livery ID, skin name or race number.
Per-participant car names and class names identify the model/class, not its paint scheme.
The three newest recording schemas have no livery field. Six existing AMS2
multiplayer logs also yielded no livery/skin/vehicle-ID identity information.
Audit evidence: `diagnostics/livery-identity-audit-20261009.json`.

Paddock's livery editor reads installed catalog IDs/names and can render preview
images. This tells us which liveries exist or are enabled, but does not link a
recorded participant to the livery it actually used. Catalog state today is not
proof of which liveries were enabled for a historical race.

The broad claim that AMS2 never exports a livery ID is too strong. Dedicated-server
participant documentation includes `LiveryId`, and an actual AMS2 server API response
shows it. This is a separate potential integration and has not been tested live here:

- [Dedicated-server participant attributes](https://heavenlysanctuary.com/ServerTypes.pdf)
- [First-hand AMS2 API response](https://forum.reizastudios.com/threads/ams2-dedicated-server-tool-steamcmd-support.11116/page-72)

It does not give Paddock a server API for the user's current in-game lobby. The
documented UDP structures inspected have no explicit livery field either; undocumented
binary/replay inference has not been established and should not be presented as reliable.

## Proposed workflow

1. In championship setup, create persistent AI identities. Assign each identity a
   car model and livery, with its preview: for example AMG GT3 + selected livery
   maps to fictional Chris Lulham. Preserve an independent stable driver key.
2. Enable livery-based AI identities for that championship. On first review of an
   unassigned race, show entrants in finish order, including retirements and
   disconnects. Show original recorded name, model and result alongside the picker.
3. Filter livery choices to the matching car and championship roster. Reuse existing
   preview images with a clear missing-image fallback. The user matches the entrant
   to its observed livery using the game, a saved game replay or a screenshot.
   Paddock's telemetry replay cannot reveal paint information absent from the recording.
4. Save livery facts once for the recording. Apply the championship's livery-to-driver
   mapping to reports, championship results, standings and profiles. Subsequent
   reviews reuse the saved assignments. Provide an Edit assignments action.

## Identity, scoring and preservation requirements

- Store assignments against the recorded entrant, not finishing position. Penalties
  and reclassification must not move Chris's identity to a different car.
- Keep original recorded names available and raw Parquet/events/session files intact.
  Save additional identity metadata separately, with atomic writes and validation.
- Separate recording-level livery facts from championship-level fictional identities.
  The same recording may belong to championships with different fictional rosters.
- Add an explicit human/AI roster role. `SeasonConfig.human_names()` currently
  considers every roster alias human, and standings explicitly exclude `is_ai`
  entrants. Aliasing random AI names to fictional drivers alone would misclassify
  AI and distort human ranks, awards and points. Full-field championship scoring
  must include registered AI while human-only standings continue to exclude them.
- Include assignment/config revisions in derived-analysis cache keys. Editing an
  assignment must refresh affected imported results without erasing corrections.
- Require explicit resolution if two entrants share the same car/livery or one
  fictional driver is assigned twice in a race. Paint alone is not unique in that case.
- Allow unknown/skip-for-now entries; do not invent a livery for a DNF or disconnected
  driver the user cannot identify. Prompt only for unresolved assignments in enabled
  championships, and avoid repeatedly interrupting an already-reviewed recording.
- Capture catalog/preview identity when assignments are saved so later mod scans or
  livery restrictions do not silently change historical championship identity.

## Required implementation verification

Test identity persistence across reopen and restart; per-car picker filtering;
missing images; duplicate liveries; DNFs; changed finish order after penalties;
multiple championship mappings for one recording; AI points and human-only ranks;
correction preservation; refreshed reports/profiles; and unchanged original telemetry.
Dedicated-server auto-identification remains a later optional source, with the
same manual confirmation path for missing or ambiguous data.
