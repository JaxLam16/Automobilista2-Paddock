# Balance of Performance

**Balance of Performance** compares installed class values and stages performance
adjustments. **Car Conversion** owns conversion packages and individual class drafts;
see CAR_CONVERSION_README.md. Existing race analysis, recordings, championships,
engineer and livery tools keep their behavior and launcher.

## Use

1. Scan your AMS2 installation folder and select a car.
2. Choose a **Comparison class**. Its median excludes the selected car.
3. **Adjustment draft** moves selected mass, power-per-tonne, wing proxy, body
   drag and brake torque toward the automatic reference median. Cars modified by
   active Paddock transactions are excluded; incomplete turbo/boost power proxies
   and unknown boost status are excluded from the power target. Raw comparison
   rows still show all installed cars. Expand **Automatic power reference** to
   see the actual target sources. The draft does not reassign the car’s class.
4. **Percentage tuning** adjusts power, mass, wing downforce, body/wing drag,
   brake torque, springs, damping, anti-roll bars and CG height together by
   category. Use the **−0.25 / +0.25** buttons or type a signed percentage and
   press Enter (or leave the field). The supported range is −50% to +50%.
   **Manual tuning** edits supported parameters, tyre references and positive
   torque maps. Draft metrics and curves update as you edit.
5. Stage other cars if needed, then **Review changes**. Close AMS2 and Rocky’s
   Content Manager before **Apply changes**. Full affected files are backed up.
6. **Undo last apply** restores the latest physics or class transaction from either page.
   It stops if another tool has changed those files since the apply.

Both pages use the same saved league profile format and transaction history.
Profiles containing class changes or full donor transfers open on Car Conversion. Legacy class drafts
are moved there automatically. Profiles require matching starting definitions
and physics files; geometry and livery assets are excluded from their fingerprint.

**Manage classes** on either page creates saved custom grids such as Testing.
Search/filter the installed cars, check the members and review/apply the batch.
Uncheck members or use **Remove all**, then review/apply to return them to their
remembered original classes while retaining current tuning. Class-only moves keep
stock physics eligible as automatic references. Details are in
CAR_CONVERSION_README.md under Custom classes for testing.

## Metrics and limits

Power is a capped map-1 torque × RPM × chassis-multiplier proxy. Boost, restrictors,
driveline loss and special engine modifiers are not simulated. The wing proxy
uses default wing settings and excludes diffuser/body/ride-height effects. Body
base drag is not total drag, brake torque is not stopping distance, and turning
inertia is not steady-state cornering grip.

Spring proxies are default ranges × multipliers; geometry is not simulated.
Tyre references choose an existing installed model; tyre grip curves are not
extracted. Use recorded tests with consistent drivers, fuel, tyres, setups and
conditions, and validate player and AI behavior separately.

Automatic power matching uses qualified nonboosted curve proxies. It skips turbo
candidates or a class with no eligible power references rather than matching an
incomplete boost estimate. Restrictors still affect real output, so the qualified
median is not a verified horsepower target. Manual power tuning remains available.
Target source fingerprints and exclusions are retained in profiles and transaction
logs; source files used by automatic targets are guarded between review and apply.

Spring-based anti-roll-bar defaults, travel coordinates and supported bump-stop
coefficients are available in the comparison picker. Their units and caveats are
shown alongside them. Actual garage changes are not recovered from those defaults.

The decoder supports documented ShCB 1/2 CDF/EDF/GDF encodings and post-1.4 VDFM
links. Supported byte/int CDF real-valued properties can widen to documented
float encodings. This updates the ShCB length registers; compressed CDF streams
must still fit their original BFF allocation, and their uncompressed size is
updated in the index. Normal parameter edits keep their original allocation.
Complete donor transfer is currently blocked following the Mustang event/menu
hang. Saved baselines and source selection remain available for diagnosis, but
donor payload relocation cannot be applied. Unsupported CRC/section tables,
flags/alignment and Oodle/LZX stop before apply. Unknown
parameter encodings, inconsistent copies, shared candidate core models and
payload-free zero defaults remain unsupported for manual writing.

Discovered matching loose/packed copies are synchronized. Review rejects stale
files and insufficient package space before applying. DDS, meshes and livery
configuration are excluded. Reinstallation or game updates can replace edits;
rescan afterward and use matching mod/profile versions on league machines.

State, profiles and numbered full-file game backups live in
`balance_of_performance/`. Keep the backups and transaction journals.

## Percentage tuning

Each category scales its relevant values from the current draft when that category
is first adjusted. Changing +1% to +2% gives a total +2%; repeated changes do not
compound. **Reset to 0%** restores that category's starting values while keeping
other edits. After applying, the installed values become the next draft's start.
An individual manual edit clears its category's percentage label and keeps the
current values, which become the start of any further percentage adjustment.
Percentage values and baselines are retained in saved profiles and apply journals.

Wing downforce scales front and rear lift polynomials together, keeping their
balance and drag. Zero coefficients remain zero. Springs and damping scale their
four multipliers once; setup ranges, settings and travel remain as set. Anti-roll
bars scale both spring-based range bases and steps without changing adjustment
counts. Mass and brake torque round to their stored whole units. The card explains
what each category changes. A category is disabled when its complete required
values cannot be decoded or safely edited. Tyre grip curves are not decoded.

These are ordinary parameter drafts: **Review changes** shows each value and checks
package space before **Apply changes** makes full-file backups. **Undo last apply**
restores those files. BOP API responses preserve small coefficients at full precision.
Finish recording before restarting Paddock to load the updated controls, and close
AMS2 and Content Manager before applying a reviewed draft.

Percentages apply to the current draft baseline and describe parameter changes,
not guaranteed lap time changes. Complete donor transfer remains blocked after
an event/menu hang; percentage tuning does not enable donor relocation.

## Individual car setups

After scanning, select a car and use **This car’s saved setups** on either BOP or
Car Conversion:

- **Save car setup** names a snapshot of all supported private numeric settings,
  class/group/grid assignment and tyre-model reference. It includes that car’s
  staged changes and works with no draft, so you can save an already applied setup.
- Choose a saved setup, then **Load car setup** to replace only this car’s draft.
  Other cars’ staged changes remain. An identical setup produces no game changes.
  A class conversion opened from BOP moves this car’s draft to Car Conversion.
- **Export car setup** downloads the selected saved setup as JSON. **Import car
  setup** validates a JSON file, saves a new local copy, and stages its one car.
  Select the matching car first. A legacy profile containing exactly one car can
  also be imported here; multi-car profiles use the league profile importer.
- **Review changes**, then **Apply changes** with AMS2 and Content Manager closed.
  Review still includes any other cars with staged edits. Full-file backups and
  **Undo last apply** use the existing transaction flow.

Presets can restore earlier numeric settings, class assignments and tyre links
after ordinary tuning applies. They require the same car model and compatible
physics version; unknown binary data, component bindings and engine RPM axes are
checked. A readable tyre model is hash-pinned, including an installed original
model no longer used by another car. Changed or missing pinned dependencies block
load/apply. Staged automatic conversion references retain their fingerprint checks.
Imported setups never copy game binaries or overwrite another saved setup.

These presets cover the editor’s supported values, not garage setups or opaque
physics components. Complete donor drafts retain their local baseline identity and
starting fingerprint; another installation needs the matching captured baseline.
The complete donor relocation block remains in force. Ordinary snapshots of an
applied configuration do not reconstruct an entire donor transfer.

Saved setups live under `balance_of_performance/car_setups/`. Existing league
profiles, backups, recordings and championships are retained. Finish recording
before restarting Paddock to load the new backend and controls.

## Sources and validation

Format facts: [JDougNY/GvsE chassis translation](https://mikevapour.github.io/ams2-modding-docs/chassis/),
[chassis parameter explanation](https://mikevapour.github.io/ams2-modding-docs/chassis2/),
[gearbox translation](https://mikevapour.github.io/ams2-modding-docs/gearbox/),
[VDFM translation](https://mikevapour.github.io/ams2-modding-docs/vehicles/).
The decoder/writer is independently implemented and uses the app’s existing
BFF index/hash/encryption routines and retained MIT attribution.
Relocation uses the registers in [PCarsTools PakFileHeader.cs](https://github.com/Nenkai/PCarsTools/blob/master/PCarsTools/Pak/PakFileHeader.cs)
and [PAK.bt](https://github.com/Nenkai/PCarsTools/blob/master/BinaryTemplates/PAK.bt).

The alpha release has an adjacent verification report. Development tests cover
package edits, numeric widening, baseline inertia, guard failures, module
coverage, profiles and byte-exact undo. Supplied Camaro/Ferrari files are used
only for local verification and are not redistributed in the alpha.
AMS2 itself must be tested on your Windows installation.
