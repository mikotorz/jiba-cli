"""Tests for the language detector module."""
import pytest

from jiba.detector import (
    analyze_title, has_cjk, has_kana, has_hangul, has_thai,
    is_ascii, has_latin,
)
from jiba.models import Classification


class TestUnicodeHelpers:
    def test_has_cjk(self):
        assert has_cjk("日本語") is True  # kanji
        assert has_cjk("アイドル") is False  # katakana only
        assert has_cjk("中文") is True
        assert has_cjk("한국어") is False  # hangul, not CJK
        assert has_cjk("English") is False

    def test_has_kana(self):
        assert has_kana("ひらがな") is True
        assert has_kana("カタカナ") is True
        assert has_kana("日本語") is False  # mostly kanji
        assert has_kana("English") is False

    def test_has_hangul(self):
        assert has_hangul("한국어") is True
        assert has_hangul("日本語") is False
        assert has_hangul("English") is False

    def test_has_thai(self):
        assert has_thai("ภาษาไทย") is True
        assert has_thai("日本語") is False
        assert has_thai("English") is False

    def test_is_ascii(self):
        assert is_ascii("Hello World") is True
        assert is_ascii("Pokémon") is False  # é is non-ASCII
        assert is_ascii("日本語") is False

    def test_has_latin(self):
        assert has_latin("Hello") is True
        assert has_latin("日本語") is False
        assert has_latin("Mix of 日本語 and English") is True


class TestAnalyzeTitle:
    def test_japanese_kana_title(self):
        """Track with kana should be ORIGINAL Japanese."""
        result = analyze_title("アイドル", "YOASOBI")
        assert result.classification == Classification.ORIGINAL
        assert result.language == "ja"
        assert result.has_cjk is False
        assert result.is_romanized_candidate is False
        assert result.confidence >= 0.9

    def test_japanese_kanji_title(self):
        """Track with kanji should be ORIGINAL."""
        result = analyze_title("夜に駆ける", "YOASOBI")
        assert result.classification == Classification.ORIGINAL
        assert result.language == "ja"
        assert result.has_cjk is True

    def test_korean_hangul_title(self):
        """Track with hangul should be ORIGINAL Korean."""
        result = analyze_title("봄날", "BTS")
        assert result.classification == Classification.ORIGINAL
        assert result.language == "ko"
        assert result.has_cjk is False

    def test_chinese_title(self):
        """Track with significant CJK should be ORIGINAL Chinese."""
        result = analyze_title("晴天", "Jay Chou")
        assert result.classification == Classification.ORIGINAL
        assert result.language == "zh"
        assert result.has_cjk is True

    def test_thai_title(self):
        """Track with Thai script should be ORIGINAL."""
        result = analyze_title("รักแรก", "NONT TANONT")
        assert result.classification == Classification.ORIGINAL
        assert result.language == "th"

    def test_romanized_japanese_title(self):
        """Romanized Japanese by a Japanese artist should be flagged."""
        result = analyze_title("Rocket", "YOASOBI")
        assert result.classification == Classification.ROMANIZED
        assert result.is_romanized_candidate is True
        assert result.has_cjk is False

    def test_romanized_korean_title(self):
        """Romanized Korean by a Korean artist should be flagged."""
        result = analyze_title("Love Me Right", "EXO")
        assert result.classification == Classification.ROMANIZED
        assert result.is_romanized_candidate is True

    def test_english_artist_english_title(self):
        """English title by English artist should NOT be flagged."""
        result = analyze_title("Shape of You", "Ed Sheeran")
        # Unknown — not clearly romanized
        assert result.is_romanized_candidate is False

    def test_mixed_script_title(self):
        """Mixed script title with parenthetical Japanese."""
        result = analyze_title("いつか (Someday)", "Mrs. GREEN APPLE")
        assert result.classification == Classification.ORIGINAL
        assert result.language == "ja"

    def test_empty_title(self):
        """Empty title should return UNKNOWN."""
        result = analyze_title("", "Some Artist")
        assert result.classification == Classification.UNKNOWN
        assert result.is_romanized_candidate is False

    def test_romaji_pattern_detection(self):
        """Title with typical romaji patterns should be detected."""
        # 'No' is a Japanese particle commonly in song titles
        result = analyze_title("Am I Nothing No More", "YOASOBI")
        assert result.is_romanized_candidate is True

    def test_japanese_artist_no_name(self):
        """Artist name detection works even with minimal artist string."""
        # Even partial match on known artist should work
        result = analyze_title("Polaroid", "Yorushika")
        assert result.is_romanized_candidate is True

    def test_long_vowel_romaji(self):
        """Doubled vowels (ou, aa, ii, uu, ee) suggest romaji."""
        result = analyze_title("Ookami", "YOASOBI")
        assert result.is_romanized_candidate is True

    def test_artist_with_cjk_suggests_japanese(self):
        """Artist name in CJK/kana suggests the title may be romanized."""
        result = analyze_title("Rocket", "米津玄師")
        assert result.is_romanized_candidate is True
