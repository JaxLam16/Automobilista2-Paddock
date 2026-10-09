# Workspace and release builds

## Folder layout

| Location | Purpose |
| --- | --- |
| `ams2season/` | App code and bundled UI assets |
| `tests/`, `config/` | Tests, preserved recording fixtures and example configuration |
| `docs/` | User guides and alpha notes |
| `tools/` | Workspace organisation and release tooling |
| `releases/` | Windows alpha ZIPs, checksums and validation reports |
| `build/` | Disposable release build staging and frozen app smoke test data |
| `archive/pre-alpha-*/` | Superseded installers, payloads, previews and diagnostic export |
| `diagnostics/` | Development investigations and preservation checkpoints; never shipped |
| `recordings/`, `championships/`, `Car Setups/` | Personal recordings, championships and exported setups |
| `tracks/`, `car_icons/`, `engineer/` | Personal maps, icons and engineer state |
| `livery_editor/`, `balance_of_performance/` | Personal editor state and game backups |
| `*_backups/`, `*_install_backup/` | Original update backups; paths preserved for restore tools |
| `.appwindow/`, `ams2season.json`, `ams2season.log` | Installed browser profile, settings and log |

Old update installers have been archived instead of deleted. Their manifest maps
the original paths to preserved paths with SHA-256 checksums. The active runtime
folders and all backup folders remain in their original locations. The source
launchers `AMS2 Season.bat`, `record.bat` and `report.bat` remain at the root.

## Build the standalone Windows ZIP

Use a Windows x64 Python 3.12 installation with the application dependencies and
PyInstaller installed. The tested versions are in `tools/release/requirements.txt`.

```powershell
python tools/release/build_windows.py
```

The builder freezes an explicit source snapshot, includes only packaged UI assets
and user docs, collects third-party license notices, and writes a ZIP, SHA-256
checksum and file manifest. It never recursively packages the working folder.
It refuses to overwrite an existing release. Use `--output <new-folder>` for a
new candidate. Do not upload `build/`, `diagnostics/`, `archive/` or the installed
working folder; give testers only the release ZIP.

Run `python tools/release/smoke_windows.py <release-folder>` on the built output.
This launches the EXE with a separate empty data directory and port, tests the UI
assets and API, exercises synthetic recording/analysis and checks shutdown. It
does not use the installed app's recordings or modify game files.

Packaging tests do not establish real game compatibility. Complete the tester
pass in `ALPHA_NOTES.md`, preferably on a PC without Python installed, before
widening distribution. Project licensing has not been specified in this checkout;
decide the project's distribution terms before publishing source code publicly.
