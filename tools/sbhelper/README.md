# Simulator SpringBoard harness

Lets you feed any layout to the iOS Simulator's SpringBoard through the same call the
USB `setIconState` request reaches on a phone: `[[SBApp defaultIconController] importIconState:]`
(SpringBoard's `_SBXXSetIconState` handler; only its `com.apple.springboard.iconState.mutate`
entitlement check is skipped).

- `sbinject.m`: dylib loaded into SpringBoard; on the Darwin notification `homescreen.import`
  it imports `$SBTEST_DIR/in.plist` and writes the result to `$SBTEST_DIR/out.txt`.
- `post.c`: posts that notification from inside the simulator.
- `sbhelper.m`: calls the MIG functions directly. It can't be used, because the simulator
  refuses to launch binaries that claim the entitlement ("Security policy issue").

Build (outside iCloud, e.g. a scratch dir), then load it:
```bash
SDK=$(xcrun --sdk iphonesimulator --show-sdk-path)
xcrun --sdk iphonesimulator clang -target arm64-apple-ios27.0-simulator -isysroot "$SDK" -fobjc-arc -dynamiclib -framework Foundation -framework UIKit sbinject.m -o $DIR/sbinject.dylib
xcrun --sdk iphonesimulator clang -target arm64-apple-ios27.0-simulator -isysroot "$SDK" post.c -o $DIR/post
codesign -s - -f $DIR/sbinject.dylib $DIR/post
xcrun simctl spawn booted launchctl setenv DYLD_INSERT_LIBRARIES $DIR/sbinject.dylib
xcrun simctl spawn booted launchctl setenv SBTEST_DIR $DIR
xcrun simctl spawn booted launchctl kill SIGKILL system/com.apple.SpringBoard
# write $DIR/in.plist, then:
xcrun simctl spawn booted $DIR/post
```

Findings (iOS 27.2 simulator, 2026-10-31):
- A list (`[dock, page, ...]`) imports as `{buttonBar, iconLists}` only, and every App Library
  app it doesn't mention is put on a page. This is the bug a USB write hits.
- A dict with `buttonBar`, `iconLists` and `ignored` keeps the App Library. Keys left out (`today`)
  stay as they were. Apps must be bundle-id strings, or SpringBoard saves the dicts verbatim.
- An app left out of both `iconLists` and `ignored` is still put on a page.
- `importIconState:` returns NO for the string form even though it applies; verify by re-reading.
- Gaps: a page's pinned cells live in `listMetadata[<page id>].fixedLocations` ({identifier: cell 0-23},
  with `fixedLocationsGridColumns`/`Rows`). Importing them with our own `listUniqueIdentifiers` works;
  importing without them clears every gap. None of SpringBoard's exports (`exportState:`,
  `exportFlattenedState:includeMissingIcons:`, `exportPendingState:includeMissingIcons:`, i.e. the USB
  getIconState paths) carry them. The `homescreen.exports` hook in `sbinject.m` dumps all three.
- Widgets: a configured widget's settings hang off its element id; over USB that is
  `userSelectedElementIdentifier`, and it must be written back as `uniqueIdentifier`.

Duplicate experiment (iOS 27.0 simulator, 2026-11-07):
- Importing a root archive with `com.apple.mobilecal` on two pages returned YES and left both
  strings in the on-disk archive. The live `exportState:YES` reported Calendar only on its
  original page, including after a SpringBoard restart. A repeated bundle identifier in the
  archive is therefore not sufficient evidence of two live placements.
- A native App Library drag was not successfully completed in this first experiment. No
  physical iPhone was written.

Follow-up (iOS 27.0 simulator, 2026-11-07):
- Invoking `SBHIconManager`'s `addApplicationIconWithBundleIdentifier:toPage:iconIndex:`
  created a second live Calendar icon. Its live `exportState:YES` record contained the same
  `bundleIdentifier`, an independently generated UUID `displayIdentifier`, `iconType: app`,
  and an empty `iconLists`. The disk archive used the same dictionary without `iconLists`.
- The duplicate survived a SpringBoard restart. After removing it, importing its archive
  recreated both placements. Importing a newly generated UUID also worked; the project's
  `to_root_archive` output was independently imported and read back with both placements.
- Removing the original placement while retaining the UUID-backed icon made SpringBoard
  report the remaining icon under the ordinary bundle identifier. A verification or draft
  identity scheme must account for this normalization. The UI drag and physical iPhone
  behavior remain unverified, and the write guard remains in place.
