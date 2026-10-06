# ams2season

Record AMS2 multiplayer races (friends + AI) from shared memory, then turn them into championship standings and debrief stats: passes, battles, lap-1 gains, consistency, pace vs the AI, and head-to-heads.

The recorder stores raw frames for every car at 20 Hz. All stats are computed afterwards, so any stat you add mid-season can be backfilled over every race already recorded.

## The app

Double-click **`AMS2 Season.bat`**. The first run installs what it needs. Then go to **Settings → Create desktop shortcut**, and from then on it's a normal app with its own icon and no console window.

The app runs everything in one place:

- **Recorder.** It runs in the background, and the light in the sidebar shows what it's doing: amber means waiting for AMS2, green means connected, pulsing red means recording. Closing the window stops it cleanly.
- **Home.** Shows your latest race, races not yet filed, and championship leaders. When a race finishes you get a prompt to file it.
- **Championships.** Create as many as you like. Each one has five tabs:
  - **Standings**, with a humans-only / full-field comparison and a points-progression chart
  - **Rounds**, listing every filed race
  - **Drivers**, with season stats and head-to-head tables
  - **Penalties**, for stewarding decisions, which update the standings immediately
  - **Settings**, for the roster, points system and AI rules, with no text files involved. Names seen in several races are suggested as drivers, since AI names change every race.
- **Race view.** The full interactive race report for any recording, with penalties for that round.
- **Replay.** "Watch replay" animates the whole race from the recorded position and heading of every car.
  - **Cars.** GT3 cars with an icon are drawn as top-down pictures of the actual car, at its real length, with the bodywork tinted in the driver's colour (AI cars stay grey). 14 GT3 icons are built in. Any other car is drawn as a generic silhouette of its body type. See **Car icons** below.
  - **Zoom and pan.** Scroll to zoom down to individual cars, drag to pan, double-click or "Fit" to reset. Full screen covers the whole replay.
  - **Compare drivers.** Click drivers in the timing tower, or their cars, to add or remove them from the comparison. With one driver, the camera follows them. With several, it keeps the whole group in frame and the telemetry compares everyone in it, including who braked latest into each corner. The eye button hides a car; "Show" offers All, None, Humans or Compared.
  - **View options.** One menu holds the map settings: trails, pass circles, pass captions, the list of passes, name labels, raw positions, and mirroring.
  - **Trails.** Each focused car leaves a 500 m trail coloured by what the driver was doing: deep red under heavy braking, amber when lifting or coasting, green on the throttle.
  - **Pass circles.** Set them to on, after lap 1, or off. The choice is remembered.
  - **Show or hide cars.** Tick boxes in the timing tower, or use "Show all", "Humans only" or "Only followed".
  - **Telemetry.** For the followed car: speed, a braking/throttle/coasting readout, and a speed trace for the current lap with braking and throttle zones and braking points marked, compared against the car ahead, the car behind, or anyone you choose. A note under it gives the braking-point difference into the last corner and each car's minimum corner speed. For the driver whose PC ran the recorder, real throttle, brake and gear are shown; for everyone else, braking and throttle are worked out from speed changes.
  - **Playback.** A live timing tower with real intervals; a scrubber with laps and every pass marked; 0.25x to 16x speed; captions as passes happen.
  - **Keyboard.** Space to play or pause, arrow keys to skip 10 s (2 s with Shift), + and - to zoom, keys 1 to 7 for speed.
  - **Watch buttons.** Every "Watch" button in a race report jumps the replay to just before that moment.
- **Qualifying analysis.** Click a qualifying session in Recordings, or "Qualifying" on a race, to compare everyone's best lap.
  - **Same start time.** All best laps start together, so you watch who pulls ahead and where.
  - **Same track position.** Every car is placed at the same point on the lap, so racing lines can be compared directly. Zoom in and turn on "Racing lines".
  - **Markers.** Braking points (triangles) and back-on-throttle points (circles) for every compared lap.
  - **Comparing drivers.** Click names to add or remove them, and tick boxes to show or hide cars. "Compare to" sets the reference lap (pole by default).
  - **Telemetry.** Speed, time delta to the reference along the lap, pedals and steering (with a wheel graphic), and braking/throttle bars.
  - **Debrief.** Where time was gained or lost, corner by corner. Each line gives the time difference, plus how much earlier or later the driver braked, the speed difference at the apex, and how much sooner or later they got back on the throttle. Click a corner to jump there.
  - **Real inputs.** Pedals and steering are only shared for the car on the PC that recorded. If friends also ran the recorder, put their recording folders into `recordings/` and they're merged automatically, so everyone who recorded gets real inputs. Steering is shown as a share of full lock, because the game doesn't share steering angle in degrees.
- **Track edges.** The game doesn't share track edges, so they come from one of two sources:
  - **Mapped (exact).** For the car on the recording PC, AMS2 reports the surface under each wheel. Open **Track maps**, click Start mapping, and drive one lap with your left wheels on the white line and one with your right wheels on it. Every time a wheel crosses between asphalt and kerb or grass, that's the edge. Save it, and that layout is mapped for good. Replays and qualifying use the map automatically. You can map in several goes; each save adds to the map. Your normal races also add edge points wherever your wheels touch a kerb, and in qualifying, friends' merged recordings add theirs.
  - **Modelled (fallback).** Every lap that looks normal is averaged into one racing line, with spins, offs and odd lines dropped. At each corner's slowest point, the inside edge goes where the tightest normal laps put their wheels; at turn-in and exit, the outside edge goes where the widest ones ran. The road eases smoothly between those points at a typical 12 m width, adjustable per track under View options or on the Track maps page, and never cuts through a normal lap. A partly mapped track uses its mapped sections and models the rest, and the model takes its width from the mapped parts.

  View options in the replay and qualifying views say which source each map is using.
- **Qualifying breakdown.** The "Breakdown" tab on any qualifying session has:
  - the classification, with the session's fastest sectors in purple, the ideal lap, and each driver's time left on the table against their own best sectors
  - qualifying talking points
  - sector-by-sector gap charts
  - a corner-by-corner table of minimum speeds and braking points
  - a chart of everyone's lap times through the session
  - the grid as it would have been on best sectors
  - every lap of every driver
- **Practice.** Open **Practice**, pick objectives, then drive a Practice session in AMS2. The app follows your laps live and ticks the objectives off. Lap times and validity come from the game, braking points from your brake pedal, and lock-ups and wheelspin from wheel speed against car speed. Each objective's numbers are adjustable:
  - **Consistency run:** N clean laps in a row within X% of your personal best. Personal bests are per car and layout, looked up from every earlier recording.
  - **Beat the target:** a clean lap X s under your personal best.
  - **Clean streak:** N clean laps in a row.
  - **Braking markers:** N laps in a row with every braking point within X m of your average.
  - **Smooth operator:** N laps in a row without a lock-up or wheelspin.
  - **Sector focus:** beat your best time in one sector of the session by X s.

  Out laps and pit laps don't count. Practice sessions are now recorded, and "End session" links straight to their analysis.
- **Brake & throttle.** Available for any recording with pedal inputs: practice, qualifying, or a race recorded on your PC. Friends' recordings of the same session are merged in, so you can compare drivers.
  - **Per corner:** every lap's brake and throttle traces lined up by distance to the apex, showing each lap, the middle half, your average and your fastest lap.
  - **Per lap:** braking point, peak pressure, build-up, trail length, minimum speed, throttle pickup, flat-out point and throttle hesitations.
  - **Scores:** a consistency score out of 100 per corner, an overall score, the corner to work on, and tips.
  - **Tyres:** wear per lap and per wheel, remaining tread, temperatures, front/rear balance, and lock-ups and wheelspin. These are found by comparing each wheel's rotation with the car's speed, with each wheel's radius learned from steady driving.
- **Tyre care.** The championship Drivers tab ranks everyone who recorded their own races. Wear is compared with the others in the same race, so different cars and wear settings don't skew it, alongside lock-ups and wheelspin per lap.
- **Teams.** In championship Settings, add teams with a name, a colour (from the swatches or any custom colour) and an icon tinted in that colour, then assign drivers. Each driver can be in one team. Team points can count every driver or the best 1, 2 or 3 per race. Standings get a Teams table, the Drivers tab gets teammate battles, team icons appear beside driver names, and you can colour drivers in shades of their team colour across charts and replays.
- **Where the passes happened.** The race report's map opens as a heat map: the track is coloured by how many passes happened along it, from pale yellow to deep red, with the busiest stretches labelled. "Every pass" switches to the individual passes, coloured by kind.
- **Following a car.** The followed car gets a white outline traced just inside its edge, so its size doesn't change. In qualifying, use the follow button on a driver's row, the Follow picker, or double-click the car.
- **Precise scrubbing.** In the race replay and qualifying, drag across the telemetry chart to move through the lap metre by metre.
- **Replay camera.** Follow a car from the "Follow" picker, in the race replay, qualifying and practice. While following, right-click and drag to move the camera around the car. It stays locked on as the car drives, until you hit "Re-centre". Left-drag pans freely, which ends the follow.
- **Race replay markers.** Compared cars show where they started braking (triangles) and got back on the throttle (rings), only along their trail, so the markers follow each car round. Switch them off under View options.
- **Practice replay.** "Replay your laps", on a practice session's Brake & throttle page or after ending a practice, replays your clean laps against each other in the qualifying view, against your fastest by default. You get the same time and track-position modes, racing lines, markers, telemetry and debrief.
- **Driving style.** Every car in every race gets three scores, worked out from speed and position:
  - **Braking points:** how much the spot where the driver starts braking moves from lap to lap at each corner (100 = the same spot every lap).
  - **Throttle pickup:** the same for getting back on the power after the apex.
  - **Track usage:** how close the car gets to the inside edge at the apex and the outside edge at turn-in and exit (100 = edge to edge), measured against the mapped edges if the track is mapped, otherwise the modelled ones.

  They appear in the race report and, averaged over the season, on the championship's Drivers tab. Two awards come from them: "Same marker every lap" and "Every inch of road".
- **Livery editor** (sidebar → Livery editor): choose which liveries appear in AMS2 for each car, so your league runs the liveries you want.
  - **Scan and choose:** point it at your Automobilista 2 folder and scan (reading only). Toggle liveries per car, at least one enabled per car, with search, class filters and enable/disable all.
  - **Apply and undo:** apply when AMS2 is closed. Every apply backs up the files it changes first, writes them atomically, rolls back if anything fails, and can be undone byte for byte.
  - **Presets:** save, export and import presets to share the league's selection.
  - **Recovery:** liveries hidden before you had the editor can be recovered from an original backup.

  Full guide in LIVERY_EDITOR_README.md; third-party notices in ams2season/LIVERY_EDITOR_NOTICES.txt. Check it on your PC first: AMS2 itself, Windows file locking and real mod packages can only be tested there.
- **Race review pages.** Every race page (Report, Replay, Driving style, Brake & throttle, Tyres, Pace, Overtaking, Errors, Cars) has the same tab bar, so each one is a click from every other, with the championship context kept.
- **Driving style page.** Braking points, throttle pickup, track usage, distance from the apex and racing corners for every driver, with the racing-corners switch (moved off the race report).
- **Awards on their pages.** Every award lives on the page it's about: overtaking awards on Overtaking, mistakes on Errors, pace on Pace, braking and throttle on Driving style, cars on Cars. The race story (results, positions, retirements) stays on the report, and the report's full award list links each award to its page. New awards from the newer analyses:
  - **Errors:** Error-free, Spin doctor, "Late, later, latest" (overshooting by braking too late), Scenic route (offs), Most expensive mistake.
  - **Overtaking:** Clinical (best pass rate), Immovable (best hold rate), Opportunist (places from others' mistakes).
  - **Pace:** Strong finish, Traffic tamer.
  - **Driving style:** Smooth on the power, Wheel to wheel, Apex hunter.

  Each needs enough evidence to be given (e.g. at least 4 laps spent attacking for Clinical).
- **Sharing recordings with friends.** Send your recording folder (zip it for Discord). Your friend drops the folder or zip anywhere in the app, or uses Import a zip / Import a folder on the Recordings page. Only the recording files are imported (a malicious zip can't write anywhere else), importing twice is recognised, and imported recordings show "from Mason". If you were both in the same session, even with your clocks in different time zones, their car shows beside yours on Brake & throttle, so you can compare brake and throttle traces corner by corner.
- **Practice points.** Practice sessions filed to a championship round (Add to championship, like a race) award a small number of points, so turning up to practice counts even if racing isn't your thing.
  - **The awards:** Iron man (most valid laps in a row), Mileage (most laps), Metronome (most consistent laps, at least 5 within 3% of their best), Every inch (best track usage, measured as in race reports), Most improved (first flying lap to best lap) and Clean sheet (fewest invalid laps, at least 5 laps). Fastest lap is available but off by default.
  - **Scoring:** each award goes to the best human, and ties share it. Points per award (default 1) and which awards count are set in the championship's settings; changing them re-awards every filed practice.
  - **Where they show:** practice points have their own Practice column in the standings and count towards the total. The Rounds tab lists each practice's awards.
- **Practice page.** "Pick my goals" sets your clean-streak and consistency goals just beyond your best so far in the same car at the same track, and says why. The page explains the practice awards, and the end-of-session summary offers "Add to championship".
- **Race engineer** (sidebar → Race engineer): your engineering team for practice, one session per car and track.
  - **How it works:** AMS2 doesn't share your setup with other programs, so the engineer starts from the car's default setup (turn Symmetrical Setup off in AMS2) and tracks it in ticks through the changes you confirm.
  - **Each run:** turn on live engineering and drive. Each run is analysed when you return to the garage or pit box, or you can analyse a practice session you already recorded.
  - **What it measures:**
    - corner balance (steering needed per unit of curvature, corner by corner), the fast-corner understeer gradient, and countersteer (oversteer) at entry, mid-corner, exit and on lift
    - hot pressures and inside, middle and outside tyre temperatures
    - ride height, bottoming and hard travel limits, wheel lift
    - top-gear RPM against the limiter
    - lock-ups, ABS intervention and wheelspin
    - water, oil and brake temperatures
    - fuel per lap
  - **Recommendations:** in ticks ("Soften by 2 ticks"), each with Done, Maxed out, Not on this car or Skip. Directions are worded so they can't be misread ("More negative camber", "Less negative camber"), and every card says what the number on AMS2's setup screen does ("the number goes further below zero, e.g. -3.5° → -3.7°"; "the ratio number goes up, e.g. 3.525 → 3.600 (higher ratio = shorter gearing)"). Where the numbering differs between cars (TC, ABS, engine braking), it says so and asks you to check the garage description. Simple shows just the ticks; Advanced shows why, the evidence, a run review, and corner-by-corner balance against the last run.
  - **Your own changes:** settings you change yourself can be added so the setup is always tracked.
  - **Categories:** nine status categories (pit strategy, gearing, ground clearance, tyre contact, chassis balance, aero balance, downforce level, braking & traction, thermals & reliability) go from red through orange and yellow to green (dialled in) and blue (two runs with evidence, nothing left to change).
  - **Run plans:** a full-tank run, then low fuel (giving what the fuel load costs per 10 L), then confirmation runs.
  - **Race settings and race plan:** in Session setup, set the race length (time or laps), fuel usage and tyre wear multipliers (1 = real, 0 = off), mandatory pit stops and time acceleration. If practice ran at different multipliers, enter those too and the engineer converts what it measured. The race plan works out:
    - **Laps and fuel** from your measured fuel use.
    - **Stops:** the most of the mandatory stops, what the fuel tank needs and what your measured tyre wear needs (a change is planned before the worst tyre is 70% worn).
    - **Each stint:** its laps, fuel to start with or add, whether to change tyres, and how worn that set will be by the end.

    Time acceleration doesn't change fuel or wear (the race length is real time), but a long accelerated race gets a warning that light, track temperature and tyre pressures will drift.
  - **Category breakdowns:** click any category tile to see why it has its colour: every measurement against its target, how confident the engineer is and why (flying laps, samples, whether earlier runs agree), the key figure across your runs, and the recommendations it's driving.
  - **How did the car feel? (optional, after each run):**
    - **What it asks:** each of brakes, turn-in, mid-corner and exit for slow, medium and fast corners, rated from big understeer to big oversteer. Also how it is on throttle (pushes on power to lots of wheelspin), how it rides kerbs (harsh, fine, soft or bottoming), and notes.
    - **How answers become changes:** slow and medium corners use mechanical grip. The two anti-roll bars are one balance axis, so understeer and oversteer answers net out before a bar is chosen, and a tie is reported as mixed feel. Exits on power use the diff and TC. Fast corners use the wings, braking uses bias, and kerbs use fast bump or ride height.
    - **Feel and data together:** where your feel matches the data, the recommendation gets more confident ("matches your feel"). Where the data says the opposite, the data wins and your feel is noted ("you felt the opposite"). Things only you felt get their own recommendation ("from your feel"), at low confidence unless some telemetry supports it, and only one remedy per symptom.
  - **How you like the car (optional):** sliders from understeer to oversteer and from safe to aggressive. They move what the engineer aims for (balance at speed, how much sliding is tolerated, how close to the ground it runs the car, how much ABS intervention is fine), never the evidence. Changing them re-evaluates your latest run.
  - **Race and qualifying setups:** the recommendations build the race setup. The Qualifying setup tab lists changes on top of it, each from your own measurements: just enough fuel, higher cold pressures so the tyres are up to pressure for the timed lap, less cooling where the temperatures allow, and a step less TC if the rear isn't stepping out.
  - **Learning:** after each change, it measures what one tick did on your car and uses that. An effect too small to be plausible isn't learned: it's flagged ("check the change went in"). Brake bias, TC and ABS are read from the game, so it can tell when one of those changes didn't go in.
- **Racing corners in braking and throttle consistency.** Your markers move for good reasons when you're fighting another car: following someone in, braking on a defensive line, lapping a backmarker. A pass through a corner counts as racing when another car was within 1 s ahead or 0.7 s behind at the braking point or the apex (on any lap; cars in the pits don't count). Racing corners can count:
  - **Equal weight:** like any other corner.
  - **Less weight:** at a quarter (the default).
  - **Excluded:** left out entirely, unless a corner would be left with fewer than 3 laps, in which case every lap counts there and the page says so.

  The Brake & throttle page has a switch to see all three instantly, with racing laps marked in each corner's lap table. The race report's Driving style table has the same switch and shows each driver's share of racing corners. The choice in Settings sets what race reports, season stats and driver profiles use.
- **Sorting:** click any column heading, in any table in the app or the race report, to sort by it; click again to reverse. Lap times, percentages, positions and turn names sort properly (T2 before T10), blanks go last, and reference rows like "Whole field" stay on top.
- **Driver profiles and F1 legends** (championship → Drivers):
  - **Your profile:** each of you is measured across every race in the championship on twelve dimensions, each scored 0-100 (about 50 is typical): qualifying, race pace, consistency, braking precision, throttle control, track usage, overtaking, defending, starts, clean driving, tyre management and late-race pace.
  - **The legends:** your profile is matched against 20 F1 legends, from Fangio to Norris. They aren't measured: there's no telemetry for them, so each has a fingerprint of their well-known strengths, from 0 to 10 on the same dimensions.
  - **How matching works:** it compares the shape of two styles (what stands out for you against your own average, against what stood out for them), so a club racer can match Prost without Prost's pace.
  - **What you see:** your best match with a radar chart, why you match (shared strengths and lower priorities, and where you differ most), a picker to compare with any legend, every measurement behind your scores, and every legend's fingerprint.
- **Errors page** (from the race view): every driver's mistakes.
  - **Detection:** every corner on every lap is compared with that driver's own typical time there. Losing more than half a second is an error, unless they were stuck right behind another car.
  - **Kinds:** spin (speed collapsed), off track (lap invalidated there), braked too late (braking started well after their usual point and the corner was slower), or slow corner.
  - **Cost:** each error shows its time lost and the positions lost in the seconds after, with a "Watch" link into the replay.
  - **Summaries:** per driver (counts, time lost, positions lost, error-free laps, worst turn), on a map and per turn.
- **Overtaking page** (from the race view): the pass heat map (switchable to every pass) and the pass log, both moved off the race report, with a driver focus. It also rates every driver:
  - **Pass rate:** laps spent attacking (within 1 s of the car ahead, or with a pass) that ended in a pass.
  - **Hold rate:** laps spent defending (a car within 1 s behind, or being passed) that kept the place.
  - **Other columns:** lap 1, net places, gifted passes counted separately, favourite overtaking spot and weak spot.
- **Brake & throttle** (formerly "Brake & throttle") is now only about pedals. All tyre data, including lock-ups and wheelspin, is on the Tyres page.
- **Tyres page** (from the race view, Brake & throttle, or after a practice): the recording car's tyres in depth.
  - **What's recorded:** for every tyre, the surface temperature across the tread (inside, middle and outside), the tread, layer, carcass, rim and internal air temperatures, pressure, wear, brake temperature, ride height and suspension travel. Recordings made before this update only have the basics, or no tyre data at all.
  - **At a glance:** a top-down car with each tyre split into inside, middle and outside zones, coloured against your operating window (blue cold, green in the window, red hot), with time in the window, hot pressure, wear, and front/rear and left/right balance.
  - **Talking points** pull out the main findings, saying a shared issue once for all the tyres it affects.
  - **Across the tread:** each tyre's profile and its setup hints. A centre hotter than the shoulders means over-inflation, shoulders hotter means under-inflation. The inside should run a few degrees hotter than the outside with negative camber. Each tyre's character is stable, lively or peaky, by how much the surface swings within a lap.
  - **Temperatures through the session:** every layer, surface zones down to internal air, for any tyre, against the window, with pressure and brake charts below.
  - **Warm-up:** from the start and every pit exit, how long (seconds and laps) until each tyre's rolling 20-second average reached the window.
  - **Pressures:** cold, hot, the build-up, time in the hot-pressure window, and how much to change the cold pressure.
  - **Where the heat goes:** the track coloured by any tyre's temperature, every tyre's peak in each turn, the hardest-worked tyre per turn, and overheating spots.
  - **Lap by lap:** per-lap temperatures, pressures and wear.
  - **Lap time against temperature:** shows the temperature band of your quickest laps.
  - **Wear, stints, brakes and ride height:** wear per lap and laps until 50% worn, stints, brake peaks and time over 800 °C, typical and lowest ride height, and where the car bottomed out.
  - **Operating window:** set per car (surface temperature and hot pressure); the defaults are generic GT values.
- **Pace page** (from the race view): three analyses.
  - **Race against qualifying:** each driver's qualifying best against their race best and typical race lap. A typical lap is the median of representative laps: no lap 1, pit or invalid laps, nothing over 107% of their best.
  - **Pace through the race:** a chart of every human's laps with a rolling 3-lap average against the field's median lap, and a table of each third of the race plus the trend in seconds per lap.
  - **Clean air and traffic:** each lap is classed by the gap to the car directly ahead at the line, at both ends of the lap: clean air (over 2 s both times) or traffic (under 1.5 s both times). The table shows what traffic cost each driver.
- **Cars page** (from the race view) and the championship's **Cars** tab hold the car comparisons, which moved off the race report and the Drivers tab to keep those pages short.
- **Replay:** compared cars show the average of their last 3 completed laps in the timing tower, and the selected car shows it in the readout.
- **Corner percentiles:** each corner on the Brake & throttle page shows how you ranked against everyone in the session, by time through the turn (60 m either side of the apex).
- **Placing turns by hand:** on the Track maps page, "Turns" opens a map of the track. Suggestions come from your own recordings there. Drag turns along the track, add, rename, delete or renumber them, then save. Saved turns replace the automatic ones in every report, replay, qualifying and Brake & throttle analysis at that track; "Use automatic" goes back.
- **Where each car is quick.** The race report shows each car's sector times and apex speeds against the field, with corners grouped as slow (under 100 km/h), medium and fast (over 160 km/h). A turn-by-turn table gives every car's apex speed at every turn. The best car in each column is highlighted, and the season Cars table carries the corner groups across races.
- **Cars.** The race report and the championship's Drivers tab compare every car model, with a "Whole field" row on top for the field's own pace. They show pace (the car's clean laps against the whole field, in each race, so it works across tracks), best lap, top speed and results. The "Fastest car" award goes to the quickest.
- **Car icons.** The **Car icons** page lists every GT3 car in your recordings with the icon it was matched to, previewed in several driver colours.
  - **Matching:** cars are matched by name, ignoring spaces, punctuation and accents, with a word-by-word fallback. A conflicting model number blocks a match, so a BMW M4 never gets the M6's icon. If a match is wrong or missing, pick the right icon from the list, or choose "no icon".
  - **Adding icons:** use "Add icons". Images work best painted neutral grey on a transparent background. They're cropped to the car and turned nose-up automatically (a rear wing is a straight bar at the car's end; a nose is rounded), and Flip fixes any that come out backwards. Your icons replace built-in ones of the same name.
  - **Lengths:** each icon has a length in metres, marked as a published spec, an estimate, or set by you. Width follows the image's proportions. Of the built-in set, only the Audi R8 LMS GT3's length is from a published spec (4.583 m); the rest are estimates in GT3's usual 4.4-4.95 m range, so correct any you know.
- **How mapped track edges are built.** Each edge is built as its own curve in world coordinates, not as distances from the racing line. The racing line swings across the road and touches the inside edge at every apex, and in a tight corner an edge point isn't square across from it, so measuring from it distorted exactly the tightest corners.
  - **Filtering:** each 5 m section takes the outermost edge point with real support around it. This skips scattered strays outside the road and dense false clusters inside it (paint, patches).
  - **Impossible points:** edge points inside the road the cars actually drove are rejected, allowing 1 m for kerb-riding.
  - **Pinch check:** points that would pinch the road below 70% of its typical width against the other edge are dropped.
  - **Output:** the curve is turned into the app's edge format by exact intersection.
  - **Backstop:** any remaining pinch under 75% of typical width is widened on the side the cars aren't using. An edge the cars run along is never moved, so an apex can't be undone.
  - **Mapping first:** mapping laps are the source. Racing laps only fill stretches a mapping doesn't cover.
  - **Lap length and paint:** track files are rescaled to each session's lap length, and painted concrete doesn't count as track.
  - **Real-data test:** a real Red Bull Ring mapping and qualifying session is part of the tests (`tests/data/rbr`).
- **Turns.** Turns are found from the track's shape, as curvature peaks in the recorded racing line, so fast kinks, both halves of a chicane and every part of the esses count. The slowest point near each one marks the apex. Turns are numbered from the start line, shown as badges on every map, and the Brake & throttle page and qualifying breakdown include a turn map. Click a turn on it to jump to that corner.
- **Gifted passes.** A pass counts as gifted when the passed car was far slower than the cars around it (a spin, an off, a car crawling), not slower than usual for that spot. So a whole pack slowing into turn 1 on lap 1 doesn't make every pass look gifted. Lap invalidations that hit most of the field at once are ignored too.
- **Battles.** Battles show the average gap over the whole fight. A pass takes the gap through zero, so the closest gap always looked like 0.00.
- **Duplicate and ghost entries.** Entries that never move, set impossible lap times, or duplicate another driver's name without behaving like a real car are left out of the analysis. The race report notes which ones. Humans on your roster are never dropped.
- **Full screen figures.** Every chart and map in a race report, plus the app's standings and head-to-head figures, has a "Full screen" button. Double-clicking the figure does the same.
- **Awards.** Each race gets up to ~40 awards and each season ~25, grouped into battles, overtaking, positions, start, pace, consistency, strategy and hard luck. They're ranked by how interesting they are, with your group ahead of the AI. In **Settings → Talking points**, choose how many appear up front and pin the ones you always want first; the rest are under "See all".

Data lives next to the app:

- `recordings/`: one folder per session, same format as before
- `championships/`: one `.db` file per championship
- `ams2season.json`: app settings

An existing `season.json` + `season.db` is imported automatically on first launch.

Everything below still works from the command line if you prefer.

## Setup (Windows)

1. Python 3.10+. Put this folder somewhere permanent (e.g. `C:\AMS2Season`), then either double-click `record.bat` (it installs the libraries on first run) or run `python -m pip install -e .` from this folder.
2. In AMS2: **Options → System → Shared Memory → "Project CARS 2"**.
3. Copy `config/season.example.json` to `season.json`. List your friends with **every in-game name they might show up as** under `aliases`. Anyone not in the roster is treated as AI.

## Race night

```bat
:: before joining the lobby (or double-click record.bat)
ams2season record --out recordings --label Jax
```

Leave the recorder running all night. It waits for the game, opens a new folder per qualifying/race session, detects restarts, and ignores menus and replays. Ideally **every friend runs it**:

- If the only recording PC crashes or drops, that race is lost.
- Each recorder captures its own driver's contacts, spins and damage. Shared memory only exposes those for the local car.

## Viewing a race

Double-click **`report.bat`**. It builds a report for your newest race and opens it in your browser. To report an older race, drag its folder onto `report.bat`. From a terminal:

```bat
python -m ams2season report                         (newest race in .\recordings)
python -m ams2season report recordings\<race folder>
python -m ams2season report --db season.db --round 3
```

The report is a single `report.html` saved inside the race folder. It works offline, so you can drop it straight into Discord. It shows:
- how the running order changed lap by lap
- classification and gaps to the leader
- where every pass happened on a track map
- lap times, with the fastest lap in purple and personal bests in green
- humans-only stats, battles, pit stops, and talking points for the debrief

Click any of your names to follow that driver through every chart and table. `season.json` in the project folder is picked up automatically so the report knows who's human. For a text version in the terminal, use `python -m ams2season inspect`.

The `.parquet` files in each recording are raw data for the tools, not meant to be opened directly. `session.json` and `events.jsonl` are plain text if you're curious.

## Season tracking

```bat
ams2season ingest  --db season.db --config season.json recordings\..._race
ams2season standings --db season.db --policy both
ams2season stats --db season.db
```

`ingest` takes the next round number automatically, or use `--round N`. Use `--race-no 2` for double-headers. Re-ingesting the same round replaces it. The config is stored in the db, so `--config` is only needed when it changes. If a friend appears in the "treated as AI" list, add that name to their aliases and re-run ingest.

**Stewarding:**

```bat
ams2season correct --db season.db --round 3 --driver Mason --kind time_penalty --value 5 --note "T1 divebomb"
ams2season correct --db season.db --round 3 --driver Eli --kind position_penalty --value 2
ams2season correct --db season.db --round 3 --driver Theo --kind points --value -3
ams2season corrections --db season.db            (list; --delete ID to remove)
```

Corrections are kept separately from the race data and survive re-ingesting.

**Try it without the game:**

```bat
ams2season simulate --out demo_recordings
```

This writes four simulated rounds plus a demo config. The simulator produces real shared-memory structs through the real recorder, so it exercises the same code path as race night.

## AI handling

AMS2 multiplayer AI get random names and cars every race, so AI are stored per race only. Drivers in your roster are persistent. The `ai_policy` setting (or `--policy`) decides points:

- **`humans_only`**: points by finishing order among humans; AI are just traffic. This is the fairest option when AI count or strength varies between rounds.
- **`full_field`**: points by overall position; AI take places and their points are discarded. This rewards beating the AI but is sensitive to grid size.

`--policy both` prints both tables side by side.

Two normalized metrics work across different AI fields:

- **Field %** = cars beaten ÷ (field − 1). A P5 of 24 scores higher than a P5 of 12.
- **vs AI** = your median clean lap ÷ the median AI clean lap in that race. Below 1.00 means faster than the AI. This cancels out both track differences and AI strength.

## How the stats work

| Stat | How it's computed |
|---|---|
| Race distance | Lap distance unwrapped into a continuous metre count. `laps_completed` only anchors each segment (it lags the line by a few frames), which also handles grid slots behind the S/F line. |
| Grid | Running order captured just before the green flag. |
| Laps | Line-crossing times from distance, reconciled with the game's lap time when they agree within 0.5 s. |
| Sectors | Game sector times when they are available, otherwise sector-index transitions. |
| Clean laps | Exclude lap 1, invalid laps, pit laps, and laps over 107% of the driver's median. |
| Passes | Every pair of cars on a 10 Hz grid. A pass is a change between two running orders that each hold for `hold_s` (3 s), so side-by-side flicker counts at most once. Pairs more than half a lap apart (lappings) are ignored. The game's race position must agree, otherwise the swap is tagged `unconfirmed`. |
| Pass kinds | `clean`. `gifted`: the passed car dropped below 50% of field speed at that spot, or its lap was invalidated (spin or off). `contact`: a recorded collision between the two cars within 3 s. `pit_cycle`: the order changed while one car was in the pit lane; this is not counted as a pass. |
| Corners | Prominent minima of the field's median speed-vs-distance profile, named T1…Tn. A pass belongs to the corner whose braking zone or apex it happened in. `inspect` prints apex distances; give them real names under `corners` in the config, keyed `"Track|Layout"`. |
| Battles | Cars directly adjacent in running order, within 1.0 s, for at least 2 laps. Records min gap, swaps, and who came out ahead. |
| Pit stops | Pit-mode sequence, giving lane time and stationary time. Drive-through and stop-go penalties are flagged from the pit schedule. |
| Status | `finished`, `dnf` (retired), `dsq`, `disconnected` (left mid-race), or `running`. Classification uses the game's final order for cars still present, then non-finishers by laps and distance. |

## First real race: things to verify

Everything is tested against a simulator built to mimic the game's quirks. A few behaviours can only be confirmed in a live lobby. After your first race, run `inspect` and check:

1. **Grid order** matches what you saw on the grid. This depends on the game's race positions before green.
2. **Sector times** are present for other cars (`laps` table s1/s2/s3). If remote sector times are unset in multiplayer, the code falls back to sector transitions automatically, so you just get slightly coarser splits.
3. **A friend leaving** shows as `disconnected`, not a phantom DNF or a stuck car.
4. **Pass counts** look right. Watch one battle in the replay and compare. Tune `hold_s` in the config if needed. Re-ingest to apply.
5. **Contacts** appear for the recording driver (`local_collision` events in `events.jsonl`).

If something looks off, keep the recording folder. Raw frames make any fix re-runnable.

## Layout

```
ams2season/
  shm.py        ctypes mirror of SharedMemory.h v14 + read-only Windows reader
  recorder.py   session state machine, crash-safe chunked Parquet writer
  derive.py     distance, laps/sectors, classification, pit stops, corners
  passes.py     pass + battle detection
  race.py       per-race analysis, stats and highlights
  report.py     self-contained HTML race report
  awards.py     race and season awards: detection, wording, ranking, pinning
  replay.py     replay payload (every car on a shared timeline)
  quali.py      qualifying analysis: best laps on a shared lap-distance grid, inputs merged across recordings, breakdown
  trackmap.py   track edges: mapping laps from wheel-surface data, racing-line model, track files, live mapper
  practice.py   live practice tracker and objectives
  technique.py  brake/throttle shapes per corner, consistency, tyre report
  caricons.py   car icons: normalising images, matching in-game names, real lengths
  metrics.py    driving style (braking/throttle point consistency, track usage) and car statistics
  tyres.py      tyre analysis: tread profile, layers, window, warm-up, pressures, heat map, wear, brakes, ride height
  errors.py     driver errors: spins, offs, late braking, slow corners, time and positions lost
  overtakes.py  pass and hold rates per driver
  legends.py    20 F1 legends' style fingerprints and style matching
  practice_points.py  practice awards for championships
  liveries.py, bff.py, livery_editor.js/.css  livery editor (AMS2 package reading and writing, with backups and undo)
  traffic.py    racing corners: detection and weighting for braking/throttle consistency
  engineer/     race engineer: catalog (settings), evidence + corners (measuring), engine (rules, colours, plans), store (sessions, learning), live (tracker)
  assets/car_icons/  the built-in GT3 icon set
  app.py        desktop app backend (localhost API, recorder service, window launcher)
  app_ui.html   desktop app interface
  season.py     SQLite schema, ingest, corrections, standings, season stats
  simulate.py   synthetic races (spins, pits, retirements, disconnects, slot shuffles)
  cli.py        command line
tests/          layout check against the real header + end-to-end pipeline tests
```

Each recording folder contains `session.json`, `events.jsonl`, `frames.parquet` (every car, every tick), and `local.parquet` (your car's damage, inputs and weather). If the recorder dies mid-race, the 30-second chunks in `frames_parts/` are still readable.

## Tests

```bat
pip install -e .[test]
set AMS2_SHM_HEADER=C:\Program Files (x86)\Steam\steamapps\common\Automobilista 2\Support\SharedMemory\AMS2_SharedMemoryExampleApp\SharedMemory.h
pytest
```

The layout test compiles the game's own header with g++ and compares every field offset to the ctypes struct. It's skipped if g++ isn't available. Run it after big AMS2 updates.

## Embedding in the PyQt6 app

`Recorder.run(reader, stop_event)` blocks, so run it in a `QThread` with a `threading.Event` to stop it. For full control, call `Recorder.step(reader.snapshot(), time.perf_counter())` from a `QTimer` at 20 Hz. For views, `analyze_race(path, humans)` returns DataFrames (classification, laps, passes, battles, pits, stats), and `season.standings()` / `driver_stats()` / `head_to_head()` return the season tables.
