"""
Language detection for track titles.

This file answers one question: "Is this track title already in its original
language, or has it been converted to Roman letters (romanized/translated)?"

How it works, in plain English:

  Step 1 — Look at the characters in the title.
    Japanese kana (hiragana/katakana), Korean hangul, Thai script, and Chinese
    kanji are all visually distinct from the A–Z alphabet. If the title contains
    those characters, it's probably already in its original language.

  Step 2 — Special case: Japanese-looking title by a Western artist.
    If a title has Japanese kana but the artist is clearly Western (e.g. Taylor
    Swift), Apple Music most likely auto-translated the title. We flag it as
    JAPANIZED so the reverse command can restore the English original.

  Step 3 — Latin-alphabet title by an Asian artist.
    If the title is written in regular A–Z letters but the artist is Japanese,
    Korean, or Chinese, the title is probably a romanization or translation.
    We build a confidence score from several clues and flag it as ROMANIZED
    if the score is high enough.

The output of every analysis is an AnalysisResult (defined in models.py).
"""
import re
import unicodedata

from .models import AnalysisResult, Classification

from langdetect import DetectorFactory
# Fix the random seed so langdetect gives the same result every run
DetectorFactory.seed = 0


# ── Unicode character ranges ─────────────────────────────────────────────────
# Every character in the world has a unique number (its "code point").
# The ranges below define which numbers belong to which writing systems.
# For example, standard Chinese/Japanese kanji live between 0x4E00 and 0x9FFF.
# Checking whether a character's code point falls inside a range tells us
# instantly which script it belongs to — without any AI or language model.

CJK_RANGES = [
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs — the main block of kanji/hanzi
    (0x3400, 0x4DBF),    # CJK Unified Ideographs Extension A — less common characters
    (0x2E80, 0x2EFF),    # CJK Radicals Supplement — the building-block strokes
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs — duplicates kept for legacy
    (0x2F800, 0x2FA1F),  # CJK Compatibility Ideographs Supplement
    (0x3000, 0x303F),    # CJK Symbols and Punctuation (e.g. 。「」)
    (0xFF00, 0xFFEF),    # Halfwidth and Fullwidth Forms (e.g. ａｂｃ)
]

HIRAGANA_RANGE = (0x3040, 0x309F)   # Hiragana — the rounded Japanese syllabary (あいうえお...)
KATAKANA_RANGE = (0x30A0, 0x30FF)   # Katakana — the angular Japanese syllabary (アイウエオ...)
KATAKANA_EXT = (0x31F0, 0x31FF)     # Katakana Phonetic Extensions — extra katakana symbols
HANGUL_RANGES = [
    (0xAC00, 0xD7AF),    # Hangul Syllables — the main block of Korean syllable blocks
    (0x1100, 0x11FF),    # Hangul Jamo — the individual consonant/vowel components
    (0x3130, 0x318F),    # Hangul Compatibility Jamo — an older encoding block
]
THAI_RANGE = (0x0E00, 0x0E7F)   # Thai script


def _in_range(char: str, ranges: list[tuple[int, int]] | tuple[int, int]) -> bool:
    """Return True if the character's code point falls within any of the given ranges."""
    cp = ord(char)
    # If a single range (a pair of numbers) was passed instead of a list, handle it directly
    if isinstance(ranges, tuple) and len(ranges) == 2 and isinstance(ranges[0], int):
        return ranges[0] <= cp <= ranges[1]
    for lo, hi in ranges:
        if lo <= cp <= hi:
            return True
    return False


def has_cjk(text: str) -> bool:
    """Return True if the text contains at least one Chinese/Japanese kanji character."""
    return any(_in_range(c, CJK_RANGES) for c in text)


def has_kana(text: str) -> bool:
    """Return True if the text contains hiragana or katakana (the Japanese syllabic scripts)."""
    return any(_in_range(c, HIRAGANA_RANGE) or _in_range(c, KATAKANA_RANGE) or _in_range(c, KATAKANA_EXT) for c in text)


def has_hangul(text: str) -> bool:
    """Return True if the text contains Korean hangul characters."""
    return any(_in_range(c, HANGUL_RANGES) for c in text)


def has_thai(text: str) -> bool:
    """Return True if the text contains Thai script characters."""
    return any(_in_range(c, THAI_RANGE) for c in text)


def has_latin(text: str) -> bool:
    """Return True if the text contains any basic A–Z letters."""
    return any('a' <= c.lower() <= 'z' for c in text)


def is_ascii(text: str) -> bool:
    """Return True if every character in the text is plain ASCII (no accents, no special scripts)."""
    return all(ord(c) < 128 for c in text)


# ── Romaji pattern detection ──────────────────────────────────────────────────
# "Romaji" is Japanese written out with the Latin alphabet (e.g. "Sakura" instead of 桜).
# The patterns below are regular-expression rules that match sounds or words
# that appear very often in romanized Japanese titles but rarely in native English.
ROMAJI_PATTERNS = [
    # Common Japanese grammar particles and sentence-ending words when romanized
    r'\b(?:no|ni|wa|ga|to|de|o|e|ka|mo|ne|yo|sa|na|shi|tsu|dake|made|koso|demo|suru)\b',
    # Doubled vowels — used in romaji to show a long vowel sound (e.g. "tōkyō" → "tookyo")
    r'(?:aa|ii|uu|ee|oo)',
    # Typical Japanese consonant-vowel syllable clusters that are rare in English
    r'(?:sh[aiueo]|ch[aiueo]|ts[auoe]|nj[ao]|ry[auo]|ky[auo]|gy[auo]|hy[auo]|my[auo]|py[auo]|by[auo])',
    # Common English words that appear in Japanese song titles (borrowed from English)
    r'\b(?:feat|feat\.|with|remix|version|edit|mix|radio|live|acoustic|instrumental)\b',
]

# ── Known artist databases ────────────────────────────────────────────────────
# These lists contain well-known artist names so we can make a confident guess
# about what language the original title should be in, even when the title itself
# is written in Latin letters.

JAPANESE_ARTIST_INDICATORS = [
    'yoasobi', 'ado', 'kenshi yonezu', 'yorushika', 'zutomayo',
    'king gnu', 'official hige dandism', 'back number', 'radwimps',
    'aimer', 'li sa', 'reol', 'milet', 'vaundy', 'fujii kaze',
    'mrs. green apple', 'natori', 'tuyu', 'eve',
    'be:first', 'jo1', 'ini', 'nizi u', '&team', 'xikers',
    'tuki.', 'wacci', 'ano', 'yangskinny', 'macaroni enpit',
    'hikaru utada', 'namie amuro', 'ayumi hamasaki',
    'koda kumi', 'arashi', 'smap', 'tackey & tsubasa',
    'm-flo', 'mili', 'ichiko aoba', 'toe', 'tricot',
    'mass of the fermenting dregs', 'polysics', 'sakanaction',
    'hinatazaka46', 'nogi46', 'keyakizaka46', 'sakurazaka46',
    'akb48', 'morning musume', 'perfume',
]

KOREAN_ARTIST_INDICATORS = [
    'bts', 'blackpink', 'twice', 'exo', 'nct', 'stray kids',
    'seventeen', 'aespa', 'ive', 'le sserafim', 'newjeans',
    'red velvet', 'g idle', 'itzy', 'enhyphen', 'txt',
    'bigbang', 'girls generation', 'snsd', 'shinee', 'super junior',
    '2ne1', 'psy', 'mamamoo', 'ikon', 'winner', 'akmu',
    'zb1', 'riize', 'kiss of life', 'babymonster', 'nmixx',
    'fromis_9', 'stayc', 'weeekly', 'dreamcatcher',
    'day6', 'n flying', 'the rose', 'jannabi', 'bolbbalgan4',
    'iu', 'taeyeon', 'sunmi', 'chungha', 'hyuna',
]

CHINESE_ARTIST_INDICATORS = [
    'jay chou', 'jolin tsai', 'mayday', 'wutiaoren', 'wubi',
    'jj lin', 'a-mei', 'wong fei', 'eason chan', 'faye wong',
    'wakin chau', 'li ronghao', 'meng meiqi',
    'dao lang', 'the8', 'lay zhang', 'bibi zhou',
    'tia ray', 'huo zun', 'joker xue', 'jane zhang',
    'lao feng', 'wang sulong',
]

# If at least 30% of the characters in a title are CJK kanji,
# we consider the title to be in its original Chinese/Japanese script.
ORIGINAL_SCRIPT_RATIO_THRESHOLD = 0.3

# Well-known Western artists — if the artist is on this list, we can be
# confident the title is NOT supposed to be in Japanese/Korean/Chinese.
WESTERN_ARTIST_INDICATORS = [
    'taylor swift', 'the beatles', 'ed sheeran', 'adele', 'billie eilish',
    'elvis presley', 'michael jackson', 'madonna', 'prince', 'david bowie',
    'queen', 'led zeppelin', 'pink floyd', 'the rolling stones',
    'nirvana', 'metallica', 'radiohead', 'coldplay', 'u2', 'the police',
    'eminem', 'kanye west', 'jay-z', 'beyoncé', 'lady gaga',
    'bruno mars', 'rihanna', 'drake', 'the weeknd', 'ariana grande',
    'justin bieber', 'katy perry', 'maroon 5', 'imagine dragons',
    'linkin park', 'green day', 'foo fighters', 'red hot chili peppers',
    'guns n\' roses', 'ac/dc', 'aerosmith', 'bon jovi',
    'frank sinatra', 'whitney houston', 'elton john', 'stevie wonder',
    'bob dylan', 'johnny cash', 'marvin gaye', 'aretha franklin',
    'lana del rey', 'halsey', 'melanie martinez', 'olivia rodrigo',
    'post malone', 'travis scott', 'tyler the creator',
    'doja cat', 'megan thee stallion', 'cardi b', 'nicki minaj',
    'dolly parton', 'willie nelson',
    'shakira', 'enrique iglesias', 'rosalía', 'bad bunny',
    'lil wayne', 'lil nas x', 'kendrick lamar', 'j. cole',
    'bob marley', 'jimi hendrix', 'janis joplin', 'the doors',
    'bee gees', 'abba', 'wham!', 'george michael',
    'phil collins', 'peter gabriel', 'sting',
    'snoop dogg', 'dr. dre', '50 cent', 'ice cube', 'tupac',
    'britney spears', 'christina aguilera', '*nsync', 'backstreet boys',
    'one direction', 'harry styles', 'louis tomlinson',
    'sam smith', 'lewis capaldi', 'dua lipa', 'adele',
    'amy winehouse', 'norah jones', 'alicia keys',
    'john legend', 'the black eyed peas', 'will.i.am',
    'pitbull', 'flo rida', 'kesha', 'pink',
    'avril lavigne', 'shania twain',
    'pharrell williams', 'robin thicke',
    'jason mraz', 'jack johnson', 'ben harper', 'dave matthews',
    'the white stripes', 'jack white', 'the black keys',
    'muse', 'oasis', 'blur', 'pulp', 'the smiths',
    'depeche mode', 'new order', 'joy division',
    'talking heads', 'ramones', 'the clash', 'sex pistols',
]


def _artist_is_western(artist: str) -> bool:
    """
    Return True if the artist is almost certainly a Western (non-Asian) artist.

    We check in order:
      1. Does the artist name contain Japanese or Korean characters? → not Western.
      2. Is the artist in our known-Western list? → definitely Western.
      3. Is the name written in plain Latin letters and NOT in our Asian artist lists?
         → probably Western (most Western artists write their names in Latin).
    """
    artist_lower = artist.lower().strip()
    # Native-script artist names are never Western
    if has_kana(artist_lower) or has_cjk(artist_lower) or has_hangul(artist_lower):
        return False
    # Explicit match in known-Western list
    if _matches_indicators(artist_lower, WESTERN_ARTIST_INDICATORS):
        return True
    # Latin name that doesn't appear in any of our Asian artist lists → likely Western
    if is_ascii(artist_lower) or has_latin(artist_lower):
        if _matches_indicators(artist_lower, JAPANESE_ARTIST_INDICATORS):
            return False
        if _matches_indicators(artist_lower, KOREAN_ARTIST_INDICATORS):
            return False
        if has_kana(artist_lower) or has_cjk(artist_lower):
            return False
        if len(artist_lower) > 2 and has_latin(artist_lower):
            return True
    return False


def _matches_indicators(text: str, indicators: list[str]) -> bool:
    """
    Return True if text contains any of the indicator strings as a whole word.

    We use word boundaries (\b) to avoid false matches — for example,
    "ado" (Japanese artist) should not match inside the word "shadow".
    """
    for indicator in indicators:
        if re.search(r'\b' + re.escape(indicator) + r'\b', text, re.IGNORECASE):
            return True
    return False


def _artist_suggests_japanese(artist: str) -> bool:
    """Return True if the artist name suggests Japanese music (kana/CJK in name, or known Japanese artist)."""
    artist_lower = artist.lower().strip()
    if has_kana(artist_lower) or has_cjk(artist_lower):
        return True
    return _matches_indicators(artist_lower, JAPANESE_ARTIST_INDICATORS)


def _artist_suggests_korean(artist: str) -> bool:
    """Return True if the artist name suggests Korean music (hangul in name, or known K-pop/K-indie artist)."""
    artist_lower = artist.lower().strip()
    if has_hangul(artist_lower):
        return True
    return _matches_indicators(artist_lower, KOREAN_ARTIST_INDICATORS)


def _artist_suggests_chinese(artist: str) -> bool:
    """Return True if the artist name suggests Chinese music."""
    artist_lower = artist.lower().strip()
    # Avoid misclassifying Japanese artists whose names contain kanji
    if _artist_suggests_japanese(artist_lower):
        return False
    if has_cjk(artist_lower) and not has_kana(artist_lower):
        return True
    return _matches_indicators(artist_lower, CHINESE_ARTIST_INDICATORS)


def _has_romaji_patterns(text: str) -> bool:
    """Return True if the text matches any of the typical romaji (romanized Japanese) patterns."""
    text_lower = text.lower()
    return any(re.search(p, text_lower, re.IGNORECASE) for p in ROMAJI_PATTERNS)


def analyze_title(title: str, artist: str = "") -> AnalysisResult:
    """
    Inspect a track title and decide whether it needs a language correction.

    Returns an AnalysisResult with:
      - classification: ORIGINAL, ROMANIZED, TRANSLATED, JAPANIZED, or UNKNOWN
      - language: the likely original language ('ja', 'ko', 'zh', etc.)
      - confidence: a number between 0 and 1 (higher = more certain)
      - is_romanized_candidate: True if this track should be looked up for an original title
      - is_japanized_candidate: True if this track was probably auto-converted by Apple Music

    The decision process has three main branches (see module docstring for overview).
    """
    title = title or ""
    artist = artist or ""

    has_kana_chars = has_kana(title)
    has_hangul_chars = has_hangul(title)
    has_thai_chars = has_thai(title)
    has_latin_chars = has_latin(title)
    all_ascii = is_ascii(title)

    detected_lang = ""
    confidence = 0.0

    # What fraction of the title's characters are CJK kanji?
    # (Used further down to detect Chinese titles that mix kanji with punctuation)
    cjk_ratio = sum(1 for c in title if _in_range(c, CJK_RANGES)) / max(len(title), 1)

    # ── Branch A: Title contains Japanese kana (hiragana / katakana) ──────────
    # Kana is always either genuinely Japanese or an Apple Music auto-conversion.
    # The artist name tells us which.
    if has_kana_chars:
        if not artist.strip():
            # No artist info — can't tell if it's real Japanese or auto-converted
            return AnalysisResult(
                title=title, artist=artist,
                classification=Classification.UNKNOWN,
                language="ja", confidence=0.2,
                has_cjk=has_cjk(title), is_romanized_candidate=False,
            )
        artist_is_western = _artist_is_western(artist)
        if artist_is_western or not (_artist_suggests_japanese(artist) or _artist_suggests_korean(artist)):
            # Western artist + Japanese-kana title → Apple Music converted it.
            # The "reverse" command handles these.
            return AnalysisResult(
                title=title, artist=artist,
                classification=Classification.JAPANIZED,
                language="ja", confidence=0.85,
                has_cjk=has_cjk(title), is_romanized_candidate=False,
                is_japanized_candidate=True,
            )
        # Japanese/Asian artist with kana → this is the genuine original title
        return AnalysisResult(
            title=title, artist=artist,
            classification=Classification.ORIGINAL,
            language="ja", confidence=0.95,
            has_cjk=has_cjk(title), is_romanized_candidate=False,
        )

    # ── Branch B: Title contains Korean hangul ────────────────────────────────
    elif has_hangul_chars:
        return AnalysisResult(
            title=title, artist=artist,
            classification=Classification.ORIGINAL,
            language="ko", confidence=0.95,
            has_cjk=False, is_romanized_candidate=False,
        )

    # ── Branch C: Title contains Thai script ─────────────────────────────────
    elif has_thai_chars:
        return AnalysisResult(
            title=title, artist=artist,
            classification=Classification.ORIGINAL,
            language="th", confidence=0.95,
            has_cjk=False, is_romanized_candidate=False,
        )

    # ── Branch D: Title is mostly CJK kanji (Chinese-style) ──────────────────
    elif cjk_ratio >= ORIGINAL_SCRIPT_RATIO_THRESHOLD:
        # At least 30% kanji → treat as original Chinese
        return AnalysisResult(
            title=title, artist=artist,
            classification=Classification.ORIGINAL,
            language="zh", confidence=min(0.8 + cjk_ratio, 0.95),
            has_cjk=True, is_romanized_candidate=False,
        )

    # ── Branch E: Title is in the Latin alphabet ──────────────────────────────
    # At this point we know the title has no native Asian script.
    # Now we try to decide: is this a genuine English/Latin title, or a
    # romanization/translation of a song that has an original-script version?

    if not has_latin_chars and not title.strip():
        # Empty or unrecognizable — give up
        return AnalysisResult(
            title=title, artist=artist,
            classification=Classification.UNKNOWN,
            language="", confidence=0.0,
            has_cjk=False, is_romanized_candidate=False,
        )

    artist_is_japanese = _artist_suggests_japanese(artist)
    artist_is_korean = _artist_suggests_korean(artist)
    artist_is_chinese = _artist_suggests_chinese(artist)

    # Record the most likely original language based on artist origin
    if artist_is_japanese:
        detected_lang = "ja"
    elif artist_is_korean:
        detected_lang = "ko"
    elif artist_is_chinese:
        detected_lang = "zh"

    # ── Confidence scoring ────────────────────────────────────────────────────
    # We can't be certain a Latin-script title is romanized, so we accumulate
    # evidence and add it up. If the total reaches 0.35 (35%), we call it ROMANIZED.
    #
    # Each clue adds to the score:
    #   • Artist is Japanese → +0.30  (strong signal — Japanese artists have Japanese titles)
    #   • Artist is Korean   → +0.20
    #   • Artist is Chinese  → +0.20
    #   • Title is plain ASCII with an Asian artist → +0.20 (no accents, no script clues)
    #   • Title matches romaji sound patterns → +0.15  (e.g. "no", "ne", doubled vowels)
    #   • langdetect says the title is English (unusual for non-English artist) → +0.15
    romaji_score = 0

    if artist_is_japanese:
        romaji_score += 0.3
    if artist_is_korean:
        romaji_score += 0.2
    if artist_is_chinese:
        romaji_score += 0.2
    if all_ascii and (artist_is_japanese or artist_is_korean or artist_is_chinese):
        romaji_score += 0.2
    if _has_romaji_patterns(title):
        romaji_score += 0.15

    # Use a language-detection library for an extra data point on ambiguous cases
    if all_ascii and (artist_is_japanese or artist_is_korean):
        try:
            from langdetect import detect as langdetect_detect
            title_lang = langdetect_detect(title)
            if title_lang == 'en':
                # The title looks like English → likely translated rather than original
                romaji_score += 0.15
        except Exception:
            pass

    if romaji_score >= 0.35:
        return AnalysisResult(
            title=title, artist=artist,
            classification=Classification.ROMANIZED,
            language=detected_lang, confidence=min(romaji_score, 0.95),
            has_cjk=False, is_romanized_candidate=True,
        )

    # Score too low to call it romanized — could be a genuine English-language
    # release by a non-English artist (many Asian artists release English songs)
    return AnalysisResult(
        title=title, artist=artist,
        classification=Classification.UNKNOWN,
        language=detected_lang, confidence=romaji_score,
        has_cjk=False, is_romanized_candidate=romaji_score >= 0.2,
    )
