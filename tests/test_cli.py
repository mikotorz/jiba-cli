"""Tests for the CLI commands."""
from pathlib import Path

import pytest
from click.testing import CliRunner

from jiba.cli import cli

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_LIBRARY = FIXTURES_DIR / "sample_library.xml"


@pytest.fixture
def runner():
    return CliRunner()


class TestDetectCommand:
    def test_english_song_not_flagged(self, runner):
        """English title by an English artist should show Unknown/not romanized."""
        result = runner.invoke(cli, ["detect", "Shape of You", "Ed Sheeran"])
        assert result.exit_code == 0
        assert "UNKNOWN" in result.output or "ORIGINAL" in result.output

    def test_japanized_detected(self, runner):
        """Kana title by a Western artist should be classified JAPANIZED."""
        result = runner.invoke(cli, ["detect", "シェイク・イット・オフ", "Taylor Swift"])
        assert result.exit_code == 0
        assert "JAPANIZED" in result.output

    def test_romanized_detected(self, runner):
        """Latin-script title by a known Japanese artist should be ROMANIZED."""
        result = runner.invoke(cli, ["detect", "Idol", "YOASOBI"])
        assert result.exit_code == 0
        assert "ROMANIZED" in result.output

    def test_original_japanese_detected(self, runner):
        """Kana title by a Japanese artist should be ORIGINAL."""
        result = runner.invoke(cli, ["detect", "アイドル", "YOASOBI"])
        assert result.exit_code == 0
        assert "ORIGINAL" in result.output

    def test_no_artist_argument(self, runner):
        """Artist argument is optional — command should not crash without it."""
        result = runner.invoke(cli, ["detect", "アイドル"])
        assert result.exit_code == 0


class TestRollbackCommand:
    def test_no_backups_found(self, runner, tmp_path):
        """Should report no backups when the directory has none."""
        lib = tmp_path / "iTunes Music Library.xml"
        lib.write_bytes(SAMPLE_LIBRARY.read_bytes())

        result = runner.invoke(cli, ["rollback", "--library-path", str(lib)])
        assert result.exit_code == 0
        assert "No backups" in result.output

    def test_missing_library_path(self, runner):
        """Should error when a non-existent path is given."""
        result = runner.invoke(cli, ["rollback", "--library-path", "/nonexistent/path.xml"])
        assert result.exit_code != 0


class TestScanCommand:
    def test_scan_without_match(self, runner):
        """Scan without --match should show the summary table without hitting any API."""
        result = runner.invoke(cli, ["scan", "--library-path", str(SAMPLE_LIBRARY)])
        assert result.exit_code == 0
        assert "Total tracks" in result.output
        assert "4" in result.output  # sample library has 4 tracks

    def test_scan_dry_run(self, runner):
        """Dry-run flag should be accepted without error."""
        result = runner.invoke(
            cli, ["scan", "--library-path", str(SAMPLE_LIBRARY), "--dry-run"]
        )
        assert result.exit_code == 0


class TestReverseCommand:
    def test_reverse_without_match(self, runner):
        """Reverse without --match should show the summary table."""
        result = runner.invoke(cli, ["reverse", "--library-path", str(SAMPLE_LIBRARY)])
        assert result.exit_code == 0
        assert "Total tracks" in result.output
