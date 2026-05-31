# jiba-cli

**Restore the original song titles that Apple Music replaced in your library.**

> **⚠️ AI-Generated Project Disclaimer**
> This project was built with AI assistance (Claude Code by Anthropic). It is provided as-is with no guarantees. Always review what it proposes before applying changes. The author is not responsible for any data loss or library issues. Make sure to keep backups — jiba-cli creates them automatically, but read the disclaimer and use at your own risk.

---

Apple Music changes song titles in two ways that jiba-cli fixes:

| Problem | Example | Command |
|---------|---------|---------|
| Japanese/Korean/Chinese songs show their romanized or translated title instead of the original | "Yoru ni Kakeru" instead of 夜に駆ける | `jiba scan` |
| Western songs show a Japanese katakana title instead of the original English | "シェイク・イット・オフ" instead of "Shake It Off" | `jiba reverse` |

Inspired by [JiBA](https://jiba.hee.ink/) (Japanese is Back Again) by Konnyaku — a macOS GUI app that does the same thing. jiba-cli brings the same idea to **Windows** (and Linux/macOS) as a command-line tool.

---

## Installation

jiba-cli is not published to PyPI yet. Install it directly from the source:

```bash
git clone https://github.com/mikotorz/jiba-cli
cd jiba-cli
uv venv
uv pip install -e .
```

After that the `jiba` command is available in your terminal (within the virtual environment).

---

## Typical workflow

```bash
# Step 1 — See which tracks have romanized/translated titles
jiba scan

# Step 2 — Look up the original titles online (MusicBrainz + iTunes)
jiba scan --match --output corrections.json

# Step 3 — Review corrections.json, then apply
jiba apply --corrections corrections.json

# Made a mistake? Roll back to the backup
jiba rollback
```

For the reverse problem (Apple Music converted English titles to Japanese):

```bash
jiba reverse --match --output reverse-corrections.json
jiba apply --corrections reverse-corrections.json
```

---

## Commands

### `jiba scan`

Scans your library for tracks whose titles have been romanized or translated, and optionally looks up the original titles.

```
Options:
  -l, --library-path PATH      Path to iTunes Music Library.xml (auto-detected if omitted)
  -t, --target-languages TEXT  Language codes to look for (default: ja,zh,ko)
  -m, --match                  Look up original titles via MusicBrainz and iTunes
  -o, --output FILE            Save corrections to a JSON file
  -n, --dry-run                Scan only — don't write anything
  -v, --verbose                Show per-track detail
```

---

### `jiba reverse`

Scans your library for Western songs whose titles Apple Music converted to Japanese katakana, and looks up the original English titles.

```
Options:
  -l, --library-path PATH  Path to iTunes Music Library.xml (auto-detected if omitted)
  -m, --match              Look up original English titles via MusicBrainz and iTunes
  -o, --output FILE        Save corrections to a JSON file
  -n, --dry-run            Scan only — don't write anything
  -v, --verbose            Show per-track detail
```

---

### `jiba apply`

Takes a corrections JSON file produced by `scan` or `reverse` and writes the changes back to your library. Always creates a timestamped backup first, and asks for confirmation before writing.

```
Options:
  -c, --corrections FILE   Corrections JSON file (required)
  -l, --library-path PATH  Path to iTunes Music Library.xml (auto-detected if omitted)
  -n, --dry-run            Preview changes without writing
```

---

### `jiba rollback`

Restores your library from the most recent backup created by `apply`.

```
Options:
  -l, --library-path PATH  Path to iTunes Music Library.xml (auto-detected if omitted)
```

---

### `jiba detect`

Quick test — classify a single title without scanning the whole library.

```bash
jiba detect "Yoru ni Kakeru" "YOASOBI"
# → ROMANIZED (Japanese artist, Latin-script title)

jiba detect "アイドル" "YOASOBI"
# → ORIGINAL (Japanese artist, kana title)

jiba detect "シェイク・イット・オフ" "Taylor Swift"
# → JAPANIZED (Western artist, kana title)
```

---

## Where is my library file?

jiba-cli finds the library automatically. If it can't, pass `--library-path` manually.

| OS | Default location |
|----|-----------------|
| Windows | `%USERPROFILE%\Music\iTunes\iTunes Music Library.xml` |
| macOS | `~/Music/Music/Music Library.xml` (Music.app) or `~/Music/iTunes/iTunes Music Library.xml` (older iTunes) |
| Linux | `~/.wine/drive_c/Program Files (x86)/iTunes/iTunes Music Library.xml` |

---

## How it works

**Detecting romanized titles (`jiba scan`):**

1. Read every track from the iTunes library XML.
2. For each track, look at the characters in the title. Japanese kana, Korean hangul, Chinese kanji, and Thai script are visually distinct from the A–Z alphabet — if the title has them, it's already in its original language and can be skipped.
3. If the title is in A–Z letters but the artist is a known Japanese/Korean/Chinese artist, score it as a candidate for romanization.
4. For candidates, search MusicBrainz (primary) and then the iTunes Store Japanese/Korean/Chinese storefronts (fallback) to find the original-script title.
5. Save the proposed corrections to JSON.

**Detecting japanized titles (`jiba reverse`):**

1. Same read step as above.
2. If a title has Japanese kana/katakana but the artist is clearly a Western/Latin-script artist, Apple Music probably auto-converted it.
3. To find the English original: search the iTunes Japan store by artist name to find the track ID, then look up that same ID in the iTunes US store to get the English title. Also checks MusicBrainz aliases.

**Applying corrections (`jiba apply`):**

Creates a timestamped `.bak.xml` backup of your library, then writes the corrected titles back into the XML. You can undo at any time with `jiba rollback`.

---

## Limitations

- **MusicBrainz rate limit** — 1 request per second. Large libraries (10 000+ tracks) take a while.
- **Coverage** — Correction quality depends on MusicBrainz data and iTunes Store availability. Niche or independent releases may not be found.
- **False positives** — Some genuine English-language releases by Asian artists will be flagged as romanized. Always review the corrections JSON before applying.
- **Japan-exclusive tracks** — If a Western track only exists in the Japanese iTunes Store with no US equivalent, the reverse lookup won't find an English title.
- **iTunes XML sync** — Apple Music for Windows sometimes doesn't update the XML automatically. You may need to export it manually from iTunes: `File → Library → Export Library`.

---

## Development

```bash
git clone https://github.com/mikotorz/jiba-cli
cd jiba-cli

# Create virtual environment and install
uv venv
uv pip install -e .
uv pip install pytest respx

# Run tests
uv run pytest
```

---

## Credits

- **[JiBA](https://jiba.hee.ink/)** — The original macOS app by Konnyaku that inspired this project.
- **[MusicBrainz](https://musicbrainz.org/)** — Free, open music encyclopedia used as the primary metadata source.
- **iTunes Store API** — Apple's search API for localized metadata.
- **[Claude Code](https://claude.ai/code) (Anthropic)** — AI-assisted development throughout this project.

## License

MIT
