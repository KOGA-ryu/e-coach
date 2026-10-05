"""Riot Developer API client for fetching Valorant match telemetry."""

import json
import logging
import time
from typing import Any, Optional
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_REGION = "na"


class RiotApiClient:
    """Client for the official Riot VAL-MATCH-V1 API using standard library urllib."""

    def __init__(self, api_key: Optional[str] = None, region: str = DEFAULT_REGION):
        self.api_key = api_key
        self.region = region.lower()

    @property
    def base_url(self) -> str:
        return f"https://{self.region}.api.riotgames.com"

    def _get_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "ValLens/0.1.0"}
        if self.api_key:
            headers["X-Riot-Token"] = self.api_key
        return headers

    def _request(self, endpoint: str, retries: int = 3) -> dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        req = urllib.request.Request(url, headers=self._get_headers())

        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = response.read().decode("utf-8")
                    return json.loads(data)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    retry_after = int(e.headers.get("Retry-After", 2))
                    logger.warning(f"Riot API rate limit (429). Retrying in {retry_after}s...")
                    time.sleep(retry_after)
                else:
                    raise RuntimeError(f"HTTP {e.code} error requesting {url}: {e.reason}") from e
            except Exception as e:
                if attempt == retries - 1:
                    raise RuntimeError(f"Network error requesting {url}: {e}") from e
                time.sleep(1)

        raise RuntimeError(f"Failed to fetch {url} after {retries} retries.")

    def fetch_match(self, match_id: str, retries: int = 3) -> dict[str, Any]:
        """Fetch raw match payload for a given matchId."""
        return self._request(f"/val/match/v1/matches/{match_id}", retries=retries)

    def fetch_matchlist_by_puuid(self, puuid: str, retries: int = 3) -> dict[str, Any]:
        """Fetch recent match history list for a player PUUID."""
        return self._request(f"/val/match/v1/matchlists/by-puuid/{puuid}", retries=retries)
