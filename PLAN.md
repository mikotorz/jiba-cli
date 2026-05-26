# jiba-cli Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a cross-platform CLI tool that restores original language titles (Japanese, Chinese, Korean) in Apple Music / iTunes libraries — a Windows-compatible equivalent of JiBA's metadata restoration pipeline.

**Architecture:** Python CLI reads the iTunes Music Library XML (cross-platform), uses MusicBrainz API + heuristic detection to find original-language metadata, and writes corrections back. CLI-first, designed for scripting and pipeline integration.

**Tech Stack:** Python 3.10+, plistlib (stdlib), click (CLI), MusicBrainz API (direct HTTP), langdetect, httpx, rich (formatted output), pytest, responses (mock HTTP).

**Repository:** `/home/m/jiba-cli`

---

## Phase 1: Project Scaffold + Library Reader

### Task 1 — Project skeleton

**Files:** pyproject.toml, src/jiba/{__init__,cli,models,library}.py, tests/__init__.py, README.md

Set up venv, install deps, ensure `jiba --help` works.

### Task 2 — Track model + Library XML parser

Implement `models.Track` dataclass and `library.read_library(path)` that:
- Parses iTunes Music Library XML via `plistlib`
- Extracts Track ID, Name, Artist, Album, Album Artist, Persistent ID, Location
- Returns `list[Track]`
- Auto-detects library path per OS (Windows: `%USERPROFILE%\Music\iTunes\iTunes Music Library.xml`)

### Task 3 — CLI `scan` command

Wire up `jiba scan` with options:
- `--library-path` / `-l`
- `--dry-run` / `-n` (default: on)
- `--auto-write` / `-w` (default: off)
- `--target-languages` / `-t` (default: `ja,zh,ko`)

Print summary: total tracks, tracks by language, tracks flagged for correction.

---

## Phase 2: Language Detection

### Task 4 — Title language detector

`detector.detect_title_language(title: str, artist: str) -> tuple[str, float]`
Returns (language_code, confidence).

Logic:
1. Check for CJK characters (Unicode blocks) → flag as original-script
2. Check for romaji patterns (Latin chars with Japanese phonotactics) → flag as romanized
3. Use langdetect on the text to predict language
4. Compare predicted vs expected (if track has known Japanese/Chinese artist)

Also add `DetectResult` enum: ORIGINAL, ROMANIZED, TRANSLATED, UNKNOWN

### Task 5 — Detector CLI command

Add `jiba detect` subcommand that takes a track name + artist and reports language analysis.

---

## Phase 3: Metadata Matcher (MusicBrainz)

### Task 6 — MusicBrainz API client

`matcher.MusicBrainzClient` class:
- `search_track(artist, title)` — search MusicBrainz for matching recordings
- Extract original-language title from aliases or tags
- Handle rate limiting (1 req/sec)
- Handle no-results gracefully

Uses MusicBrainz JSON API: `https://musicbrainz.org/ws/2/recording/?query=artist:{artist}%20AND%20recording:{title}&fmt=json`

### Task 7 — iTunes Store API client (fallback)

`matcher.iTunesClient`:
- Use iTunes Search API: `https://itunes.apple.com/search?term={artist}+{title}&entity=song&country=JP` (for Japanese store)
- Compare results to find original-script version
- Primary use: verify MusicBrainz results / fill gaps

### Task 8 — Matcher orchestration

`matcher.find_original_metadata(track, target_langs) -> list[Correction]`

Pipeline:
1. If track title already has CJK characters → skip (already original)
2. Search MusicBrainz for artist+track
3. Search iTunes API (different storefronts: JP, CN, KR)
4. Rank results by confidence
5. Return proposed corrections

---

## Phase 4: Writer + Rollback

### Task 9 — Library XML writer

`library.write_library(tracks, output_path, template_path)`:
- Reads original plist (template) to preserve playlists/settings
- Updates Track dict entries with corrected metadata
- Writes new XML
- Creates `.bak` backup before writing

### Task 10 — Apply corrections from CLI

`jiba apply` command that:
- Reads a corrections JSON file (from `jiba scan --output corrections.json`)
- Shows diff
- Writes to library with backup
- Confirms success

### Task 11 — Rollback command

`jiba rollback` — restore from last `.bak` file.

---

## Phase 5: Polish

### Task 12 — Progress bar + rich output

Use `rich.progress.Progress` for scan/apply progress.
Use `rich.table.Table` for proposed corrections.
Color-coded confidence levels.

### Task 13 — README + docs

Write full README with:
- Installation (pip install, brew alternative)
- Usage examples
- How it works
- Limitations
- Links to original JiBA

---

## Implementation Order

```
Task 1  (scaffold)
  → Task 2  (library parser)
    → Task 3  (scan CLI)
      → Task 4  (detector)
        → Task 5  (detect CLI)
          → Task 6  (MusicBrainz client)
            → Task 7  (iTunes fallback)
              → Task 8  (orchestration)
                → Task 9  (writer)
                  → Task 10 (apply CLI)
                    → Task 11 (rollback)
                      → Task 12 (rich output)
                        → Task 13 (README)
```

Each task includes: test, implementation, verification commit.

---

## Key Design Decisions

1. **iTunes XML over SQLite** — XML is documented, cross-platform, writable. Apple Music for Windows reads it.
2. **MusicBrainz primary, iTunes API fallback** — MusicBrainz is free and open; iTunes API has better CJK coverage but is proprietary.
3. **JSON interchange** — `jiba scan --output` writes JSON so you can review/edit before `jiba apply`.
4. **Backup-first** — every write creates a `.bak` of the original library XML.
5. **No cloud dependency** — unlike JiBA Enhanced Mode, this is fully offline-capable.
