"""
Football data API client. One module — swap the implementation here to change provider.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx


@dataclass
class FixtureData:
    external_id: str
    team_a: str           # home team
    team_b: str           # away team
    kickoff_time: datetime
    status: str           # "scheduled"|"live"|"live_h1"|"live_ht"|"live_h2"|"live_et"|"live_pk"|"live_aet"|"finished"|"postponed"
    score_a: Optional[int] = None
    score_b: Optional[int] = None
    round_number: Optional[int] = None
    round_name: Optional[str] = None
    group_name: Optional[str] = None


class FootballClientBase(ABC):
    @abstractmethod
    async def fetch_upcoming_fixtures(self) -> list[FixtureData]:
        """Return fixtures within a reasonable window (recently finished + upcoming)."""
        ...

    @abstractmethod
    async def fetch_fixture(self, external_id: str) -> Optional[FixtureData]:
        """Return the current state of one fixture by its external ID."""
        ...


_STATUS_MAP = {
    "notstarted": "scheduled",
    "inprogress": "live",
    "1st_half": "live_h1",
    "halftime": "live_ht",
    "2nd_half": "live_h2",
    "extratime": "live_et",
    "penalties": "live_pk",
    "aet": "live_aet",
    "finished": "finished",
    "postponed": "postponed",
    "cancelled": "postponed",
}


def _parse_dt(raw: str) -> datetime:
    """Parse ISO-8601 date string to a timezone-aware datetime (UTC fallback)."""
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class BzzOiroClient(FootballClientBase):
    """
    sports.bzzoiro.com v2 client for the World Cup.
    Swap this class (and the factory in matches.py) to change provider.
    """

    def __init__(self, api_key: str, base_url: str, league_id: int = 27) -> None:
        self.base_url = base_url.rstrip("/")
        self.league_id = league_id
        self._headers = {"Authorization": f"Token {api_key}"}

    def _parse_event(self, event: dict) -> FixtureData:
        home = event["home_team"]
        away = event["away_team"]
        return FixtureData(
            external_id=str(event["id"]),
            team_a=home["name"] if isinstance(home, dict) else home,
            team_b=away["name"] if isinstance(away, dict) else away,
            kickoff_time=_parse_dt(event["event_date"]),
            status=_STATUS_MAP.get((event.get("status") or "").lower(), "scheduled"),
            score_a=event.get("home_score"),
            score_b=event.get("away_score"),
            round_number=event.get("round_number"),
            round_name=event.get("round_name") or None,
            group_name=event.get("group_name"),
        )

    async def fetch_upcoming_fixtures(self) -> list[FixtureData]:
        today = datetime.now(timezone.utc).date()
        params: dict = {
            "league_id": self.league_id,
            "date_from": (today - timedelta(days=3)).isoformat(),
            "date_to": (today + timedelta(days=60)).isoformat(),
            "limit": 200,
        }
        url: Optional[str] = f"{self.base_url}/events/"
        fixtures: list[FixtureData] = []

        async with httpx.AsyncClient(headers=self._headers, timeout=15.0) as client:
            while url:
                r = await client.get(url, params=params)
                r.raise_for_status()
                data = r.json()
                fixtures.extend(self._parse_event(e) for e in data.get("results", []))
                url = data.get("next")
                params = {}  # subsequent pages: full URL already has all params

        return fixtures

    async def fetch_fixture(self, external_id: str) -> Optional[FixtureData]:
        url = f"{self.base_url}/events/{external_id}/"
        async with httpx.AsyncClient(headers=self._headers, timeout=15.0) as client:
            r = await client.get(url)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return self._parse_event(r.json())


# Keep the old name as an alias so existing stubs don't break
FootballDataClient = BzzOiroClient
