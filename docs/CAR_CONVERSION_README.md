# Car Conversion

The **Car Conversion** sidebar page brings class reassignment and physics
conversion together. BOP stays available for performance comparison and final
balancing after a conversion.

**This car’s saved setups** provides save/load/export/import for the selected car’s
supported configuration, including installed settings plus its draft, class and
tyre links. Presets can restore earlier settings after further tuning; loading and
importing stage only that car for review. The same library is available on BOP.
See [Individual car setups](BALANCE_OF_PERFORMANCE_README.md#individual-car-setups)
for compatibility checks and complete donor baseline requirements.

## Custom classes for testing

Open **Manage classes** on Car Conversion or Balance of Performance after scanning.
Create **Testing** and choose **GT3 Gen0** under **Use group from**. This saves an
empty class in Paddock; the class appears in the game after adding cars and applying.
Search or filter by source class, check the cars, and choose **Review class changes**
then **Apply class changes** with AMS2 and Content Manager closed. For the Mustang
comparison, choose Ford Mustang GT Racing, Nissan GT-R Nismo GT3 (R35), and BMW M6
GT3. The Nissan identifier is `nis_gtrgt3`, and the BMW identifier is `m6_gt3`.

Reopen **Manage classes**, choose Testing, and check/uncheck cars to swap the grid.
**Remove all** clears the selection; reviewing and applying restores each member's
remembered class, vehicle group and grid grouping. The remembered assignment is
the one present when first added, including any earlier conversion. Transferring a
car between saved custom classes retains that first assignment. Removing members
keeps their current tuning; it does not restore old physics files. **Reset selection**
discards unapplied membership choices. **Undo last apply** restores the last applied
transaction and its membership state.

Classes are saved separately per game installation in
`balance_of_performance/installs/<install>/class_sets.json`. Original assignments
are recorded in the ordinary backup journals. Keep both the catalog and backups.
Only CRD class properties change; no donor transfer is involved. Stock physics
remains eligible for BOP references after a class-only move. If another tool changes
a managed assignment or its copies disagree, the manager explains the conflict
and blocks that car. Reviews also block text that cannot fit the package's existing
CRD allocation; they never relocate class streams. Verify the new class and selected
cars in AMS2 before recording the comparison session.

## Complete donor baseline — experimental; native relocation blocked

The Mustang/Nissan complete donor experiment caused AMS2 event loading and car
menu hangs. Native package relocation with section metadata remains blocked.
Capturing or inspecting a donor baseline does not make its complete transfer safe to apply.
Use supported individual tuning or selected upgrade drafts and validate each
change in game. They do not establish a complete GT3 conversion.

Donor source selection can inspect validated readable CDF/EDF/GDF/VDFM sources,
including when an additional archive copy is unreadable. If readable versions
differ, explicitly choose the source version. Paths and hashes identify what was
captured; the picker cannot determine which loose/packed copy AMS2 loads.
Missing or inconsistent essential linked components block capture. Changed pinned
components block later use. Existing saved baseline identities are preserved.

Captured files live under
`balance_of_performance/installs/<install>/donor_baselines/`. Keep them with the
editor's backups. Exported profiles reference baseline identity and offsets;
they do not distribute the donor's game files. Complete transfer is a development
experiment that has not been validated as an alpha workflow.

## Selected upgrade packages (advanced)

Choose **Selected upgrade packages (advanced)** under **Starting point** for the
earlier modular conversion, which retains the candidate's engine and geometry.
Its qualified class-median matching is separate from a complete donor copy.

1. Scan the installed game, then choose the car to convert.
2. Choose its **Target class**, or **Create a class…** with class, group and grid
   identifiers. Leave **Move car to…** selected to include that move in the same
   reviewed transaction. Turn it off for a physics-only draft.
3. Choose an installed **Reference car** for the tyre/aero/suspension packages.
   The initial suggestion comes from the target class, favoring a similar rear
   weight share among cars with decoded wing data. You can choose any other
   installed car, including when creating a new class.
4. Select **Target class median** or **Reference car** as the mass/power target.
   **Performance matching** interpolates mass and power per tonne only: 100%
   reaches the qualified decoded target within encoding precision. Automatic
   class targets exclude cars with active Paddock changes; power additionally
   excludes turbo/boost curves and unknown boost status. The power-reference
   panel shows the cars used and the reasons for exclusions. It is not a lap-time
   match. Selected tyre/aero models use the reference values in full.
5. Choose the conversion modules, then **Build conversion draft**. Each module
   reports Ready, Already matches or Skipped, with a reason. Incomplete modules
   are skipped as a whole; they do not quietly apply half a diffuser model.
6. Fine-tune the draft in **Manual tuning** if desired. Review the exact parameter
   and class changes, close AMS2 and Rocky’s Content Manager, then apply.

**Stage class change only** is also on this page. A custom class has no median,
so use Reference car performance or set values manually. Existing class-change
profiles/drafts are routed here; no game writes occur until review and apply.

## Conversion modules

- **Mass / power per tonne:** class or reference matching through the car’s own
  chassis multiplier. Engine torque shape, rev limit and gearing are retained.
- **Tyres:** the installed reference tyre-model link. It must fit the supported
  VDFM slot and be checked in game; a matching name does not establish grip.
- **Wings:** decoded front/rear lift and drag polynomials, adjustment ranges,
  defaults and supported height/sideways responses from one reference car.
- **Underbody and body aero:** reference diffuser base, front-height/rake
  response, limits/stall/sideways response and body drag/height/rake settings.
  Aero force positions and geometry retain the candidate car’s layout.
- **Springs/dampers:** scale each candidate spring and damper range so its default
  range × multiplier targets the reference rate scaled by the candidate/reference
  static corner load ratio. Candidate multipliers, setting indexes, range counts
  and geometry are retained. This approximates a comparable suspension response;
  pushrod geometry, motion ratios, bump stops and nonlinear effects need testing.
- **Anti-roll bars (optional, initially off):** for spring-based bars, scale each
  candidate range’s base and step to match reference default rate per static axle
  load. Candidate settings, counts and bar mode stay in place. Diameter-based or
  incomplete packages are skipped as a whole. This is an approximation and does
  not establish total roll stiffness or validate a performance upgrade.
- **Ride height:** reference ranges and defaults for each corner.
- **Brakes:** reference total torque per kg, retaining the candidate front/rear
  torque relationship. Fade/thermal behavior is not homologated automatically.
- **Inertia:** original candidate inertia × proposed mass / original mass. The
  earliest still-applied chassis backup supplies the baseline when available,
  which also repairs previous mass-only BOP changes. Repeated conversion does
  not compound this scaling. The baseline mass can be entered manually for an
  externally modified car; use the mass corresponding to the baseline inertia.

Each module requires decoded candidate/reference fields and writable candidate
physics. Read-only references can still supply decoded values. Unsupported
modules are clearly reported. The review can also reject insufficient package
space before any game files are replaced.

**Handling defaults and retained hardware** compares bar rates, ride heights,
bump/rebound coordinates and supported stop coefficients with the selected
donor. Coordinates are not available droop from the current ride height. Travel
limits, bump stops, suspension geometry and differential settings retain the
candidate’s values; they are not part of the automatic spring/damper package.
Unsupported progression encodings remain unavailable rather than becoming zero.
Changing mass afterward can require rebuilding springs/dampers, bars and inertia
for the new mass. Select those modules alone to keep mass, power and aero as set.

Automatic power retains the candidate’s torque curve, but is still a proxy.
Restrictors and engine-specific modifiers are not modelled. Turbo candidates or
turbo reference cars skip automatic power matching; manual multiplier tuning is
available. Profiles and transaction logs retain the target sources and their
fingerprints, and review guards all source files actually used by those targets.

## Test the result

These edits change physics without creating wing, splitter or body meshes.
Native section-table relocation is blocked. For modular conversion, test one
module at a time. Repeat driver, fuel, tyres,
weather and garage setup; validate player and AI behaviour separately. Use BOP
and Recorded tests afterward to balance the car across multiple tracks.

Both pages share full-file backups, profiles, stale-file checks and undo. Undo
restores the latest apply from either page. Existing recordings and league data
are kept separately from the alpha executable and its bundled dependencies.
