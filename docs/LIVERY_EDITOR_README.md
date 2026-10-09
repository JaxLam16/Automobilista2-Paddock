# Paddock livery editor

The new **Livery editor** page appears in the existing sidebar. Existing race analysis, recordings, championships, practice, race engineer, settings, and car icons retain their original behavior.

## Open the editor

The editor is included in the Windows alpha. Start **AMS2 Paddock.exe** and
select **Livery editor**. No separate update installer is needed.

Read [Alpha limitations](ALPHA_NOTES.md) before editing game files. Your game
backups and editor selections are stored in `livery_editor/` beside the app.

## Choose the league's liveries

1. Enter your AMS2 installation folder, for example:
   `J:\SteamLibrary\steamapps\common\Automobilista 2`
2. Select **Scan game**. Scanning reads the game and stores a catalog in the app; it does not change the game.
3. Search for a car or filter its class, including **GT3 Gen 0** when that class is declared in the installed car metadata.
4. Toggle the livery cards. Installed preview images are shown when readable; every card still has the livery name and ID when no preview can be displayed.
5. Continue through other cars. Their selections stay staged when you switch cars or visit another page.
6. Close AMS2 and your content manager, then select **Review changes → Apply to game**.
7. Start AMS2 and check its livery selection menu.

At least one livery must remain enabled per car. **Enable all**, **Disable all**, and **Reset this car** make bulk selection easier. Scanning again discards the current unsaved selections.

Applying updates both normal and HR RCFs wherever discovered: the shared `vehiclespersistent.bff`, the car's main BFF, and loose RCFs. Matching files for multiple cars are patched together, so the shared menu package is written once per apply. Texture and material assets are retained.

## Re-enable liveries and recover old restrictions

The editor saves the original RCF catalog when it first sees each installed car. A disabled livery remains in this catalog and can be turned back on, including after restarting the app.

For liveries removed before installing this editor, expand **Recover liveries restricted before using this editor**. Enter the full path to an original BFF backup or original RCF, then select **Import original catalog**. A shared original `vehiclespersistent.bff` can recover catalogs for many matching cars at once. Importing only updates the editor's catalog; the in-game selection stays unchanged until you apply it.

## Presets for the league

**Save preset** stores selections for the editable cars you have opened in the editor. Saving and loading presets do not modify the game. After loading, review and apply the changes.

**Export** downloads the chosen saved preset as JSON. Another league member can **Import** that JSON, scan the same installed car mods, and load/apply the preset. These are local installations, so applying on one PC does not automatically change another PC.

## Backup and undo

Every apply first backs up all affected files in `livery_editor/installs/<installation-id>/backups/` inside the app folder. Every staged replacement is validated before any game file is replaced. A failed multi-file apply rolls back files already replaced.

**Undo last apply** restores those original file bytes, after checking that no other tool or update has since changed the files. It can undo successive applies. The editor keeps its catalog, so hidden liveries remain selectable.

Game or mod updates and reinstalls can overwrite applied game files. Scan again afterward. Keep the editor's `livery_editor` folder when moving the app: it contains catalogs, presets, and game-file backups.

## Supported packages

This release supports the unencrypted and RC4-encrypted BFF variants with uncompressed or zlib/Deflate-compressed RCF entries, including your supplied Camaro and shared packages. Unsupported package/entry variants are reported and affected cars stay read-only. It never silently deletes a packed asset or relocates streams to force an edit into an unsupported archive.

If an RCF cannot fit in its original packed slot, preview stops before any game file is changed. Original-expanded-size padding preserves space for later re-enabling the catalog.

## Verification

- The full application regression run passed (114 tests, two environment-dependent skips). The focused editor checks also pass, including subsequently added catalog recovery and mod-update cases.
- Added tests cover packed/loose synchronization, retained tire/dirt declarations, unrelated car data, shared writes, presets, catalog recovery, stale-file detection, rollback, exact undo, HTTP routing, and rejected cross-origin writes.
- Your actual uploaded Camaro and shared BFFs passed: choose IDs 71/72, re-enable IDs 73/89, and undo both operations back to the originals byte for byte. All 825 shared-package entry checksums were checked.
- Browser interaction checks exercise preview cards, selection validation, presets, apply/undo, original views, and responsive layout.
- Windows launch, actual Windows file locking, and the game itself must still be checked on your PC; this workspace cannot run AMS2.

Only `ams2season/app.py`, `ams2season/app_ui.html`, and the package-data list in `pyproject.toml` receive integration additions. All other existing app files are unchanged. The new implementation lives in `bff.py`, `liveries.py`, `livery_editor.js`, and `livery_editor.css`.
