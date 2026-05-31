"""
Data shapes used throughout jiba-cli.

Think of this file as the vocabulary. Every other file in this project
passes data around using the types defined here. If you want to know
what a "Track" or a "Correction" looks like, this is where to look.

  Track       — one song from the iTunes library (title, artist, album, etc.)
  AnalysisResult — the verdict after inspecting a track's title
                    (is it already in its original language? romanized? etc.)
  Correction  — a proposed rename: "change this field from X to Y"
  ScanResult  — a summary of what a full library scan found
"""
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class Classification(Enum):
    """The verdict for a track title after language detection."""
    ORIGINAL = auto()     # Title is already in its original script (e.g. 恋愛, 사랑)
    ROMANIZED = auto()    # Title was written out in Roman letters (e.g. "Koibito" instead of 恋人)
    TRANSLATED = auto()   # Title was translated into another language (e.g. English instead of Japanese)
    JAPANIZED = auto()    # Apple Music auto-converted a Western song title into Japanese kana
    UNKNOWN = auto()      # Not enough information to decide


@dataclass
class Track:
    """One song from the iTunes Music Library XML."""
    track_id: int           # Internal number iTunes uses to identify the track
    name: str               # Song title
    artist: str
    album: str
    album_artist: str
    persistent_id: str      # A stable ID that stays the same even if track_id changes
    track_type: Optional[str] = None
    location: Optional[str] = None           # File path on disk, if known
    file_folder_count: Optional[int] = None  # iTunes internal bookkeeping fields
    library_folder_count: Optional[int] = None


@dataclass
class AnalysisResult:
    """The result of inspecting one track title."""
    title: str
    artist: str
    classification: Classification            # The verdict (see Classification above)
    language: str                             # Two-letter language code: 'ja'=Japanese, 'ko'=Korean, 'zh'=Chinese, etc.
    confidence: float = 0.0                   # How sure we are (0.0 = no idea, 1.0 = certain)
    has_cjk: bool = False                     # True if the title contains Chinese/Japanese kanji characters
    is_romanized_candidate: bool = False      # True if we suspect this is a romanized/translated title that needs fixing
    is_japanized_candidate: bool = False      # True if we suspect Apple Music auto-converted this title to Japanese


@dataclass
class Correction:
    """A proposed change to one metadata field on one track."""
    track_id: int
    field: str            # Which field to change: 'name', 'artist', 'album', or 'album_artist'
    original_value: str   # The current (wrong) value
    corrected_value: str  # The original-language value we found
    source: str           # Where we found it: 'musicbrainz', 'itunes_jp', 'itunes_us', etc.
    confidence: float     # How confident we are this is correct (0.0–1.0)


@dataclass
class ScanResult:
    """A summary of what was found after scanning the whole library."""
    tracks_scanned: int
    corrections: list[Correction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
