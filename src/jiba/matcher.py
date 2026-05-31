"""
Music metadata lookup via MusicBrainz and the iTunes Store API.

Once the detector (detector.py) has flagged a track as romanized or japanized,
this file is responsible for finding the correct original-language title.

Two data sources are used:

  MusicBrainzClient — queries MusicBrainz (musicbrainz.org), a free, community-
      maintained music encyclopedia. It often stores multiple versions of a title
      (original script + romanized aliases), which makes it ideal for this purpose.
      MusicBrainz requires at most 1 request per second, so we enforce that limit.

  iTunesClient — queries the iTunes Store search API. By searching the Japanese (JP),
      Korean (KR), or Chinese (CN/HK/TW) storefronts, we can retrieve the
      original-language titles that Apple Music shows in those regions.
      For the reverse direction (japanized → English), we do a two-step lookup:
        Step 1: Search the JP store for the artist to find the track and its ID.
        Step 2: Look up that same track ID in the US store to get the English title.

Both clients return a Correction object (defined in models.py) when they find
a better title, or None if they come up empty.
"""
import json
import time
import unicodedata
from typing import Optional

import httpx

from .models import Track, Correction


def is_ascii_or_latin(text: str) -> bool:
    """
    Return True if the text is written entirely in the Latin alphabet.

    "Latin" here includes plain ASCII (A–Z) plus accented characters like
    é, ü, ñ — but NOT Japanese, Korean, or Chinese characters.
    This is used to check whether a title is in English/European script.
    """
    if not text:
        return False
    non_ascii = [c for c in text if ord(c) > 127]
    if not non_ascii:
        return True  # Pure ASCII
    # Check if the non-ASCII characters are extended Latin (accents, etc.) not CJK
    for c in non_ascii:
        cp = ord(c)
        # Latin-1 Supplement, Latin Extended-A/B — the blocks that cover accented
        # European letters. Characters outside these blocks (e.g. kanji) are excluded.
        in_latin = (0x00C0 <= cp <= 0x024F) or cp == 0x00D7 or cp == 0x00F7
        if not in_latin:
            return False
    return True


# Identifies this tool to external APIs (good practice; MusicBrainz requires it)
USER_AGENT = "jiba-cli/0.1.0 (https://github.com/mikotorz/jiba-cli)"


class MusicBrainzClient:
    """
    Queries the MusicBrainz open music database for original-language titles.

    MusicBrainz (musicbrainz.org) is a free, community-maintained encyclopedia
    of music metadata. It often stores a song under its original-script title AND
    keeps romanized versions as "aliases", which makes it very useful for this tool.

    Usage limit: MusicBrainz allows at most 1 request per second. We enforce this
    automatically with the _rate_limit() method.
    """

    BASE_URL = "https://musicbrainz.org/ws/2"
    MIN_INTERVAL = 1.0  # Seconds to wait between requests (MusicBrainz policy)

    def __init__(self):
        self._client = httpx.Client(headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        self._last_request = 0.0

    def _rate_limit(self):
        """Wait if needed so we don't send requests faster than once per second."""
        elapsed = time.time() - self._last_request
        if elapsed < self.MIN_INTERVAL:
            time.sleep(self.MIN_INTERVAL - elapsed)
        self._last_request = time.time()

    def search_recording(self, artist: str, title: str, limit: int = 5) -> list[dict]:
        """
        Search MusicBrainz for a recording that matches the given artist and title.

        Returns a list of raw result dictionaries from the MusicBrainz API.
        Each dict contains the title, any aliases, and other metadata.
        """
        self._rate_limit()
        query = f'artist:"{artist}" AND recording:"{title}"'
        params = {
            "query": query,
            "fmt": "json",
            "limit": limit,
            "inc": "aliases",  # Also fetch alternative title spellings
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
        """
        Given a romanized or translated title, search MusicBrainz for the
        original-script version (e.g. kanji/kana for Japanese songs).

        Strategy:
          1. Search for the recording by artist + title.
          2. Check if MusicBrainz's primary title for the top result is
             different from ours AND contains non-Latin characters.
             If so, that's the original-script title we want.
          3. If the primary title is the same, check the "aliases" list
             (alternative spellings) for a non-Latin version.

        Returns a Correction if a better title is found, or None.
        """
        recordings = self.search_recording(artist, title)
        if not recordings:
            return None

        rec = recordings[0]  # Use the top (most relevant) search result
        mb_title = rec.get("title", "")

        # If MusicBrainz stores a different title with non-Latin characters → use it
        if mb_title and mb_title.lower() != title.lower():
            has_non_ascii = any(ord(c) > 127 for c in mb_title)
            if has_non_ascii:
                return Correction(
                    track_id=0,  # Will be filled in by the caller
                    field="name",
                    original_value=title,
                    corrected_value=mb_title,
                    source="musicbrainz",
                    confidence=0.8,
                )

        # Check the aliases (alternative spellings stored by contributors)
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
        """
        Reverse lookup: given a japanized title (kana/kanji), find the original
        English title for a Western artist.

        Strategy:
          1. Search MusicBrainz for the recording using the Japanese title.
          2. Look through the results for a primary title that is in Latin script.
          3. If the primary title is also Japanese, check aliases for a Latin version.

        Returns a Correction with the original English title, or None.
        """
        recordings = self.search_recording(artist, title)
        if not recordings:
            return None

        for rec in recordings:
            mb_title = rec.get("title", "")
            if not mb_title:
                continue
            # If the MusicBrainz title is in Latin script and different from our input,
            # it's the original English title
            if is_ascii_or_latin(mb_title) and mb_title.lower() != title.lower():
                return Correction(
                    track_id=0,
                    field="name",
                    original_value=title,
                    corrected_value=mb_title,
                    source="musicbrainz",
                    confidence=0.8,
                )
            # Also check aliases for a Latin-script alternative
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
    """
    Queries the iTunes Store Search API for original-language titles.

    The iTunes Store exists in many regional versions (storefronts). When you
    search the Japanese storefront (country=JP), Apple returns Japanese titles.
    When you search the US storefront (country=US), you get English titles.
    We exploit this to find the original title for a track.

    Forward lookup (romanized → original):
      Search the CJK storefronts (JP, KR, CN, HK, TW) and return the first
      result whose title contains non-Latin characters.

    Reverse lookup (japanized → English):
      Two-step process:
        Step 1 — Search the JP store by artist name to find the track and
                  get its iTunes track ID (a number that's the same in all stores).
        Step 2 — Look up that track ID in the US store to get the English title.
    """

    BASE_URL = "https://itunes.apple.com/search"
    LOOKUP_URL = "https://itunes.apple.com/lookup"

    CJK_COUNTRIES = ["JP", "KR", "CN", "HK", "TW", "TH"]

    def __init__(self):
        self._client = httpx.Client(headers={
            "User-Agent": USER_AGENT,
        })

    def search(self, term: str, country: str = "US", limit: int = 5) -> list[dict]:
        """
        Search a specific iTunes Store regional storefront for a track.

        country is a two-letter country code: 'JP' for Japan, 'KR' for Korea,
        'US' for the United States, etc.
        Returns a list of result dictionaries from the iTunes API.
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
        """
        Search CJK regional storefronts to find the original-script title.

        Searches the Japanese, Korean, and Chinese iTunes stores in order.
        Returns the first result whose title contains non-Latin characters,
        which is likely the original-language version of the track.
        """
        if target_langs is None:
            target_langs = ["ja", "zh", "ko"]

        # Each language maps to one or more iTunes country codes
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
                    # If the result title has non-ASCII characters, it's in the original script
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
        """
        Reverse lookup: given a japanized title, find the original English title.

        This is a two-step process that exploits the fact that every song in the
        iTunes Store has a single numeric ID that is the same across all storefronts:

          Step 1 — Search the JP store by artist name (using Latin letters).
                   Scan the results for a track whose Japanese title matches ours.
                   Record that track's iTunes ID.

          Step 2 — Ask the US store: "what is track #[ID] called?"
                   The US store returns the English title.

        The title matching in Step 1 is fuzzy — we strip spaces, punctuation,
        and normalize unicode so that e.g. "シェイク・イット・オフ" and
        "シェイクイットオフ" are treated as the same.
        """
        # Step 1: Search JP store by artist name to get candidate tracks
        results = self.search(artist, country="JP", limit=25)
        if not results:
            return None

        def normalize(s: str) -> str:
            """
            Normalize a title for fuzzy comparison.
            Strips spaces, punctuation, and normalizes unicode width variations
            (e.g. full-width vs half-width katakana) so minor formatting
            differences don't prevent a match.
            """
            s = s.replace(" ", "").replace("　", "")       # Remove spaces (including full-width)
            s = s.replace("・", "").replace("·", "").replace(".", "")  # Remove middle dots
            s = s.replace("-", "").replace("—", "").replace("–", "")  # Remove dashes
            s = s.replace("'", "").replace("`", "").replace("ʻ", "")  # Remove apostrophes
            s = s.lower()
            return unicodedata.normalize("NFKC", s)  # Normalize unicode (e.g. ｶ → カ)

        target_norm = normalize(title)
        matched_track = None

        # Find the JP result whose title matches our japanized title
        for result in results:
            track_name = result.get("trackName", "")
            artist_name = result.get("artistName", "")

            # Confirm the artist matches (partial match in either direction is OK)
            if artist.lower() not in artist_name.lower() and artist_name.lower() not in artist.lower():
                continue

            track_norm = normalize(track_name)
            # Accept if one title contains the other (handles truncation differences)
            if target_norm in track_norm or track_norm in target_norm:
                matched_track = result
                break

        if not matched_track:
            return None

        # Step 2: Use the track's iTunes ID to look up the English title in the US store
        track_id = matched_track.get("trackId")
        if not track_id:
            return None

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
