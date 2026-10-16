"""Thin HTTP clients for The Blue Alliance and Statbotics APIs."""
import logging

import requests
from django.conf import settings

log = logging.getLogger("frcdata")


class APIError(Exception):
    pass


class TBAClient:
    """
    The Blue Alliance API v3. Docs: https://www.thebluealliance.com/apidocs/v3
    Needs a free "Read API key" from your TBA account page.
    """

    def __init__(self, api_key=None, base_url=None, session=None):
        self.api_key = api_key if api_key is not None else settings.TBA_API_KEY
        self.base_url = base_url or settings.TBA_BASE_URL
        self.session = session or requests.Session()

    @property
    def configured(self):
        return bool(self.api_key)

    def get(self, path):
        if not self.configured:
            raise APIError("TBA_API_KEY is not set. Add it to your .env file.")
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(url, headers={"X-TBA-Auth-Key": self.api_key}, timeout=15)
        except requests.RequestException as exc:
            raise APIError(f"TBA request failed: {exc}") from exc
        if resp.status_code == 401:
            raise APIError("TBA rejected the API key (401). Check TBA_API_KEY.")
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise APIError(f"TBA error {resp.status_code} for {path}")
        return resp.json()

    # Convenience wrappers -------------------------------------------------
    def team(self, number):
        return self.get(f"/team/frc{number}/simple")

    def team_events(self, number, year):
        return self.get(f"/team/frc{number}/events/{year}") or []

    def event(self, key):
        return self.get(f"/event/{key}")

    def event_teams(self, key):
        return self.get(f"/event/{key}/teams/simple") or []

    def event_matches(self, key):
        return self.get(f"/event/{key}/matches/simple") or []

    def event_rankings(self, key):
        return self.get(f"/event/{key}/rankings")

    def event_alliances(self, key):
        return self.get(f"/event/{key}/alliances") or []

    def event_oprs(self, key):
        return self.get(f"/event/{key}/oprs")


class StatboticsClient:
    """Statbotics API v3 (no key needed). Docs: https://www.statbotics.io/docs/rest"""

    def __init__(self, base_url=None, session=None):
        self.base_url = base_url or settings.STATBOTICS_BASE_URL
        self.session = session or requests.Session()

    def get(self, path, params=None):
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=20)
        except requests.RequestException as exc:
            raise APIError(f"Statbotics request failed: {exc}") from exc
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise APIError(f"Statbotics error {resp.status_code} for {path}")
        return resp.json()

    def team_events(self, event_key):
        return self.get("/team_events", {"event": event_key, "limit": 1000}) or []

    def matches(self, event_key):
        return self.get("/matches", {"event": event_key, "limit": 1000}) or []

    def team_year(self, number, year):
        return self.get(f"/team_year/{number}/{year}")
