# jiba-cli

**Restore original language titles in Apple Music / iTunes libraries.**

A cross-platform CLI tool that detects romanized/translated track titles (Japanese, Chinese, Korean, Thai) and restores their original scripts. Inspired by the macOS app [JiBA](https://jiba.hee.ink/) (Japanese is Back Again) by Konnyaku.

## Why?

Apple Music often romanizes Japanese tracks ("Rocket" → ロケット) and translates Chinese/Korean titles into English. JiBA for macOS solves this via a GUI. `jiba-cli` brings the same pipeline to **Windows** (and Linux/macOS) as a command-line tool that can be:

- Run on a schedule (Task Scheduler, cron)
- Integrated into media server workflows
- Used headless on a NAS or server

## Quick Start

```bash
# Install
pip install jiba-cli

# Scan your library for tracks needing correction
jiba scan

# Scan + look up original titles via MusicBrainz
jiba scan --match

# Save corrections to a file
jiba scan --match --output corrections.json

# Review and apply
jiba apply --corrections corrections.json

# Oops — rollback
jiba rollback
```

## Commands

### `jiba scan`

Scans your iTunes Music Library XML and identifies tracks with romanized/translated titles.

```
Options:
  -l, --library-path PATH    Path to iTunes Music Library.xml
  -t, --target-languages     Target language codes (default: ja,zh,ko)
  -m, --match                Look up original titles via MusicBrainz API
  -o, --output FILE          Save corrections to JSON file
  -n, --dry-run              Scan only (default: on)
  -w, --auto-write           Write changes automatically
  -v, --verbose              Detailed per-track analysis
```

**Language detection:**
- Detects CJK characters (Chinese, Japanese kanji), Hiragana, Katakana, Hangul, Thai
- Identifies romanized tracks from known Japanese/Korean/Chinese artists
- Uses romaji pattern matching (particles, long vowels, common keywords)
- Falls back to langdetect for ambiguous titles

### `jiba apply`

Applies previously-scanned corrections.

```
Options:
  -c, --corrections FILE     Corrections JSON file (required)
  -l, --library-path PATH    Path to iTunes Music Library.xml
  -n, --dry-run              Preview without writing
```

Creates a timestamped `.bak.xml` backup before writing. Prompts for confirmation.

### `jiba rollback`

Restore your library from the most recent backup.

```
Options:
  -l, --library-path PATH    Path to iTunes Music Library.xml
```

### `jiba detect`

Analyze a single track title.

```bash
jiba detect "Rocket" "YOASOBI"
# → Classification: ROMANIZED
```

## How It Works

```
┌──────────────────────────────────────────────┐
│  $ jiba scan --match                         │
│       ↓                                      │
│  iTunes Library XML ──► parser ──► tracks    │
│       (Windows/macOS)                         │
│       ↓                                      │
│  Language detector ──► CJK/Kana/Hangul/Thai  │
│                         detection + romaji    │
│       ↓                                      │
│  MusicBrainz API ──► find original titles    │
│  iTunes Store API ──► (fallback via JP/KR/   │
│                         CN/HK/TW storefronts) │
│       ↓                                      │
│  $ jiba apply corrections.json               │
│       ↓                                      │
│  Writer ──► Updated Library XML + .bak backup │
└──────────────────────────────────────────────┘
```

### Pipeline stages:

1. **Library reader** — Parses `iTunes Music Library.xml` via `plistlib`. Auto-detects path per OS (Windows: `%USERPROFILE%\Music\iTunes\iTunes Music Library.xml`).

2. **Language detector** — For each track, checks:
   - Contains CJK/kana/hangul/thai? → Already original, skip
   - ASCII title + known Japanese/Korean/Chinese artist? → Romanized candidate
   - Title has romaji patterns? → Romanized candidate

3. **Metadata matcher** — For flagged tracks:
   - **MusicBrainz** (primary): Free, open music database. Searches recordings by artist+title, checks for non-ASCII versions or aliases.
   - **iTunes Store API** (fallback): Queries Japanese/Korean/Chinese storefronts for original-language titles.

4. **Writer** — Updates the library XML with corrected metadata, preserving playlists and other structure. Creates timestamped `.bak.xml` backup.

## Library File Location

| OS | Default Path |
|---|---|
| Windows | `%USERPROFILE%\Music\iTunes\iTunes Music Library.xml` |
| macOS | `~/Music/Music/Music Library.xml` or `~/Music/iTunes/iTunes Music Library.xml` |
| Linux | `~/.wine/.../iTunes Music Library.xml` |

## Project Structure

```
jiba-cli/
├── pyproject.toml
├── src/
│   └── jiba/
│       ├── cli.py           # CLI entry point (click + rich)
│       ├── models.py        # Data models (Track, Correction, etc.)
│       ├── library.py       # iTunes XML reader/writer + backup
│       ├── detector.py      # Language/script detection
│       ├── matcher.py       # MusicBrainz + iTunes API clients
│       └── orchestrator.py  # Matching pipeline coordination
└── tests/
    ├── fixtures/
    │   └── sample_library.xml
    ├── test_library.py
    ├── test_detector.py
    └── test_matcher.py
```

## Development

```bash
git clone https://github.com/mikotorz/jiba-cli
cd jiba-cli
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest

# Install pre-commit hooks
pre-commit install
```

## Limitations

- **No cloud backend**: Unlike JiBA Enhanced Mode, this uses only public APIs (MusicBrainz, iTunes Store). Coverage depends on MusicBrainz data quality.
- **iTunes XML format**: Apple Music for Windows still generates the XML, but some users report it doesn't auto-update when the library changes. May need manual export.
- **Rate-limited**: MusicBrainz allows 1 req/sec. Large libraries (10k+ tracks) take time.
- **Read-only detection**: The detector is heuristic — some genuine English titles by Japanese artists will be flagged (false positives).

## Credits

- **JiBA** — The original macOS app by [Konnyaku](https://hee.ink) that inspired this project.
- **MusicBrainz** — Free, open music database providing metadata.
- **iTunes Store API** — Apple's search API for localized metadata.

## License

MIT
