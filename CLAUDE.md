# PlaylistHelper

PySide6 desktop app (Windows): paste a Spotify / Deezer / Apple Music / YouTube Music playlist link, match its tracks against the VirtualDJ `database.xml` files on the user's drives, preview the result as M3U, and save it.

- Run: `PlaylistHelper.bat` (uses `pythonw`, no console) or `python playlist_helper.py` to see errors.
- Setup: `pip install -r requirements.txt` (PySide6, requests, ytmusicapi).
- Everything is in `playlist_helper.py`: database loading, playlist fetchers, matcher, UI.

## Databases
- Found automatically: `X:\VirtualDJ\database.xml` on every drive letter, plus `%USERPROFILE%\Documents\VirtualDJ\database.xml`. The main library is on D: and Z: (about 120k tracks combined).
- Paths without a drive letter get the database's drive added.
- VirtualDJ sometimes writes corrupt tags (byte-swapped UTF-16 starting with U+FFFE) that make the XML invalid. On a parse error, `sanitize_xml` repairs those in memory and retries. The files on disk are never changed.

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
- The preview shows `[N plays]` after each title. The saved `.m3u` does not include that note.
- Files are saved as UTF-8 with BOM and CRLF line endings.

## Testing
No test suite. Verify with a headless snippet: `Library().load()`, then `fetch_playlist(url)` and `lib.match(track)`. The user's reference playlist is https://music.apple.com/au/playlist/wedding-playlist/pl.u-mJy81XDFaG787a (52 tracks; 49 matched at last check).
