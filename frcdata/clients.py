"""
Clients for The Blue Alliance API (HTTP) and Statbotics (official `statbotics` Python package).
"""
import functools
import hashlib
import logging

import requests
from django.conf import settings
from django.core.cache import cache

log = logging.getLogger("frcdata")


class APIError(Exception):
    pass


class TBAClient:
    """
    The Blue Alliance API v3. Docs: https://www.thebluealliance.com/apidocs/v3
    Needs a free "Read API key" from your TBA account page.

    Uses ETags: TBA answers "304 Not Modified" when nothing changed, which is
    faster for us and kinder to TBA during live events.
    """

    def __init__(self, api_key=None, base_url=None, session=None):
        self.api_key = api_key if api_key is not None else settings.TBA_API_KEY
        self.base_url = base_url or settings.TBA_BASE_URL
        self.session = session or requests.Session()

    @property
    def configured(self):
        return bool(self.api_key)

    def _cache_key(self, path):
        return "tba:" + hashlib.sha1(path.encode()).hexdigest()

    def get(self, path):
        if not self.configured:
            raise APIError("TBA_API_KEY is not set. Add it to your .env file.")
        url = f"{self.base_url}{path}"
        headers = {"X-TBA-Auth-Key": self.api_key}
        cached = cache.get(self._cache_key(path))
        if cached:
            headers["If-None-Match"] = cached["etag"]
        try:
            resp = self.session.get(url, headers=headers, timeout=15)
        except requests.RequestException as exc:
            raise APIError(f"TBA request failed: {exc}") from exc
        if resp.status_code == 304 and cached:
            return cached["data"]
        if resp.status_code == 401:
            raise APIError("TBA rejected the API key (401). Check TBA_API_KEY in .env.")
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise APIError(f"TBA error {resp.status_code} for {path}")
        data = resp.json()
        etag = resp.headers.get("ETag")
        if etag:
            cache.set(self._cache_key(path), {"etag": etag, "data": data}, 60 * 60 * 24)
        return data

    # Convenience wrappers -------------------------------------------------
    def status(self):
        return self.get("/status")

    def team(self, number):
        return self.get(f"/team/frc{number}")

    def team_events(self, number, year):
        return self.get(f"/team/frc{number}/events/{year}") or []

    def event(self, key):
        return self.get(f"/event/{key}")

    def event_teams(self, key):
        return self.get(f"/event/{key}/teams/simple") or []

    def event_matches(self, key):
        # Full match objects: include score_breakdown and videos.
        return self.get(f"/event/{key}/matches") or []

    def event_rankings(self, key):
        return self.get(f"/event/{key}/rankings")

    def event_alliances(self, key):
        return self.get(f"/event/{key}/alliances") or []

    def event_oprs(self, key):
        return self.get(f"/event/{key}/oprs")


class StatboticsClient:
    """
    Statbotics data through the official package (pip install statbotics,
    source: https://github.com/avgupta456/statbotics). No key needed.

    The package raises UserWarning when a query returns no data (e.g. an event
    Statbotics hasn't processed yet); we turn that into an empty result.
    """

    PAGE = 1000  # the Statbotics API returns at most 1000 rows per request

    def __init__(self, client=None, timeout=20):
        if client is None:
            import statbotics

            client = statbotics.Statbotics()
            # The package doesn't set a timeout; never let a page hang forever.
            client.session.request = functools.partial(client.session.request, timeout=timeout)
        self.sb = client

    def _call(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except UserWarning as exc:
            log.info("Statbotics returned no data: %s", exc)
            return None
        except requests.RequestException as exc:
            raise APIError(f"Statbotics request failed: {exc}") from exc
        except ValueError as exc:
            raise APIError(f"Statbotics query error: {exc}") from exc

    def _paged(self, func, **kwargs):
        rows, offset = [], 0
        while True:
            page = self._call(func, limit=self.PAGE, offset=offset, **kwargs) or []
            rows.extend(page)
            if len(page) < self.PAGE:
                return rows
            offset += self.PAGE

    def team_events(self, event_key):
        return self._paged(self.sb.get_team_events, event=event_key)

    def matches(self, event_key):
        return self._paged(self.sb.get_matches, event=event_key)

    def team_year(self, number, year):
        return self._call(self.sb.get_team_year, number, year)

    def event(self, event_key):
        return self._call(self.sb.get_event, event_key)
