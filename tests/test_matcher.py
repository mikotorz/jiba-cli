"""Tests for the metadata matcher (MusicBrainz + iTunes API)."""
import json
import pytest
import respx
from httpx import Response

from jiba.matcher import MusicBrainzClient, iTunesClient
from jiba.models import Correction


class TestMusicBrainzClient:
    @respx.mock
    def test_search_recording_success(self):
        """Should return recordings from MusicBrainz API."""
        route = respx.get("https://musicbrainz.org/ws/2/recording/").respond(
            200,
            json={
                "recordings": [
                    {
                        "id": "abc-123",
                        "title": "アイドル",
                        "artist-credit": [{"name": "YOASOBI"}],
                        "releases": [{"title": "アイドル"}],
                    }
                ]
            },
        )

        client = MusicBrainzClient()
        recordings = client.search_recording("YOASOBI", "Idol")
        assert len(recordings) == 1
        assert recordings[0]["title"] == "アイドル"
        assert route.called

    @respx.mock
    def test_find_original_title_found(self):
        """Should return a Correction when MusicBrainz has original title."""
        respx.get("https://musicbrainz.org/ws/2/recording/").respond(
            200,
            json={
                "recordings": [
                    {
                        "id": "abc-123",
                        "title": "アイドル",
                        "artist-credit": [{"name": "YOASOBI"}],
                    }
                ]
            },
        )

        client = MusicBrainzClient()
        correction = client.find_original_title("YOASOBI", "Idol")
        assert correction is not None
        assert correction.field == "name"
        assert correction.original_value == "Idol"
        assert correction.corrected_value == "アイドル"
        assert correction.source == "musicbrainz"

    @respx.mock
    def test_find_original_title_not_found(self):
        """Should return None when MusicBrainz has no match."""
        respx.get("https://musicbrainz.org/ws/2/recording/").respond(
            200, json={"recordings": []}
        )

        client = MusicBrainzClient()
        correction = client.find_original_title("Unknown Artist", "Unknown Song")
        assert correction is None

    @respx.mock
    def test_find_original_title_uses_aliases(self):
        """Should check aliases for original script titles."""
        respx.get("https://musicbrainz.org/ws/2/recording/").respond(
            200,
            json={
                "recordings": [
                    {
                        "id": "abc-123",
                        "title": "Rocket",
                        "artist-credit": [{"name": "YOASOBI"}],
                        "aliases": [{"name": "ロケット"}],
                    }
                ]
            },
        )

        client = MusicBrainzClient()
        correction = client.find_original_title("YOASOBI", "Rocket")
        assert correction is not None
        assert correction.corrected_value == "ロケット"


class TestiTunesClient:
    @respx.mock
    def test_search_japanese_store(self):
        """Should search Japanese iTunes store and return results."""
        respx.get("https://itunes.apple.com/search").respond(
            200,
            json={
                "resultCount": 1,
                "results": [
                    {
                        "trackName": "アイドル",
                        "artistName": "YOASOBI",
                        "collectionName": "アイドル",
                    }
                ]
            },
        )

        client = iTunesClient()
        results = client.search("YOASOBI Idol", country="JP")
        assert len(results) == 1
        assert results[0]["trackName"] == "アイドル"

    @respx.mock
    def test_find_original_title_jp(self):
        """Should find original Japanese title from JP storefront."""
        def jp_response(request):
            if "country=JP" in str(request.url):
                return Response(200, json={
                    "resultCount": 1,
                    "results": [{
                        "trackName": "夜に駆ける",
                        "artistName": "YOASOBI",
                        "collectionName": "夜に駆ける",
                    }]
                })
            return Response(200, json={"resultCount": 0, "results": []})

        respx.get("https://itunes.apple.com/search").mock(side_effect=jp_response)

        client = iTunesClient()
        correction = client.find_original_title("YOASOBI", "Yoru ni Kakeru", target_langs=["ja"])
        assert correction is not None
        assert correction.corrected_value == "夜に駆ける"
        assert correction.source == "itunes_jp"

    @respx.mock
    def test_find_original_title_not_found(self):
        """Should return None when no CJK titles found."""
        respx.get("https://itunes.apple.com/search").respond(
            200, json={"resultCount": 0, "results": []}
        )

        client = iTunesClient()
        correction = client.find_original_title(
            "English Band", "English Song", target_langs=["ja"]
        )
        assert correction is None
