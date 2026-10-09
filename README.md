# Automobilista 2 Paddock — first alpha

Paddock records AMS2 sessions, builds championship standings and helps you review
race pace, braking, throttle, tyres and driving consistency. It also includes
experimental race engineer, livery, Balance of Performance and car conversion tools.

Championships support fictional AI drivers linked to car/livery, with a saved
picture-based review per race and separate human-friends filters. Human drivers
can select liveries too; championship class filters narrow car choices, and
selected paint colors and pictures appear in replay. Follow the
[championship livery guide](docs/CHAMPIONSHIP_LIVERIES.md) to configure a roster.

## Run the Windows alpha

Download [0.1.0 Alpha 3 for Windows](https://github.com/JaxLam16/Automobilista2-Paddock/releases/tag/v0.1.0-alpha.3)
and choose the `AMS2-Paddock-0.1.0-alpha.3-Windows.zip` asset.

1. Extract the **entire ZIP** to a writable folder, such as `Documents\AMS2 Paddock`.
2. Double-click **AMS2 Paddock.exe**. Keep the `_internal` folder beside it.
3. In AMS2, enable **Options → System → Shared Memory → Project CARS 2**.
4. Open Paddock Settings, check your driver label and recording options, then run a session.

Python is included in the Windows build. Edge or Chrome opens the app window;
otherwise your default browser opens the local page. The app needs to be running
while you drive to capture telemetry. Use the recorder indicator to confirm recording.

For installation, updates, data backup and troubleshooting, see
[Quick start](docs/QUICKSTART.md). Read [Alpha limitations](docs/ALPHA_NOTES.md)
before testing the game editing tools.

## Your data

The portable app stores settings, recordings, championships and tool state beside
the executable. Back up the whole extracted folder with the app closed. When
updating, extract to a new folder and copy your data as described in the quick start.
Do not replace your working installation with an old incremental update installer.

## Feature guides

- [Balance of Performance](docs/BALANCE_OF_PERFORMANCE_README.md)
- [Car conversion and custom classes](docs/CAR_CONVERSION_README.md)
- [Livery editor](docs/LIVERY_EDITOR_README.md)

## Develop from this checkout

The source installation still runs through **AMS2 Season.bat**. It requires Python
3.10+ and the dependencies in `pyproject.toml`. Alternatively:

```powershell
python -m pip install -e ".[test]"
python -m ams2season app
python -m pytest
```

[Workspace layout and release build instructions](docs/DEVELOPMENT.md) explain
which folders are application data, archived updates and build outputs.
`HANDOFF.md` records development history and current implementation constraints.
