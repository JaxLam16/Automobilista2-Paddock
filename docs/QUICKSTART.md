# Windows alpha quick start

## Install and record

Extract the whole ZIP to a writable folder. Double-click **AMS2 Paddock.exe**;
do not run it from inside the ZIP or move the executable away from `_internal`.
Python installation is unnecessary. The alpha is unsigned.

In AMS2, set **Options → System → Shared Memory** to **Project CARS 2**.
Open Paddock Settings, set the driver label and check recorder autostart.
The app records practice, qualifying and races automatically while its recorder
is running. Confirm the recorder is connected before driving.
Finish the session and return to the menu so the recording can finish writing.

Use Recordings to review the session. Create a championship and import recorded
races for standings and season statistics. Track map capture and track boundaries
improve corner geometry analysis; only available telemetry can be analysed.

The window uses a local web server, normally `http://127.0.0.1:8642`.
Closing the window normally stops the app after a short delay. Close the app
before copying data or replacing release files.

## Back up and update

Back up the entire extracted folder with Paddock closed. For an update, extract
the new release into a separate folder and copy these items from the old folder:

- `ams2season.json` — settings, including any custom recording directory paths.
- `recordings/` and `championships/` — telemetry and championship databases.
- `tracks/`, `car_icons/`, `engineer/` — captured maps, custom icons and engineer state.
- `livery_editor/`, `balance_of_performance/` — editor state, profiles and game backups.
- `Car Setups/` and any other folders where you exported your setups.

Copy complete directories, including backup and transaction files. Preserve any
separate exported setups or old update backup folders too. If settings point to
custom external data folders, back up those folders and keep their paths valid.
Do not copy an old `_internal` folder or old executable into a new release.
Keep the old installation until your recordings and championships appear correctly.

Only run one Paddock installation at a time. An already-running instance on the
same port takes precedence, so it may display the old installation's data.

## Troubleshooting and feedback

If the window is missing, check whether the app is already running and try the
local address above in your browser. A blank recording list on a fresh install
is expected; data is not bundled with the release.

If startup fails, look for `startup-error.log` next to the executable. Confirm
the ZIP was fully extracted to a writable folder and `_internal` is present.
For recorder issues, verify the shared memory option and the recorder indicator.

Report the alpha version, Windows version, track/car, steps to reproduce,
expected and actual result, and any error log or screenshot. Share a recording
only if you are happy to share its driver names and telemetry.

Game editing features require AMS2 and Content Manager to be closed before
applying changes. Review the staged changes and preserve the editor's backups.
Read [Alpha limitations](ALPHA_NOTES.md) before using them.
