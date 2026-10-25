# PlaylistHelper

PySide6 desktop app (Windows and macOS): paste a Spotify / Deezer / Apple Music / YouTube Music playlist link, match its tracks against the user's DJ libraries (VirtualDJ, Serato, rekordbox), preview the result as M3U, and save it.

- Run from source:
  - Windows: `PlaylistHelper.bat`. It falls back to the `py` launcher, installs missing packages on first run, then starts with `pythonw` (no console).
  - macOS: `PlaylistHelper.command` (double-click). It creates `.venv` on first run. It must keep LF line endings (`.gitattributes`) and the executable bit (`git update-index --chmod=+x`).
  - Either OS: `python playlist_helper.py` shows errors in the terminal.
- Setup: `pip install -r requirements.txt` (PySide6, requests, ytmusicapi, pyrekordbox). Needs Python 3.9 or newer.
- Everything is in `playlist_helper.py`: library loading, playlist fetchers, matcher, UI, self-test.
- Self-test: `PlaylistHelper --selftest [report.txt]` checks that the bundled modules import, loads the libraries, fetches a Deezer playlist (HTTPS) and runs matching. It then opens the real window briefly (`run_ui(smoke_test=True)`, no dialogs), which proves the Qt platform plugin and UI start. It exits non-zero on failure.
- Crash log: the windowed app writes Python errors and native crashes (`faulthandler`) to `~/Library/Logs/PlaylistHelper.log` (macOS) or `%LOCALAPPDATA%\PlaylistHelper\PlaylistHelper.log` (Windows). The log is overwritten on each launch. A startup failure also shows a dialog with the log path.

## Must work on any PC or Mac (user requirement)
Nothing may be tied to this machine: no hardcoded user names or drive letters, no Windows-only APIs without a macOS path, and no reliance on the working directory (a packaged Mac app starts in `/`). Per-user state goes in QSettings: the checkbox, extra libraries and the last save folder.

## Building
- `build_windows.bat` installs the requirements plus PyInstaller, then runs `build.py`, which writes `dist\PlaylistHelper.exe` (one file, about 75 MB).
- A .dmg can only be built on a Mac. On every push to main, `.github/workflows/build.yml` builds on GitHub's Windows, macOS Apple Silicon (`macos-latest`) and macOS Intel (`macos-15-intel`) machines. It runs `--selftest` on each packaged app, then uploads the .exe and .dmg files as downloadable artifacts. If all three succeed, a `release` job moves the `latest` tag to the commit and replaces the files on the single always-latest GitHub release ("Latest build"): `PlaylistHelper-Windows.exe`, `PlaylistHelper-macOS-AppleSilicon.dmg` and `PlaylistHelper-macOS-Intel.dmg`. The user chose this over versioned tags. On a Mac, `build.py` makes the .app, sets `LSMinimumSystemVersion` (`MIN_MACOS`), re-signs it ad hoc and verifies the signature, then makes the .dmg with `hdiutil`.
- PySide6 is pinned to `<6.10` in `requirements.txt`. 6.10 and 6.11 need macOS 13, 6.12 needs macOS 14, and 6.11 also drops Python 3.9. Before the pin, CI installed 6.12 and the app bounced once in the Dock and quit on an M1 running an older macOS. If you raise the pin, raise `MIN_MACOS` in `build.py` to match.
- The Mac app is unsigned. On first launch, right-click it and choose Open. On macOS 15 or newer, go to System Settings → Privacy & Security → Open Anyway instead.
- PyInstaller needs `--collect-all pyrekordbox sqlcipher3` and `--collect-data ytmusicapi` (already in `build.py`).

## Libraries
- Discovery checks every mounted drive root (Windows: drive letters from `GetLogicalDrives`, with critical-error popups disabled for empty card readers; macOS: `/` and `/Volumes/*`), plus the user's real Documents and Music folders. On Windows these are read from the registry, because they are often moved (into OneDrive, or this PC's Music folder, which is `D:\Music`).
  - VirtualDJ: `<root>/VirtualDJ/database.xml`, `<Documents>/VirtualDJ/database.xml`, and on macOS `~/Library/Application Support/VirtualDJ/database.xml`. The main libraries are on D: and Z:. Z: is a drive that is sometimes unplugged.
  - A drive's own VirtualDJ database (`<root>/VirtualDJ/database.xml`) has its paths rebased onto that drive's current mount point (`rebase()`). This handles a changed drive letter, or a drive last used on the other OS.
  - Serato: `<root>/_Serato_/database V2` and `<Music>/_Serato_/database V2`. This is a binary format of nested tag/length records with UTF-16BE text. `pfil` holds a path relative to the drive the `_Serato_` folder is on. `utpc` holds the play count; a few records contain garbage in the millions, so values over 100,000 are treated as 0.
  - Anything not found automatically can be added with the "Add library…" button (`database.xml`, `database V2` or `master.db`). These are stored in QSettings under `extra_libraries`.
  - rekordbox: `%APPDATA%\Pioneer\rekordbox\master.db` (macOS `~/Library/Pioneer/rekordbox`). It is SQLCipher-encrypted and read via `pyrekordbox.MasterDatabase`, using `DJPlayCount`.
- The same file listed in several libraries is merged by path. Play counts **add up across libraries** (VirtualDJ + Serato + rekordbox) and take the max within one library.
- VirtualDJ paths without a drive letter get the database's drive added (Windows only).
- VirtualDJ sometimes writes corrupt tags (byte-swapped UTF-16 starting with U+FFFE) that make the XML invalid. On a parse error, `sanitize_xml` repairs those in memory and retries. The library files on disk are never changed.

## Matching rules (agreed with the user)
- **Highest PlayCount wins** among duplicate copies. Other heuristics (track length within 15 s, match score, file exists) only break ties and must never override play count.
- The only filter applied before play count is the version check: if the playlist names a remix/edit/flip, look for that version; otherwise prefer the original. If no copy of the requested version exists, fall back to any version.
- The "Prefer most-played (any version)" checkbox skips even the version check. Its state is saved with QSettings.
- VirtualDJ fills its `Remix` tag from any bracket text in the filename (e.g. "Album Version", "www.slider.kz"). Run it through `remix_key` like a title qualifier; never treat a filled-in Remix tag as proof of a remix.
- Fuzzy matching: title ratio ≥ 0.85 and artist ratio ≥ 0.85. The artist threshold was raised from 0.75 because "Kane Brown" matched "James Brown".

## Fetcher limits
- Spotify uses the public embed page (no login), which lists only the first 100 tracks. Apple Music's public page may list only 50–100 tracks. A warning appears in the "Not found" pane when a playlist may have been cut short.
- Spotify and Apple Music scrape page JSON (`__NEXT_DATA__`, `serialized-server-data`), so they can break if those sites change. Deezer uses its public API; YouTube uses `ytmusicapi`.

## Output
- The preview shows `[N plays]` after each title, with a per-library breakdown when more than one library has plays (e.g. `[27 plays: VirtualDJ 14, Serato 13]`). The saved `.m3u` does not include that note.
- Files are saved as UTF-8 with BOM and CRLF line endings.

## Testing
No test suite. Verify with a headless snippet: `Library().load()`, then `fetch_playlist(url)` and `lib.match(track)`. The user's reference playlist is https://music.apple.com/au/playlist/wedding-playlist/pl.u-mJy81XDFaG787a (52 tracks; 49 matched at last check).
