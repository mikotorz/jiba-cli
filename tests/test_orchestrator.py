"""Tests for the orchestrator module."""
import json
import pytest
from pathlib import Path

from jiba.orchestrator import save_corrections, load_corrections, match_tracks
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
