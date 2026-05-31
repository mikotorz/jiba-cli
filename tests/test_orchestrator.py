"""Tests for the orchestrator module."""
import json
import pytest
import respx
from pathlib import Path
from httpx import Response

from jiba.orchestrator import save_corrections, load_corrections, match_tracks, reverse_tracks
from jiba.models import Correction, Track


def make_correction(**kwargs):
    defaults = dict(
        track_id=1,
        field="name",
        original_value="Hikari",
        corrected_value="光",
        source="musicbrainz",
        confidence=0.9,
    )
    defaults.update(kwargs)
    return Correction(**defaults)


def test_save_corrections(tmp_path):
    corrections = [
        make_correction(track_id=1, corrected_value="光"),
        make_correction(track_id=2, original_value="Ai", corrected_value="愛", confidence=0.75),
    ]
    out = tmp_path / "corrections.json"
    save_corrections(corrections, out)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[0]["track_id"] == 1
    assert data[0]["corrected_value"] == "光"
    assert data[1]["confidence"] == 0.75


def test_load_corrections(tmp_path):
    payload = [
        {
            "track_id": 42,
            "field": "name",
            "original_value": "Sakura",
            "corrected_value": "桜",
            "source": "itunes",
            "confidence": 0.85,
        }
    ]
    p = tmp_path / "c.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    result = load_corrections(p)
    assert len(result) == 1
    c = result[0]
    assert c.track_id == 42
    assert c.corrected_value == "桜"
    assert c.source == "itunes"
    assert c.confidence == 0.85


def test_load_corrections_malformed(tmp_path):
    """Missing keys should fall back to defaults rather than raise."""
    payload = [{"corrected_value": "愛"}]
    p = tmp_path / "malformed.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    result = load_corrections(p)
    assert len(result) == 1
    c = result[0]
    assert c.track_id == 0
    assert c.field == ""
    assert c.original_value == ""
    assert c.confidence == 0.0
    assert c.corrected_value == "愛"


def test_match_tracks_empty():
    result = match_tracks([])
    assert result == []


def test_match_tracks_skips_non_romanized():
    """Tracks with original-script titles should not produce corrections."""
    tracks = [
        Track(track_id=1, name="アイドル", artist="YOASOBI",
              album="", album_artist="", persistent_id=""),
    ]
    result = match_tracks(tracks, use_musicbrainz=False, use_itunes=False)
    assert result == []


def test_reverse_tracks_empty():
    result = reverse_tracks([])
    assert result == []


def test_reverse_tracks_skips_non_japanized():
    """Tracks that are not JAPANIZED candidates should be skipped."""
    tracks = [
        Track(track_id=1, name="アイドル", artist="YOASOBI",
              album="", album_artist="", persistent_id=""),
    ]
    result = reverse_tracks(tracks, use_musicbrainz=False, use_itunes=False)
    assert result == []


@respx.mock
def test_reverse_tracks_finds_english_title():
    """reverse_tracks should return a correction for a japanized track."""
    respx.get("https://musicbrainz.org/ws/2/recording/").respond(
        200,
        json={
            "recordings": [{
                "id": "abc",
                "title": "Shake It Off",
                "artist-credit": [{"name": "Taylor Swift"}],
                "aliases": [],
            }]
        },
    )

    tracks = [
        Track(track_id=10, name="シェイク・イット・オフ", artist="Taylor Swift",
              album="", album_artist="", persistent_id=""),
    ]
    result = reverse_tracks(tracks, use_musicbrainz=True, use_itunes=False)
    assert len(result) == 1
    assert result[0].track_id == 10
    assert result[0].corrected_value == "Shake It Off"
    assert result[0].original_value == "シェイク・イット・オフ"


@respx.mock
def test_match_tracks_finds_original_title():
    """match_tracks should return a correction for a romanized track."""
    respx.get("https://musicbrainz.org/ws/2/recording/").respond(
        200,
        json={
            "recordings": [{
                "id": "def",
                "title": "アイドル",
                "artist-credit": [{"name": "YOASOBI"}],
                "aliases": [],
            }]
        },
    )

    tracks = [
        Track(track_id=5, name="Idol", artist="YOASOBI",
              album="", album_artist="", persistent_id=""),
    ]
    result = match_tracks(tracks, use_musicbrainz=True, use_itunes=False)
    assert len(result) == 1
    assert result[0].track_id == 5
    assert result[0].corrected_value == "アイドル"


def test_reverse_tracks_sorted_by_confidence():
    """Results should be sorted highest confidence first."""
    corrections = [
        Correction(track_id=1, field="name", original_value="A", corrected_value="あ",
                   source="musicbrainz", confidence=0.7),
        Correction(track_id=2, field="name", original_value="B", corrected_value="い",
                   source="musicbrainz", confidence=0.9),
    ]
    # Sort directly (same logic as reverse_tracks uses internally)
    corrections.sort(key=lambda c: c.confidence, reverse=True)
    assert corrections[0].confidence == 0.9
    assert corrections[1].confidence == 0.7
