"""Music metadata matching via MusicBrainz and iTunes Store APIs."""
import json
import time
import unicodedata
from typing import Optional

import httpx

from .models import Track, Correction


def is_ascii_or_latin(text: str) -> bool:
    """Check if text is primarily ASCII or Latin characters (not CJK/kana)."""
    if not text:
        return False
    non_ascii = [c for c in text if ord(c) > 127]
    if not non_ascii:
        return True  # Pure ASCII
    # Check if non-ASCII chars are extended Latin (accents, etc.) not CJK
    for c in non_ascii:
        cp = ord(c)
        # Latin-1 Supplement, Latin Extended-A/B, IPA Extensions
        in_latin = (0x00C0 <= cp <= 0x024F) or cp == 0x00D7 or cp == 0x00F7
        if not in_latin:
            return False
    return True


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

    def find_original_english_title(self, artist: str, title: str) -> Optional[Correction]:
        """Reverse lookup: given a Japanese-kana title, find the original English title.

        Strategy:
        1. Search MusicBrainz for the recording by artist (Latin) + Japanese title
        2. Look for the primary title if it's in Latin script (different from the search term)
        3. Check aliases for Latin-script alternatives

        Args:
            artist: Artist name (in Latin script, e.g. "Taylor Swift").
            title: Japanized title (e.g. "シェイク・イット・オフ").

        Returns:
            Correction with the original Latin/English title, or None.
        """
        recordings = self.search_recording(artist, title)
        if not recordings:
            return None

        for rec in recordings:
            mb_title = rec.get("title", "")
            if not mb_title:
                continue
            # Check if the MB title is in Latin script (original English)
            is_latin = is_ascii_or_latin(mb_title)

            if is_latin and mb_title.lower() != title.lower():
                return Correction(
                    track_id=0,
                    field="name",
                    original_value=title,
                    corrected_value=mb_title,
                    source="musicbrainz",
                    confidence=0.8,
                )
            # Also check aliases
            aliases = rec.get("aliases", [])
            for alias in aliases:
                alias_name = alias.get("name", "")
                if not alias_name:
                    continue
                if is_ascii_or_latin(alias_name) and alias_name.lower() != title.lower():
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
    LOOKUP_URL = "https://itunes.apple.com/lookup"

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

    def find_original_english_title(self, artist: str, title: str) -> Optional[Correction]:
        """Reverse lookup: given a Japanized title, find the original English title via iTunes.

        Strategy:
        1. Search JP store by artist name (Latin script) to find the track
        2. Match it against our Japanized title
        3. Lookup the same trackId in the US store to get the English title

        Args:
            artist: Artist name in Latin script.
            title: Japanized track title (katakana/hiragana/CJK).

        Returns:
            Correction with the original English title, or None.
        """
        URL_LOOKUP = "https://itunes.apple.com/lookup"

        # Step 1: Search JP store by artist to find matching tracks
        results = self.search(artist, country="JP", limit=25)
        if not results:
            return None

        # Step 2: Find the track with a Japanese title matching our input
        # Normalize both titles: remove spaces, normalize unicode width
        def normalize(s: str) -> str:
            s = s.replace(" ", "").replace("　", "")
            s = s.replace("・", "").replace("·", "").replace(".", "")
            s = s.replace("-", "").replace("—", "").replace("–", "")
            s = s.replace("'", "").replace("`", "").replace("ʻ", "")
            s = s.lower()
            return unicodedata.normalize("NFKC", s)

        target_norm = normalize(title)
        matched_track = None

        for result in results:
            track_name = result.get("trackName", "")
            artist_name = result.get("artistName", "")

            # Artist should match
            if artist.lower() not in artist_name.lower() and artist_name.lower() not in artist.lower():
                continue

            track_norm = normalize(track_name)
            # Check if the JP store title contains/is-contained by our target
            if target_norm in track_norm or track_norm in target_norm:
                matched_track = result
                break

        if not matched_track:
            return None

        track_id = matched_track.get("trackId")
        if not track_id:
            return None
        # Step 3: Lookup the same track in US store to get English title
        try:
            resp = self._client.get(
                self.LOOKUP_URL,
                params={"id": track_id, "country": "US", "entity": "song"},
                timeout=10.0,
            )
            resp.raise_for_status()
            us_data = resp.json()
            us_results = us_data.get("results", [])
            if not us_results:
                return None
            for us_item in us_results:
                us_track_name = us_item.get("trackName", "")
                if us_track_name and is_ascii_or_latin(us_track_name):
                    return Correction(
                        track_id=0,
                        field="name",
                        original_value=title,
                        corrected_value=us_track_name,
                        source="itunes_us",
                        confidence=0.7,
                    )
        except Exception:
            pass

        return None

    def close(self):
        self._client.close()
