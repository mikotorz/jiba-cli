"""Data models for jiba-cli."""
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class Classification(Enum):
    ORIGINAL = auto()     # Already in original script
    ROMANIZED = auto()    # Romanized (e.g., romaji)
    TRANSLATED = auto()   # Translated into another language
    JAPANIZED = auto()    # Auto-converted TO Japanese by Apple Music
    UNKNOWN = auto()      # Can't determine


@dataclass
class Track:
    """A track from the iTunes Music Library."""
    track_id: int
    name: str
    artist: str
    album: str
    album_artist: str
    persistent_id: str
    track_type: Optional[str] = None
    location: Optional[str] = None
    file_folder_count: Optional[int] = None
    library_folder_count: Optional[int] = None


@dataclass
class AnalysisResult:
    """Result of analyzing a track title's language characteristics."""
    title: str
    artist: str
    classification: Classification
    language: str  # ISO 639-1 code or empty
    confidence: float = 0.0
    has_cjk: bool = False
    is_romanized_candidate: bool = False
    is_japanized_candidate: bool = False  # Japanese script title by Western artist


@dataclass
class Correction:
    """A proposed metadata correction for a track."""
    track_id: int
    field: str  # 'name', 'artist', 'album', 'album_artist'
    original_value: str
    corrected_value: str
    source: str  # 'musicbrainz', 'itunes', 'heuristic'
    confidence: float  # 0.0 - 1.0


@dataclass
class ScanResult:
    """Result of a full library scan."""
    tracks_scanned: int
    corrections: list[Correction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
