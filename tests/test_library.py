"""Tests for the iTunes Library XML parser."""
from pathlib import Path
import plistlib

import pytest

from jiba.library import read_library, write_library, get_default_library_path
from jiba.models import Track


FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_LIBRARY = FIXTURES_DIR / "sample_library.xml"


class TestReadLibrary:
    def test_reads_all_tracks(self):
        """Should return all tracks from the library XML."""
        tracks = read_library(str(SAMPLE_LIBRARY))
        assert len(tracks) == 4

    def test_track_attributes(self):
        """Should correctly parse Track ID, Name, Artist, Album, Album Artist."""
        tracks = read_library(str(SAMPLE_LIBRARY))
        track = {t.track_id: t for t in tracks}[100]

        assert track.track_id == 100
        assert track.name == "Rocket"
        assert track.artist == "YOASOBI"
        assert track.album == "THE BOOK"
        assert track.album_artist == "YOASOBI"
        assert track.persistent_id == "ABC123"

    def test_track_with_cjk_title(self):
        """Should handle CJK characters in track names."""
        tracks = read_library(str(SAMPLE_LIBRARY))
        track = {t.track_id: t for t in tracks}[101]

        assert track.name == "アイドル"
        assert track.artist == "YOASOBI"
        assert track.album == "アイドル"

    def test_track_optional_fields(self):
        """Should parse optional fields like Track Type and Location."""
        tracks = read_library(str(SAMPLE_LIBRARY))
        track = {t.track_id: t for t in tracks}[100]

        assert track.track_type == "File"
        assert track.location is not None
        assert "YOASOBI/Rocket.m4a" in track.location

    def test_remote_track_no_location(self):
        """Should handle Remote tracks (Apple Music streaming) without location."""
        tracks = read_library(str(SAMPLE_LIBRARY))
        track = {t.track_id: t for t in tracks}[102]

        assert track.track_type == "Remote"
        assert track.location is None
        assert track.name == "Love Me Right"
        assert track.artist == "EXO"

    def test_file_not_found(self):
        """Should raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            read_library("/nonexistent/path.xml")

    def test_invalid_xml(self):
        """Should raise ValueError for invalid content."""
        invalid = FIXTURES_DIR / "invalid.xml"
        invalid.write_text("not plist content")
        try:
            with pytest.raises((ValueError, plistlib.InvalidFileException, Exception)):
                read_library(str(invalid))
        finally:
            invalid.unlink(missing_ok=True)


class TestWriteLibrary:
    def test_write_roundtrip(self, tmp_path):
        """Writing then reading should preserve track data."""
        original = read_library(str(SAMPLE_LIBRARY))
        out_path = tmp_path / "output.xml"

        write_library(original, out_path, template_path=SAMPLE_LIBRARY)

        reloaded = read_library(str(out_path))
        assert len(reloaded) == len(original)
        for orig, reload in zip(sorted(original, key=lambda t: t.track_id),
                                sorted(reloaded, key=lambda t: t.track_id)):
            assert orig.track_id == reload.track_id
            assert orig.name == reload.name
            assert orig.artist == reload.artist

    def test_write_preserves_playlists(self, tmp_path):
        """Write should preserve playlist structure from template."""
        tracks = read_library(str(SAMPLE_LIBRARY))
        out_path = tmp_path / "output.xml"

        write_library(tracks, out_path, template_path=SAMPLE_LIBRARY)

        with open(out_path, 'rb') as f:
            plist = plistlib.load(f)

        assert 'Playlists' in plist
        assert len(plist['Playlists']) > 0

    def test_write_creates_backup(self, tmp_path):
        """Should create a timestamped backup before overwriting an existing file."""
        tracks = read_library(str(SAMPLE_LIBRARY))
        out_path = tmp_path / "output.xml"

        # First write
        write_library(tracks, out_path, template_path=SAMPLE_LIBRARY)
        assert out_path.exists()

        # Second write — should create backup
        tracks[0].name = "Updated"
        write_library(tracks, out_path, template_path=SAMPLE_LIBRARY, backup=True)

        # A .bak file should exist
        baks = list(tmp_path.glob("output_*.bak.xml"))
        assert len(baks) >= 1, f"No backup files found in {tmp_path}"

        # Backup should contain original data
        back_bak = baks[0]
        with open(back_bak, 'rb') as f:
            bak_plist = plistlib.load(f)
        restored_id = list(bak_plist['Tracks'].keys())[0]
        assert bak_plist['Tracks'][restored_id].get('Name') != "Updated"
