# Livery designer

Open **Livery designer** in Paddock's sidebar, check the AMS2 game folder, then
choose **Open designer**. It reuses the Livery editor's game path unless you
choose a separate folder here. **Use folder / refresh cars** updates the list.

The designer supports mod cars with loose `.meb` meshes, `.vhf` render models
and `.rcf` livery lists. Base-game encrypted meshes are unavailable. The original
supplied designer is preserved in `ams2_livery_tool.zip` in the working folder.

## Painting and projects

Choose a blank car, existing livery or saved project. The original brush, eraser,
fill, pen, gradient, patterns, shapes, text, images, symmetry and layer controls
are available. Right-drag or Space + drag orbits; the mouse wheel zooms.
Ctrl+Z / Ctrl+Y undo and redo. Ctrl+S saves the project, including editable layers.
**Download PNG** exports the texture without changing the game.

Projects and imported decals are personal data under Paddock's `livery_designer/`
folder. They are excluded from release ZIPs. Starter decals are copied only when
missing, preserving your existing files. For migration, copy this entire personal
folder to the new portable Paddock folder. The core 3D libraries are bundled;
online racing fonts still need internet, while installed fonts work offline.

## Saving to AMS2

Close AMS2 first. If you have restricted this car's liveries with **Livery editor**,
enable all of its liveries before installing a design. **Save to game** either
adds the next slot or replaces an existing slot. It writes compressed DDS textures
and updates the car's loose normal/HR lists. Finish maps depend on support in the
car's own materials; the designer reports when they are unavailable.

The editor renders a livery-list picture too. It backs up changed originals under
`_livery_tool_backups/` in the selected game folder, using unique backup folders.
A failed save rolls back touched textures, lists and manifest files. If picture
rendering fails after the livery itself was saved, the UI reports that separately.
Rescan **Livery editor** after installing to refresh Paddock's livery choices.
Backups can be restored by copying the original files from their backup folder.

After a mod update, the designer offers to put back missing designs whose DDS
files remain. Friends need the same files at the same livery slot to see a design
in game. This does not add livery IDs to AMS2's shared-memory telemetry.

## Current limits

This is an experimental integration of the user-supplied AMS2 Livery Editor.
Synthetic car saves and rollback are tested. A real-game check is still needed
for each mod's model, texture and material layout. It edits loose mod files;
it does not rebuild encrypted packages or guarantee loader precedence.

Bundled Three.js 0.169.0 and three-mesh-bvh 0.8.3 retain their MIT licenses under
`ams2season/designer/web/vendor/`. Their source URLs and checksums are recorded
in `MANIFEST.json`. No game meshes, donor physics or personal projects are bundled.
