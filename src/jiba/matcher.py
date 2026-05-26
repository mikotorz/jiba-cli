"""Music metadata matching via MusicBrainz and iTunes Store APIs."""
import json
import time
from typing import Optional

import httpx

from .models import Track, Correction


USER_AGENT = "jiba-cli/0.1.0 (https://github.com/mikotorz/jiba-cli)"


class MusicBrainzClient:
    """Client for the MusicBrainz API (free, open music database)."""

    BASE_URL = "https://musicbrainz.org/ws/2"
    # Rate limit: 1 request per second
    MIN_INTERVAL = 1.0

    def __init__(self):
        self._client = httpx.Client(headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        self._last_request = 0.0

    def _rate_limit(self):
        """Ensure at least 1 second between requests (MusicBrainz policy)."""
        elapsed = time.time() - self._last_request
        if elapsed < self.MIN_INTERVAL:
            time.sleep(self.MIN_INTERVAL - elapsed)
        self._last_request = time.time()

    def search_recording(self, artist: str, title: str, limit: int = 5) -> list[dict]:
        """Search for a recording by artist and title.

        Returns:
            List of recording dicts from MusicBrainz.
        """
        self._rate_limit()
        query = f'artist:"{artist}" AND recording:"{title}"'
        params = {
            "query": query,
            "fmt": "json",
            "limit": limit,
            "inc": "aliases",
        }
        try:
            resp = self._client.get(
                f"{self.BASE_URL}/recording/",
                params=params,
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("recordings", [])
        except Exception as e:
            raise RuntimeError(f"MusicBrainz search failed: {e}") from e

    def find_original_title(self, artist: str, title: str) -> Optional[Correction]:
        """Search MusicBrainz for a track's original-language title.

        Strategy:
        1. Search for the recording by artist + title
        2. Check if the recording has an alias or different title
           in a non-Latin script
        3. Return the original title if found

        Args:
            artist: Current artist name.
            title: Current romanized/translated title.

        Returns:
            Correction if a better title is found, or None.
        """
        recordings = self.search_recording(artist, title)
        if not recordings:
            return None

        # Look at the top result
        rec = recordings[0]
        mb_title = rec.get("title", "")

        # If MusicBrainz already has a different (non-ASCII) title, use it
        if mb_title and mb_title.lower() != title.lower():
            has_non_ascii = any(ord(c) > 127 for c in mb_title)
            if has_non_ascii:
                return Correction(
                    track_id=0,  # Will be set by caller
                    field="name",
                    original_value=title,
                    corrected_value=mb_title,
                    source="musicbrainz",
                    confidence=0.8,
                )

        # Check if there are aliases (alternative spellings)
        aliases = rec.get("aliases", [])
        for alias in aliases:
            alias_name = alias.get("name", "")
            if alias_name and any(ord(c) > 127 for c in alias_name):
                return Correction(
                    track_id=0,
                    field="name",
                    original_value=title,
                    corrected_value=alias_name,
                    source="musicbrainz",
                    confidence=0.7,
                )

        return None

    def close(self):
        self._client.close()


class iTunesClient:
    """Client for the iTunes Store Search API.

    The iTunes API returns localized metadata. Searching a Japanese storefront
    (country=JP) will return Japanese titles when available.
    """

    BASE_URL = "https://itunes.apple.com/search"

    # Country codes for CJK storefronts
    CJK_COUNTRIES = ["JP", "KR", "CN", "HK", "TW", "TH"]

    def __init__(self):
        self._client = httpx.Client(headers={
            "User-Agent": USER_AGENT,
        })

    def search(self, term: str, country: str = "US", limit: int = 5) -> list[dict]:
        """Search iTunes Store for a track.

        Args:
            term: Search term (artist + title).
            country: Two-letter country code (e.g., 'JP', 'KR', 'US').
            limit: Max results.

        Returns:
            List of result dicts.
        """
        params = {
            "term": term,
            "entity": "song",
            "country": country,
            "limit": limit,
            "media": "music",
        }
        try:
            resp = self._client.get(self.BASE_URL, params=params, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])
        except Exception as e:
            raise RuntimeError(f"iTunes search failed for country={country}: {e}") from e

    def find_original_title(
        self, artist: str, title: str, target_langs: list[str] | None = None
    ) -> Optional[Correction]:
        """Search CJK storefronts for a track's original title.

        Searches Japanese, Korean, Chinese (HK/TW) storefronts for
        matching tracks with original-language titles.

        Args:
            artist: Current artist name.
            title: Current romanized/translated title.
            target_langs: List of target language codes.

        Returns:
            Correction if found, or None.
        """
        if target_langs is None:
            target_langs = ["ja", "zh", "ko"]

        # Map languages to iTunes storefronts
        lang_country_map = {
            "ja":   ["JP"],
            "ko":   ["KR"],
            "zh":   ["CN", "HK", "TW"],
            "th":   ["TH"],
        }

        search_term = f"{artist} {title}"

        for lang in target_langs:
            countries = lang_country_map.get(lang, [])
            for country in countries:
                results = self.search(search_term, country=country)
                for result in results:
                    track_name = result.get("trackName", "")
                    if not track_name:
                        continue

                    # Check if this title has non-ASCII characters
                    # (original script vs romanized)
                    has_script = any(ord(c) > 127 for c in track_name)

                    # Also check collection/album name
                    collection = result.get("collectionName", "")
                    has_script_collection = any(ord(c) > 127 for c in (collection or ""))

                    if has_script:
                        return Correction(
                            track_id=0,
                            field="name",
                            original_value=title,
                            corrected_value=track_name,
                            source=f"itunes_{country.lower()}",
                            confidence=0.6,
                        )

        return None

    def close(self):
        self._client.close()
