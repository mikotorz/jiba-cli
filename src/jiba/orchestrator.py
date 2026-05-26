"""Orchestrates metadata matching across multiple sources."""
import json
import warnings
from pathlib import Path
from typing import Optional

from .models import Track, Correction, ScanResult, Classification
from .detector import analyze_title
from .matcher import MusicBrainzClient, iTunesClient


def match_tracks(
    tracks: list[Track],
    target_langs: list[str] | None = None,
    use_musicbrainz: bool = True,
    use_itunes: bool = True,
    progress_callback=None,
) -> list[Correction]:
    """Find original-language titles for romanized/translated tracks.

    Pipeline:
    1. Detect if track needs correction (ROMANIZED or TRANSLATED)
    2. Search MusicBrainz for original title
    3. Fall back to iTunes Store API (CJK storefronts)
    4. Return list of corrections sorted by confidence

    Args:
        tracks: List of tracks to analyze.
        target_langs: Target language codes (e.g., ['ja', 'zh', 'ko']).
        use_musicbrainz: Whether to query MusicBrainz.
        use_itunes: Whether to query iTunes Store API.
        progress_callback: Optional callable for progress updates.

    Returns:
        List of Correction objects.
    """
    if target_langs is None:
        target_langs = ['ja', 'zh', 'ko']

    corrections: list[Correction] = []
    mb_client = MusicBrainzClient() if use_musicbrainz else None
    it_client = iTunesClient() if use_itunes else None
    total = len(tracks)

    try:
        for i, track in enumerate(tracks):
            # Check if this track needs correction
            analysis = analyze_title(track.name, track.artist)
            if not analysis.is_romanized_candidate:
                if progress_callback:
                    progress_callback(i, total, track, None)
                continue

            correction = None

            # Try MusicBrainz first (higher accuracy)
            if mb_client and not correction:
                try:
                    correction = mb_client.find_original_title(track.artist, track.name)
                except Exception as e:
                    warnings.warn(f"MusicBrainz lookup failed for {track.artist} - {track.name}: {e}")

            # Fall back to iTunes API
            if it_client and not correction:
                try:
                    correction = it_client.find_original_title(
                        track.artist, track.name, target_langs
                    )
                except Exception as e:
                    warnings.warn(f"iTunes lookup failed for {track.artist} - {track.name}: {e}")

            if correction:
                correction.track_id = track.track_id
                corrections.append(correction)

            if progress_callback:
                progress_callback(i, total, track, correction)

    finally:
        if mb_client:
            mb_client.close()
        if it_client:
            it_client.close()

    # Sort by confidence (highest first)
    corrections.sort(key=lambda c: c.confidence, reverse=True)
    return corrections


def save_corrections(corrections: list[Correction], path: Path) -> None:
    """Save corrections to a JSON file."""
    data = [
        {
            "track_id": c.track_id,
            "field": c.field,
            "original_value": c.original_value,
            "corrected_value": c.corrected_value,
            "source": c.source,
            "confidence": c.confidence,
        }
        for c in corrections
    ]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_corrections(path: Path) -> list[Correction]:
    """Load corrections from a JSON file."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return [
        Correction(
            track_id=item.get("track_id", 0),
            field=item.get("field", ""),
            original_value=item.get("original_value", ""),
            corrected_value=item.get("corrected_value", ""),
            source=item.get("source", ""),
            confidence=item.get("confidence", 0.0),
        )
        for item in data
    ]
