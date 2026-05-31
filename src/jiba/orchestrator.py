"""
Coordinates the full scan-and-match pipeline.

This file is the glue between the detector (detector.py) and the API clients
(matcher.py). When you run `jiba scan --match` or `jiba reverse --match`,
the CLI calls the functions here to process all tracks in bulk.

There are two main pipelines:

  match_tracks()   — Forward direction: find original-script titles for tracks
                     whose titles have been romanized or translated into English.
                     e.g.  "Yoru ni Kakeru"  →  夜に駆ける

  reverse_tracks() — Reverse direction: find original English titles for tracks
                     that Apple Music auto-converted to Japanese.
                     e.g.  シェイク・イット・オフ  →  "Shake It Off"

Both pipelines follow the same pattern for each track:
  1. Run the detector to decide if the track needs correction.
  2. Try MusicBrainz first (more accurate).
  3. Fall back to iTunes Store API if MusicBrainz finds nothing.
  4. Collect all corrections and return them sorted by confidence.

The save/load functions here let you write corrections to a JSON file so you
can review them before applying with `jiba apply`.
"""
import json
import warnings
from pathlib import Path
from typing import Optional

from .models import Track, Correction
from .detector import analyze_title
from .matcher import MusicBrainzClient, iTunesClient


def match_tracks(
    tracks: list[Track],
    target_langs: list[str] | None = None,
    use_musicbrainz: bool = True,
    use_itunes: bool = True,
    progress_callback=None,
) -> list[Correction]:
    """
    For each track in the list, look up its original-language title.

    Only processes tracks that the detector flags as romanized candidates.
    Returns a list of Correction objects sorted by confidence (highest first).

    progress_callback, if provided, is called after each track is processed.
    It receives: (current_index, total_tracks, track, correction_or_None).
    """
    if target_langs is None:
        target_langs = ['ja', 'zh', 'ko']

    corrections: list[Correction] = []
    mb_client = MusicBrainzClient() if use_musicbrainz else None
    it_client = iTunesClient() if use_itunes else None
    total = len(tracks)

    try:
        for i, track in enumerate(tracks):
            # Skip tracks the detector says don't need correction
            analysis = analyze_title(track.name, track.artist)
            if not analysis.is_romanized_candidate:
                if progress_callback:
                    progress_callback(i, total, track, None)
                continue

            correction = None

            # Try MusicBrainz first (community database, higher accuracy)
            if mb_client and not correction:
                try:
                    correction = mb_client.find_original_title(track.artist, track.name)
                except Exception as e:
                    warnings.warn(f"MusicBrainz lookup failed for {track.artist} - {track.name}: {e}")

            # Fall back to iTunes Store API (searches regional storefronts)
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
        # Always close the HTTP clients, even if an error occurred mid-scan
        if mb_client:
            mb_client.close()
        if it_client:
            it_client.close()

    corrections.sort(key=lambda c: c.confidence, reverse=True)
    return corrections


def reverse_tracks(
    tracks: list[Track],
    use_musicbrainz: bool = True,
    use_itunes: bool = True,
    progress_callback=None,
) -> list[Correction]:
    """
    For each track in the list, find the original English title that Apple Music
    replaced with a Japanese one.

    Only processes tracks the detector flags as japanized candidates (Japanese-kana
    title by a Western artist). Returns corrections sorted by confidence.
    """
    corrections: list[Correction] = []
    mb_client = MusicBrainzClient() if use_musicbrainz else None
    it_client = iTunesClient() if use_itunes else None
    total = len(tracks)

    try:
        for i, track in enumerate(tracks):
            # Skip tracks that don't look japanized
            analysis = analyze_title(track.name, track.artist)
            if not analysis.is_japanized_candidate:
                if progress_callback:
                    progress_callback(i, total, track, None)
                continue

            correction = None

            # Try MusicBrainz first
            if mb_client and not correction:
                try:
                    correction = mb_client.find_original_english_title(track.artist, track.name)
                except Exception as e:
                    warnings.warn(f"MusicBrainz reverse lookup failed for {track.artist} - {track.name}: {e}")

            # Fall back to iTunes two-step lookup (JP store → US store)
            if it_client and not correction:
                try:
                    correction = it_client.find_original_english_title(track.artist, track.name)
                except Exception as e:
                    warnings.warn(f"iTunes reverse lookup failed for {track.artist} - {track.name}: {e}")

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

    corrections.sort(key=lambda c: c.confidence, reverse=True)
    return corrections


def save_corrections(corrections: list[Correction], path: Path) -> None:
    """
    Save a list of corrections to a JSON file so they can be reviewed
    and applied later with `jiba apply`.
    """
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
    """Load a previously saved corrections JSON file and return the Correction objects."""
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
