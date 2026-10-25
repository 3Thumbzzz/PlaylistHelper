"""PlaylistHelper: turn a streaming playlist link into an M3U of local files
found in VirtualDJ database.xml files.

Supported: Spotify, Deezer, Apple Music, YouTube Music / YouTube playlists.
"""
from __future__ import annotations

import difflib
import io
import json
import os
import re
import string
import sys
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

import requests

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".aif", ".aiff",
              ".wma", ".alac", ".opus", ".mp4"}


@dataclass
class Track:
    """A track from a streaming playlist."""
    artist: str
    title: str
    duration: float | None = None

    def label(self) -> str:
        return f"{self.artist} - {self.title}" if self.artist else self.title


@dataclass
class Song:
    """A file entry from a VirtualDJ database."""
    path: str
    author: str
    title: str
    remix: str
    length: float | None
    playcount: int
    # derived, filled in by finalize()
    base_title: str = ""
    remix_key: str = ""
    artist_parts: list[str] = field(default_factory=list)
    title_keys: set[str] = field(default_factory=set)

    def display(self) -> str:
        if self.author and self.title:
            return f"{self.author} - {self.title}"
        return os.path.splitext(os.path.basename(self.path))[0]

    def finalize(self) -> None:
        stem = os.path.splitext(os.path.basename(self.path))[0].replace("_", " ")
        file_artist, file_title = split_filename(stem)
        title = self.title or file_title
        author = self.author or file_artist
        self.base_title = base_title(title)
        # VirtualDJ fills Remix from any bracket text (e.g. "Album Version", "www.site.com"),
        # so classify it like a title qualifier instead of trusting it as-is.
        self.remix_key = remix_key(f"{title} ({self.remix})" if self.remix else title)
        self.artist_parts = split_artists(author)
        if self.author and file_artist:
            self.artist_parts += [a for a in split_artists(file_artist) if a not in self.artist_parts]
        self.title_keys = {k for k in (self.base_title, base_title(file_title)) if k}


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

NOISE_WORDS = ("remaster", "radio edit", "official", "explicit", "clean", "video",
               "audio", "lyric", "single version", "album version", "mono", "stereo",
               " hq", " hd", "visualizer", "bonus track", "original mix", "deluxe")
MIX_WORDS = ("remix", "mix", "edit", "flip", "rework", "version", "dub", "bootleg",
             "vip", "refix", "redo", "blend", "instrumental", "acapella", "live", "riddim",
             "intro", "extended")
FEAT_RE = re.compile(r"\b(feat\.?|ft\.?|featuring|with)\s+.*$", re.I)
BRACKET_RE = re.compile(r"[\(\[\{]([^\)\]\}]*)[\)\]\}]")
DASH_SUFFIX_RE = re.compile(r"\s+-\s+(.*)$")
PUNCT_TABLE = str.maketrans({c: " " for c in string.punctuation + "’‘“”–—…"})


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize(s: str) -> str:
    s = strip_accents(s or "").lower().replace("&", " and ")
    s = s.translate(PUNCT_TABLE)
    return " ".join(s.split())


def _qualifiers(title: str) -> tuple[str, list[str]]:
    """Split a title into its core and qualifier segments (brackets, ' - xxx' suffix)."""
    quals = BRACKET_RE.findall(title)
    core = BRACKET_RE.sub(" ", title)
    m = DASH_SUFFIX_RE.search(core)
    if m:
        quals.append(m.group(1))
        core = core[:m.start()]
    return core, quals


def base_title(title: str) -> str:
    core, _ = _qualifiers(title or "")
    core = FEAT_RE.sub("", core)
    return normalize(core)


def remix_key(title: str) -> str:
    """Normalized remix/version description in a title, '' if it is the original."""
    _, quals = _qualifiers(title or "")
    keep = []
    for q in quals:
        ql = " " + q.lower()
        if any(w in ql for w in NOISE_WORDS) or re.match(r"\s*(feat|ft|featuring|with)\b", q, re.I):
            continue
        if any(w in ql for w in MIX_WORDS):
            keep.append(q)
    return normalize(" ".join(keep))


def split_artists(s: str) -> list[str]:
    s = strip_accents(s or "").lower()
    parts = re.split(r",|;|/|&|\+|\band\b|\bfeat\.?|\bft\.?|\bfeaturing\b|\bvs\.?|\bx\b|\bwith\b", s)
    out = []
    for p in parts:
        n = normalize(p)
        if n.startswith("the "):
            n = n[4:]
        if n and n not in out:
            out.append(n)
    return out


def split_filename(stem: str) -> tuple[str, str]:
    """Guess (artist, title) from a filename like '05 - Artist - Title'."""
    sep = r"\s+-\s+" if " - " in stem else r"-"  # bare hyphens only for 'artist-title' style names
    parts = [p.strip() for p in re.split(sep, stem) if p.strip()]
    while parts and re.fullmatch(r"\d{1,3}", parts[0]):
        parts.pop(0)
    if len(parts) >= 2:
        return parts[0], " - ".join(parts[1:])
    return "", parts[0] if parts else stem


def ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------------------
# VirtualDJ database
# ---------------------------------------------------------------------------

def find_databases() -> list[str]:
    found = []
    for letter in string.ascii_uppercase:
        p = f"{letter}:\\VirtualDJ\\database.xml"
        if os.path.isfile(p):
            found.append(p)
    docs = os.path.join(os.path.expanduser("~"), "Documents", "VirtualDJ", "database.xml")
    if os.path.isfile(docs) and os.path.normcase(docs) not in map(os.path.normcase, found):
        found.append(docs)
    return found


INVALID_XML_RE = re.compile("[^\t\n\r\x20-퟿-�\U00010000-\U0010ffff]")
SWAPPED_RE = re.compile("￾([^\"<]*)")


def _unswap(m: re.Match) -> str:
    # VirtualDJ sometimes writes tags as byte-swapped UTF-16 (leading U+FFFE BOM).
    text = "".join(chr(((ord(c) & 0xFF) << 8) | (ord(c) >> 8)) if ord(c) <= 0xFFFF else c
                   for c in m.group(1))
    text = INVALID_XML_RE.sub("", text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def sanitize_xml(db_path: str) -> io.BytesIO:
    with open(db_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    text = SWAPPED_RE.sub(_unswap, text)
    text = INVALID_XML_RE.sub("", text)
    return io.BytesIO(text.encode("utf-8"))


def load_database(db_path: str) -> list[Song]:
    try:
        return _parse_database(db_path, db_path)
    except ET.ParseError:
        # Malformed file (e.g. corrupt tag characters): clean it up and retry.
        return _parse_database(db_path, sanitize_xml(db_path))


def _parse_database(db_path: str, source) -> list[Song]:
    drive = os.path.splitdrive(os.path.abspath(db_path))[0]
    songs = []
    for _, el in ET.iterparse(source, events=("end",)):
        if el.tag != "Song":
            continue
        path = el.get("FilePath", "")
        if path and not os.path.splitdrive(path)[0] and not path.startswith("\\\\"):
            path = drive + ("" if path.startswith("\\") else "\\") + path
        if os.path.splitext(path)[1].lower() in AUDIO_EXTS:
            tags = el.find("Tags")
            infos = el.find("Infos")
            tags = tags.attrib if tags is not None else {}
            infos = infos.attrib if infos is not None else {}
            try:
                length = float(infos["SongLength"]) if "SongLength" in infos else None
            except ValueError:
                length = None
            try:
                plays = int(infos.get("PlayCount", 0))
            except ValueError:
                plays = 0
            s = Song(path=path, author=tags.get("Author", ""), title=tags.get("Title", ""),
                     remix=tags.get("Remix", ""), length=length, playcount=plays)
            s.finalize()
            songs.append(s)
        el.clear()
    return songs


class Library:
    def __init__(self) -> None:
        self.songs: list[Song] = []
        self.by_title: dict[str, list[Song]] = {}
        self.titles: list[str] = []
        self.databases: list[str] = []
        self.errors: list[str] = []

    def load(self) -> None:
        self.databases = find_databases()
        for db in self.databases:
            try:
                self.songs.extend(load_database(db))
            except (ET.ParseError, OSError) as e:
                self.errors.append(f"{db}: {e}")
        for s in self.songs:
            for k in s.title_keys:
                self.by_title.setdefault(k, []).append(s)
        self.titles = list(self.by_title)

    # -- matching -----------------------------------------------------------

    def match(self, track: Track, any_version: bool = False) -> Song | None:
        """Best local file for a track. With any_version, the most-played copy wins
        even if it is a remix/edit and the playlist asks for the original (or vice versa)."""
        t_base = base_title(track.title)
        if not t_base:
            return None
        t_remix = remix_key(track.title)
        t_artists = split_artists(track.artist)

        # Also try the title with its bracketed words kept, e.g. "Song (Theme Song)".
        core, quals = _qualifiers(FEAT_RE.sub("", track.title))
        quals = [q for q in quals if not any(w in " " + q.lower() for w in NOISE_WORDS)
                 and not re.match(r"\s*(feat|ft|featuring|with)\b", q, re.I)]
        t_full = normalize(" ".join([core] + quals))
        queries = [t_base] + ([t_full] if t_full != t_base else [])

        keys: dict[str, float] = {}
        for q in queries:
            if q in self.by_title:
                keys[q] = 1.0
            for k in difflib.get_close_matches(q, self.titles, n=8, cutoff=0.85):
                keys[k] = max(keys.get(k, 0.0), ratio(q, k))

        scored: list[tuple[float, Song]] = []
        seen = set()
        for k, t_score in keys.items():
            for s in self.by_title[k]:
                if id(s) in seen:
                    continue
                seen.add(id(s))
                a_score = artist_score(t_artists, s.artist_parts)
                if a_score < 0.85:
                    continue
                scored.append((t_score * 0.6 + a_score * 0.4, s))
        if not scored:
            return None

        # Narrow to the right version before applying the play-count rule.
        if t_remix:
            same = [(sc, s) for sc, s in scored if s.remix_key and
                    (ratio(t_remix, s.remix_key) >= 0.7 or t_remix in s.remix_key or s.remix_key in t_remix)]
        else:
            same = [(sc, s) for sc, s in scored if not s.remix_key]
        if not any_version:
            scored = same or scored
        same_ids = {id(s) for _, s in same}

        def close_length(s: Song) -> bool:
            return bool(track.duration and s.length and abs(s.length - track.duration) <= 15)

        # On a play-count tie, the requested version still wins.
        scored.sort(key=lambda x: (x[1].playcount, id(x[1]) in same_ids, close_length(x[1]),
                                   round(x[0], 3), os.path.exists(x[1].path)), reverse=True)
        return scored[0][1]


def artist_score(src: list[str], dst: list[str]) -> float:
    if not src:
        return 1.0  # nothing to compare against (e.g. unknown artist)
    if not dst:
        return 0.0
    best = 0.0
    for a in src:
        for b in dst:
            if a == b or (len(a) > 3 and (a in b or b in a)):
                return 1.0
            best = max(best, ratio(a, b))
    return best


# ---------------------------------------------------------------------------
# Playlist fetchers
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 20


class FetchError(Exception):
    pass


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


def _html(url: str) -> str:
    return _get(url).content.decode("utf-8", errors="replace")


def fetch_playlist(url: str) -> tuple[str, list[Track], str]:
    """Return (playlist name, tracks, warning)."""
    url = url.strip()
    if not re.match(r"https?://", url):
        url = "https://" + url
    host = urlparse(url).netloc.lower()
    if host in ("link.deezer.com", "deezer.page.link", "spotify.link", "spoti.fi"):
        url = _get(url, allow_redirects=True).url
        host = urlparse(url).netloc.lower()

    if "deezer.com" in host:
        return fetch_deezer(url)
    if "spotify.com" in host:
        return fetch_spotify(url)
    if "music.apple.com" in host:
        return fetch_apple(url)
    if "youtube.com" in host or "youtu.be" in host:
        return fetch_youtube(url)
    raise FetchError(f"Unsupported link: {host}")


def fetch_deezer(url: str) -> tuple[str, list[Track], str]:
    m = re.search(r"/(playlist|album)/(\d+)", url)
    if not m:
        raise FetchError("Could not find a Deezer playlist or album ID in the link.")
    kind, pid = m.groups()
    info = _get(f"https://api.deezer.com/{kind}/{pid}").json()
    if "error" in info:
        raise FetchError(f"Deezer: {info['error'].get('message', info['error'])}")
    tracks = []
    nxt = f"https://api.deezer.com/{kind}/{pid}/tracks?limit=100"
    while nxt:
        page = _get(nxt).json()
        for t in page.get("data", []):
            tracks.append(Track(t.get("artist", {}).get("name", ""), t.get("title", ""), t.get("duration")))
        nxt = page.get("next")
    return info.get("title", "Deezer playlist"), tracks, ""


def fetch_spotify(url: str) -> tuple[str, list[Track], str]:
    m = re.search(r"/(playlist|album)/([A-Za-z0-9]+)", url)
    if not m:
        raise FetchError("Could not find a Spotify playlist or album ID in the link.")
    kind, pid = m.groups()
    html = _html(f"https://open.spotify.com/embed/{kind}/{pid}")
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise FetchError("Spotify page layout not recognised (embed data missing).")
    try:
        entity = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError, json.JSONDecodeError):
        raise FetchError("Spotify page layout not recognised.")
    tracks = [Track(t.get("subtitle", ""), t.get("title", ""),
                    t["duration"] / 1000 if t.get("duration") else None)
              for t in entity.get("trackList", [])]
    warning = ""
    if len(tracks) >= 100:
        warning = ("Spotify's public embed only lists the first 100 tracks; "
                   "the rest of this playlist was not checked.")
    return entity.get("name") or entity.get("title") or "Spotify playlist", tracks, warning


def fetch_apple(url: str) -> tuple[str, list[Track], str]:
    html = _html(url)
    m = re.search(r'<script[^>]*id="serialized-server-data"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise FetchError("Apple Music page layout not recognised.")
    data = json.loads(m.group(1))
    items: list[dict] = []
    seen = set()

    def walk(o):
        if isinstance(o, dict):
            if "title" in o and "artistName" in o and "duration" in o:
                key = o.get("id") or (o["title"], o["artistName"])
                if key not in seen:
                    seen.add(key)
                    items.append(o)
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    tracks = [Track(i.get("artistName", ""), i.get("title", ""),
                    i["duration"] / 1000 if i.get("duration") else None) for i in items]
    name = "Apple Music playlist"
    t = re.search(r'<meta property="og:title" content="([^"]*)"', html)
    if t:
        name = re.sub(r"\s+on Apple Music$", "", unescape_html(t.group(1)))
    warning = ""
    if len(tracks) in (50, 100, 300):
        warning = ("Apple Music's public page may only list part of a long playlist; "
                   "tracks beyond the first %d may not have been checked." % len(tracks))
    return name, tracks, warning


def unescape_html(s: str) -> str:
    import html
    return html.unescape(s)


def fetch_youtube(url: str) -> tuple[str, list[Track], str]:
    pid = parse_qs(urlparse(url).query).get("list", [None])[0]
    if not pid:
        raise FetchError("No playlist ID (list=...) found in the YouTube link.")
    try:
        from ytmusicapi import YTMusic
    except ImportError:
        raise FetchError("ytmusicapi is not installed. Run: pip install ytmusicapi")
    try:
        pl = YTMusic().get_playlist(pid, limit=None)
    except Exception as e:  # ytmusicapi raises a variety of errors
        raise FetchError(f"YouTube Music: {e}")
    tracks = []
    for t in pl.get("tracks", []):
        artists = ", ".join(a["name"] for a in (t.get("artists") or []) if a.get("name"))
        artists = re.sub(r"\s+-\s+Topic$", "", artists)
        title = t.get("title") or ""
        # Plain YouTube uploads are often titled "Artist - Title"
        if " - " in title and (not artists or artists.lower() in title.lower()):
            artists, title = title.split(" - ", 1)
        tracks.append(Track(artists, title, t.get("duration_seconds")))
    return pl.get("title", "YouTube playlist"), tracks, ""


# ---------------------------------------------------------------------------
# M3U
# ---------------------------------------------------------------------------

def build_m3u(results: list[tuple[Track, Song | None]], show_plays: bool = False) -> str:
    """M3U text; show_plays adds a play-count note for the on-screen preview only."""
    lines = ["#EXTM3U"]
    for _, song in results:
        if song is None:
            continue
        secs = int(round(song.length)) if song.length else -1
        plays = f"    [{song.playcount} play{'' if song.playcount == 1 else 's'}]" if show_plays else ""
        lines.append(f"#EXTINF:{secs},{song.display()}{plays}")
        lines.append(song.path)
    return "\n".join(lines) + "\n"


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")
    return name or "playlist"


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def run_ui() -> None:
    from PySide6.QtCore import QSettings, QThread, Qt, Signal
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel,
                                   QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
                                   QProgressBar, QPushButton, QSplitter, QVBoxLayout,
                                   QWidget)

    class LoadWorker(QThread):
        done = Signal(object)

        def run(self):
            lib = Library()
            lib.load()
            self.done.emit(lib)

    class GenerateWorker(QThread):
        progress = Signal(int, int)
        done = Signal(str, object, str)
        failed = Signal(str)

        def __init__(self, lib: Library, url: str, any_version: bool):
            super().__init__()
            self.lib, self.url, self.any_version = lib, url, any_version

        def run(self):
            try:
                name, tracks, warning = fetch_playlist(self.url)
            except FetchError as e:
                self.failed.emit(str(e))
                return
            except requests.RequestException as e:
                self.failed.emit(f"Network error: {e}")
                return
            except Exception as e:
                self.failed.emit(f"Unexpected error: {e!r}")
                return
            results = []
            for i, t in enumerate(tracks, 1):
                results.append((t, self.lib.match(t, self.any_version)))
                self.progress.emit(i, len(tracks))
            self.done.emit(name, results, warning)

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("PlaylistHelper")
            self.resize(1100, 700)
            self.lib: Library | None = None
            self.playlist_name = "playlist"
            self.m3u = ""
            self.worker = None

            self.link = QLineEdit()
            self.link.setPlaceholderText("Paste a Spotify / Deezer / Apple Music / YouTube Music playlist link")
            self.link.returnPressed.connect(self.generate)
            self.gen_btn = QPushButton("Generate")
            self.gen_btn.setEnabled(False)
            self.gen_btn.clicked.connect(self.generate)
            self.settings = QSettings("PlaylistHelper", "PlaylistHelper")
            self.any_version = QCheckBox("Prefer most-played (any version)")
            self.any_version.setToolTip(
                "Pick the copy with the highest play count even if it is a remix or edit\n"
                "and the playlist asks for the original (or the other way round).")
            self.any_version.setChecked(self.settings.value("any_version", False, type=bool))
            self.any_version.toggled.connect(lambda on: self.settings.setValue("any_version", on))
            top = QHBoxLayout()
            top.addWidget(self.link, 1)
            top.addWidget(self.any_version)
            top.addWidget(self.gen_btn)

            mono = QFont("Consolas", 9)
            self.preview = QPlainTextEdit(readOnly=True)
            self.preview.setFont(mono)
            self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)
            self.preview.setPlaceholderText("M3U preview will appear here")
            self.missing = QPlainTextEdit(readOnly=True)
            self.missing.setPlaceholderText("Songs not found in your VirtualDJ databases")

            left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0)
            ll.addWidget(QLabel("Playlist preview")); ll.addWidget(self.preview)
            right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0)
            self.missing_label = QLabel("Not found")
            rl.addWidget(self.missing_label); rl.addWidget(self.missing)
            split = QSplitter(Qt.Horizontal)
            split.addWidget(left); split.addWidget(right)
            split.setSizes([770, 330])

            self.save_btn = QPushButton("Save Playlist")
            self.save_btn.setEnabled(False)
            self.save_btn.clicked.connect(self.save)
            self.status = QLabel("Loading VirtualDJ databases…")
            self.bar = QProgressBar(); self.bar.setMaximumWidth(200); self.bar.setRange(0, 0)
            bottom = QHBoxLayout()
            bottom.addWidget(self.save_btn)
            bottom.addWidget(self.status, 1)
            bottom.addWidget(self.bar)

            root = QWidget(); lay = QVBoxLayout(root)
            lay.addLayout(top); lay.addWidget(split, 1); lay.addLayout(bottom)
            self.setCentralWidget(root)

            self.loader = LoadWorker()
            self.loader.done.connect(self.on_loaded)
            self.loader.start()

        def on_loaded(self, lib: Library):
            self.lib = lib
            self.bar.hide()
            msg = f"Loaded {len(lib.songs):,} tracks from {len(lib.databases)} database(s)"
            self.status.setText(msg)
            self.status.setToolTip("\n".join(lib.databases + lib.errors))
            self.gen_btn.setEnabled(bool(lib.songs))
            if lib.errors:
                QMessageBox.warning(self, "Database errors", "\n".join(lib.errors))
            if not lib.songs:
                QMessageBox.critical(self, "No databases",
                                     "No VirtualDJ database.xml with music files was found.")

        def generate(self):
            url = self.link.text().strip()
            if not url or not self.lib or (self.worker and self.worker.isRunning()):
                return
            self.gen_btn.setEnabled(False)
            self.save_btn.setEnabled(False)
            self.status.setText("Fetching playlist…")
            self.bar.setRange(0, 0); self.bar.show()
            self.worker = GenerateWorker(self.lib, url, self.any_version.isChecked())
            self.worker.progress.connect(self.on_progress)
            self.worker.done.connect(self.on_done)
            self.worker.failed.connect(self.on_failed)
            self.worker.start()

        def on_progress(self, i, n):
            self.bar.setRange(0, n); self.bar.setValue(i)
            self.status.setText(f"Matching {i}/{n}…")

        def on_done(self, name, results, warning):
            self.playlist_name = name
            self.m3u = build_m3u(results)
            missing = [t.label() for t, s in results if s is None]
            found = len(results) - len(missing)
            self.preview.setPlainText(build_m3u(results, show_plays=True))
            text = "\n".join(missing)
            if warning:
                text = f"⚠ {warning}\n\n{text}"
            self.missing.setPlainText(text)
            self.missing_label.setText(f"Not found ({len(missing)})")
            self.status.setText(f"{name}: {found}/{len(results)} matched")
            self.bar.hide()
            self.gen_btn.setEnabled(True)
            self.save_btn.setEnabled(found > 0)

        def on_failed(self, msg):
            self.bar.hide()
            self.status.setText("Failed")
            self.gen_btn.setEnabled(True)
            QMessageBox.critical(self, "Could not load playlist", msg)

        def save(self):
            path, _ = QFileDialog.getSaveFileName(
                self, "Save playlist", safe_filename(self.playlist_name) + ".m3u",
                "M3U playlist (*.m3u *.m3u8)")
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:
                    f.write(self.m3u)
            except OSError as e:
                QMessageBox.critical(self, "Save failed", str(e))
                return
            self.status.setText(f"Saved {path}")

    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_ui()
