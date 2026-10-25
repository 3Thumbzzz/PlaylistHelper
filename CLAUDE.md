# PlaylistHelper

PySide6 desktop app (Windows and macOS): paste a Spotify / Deezer / Apple Music / YouTube Music playlist link, match its tracks against the user's DJ libraries (VirtualDJ, Serato, rekordbox), preview the result as M3U, and save it.

- Run: `PlaylistHelper.bat` (uses `pythonw`, no console) or `python playlist_helper.py` to see errors.
- Setup: `pip install -r requirements.txt` (PySide6, requests, ytmusicapi, pyrekordbox).
- Everything is in `playlist_helper.py`: library loading, playlist fetchers, matcher, UI.

## Building
- `build_windows.bat` installs the requirements plus PyInstaller, then runs `build.py`, which writes `dist\PlaylistHelper.exe` (one file, about 75 MB).
- A .dmg can only be built on a Mac. `.github/workflows/build.yml` runs `build.py` on GitHub's Windows and macOS (Apple Silicon) machines on every push to main, and uploads the .exe and .dmg as downloadable artifacts. On a Mac, `build.py` makes the .app, then the .dmg with `hdiutil`.
- The Mac app is unsigned: on first launch, right-click it and choose Open.
- PyInstaller needs `--collect-all pyrekordbox sqlcipher3` and `--collect-data ytmusicapi` (already in `build.py`).

## Libraries
- Discovery checks every drive root (Windows `C:\`–`Z:\`; macOS `/` and `/Volumes/*`) plus the home folder:
  - VirtualDJ: `<root>/VirtualDJ/database.xml` and `~/Documents/VirtualDJ/database.xml`. The main libraries are on D: and Z:. Z: is a drive that is sometimes unplugged.
  - Serato: `<root>/_Serato_/database V2` and `~/Music/_Serato_/database V2`. This is a binary format of nested tag/length records with UTF-16BE text. `pfil` holds a path relative to the drive the `_Serato_` folder is on. `utpc` holds the play count; a few records contain garbage in the millions, so values over 100,000 are treated as 0.
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
