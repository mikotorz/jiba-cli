"""Language detection for track titles.

Detects whether a track title is in its original script (CJK, Thai, etc.)
or is romanized/translated and needs correction.
"""
import re
import unicodedata

from .models import AnalysisResult, Classification

from langdetect import DetectorFactory
DetectorFactory.seed = 0


# Unicode block ranges for CJK and related scripts
CJK_RANGES = [
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0x3400, 0x4DBF),    # CJK Unified Ideographs Extension A
    (0x2E80, 0x2EFF),    # CJK Radicals Supplement
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
    (0x2F800, 0x2FA1F),  # CJK Compatibility Ideographs Supplement
    (0x3000, 0x303F),    # CJK Symbols and Punctuation
    (0xFF00, 0xFFEF),    # Halfwidth and Fullwidth Forms
]

HIRAGANA_RANGE = (0x3040, 0x309F)
KATAKANA_RANGE = (0x30A0, 0x30FF)
KATAKANA_EXT = (0x31F0, 0x31FF)  # Katakana Phonetic Extensions
HANGUL_RANGES = [
    (0xAC00, 0xD7AF),    # Hangul Syllables
    (0x1100, 0x11FF),    # Hangul Jamo
    (0x3130, 0x318F),    # Hangul Compatibility Jamo
]
THAI_RANGE = (0x0E00, 0x0E7F)


def _in_range(char: str, ranges: list[tuple[int, int]] | tuple[int, int]) -> bool:
    """Check if a character falls within any of the given Unicode ranges."""
    cp = ord(char)
    if isinstance(ranges, tuple) and len(ranges) == 2 and isinstance(ranges[0], int):
        return ranges[0] <= cp <= ranges[1]
    for lo, hi in ranges:
        if lo <= cp <= hi:
            return True
    return False


def has_cjk(text: str) -> bool:
    """Check if text contains any CJK ideograph characters."""
    return any(_in_range(c, CJK_RANGES) for c in text)


def has_kana(text: str) -> bool:
    """Check if text contains Hiragana or Katakana."""
    return any(_in_range(c, HIRAGANA_RANGE) or _in_range(c, KATAKANA_RANGE) or _in_range(c, KATAKANA_EXT) for c in text)


def has_hangul(text: str) -> bool:
    """Check if text contains Hangul (Korean) characters."""
    return any(_in_range(c, HANGUL_RANGES) for c in text)


def has_thai(text: str) -> bool:
    """Check if text contains Thai characters."""
    return any(_in_range(c, THAI_RANGE) for c in text)


def has_latin(text: str) -> bool:
    """Check if text contains Latin alphabet characters (basic)."""
    return any('a' <= c.lower() <= 'z' for c in text)


def is_ascii(text: str) -> bool:
    """Check if all characters in text are ASCII."""
    return all(ord(c) < 128 for c in text)


# Common romaji-suggestive patterns (Japanese romanization)
ROMAJI_PATTERNS = [
    # Common Japanese romanized particles and suffixes
    r'\b(?:no|ni|wa|ga|to|de|o|e|ka|mo|ne|yo|sa|na|shi|tsu|dake|made|koso|demo|suru)\b',
    # Long vowel patterns common in romaji (doubled vowels)
    r'(?:aa|ii|uu|ee|oo)',
    # Typical Japanese consonant+vowel syllable ends
    r'(?:sh[aiueo]|ch[aiueo]|ts[auoe]|nj[ao]|ry[auo]|ky[auo]|gy[auo]|hy[auo]|my[auo]|py[auo]|by[auo])',
    # Common romaji song title keywords
    r'\b(?:feat|feat\.|with|remix|version|edit|mix|radio|live|acoustic|instrumental)\b',
]

# Common romanized artist keywords for Japanese music
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

# Heuristic: ratio of non-ASCII characters needed to be considered "original script"
ORIGINAL_SCRIPT_RATIO_THRESHOLD = 0.3

# Common Western keywords in artist names — gives high confidence they're not Japanese
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
    """Check if artist name is clearly Western (Latin script, not a known Japanese/Korean/Chinese artist)."""
    artist_lower = artist.lower().strip()
    # If artist has Japanese kana/CJK itself, not Western
    if has_kana(artist_lower) or has_cjk(artist_lower) or has_hangul(artist_lower):
        return False
    # Check known Western artists
    if _matches_indicators(artist_lower, WESTERN_ARTIST_INDICATORS):
        return True
    # If artist is all ASCII/Latin and not known Japanese/Korean/Chinese → likely Western
    if is_ascii(artist_lower) or has_latin(artist_lower):
        # Don't flag if it matches known non-Western artists
        if _matches_indicators(artist_lower, JAPANESE_ARTIST_INDICATORS):
            return False
        if _matches_indicators(artist_lower, KOREAN_ARTIST_INDICATORS):
            return False
        if has_kana(artist_lower) or has_cjk(artist_lower):
            return False
        # Has Latin script and no CJK/kana/hangul → likely Western
        if len(artist_lower) > 2 and has_latin(artist_lower):
            return True
    return False


def _matches_indicators(text: str, indicators: list[str]) -> bool:
    """Check if text matches any indicator with word boundaries (prevents 'ado' matching 'shadow')."""
    for indicator in indicators:
        if re.search(r'\b' + re.escape(indicator) + r'\b', text, re.IGNORECASE):
            return True
    return False


def _artist_suggests_japanese(artist: str) -> bool:
    """Check if artist name suggests Japanese music."""
    artist_lower = artist.lower().strip()
    # If artist name itself contains CJK/kana, it's Japanese
    if has_kana(artist_lower) or has_cjk(artist_lower):
        return True
    # Check known Japanese artist patterns with word boundaries
    return _matches_indicators(artist_lower, JAPANESE_ARTIST_INDICATORS)


def _artist_suggests_korean(artist: str) -> bool:
    """Check if artist name suggests Korean music."""
    artist_lower = artist.lower().strip()
    if has_hangul(artist_lower):
        return True
    return _matches_indicators(artist_lower, KOREAN_ARTIST_INDICATORS)


def _artist_suggests_chinese(artist: str) -> bool:
    """Check if artist name suggests Chinese music."""
    artist_lower = artist.lower().strip()
    if _artist_suggests_japanese(artist_lower):
        return False
    if has_cjk(artist_lower) and not has_kana(artist_lower):
        return True
    return _matches_indicators(artist_lower, CHINESE_ARTIST_INDICATORS)


def _has_romaji_patterns(text: str) -> bool:
    """Check if text matches typical romaji patterns."""
    text_lower = text.lower()
    return any(re.search(p, text_lower, re.IGNORECASE) for p in ROMAJI_PATTERNS)


def analyze_title(title: str, artist: str = "") -> AnalysisResult:
    """Analyze a track title to determine if it needs language correction.

    Args:
        title: The track title to analyze.
        artist: The artist name (provides context for language detection).

    Returns:
        AnalysisResult with classification and detection details.
    """
    title = title or ""
    artist = artist or ""

    has_kana_chars = has_kana(title)
    has_hangul_chars = has_hangul(title)
    has_thai_chars = has_thai(title)
    has_latin_chars = has_latin(title)
    all_ascii = is_ascii(title)

    # Determine likely language from title characters
    detected_lang = ""
    confidence = 0.0

    # If title already has CJK characters (significant amount)
    cjk_ratio = sum(1 for c in title if _in_range(c, CJK_RANGES)) / max(len(title), 1)

    if has_kana_chars:
        # Contains Japanese kana — could be original Japanese or japanized (Apple Music auto-conversion)
        if not artist.strip():
            # Can't determine artist origin — return UNKNOWN
            return AnalysisResult(
                title=title, artist=artist,
                classification=Classification.UNKNOWN,
                language="ja", confidence=0.2,
                has_cjk=has_cjk(title), is_romanized_candidate=False,
            )
        artist_is_western = _artist_is_western(artist)
        if artist_is_western or not (_artist_suggests_japanese(artist) or _artist_suggests_korean(artist)):
            # Western artist + Japanese kana title → Apple Music auto-converted it
            return AnalysisResult(
                title=title, artist=artist,
                classification=Classification.JAPANIZED,
                language="ja", confidence=0.85,
                has_cjk=has_cjk(title), is_romanized_candidate=False,
                is_japanized_candidate=True,
            )
        # Japanese/Asian artist with kana → original Japanese
        detected_lang = "ja"
        confidence = 0.95
        return AnalysisResult(
            title=title, artist=artist,
            classification=Classification.ORIGINAL,
            language="ja", confidence=confidence,
            has_cjk=has_cjk(title), is_romanized_candidate=False,
        )
    elif has_hangul_chars:
        detected_lang = "ko"
        confidence = 0.95
        return AnalysisResult(
            title=title, artist=artist,
            classification=Classification.ORIGINAL,
            language="ko", confidence=confidence,
            has_cjk=False, is_romanized_candidate=False,
        )
    elif has_thai_chars:
        detected_lang = "th"
        confidence = 0.95
        return AnalysisResult(
            title=title, artist=artist,
            classification=Classification.ORIGINAL,
            language="th", confidence=confidence,
            has_cjk=False, is_romanized_candidate=False,
        )
    elif cjk_ratio >= ORIGINAL_SCRIPT_RATIO_THRESHOLD:
        # Significant CJK content — likely original Chinese
        detected_lang = "zh"
        confidence = min(0.8 + cjk_ratio, 0.95)
        return AnalysisResult(
            title=title, artist=artist,
            classification=Classification.ORIGINAL,
            language="zh", confidence=confidence,
            has_cjk=True, is_romanized_candidate=False,
        )

    # Title is in Latin/ASCII — could be original English or romanized/translated
    if not has_latin_chars and not title.strip():
        # Empty or no recognizable characters
        return AnalysisResult(
            title=title, artist=artist,
            classification=Classification.UNKNOWN,
            language="", confidence=0.0,
            has_cjk=False, is_romanized_candidate=False,
        )

    # Determine if it's a romanization/translation candidate
    artist_is_japanese = _artist_suggests_japanese(artist)
    artist_is_korean = _artist_suggests_korean(artist)
    artist_is_chinese = _artist_suggests_chinese(artist)

    if artist_is_japanese:
        detected_lang = "ja"
    elif artist_is_korean:
        detected_lang = "ko"
    elif artist_is_chinese:
        detected_lang = "zh"

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

    # Detect translated titles (English title from non-English artist)
    if all_ascii and (artist_is_japanese or artist_is_korean):
        # Use langdetect for more precise detection
        try:
            from langdetect import detect as langdetect_detect
            title_lang = langdetect_detect(title)
            if title_lang == 'en':
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

    # Not clearly romanized, not original CJK
    # Could be a legitimate English title by a non-English artist
    return AnalysisResult(
        title=title, artist=artist,
        classification=Classification.UNKNOWN,
        language=detected_lang, confidence=romaji_score,
        has_cjk=False, is_romanized_candidate=romaji_score >= 0.2,
    )
