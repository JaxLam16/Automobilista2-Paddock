# Championship drivers from liveries

Paddock can give a persistent fictional identity to an AI car, such as Chris
Lulham in a particular AMG GT3 livery. AMS2 still shows its own generated name;
Paddock uses your fictional name in race reports, replay, standings and profiles.

## Set up a roster

1. In **Livery editor**, scan your installed AMS2 folder. This supplies the car,
   livery names and available preview pictures. A scan does not apply game changes.
2. Open a championship's **Settings**. Keep yourself and your friends under
   **Human friends**, with their in-game names/aliases.
3. Under **Driver cars and liveries**, set **Championship car class** (for example
   **GT3 Gen 0**) to narrow the catalog. **All classes** removes the filter.
   Existing out-of-class selections stay visible; **Show all classes** in an
   individual picker lets you make an exception.
4. Expand a human friend's row to choose their car and livery, or use **Add
   fictional AI driver** to enter a fictional name and choose their paint.
5. Check **Recorded car model** against the exact model name in a recording.
   The input suggests previously recorded names. Mod/catalog names may differ
   from the name AMS2 exports; this field connects the two explicitly.
6. Enable **race livery assignments (including AI identities)**. Select **Full field** scoring if the
   fictional AI should earn championship points, then **Save changes**.

Human car/livery selections are optional, and human aliases/names remain intact.
One roster driver can have one car/livery binding. Two roster drivers
cannot share that binding. You can change bindings later; imported results are
reanalysed and steward corrections are retained.

## Review a race once

When you first open a completed race with an enabled roster, **Assign race
liveries** opens. An unfiled recording can use your sole enabled championship;
if several rosters are available, choose one. A filed recording uses its
championship context. Opening a recording this way does not file it for points.

Expand each entrant row and select the livery that car actually used. Rows show
the original name, recorded model, finish and status, including DNFs and
disconnects. Use AMS2, a game replay or your own screenshots to identify paint.
Paddock's telemetry replay cannot recover paint that AMS2 did not export.
Human roster selections are preselected on the first review when their recorded
model matches. Confirm or change them for this race. A reviewed Unknown remains
unknown; later roster changes do not replace an existing race assignment.

The picker initially uses the configured or matching model. You can explicitly
select the corresponding catalog model when names differ. A note identifies
models without a matching fictional driver; check **Recorded car model** in
Settings if you expected one. Missing preview pictures show a fallback label.

Leave uncertain cars **Unknown / skip for now**, then **Save assignments**.
Unknown entrants keep their recorded names. Saved reviews do not pop up again,
including after restarting. **Review later** leaves the recording unreviewed
and suppresses the dialog for that championship until the next app load.
Use **Edit livery assignments** on the race page to change a saved review.
The button is beside **Watch replay** on a championship's race overview, even
before identities are enabled. If setup is incomplete, it opens instructions
and a shortcut to that championship's Settings.

Duplicate car/livery selections are rejected because paint cannot distinguish
those entrants. Leave ambiguous entries unknown until you can resolve them.
Human friends remain human and keep their names, even when assigned a livery.

## Pictures and replay colors

Selected liveries appear beside drivers in roster summaries, championship
standings/stats, race classification and replay timing entries. Available PNG
previews are saved with selections; missing previews hide gracefully.

Replay car markers, timing bars and comparison traces use a color estimated
from the livery preview, with transparent/background pixels discounted. Under
**Replay marker color**, choose a manual override or **Use estimated livery
color**. Save the roster or race assignments to apply the change. Saved race
colors take precedence over a human roster default. A preview estimate may miss
the main paint color, especially with showroom backgrounds or multicolor designs.
Championship charts retain their driver/team colors.

## Friends, AI and points

- **Full field** awards registered fictional AI points by overall position.
  Unassigned AI still occupy places, but have no persistent championship score.
- **Humans only** computes points by the finishing order among human friends.
  Fictional AI remain AI and cannot take human ranks, head-to-heads or practice awards.
- **Show human friends only** filters the full-field standings without recalculating
  their points or overall standings positions. It also filters the points chart.
  Friends-only controls are available in driver profiles and season tables;
  existing human filters on race pages continue to work.

Livery facts live in `livery_assignments.json` beside the recording. They are
keyed to original entrants, not finishing positions, and include saved catalog
names and preview pictures where available. Penalties and reclassification
cannot swap identities between cars. A fictional AI correction is attached to
its original recorded entrant, so correcting a livery does not erase the penalty.

Fictional names and human/AI roles belong to the championship database. The same
recording can therefore use different fictional rosters in different championships.
Editing a review refreshes championships containing that recording. Keep the
sidecar when copying/zipping a recording; Paddock's recording importer accepts it.
Raw Parquet, event and session files are never rewritten by livery assignment.

For in-game Create Lobby races, the inspected shared-memory SDK and recordings
provide models/classes but no usable livery identity. Dedicated-server livery
integration is a separate future possibility and is not implemented here.
