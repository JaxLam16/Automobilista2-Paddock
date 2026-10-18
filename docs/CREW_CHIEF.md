# Crew Chief connection

Paddock connects to your existing Windows Crew Chief installation. Crew Chief
continues its normal spotting and race calls. This version provides connection
setup and a spoken radio check; automatic corner coaching is not included yet.

## Connect

1. Close Crew Chief so its existing settings are saved. Open **Race engineer**
   in Paddock and find **Crew Chief radio** (also available inside an engineer session).
2. Under **Connection setup**, check the detected executable, choose the profile
   to copy, and click **Set up local connection**. If Paddock.json already exists,
   setup automatically reuses it and backs it up, retaining its preferences.
   No renaming or program download is needed.
3. Click **Open Crew Chief**. Paddock opens it for AMS2 using a separate **Paddock**
   profile. Check that this profile is selected, then start Crew Chief's application.
4. Enter an AMS2 practice, qualifying or race session with Crew Chief started.
   Wait for Crew Chief to recognize the session. Its custom MQTT messages require
   session data; its own startup speech can work without the game.
5. Click **Send radio check**. You should hear “Paddock radio check. Your Crew Chief
   connection is working.” Click **I heard it** only after hearing the message.

The bridge starts with Paddock after setup. **Stop connection** stops only the
Paddock bridge; Crew Chief stays open. It can be started again from the same panel.
Close duplicate Paddock installations if the selected local port is already in use.

## What changes

Paddock creates `Documents/CrewChiefV4/Profiles/Paddock.json` by copying the profile
you choose, retaining audio, recognition and other preferences. When Paddock.json
already exists, setup backs it up and reuses its settings instead. It enables MQTT
and uses the MQTT driver name Paddock in that profile. Other profiles and sound
packs are preserved.

Crew Chief has one MQTT configuration file shared across profiles. Paddock backs
up any existing `Documents/CrewChiefV4/mqtt_telemetry.json`, then configures it for
an authenticated connection on your PC (default port 48643). No telemetry channels
are published, no cloud broker is used, and audio downloads are disabled.
Connection settings and original-file backups live in Paddock's personal
`crew_chief/` folder. Include that folder when moving your personal app data.

**Restore Crew Chief settings** restores the original MQTT file and any reused
Paddock profile byte for byte. A profile newly created by setup is removed instead.
Close Crew Chief first and choose your previous profile
when reopening it. If you edited either file since setup, Paddock preserves the
newer files and reports where the originals are backed up for manual recovery.

## Troubleshooting

- **Listening, not connected:** check Crew Chief is using the Paddock profile and
  its AMS2 application has been started. Restart Crew Chief if it was already
  running during setup. The bridge does not close or restart Crew Chief for you.
- **Received but no speech:** receipt means Crew Chief accepted the message;
  it does not prove audio playback. Alpha 7 sends the check using Crew Chief's
  immediate-message option to wake the audio queue, but Crew Chief still checks
  whether it has a valid game session before playback. **Enter a practice,
  qualifying or race session and wait for Crew Chief to recognize it**, then
  send the check. Crew Chief's own startup radio call uses a different path and
  can work without a game session. Paddock disables the check when its recorder
  observes menus, replay or no game; with recording stopped, session status is
  unknown and the check remains available. Check Crew Chief's audio
  device, message volume, mute setting and **TTS setting** (Only when necessary
  or Any time). Release the talk button before testing. If using an older Paddock
  build, reopen the updated build first; a page refresh alone cannot replace its
  running radio host.
- **Connection host error:** this integration was tested with Crew Chief 4.19.5.4's
  MQTTnet 3.1.2 library. Windows PowerShell and .NET compile the small local host
  using that installed library. An unsupported library version or a policy that
  blocks the host will be reported in the panel.
- **Port already in use:** close other Paddock instances. To change the port,
  restore the previous connection settings and run setup with another local port.

The radio check uses text-to-speech, so its voice may differ from Crew Chief's
recorded engineer. The connection reports sent, received and user-confirmed audio
separately. It does not claim to diagnose driving or deliver corner advice yet.

## Calls without a recording

Recorded phrases play first. With **Crew Chief reads calls without a recorded
clip** switched on (Private voice panel, on by default), any other coaching call
is sent to Crew Chief as text and read by its text-to-speech, in its regular queue
after its spotter. A recorded clip is re-checked when Crew Chief fetches it; a
text call cannot be, so Paddock re-checks it immediately before sending and sends
it only while Crew Chief's radio is observed idle. Crew Chief's own TTS setting
must allow it. Its voice differs from the recorded phrases. Sending a call does not
confirm it was heard.

## Voice replies

The engineer can ask you things, such as what a practice session is for. To answer
by voice, open **Voice replies to the engineer** in the Crew Chief radio panel and
click **Set up voice replies** with Crew Chief closed. Paddock backs up your macro
file and the Paddock profile, adds eight Paddock reply macros for AMS2, and turns
command macros on in the Paddock profile only. Your own macros and other profiles
are kept.

Hold Crew Chief's radio button and say, for example, "confirm", "negative",
"this is practice two", "it's practice one", "free practice", "what's the plan",
"how am I doing" or "debrief". Crew Chief recognises only listed phrases; the full
list is shown in the panel. None of them is one of Crew Chief's own commands ("yes"
and "say again" already are, so they are not used; "say again" still repeats the
last call through Crew Chief).

Each reply macro presses two spare keys, F24 and then one of F13-F20 (one per
reply). Ordinary keyboards don't have these keys and AMS2 ignores them unless you
bind them. Paddock notices the pair through Windows raw input, which hands it a copy
of key events without taking them from the game, so no window opens and the game
keeps focus. **Remove voice replies** takes out only Paddock's macros and settings;
the full connection restore also removes them. You can always type a reply in the
practice plan instead.

The first version ran a console command for each reply. That window popped up and
took focus from the game for a moment (AMS2 can pause when it loses focus). If your
setup is from that version, the panel shows **Update voice replies (no pop-up
window)**: with Crew Chief closed it removes the old macros, switches Crew Chief's
"run commands from macros" preference back to what it was, and adds the key
macros.

## Paddock speaking for itself

Paddock can play the engineer's calls itself (Private race coach > Engineer voice and
radio > Spoken by: Paddock). Crew Chief is then optional; keep it for its spotter.
**Crew Chief: spotter and flags only** switches off Crew Chief's lap times, tyre and
brake temperatures, fuel, tyre wear and pace comments in the Paddock profile so you
don't hear both. Its spotter, flags, damage, positions and race calls stay. **Give
those calls back to Crew Chief** restores exactly what was there.
