"""
Functions that download data from TBA / Statbotics and store it locally.

Each step is wrapped so that one failing API (e.g. Statbotics is down) does
not stop the others. Errors are collected and saved on the Event.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from . import parsing
from .background import run_in_background
from .clients import APIError, StatboticsClient, TBAClient
from .models import Event, EventAlliance, EventTeam, FRCTeam, Match, TeamSeason

log = logging.getLogger("frcdata")


def get_or_create_frc_team(number, data=None):
    defaults = parsing.parse_team(data) if data else {}
    team, created = FRCTeam.objects.get_or_create(number=number, defaults=defaults)
    if data and not created:
        for k, v in defaults.items():
            setattr(team, k, v)
        team.save()
    return team


def sync_team_events(team_number, year, tba=None):
    """Download the list of events a team is registered for in a season."""
    tba = tba or TBAClient()
    events = []
    frc_team = get_or_create_frc_team(team_number)
    for data in tba.team_events(team_number, year):
        event, _ = Event.objects.update_or_create(key=data["key"], defaults=parsing.parse_event(data))
        EventTeam.objects.get_or_create(event=event, team=frc_team)
        events.append(event)
    return events


def sync_team_season(team_number, year, statbotics=None):
    """Whole-season Statbotics stats (EPA, world/country rank) for one team. Returns TeamSeason or None."""
    statbotics = statbotics or StatboticsClient()
    data = statbotics.team_year(team_number, year)
    if not data:
        # Remember "no data" for a few hours so we don't ask Statbotics again on every page load.
        cache.set(f"sb:no_team_year:{team_number}:{year}", True, 60 * 60 * 6)
        return None
    frc_team = get_or_create_frc_team(team_number)
    season, _ = TeamSeason.objects.update_or_create(
        team=frc_team, year=year, defaults={**parsing.parse_statbotics_team_year(data), "raw": data}
    )
    return season


def _refresh_seasons(team_number, years):
    for year in years:
        try:
            sync_team_season(team_number, year)
        except APIError as exc:
            log.info("season stats %s %s: %s", team_number, year, exc)
            cache.set(f"sb:no_team_year:{team_number}:{year}", True, 60 * 10)  # API down: retry in 10 min


def season_stats(team_number, season):
    """
    Season stats for the dashboard. Never calls the API while the page waits:
    it returns what we have (the requested season, or the latest earlier one,
    e.g. 2025 before the 2026 season starts) and refreshes in the background.
    """
    current = TeamSeason.objects.filter(team__number=team_number, year=season).first()
    fresh = current and timezone.now() - current.synced_at < timedelta(hours=6)
    if not fresh:
        years = [y for y in (season, season - 1) if not cache.get(f"sb:no_team_year:{team_number}:{y}")]
        if years:
            run_in_background(f"season:{team_number}:{season}", _refresh_seasons, team_number, years)
    if current:
        return current
    return TeamSeason.objects.filter(team__number=team_number, year__lt=season).order_by("-year").first()


# --- Team avatars (TBA media) ------------------------------------------------

def fetch_avatar(team_number, year, tba=None):
    """Download a team's 40x40 avatar from TBA (teams upload one per season). Stores '' if none."""
    tba = tba or TBAClient()
    frc_team = get_or_create_frc_team(team_number)
    avatar = ""
    for y in (year, year - 1, year - 2):
        for media in tba.team_media(team_number, y) or []:
            if media.get("type") == "avatar":
                avatar = (media.get("details") or {}).get("base64Image") or ""
                if avatar:
                    break
        if avatar:
            break
    frc_team.avatar = avatar
    frc_team.avatar_checked_at = timezone.now()
    frc_team.save(update_fields=["avatar", "avatar_checked_at"])
    return avatar


def ensure_avatars(team_numbers, year):
    """Fetch avatars we have never checked (or checked more than 2 weeks ago)."""
    if not settings.TBA_API_KEY:
        return
    cutoff = timezone.now() - timedelta(days=14)
    known = {t.number: t for t in FRCTeam.objects.filter(number__in=team_numbers)}
    tba = TBAClient()
    for n in team_numbers:
        t = known.get(n)
        if t and t.avatar_checked_at and t.avatar_checked_at > cutoff:
            continue
        try:
            fetch_avatar(n, year, tba=tba)
        except APIError as exc:
            log.info("avatar %s: %s", n, exc)


def ensure_avatars_background(team_numbers, year):
    if settings.TBA_API_KEY and team_numbers:
        run_in_background(f"avatars:{year}:{min(team_numbers)}:{len(team_numbers)}", ensure_avatars, list(team_numbers), year)


def is_stale(event):
    if event.is_demo:
        return False
    if not event.last_synced_at:
        return True
    return timezone.now() - event.last_synced_at > timedelta(minutes=settings.DATA_REFRESH_MINUTES)


def sync_event(event_key, tba=None, statbotics=None):
    """Download everything we need for one event. Returns (event, [errors])."""
    tba = tba or TBAClient()
    statbotics = statbotics or StatboticsClient()
    errors = []

    data = tba.event(event_key)
    if data is None:
        raise APIError(f"Event {event_key} not found on TBA.")
    event, _ = Event.objects.update_or_create(key=event_key, defaults=parsing.parse_event(data))
    if event.is_demo:
        return event, ["Demo events are not synced."]

    def step(name, func):
        try:
            with transaction.atomic():
                func()
        except Exception as exc:  # noqa: BLE001 - we want to keep going
            log.warning("sync %s %s failed: %s", event_key, name, exc)
            errors.append(f"{name}: {exc}")

    def teams():
        for t in tba.event_teams(event_key):
            frc_team = get_or_create_frc_team(t["team_number"], t)
            EventTeam.objects.get_or_create(event=event, team=frc_team)

    def matches():
        for m in tba.event_matches(event_key):
            Match.objects.update_or_create(key=m["key"], defaults={"event": event, **parsing.parse_match(m)})

    def rankings():
        ranks = parsing.parse_rankings(tba.event_rankings(event_key))
        for number, fields in ranks.items():
            frc_team = get_or_create_frc_team(number)
            EventTeam.objects.update_or_create(event=event, team=frc_team, defaults=fields)

    def oprs():
        data = tba.event_oprs(event_key) or {}
        for key, value in (data.get("oprs") or {}).items():
            EventTeam.objects.filter(event=event, team__number=parsing.team_number(key)).update(opr=value)

    def alliances():
        rows = parsing.parse_alliances(tba.event_alliances(event_key))
        if rows:
            EventAlliance.objects.filter(event=event).delete()
            for row in rows:
                EventAlliance.objects.create(event=event, **row)

    def sb_teams():
        for row in statbotics.team_events(event_key):
            fields = parsing.parse_statbotics_team_event(row)
            EventTeam.objects.filter(event=event, team__number=row.get("team")).update(statbotics_raw=row, **fields)

    def sb_matches():
        for row in statbotics.matches(event_key):
            Match.objects.filter(key=row.get("key")).update(**parsing.parse_statbotics_match(row))

    step("teams", teams)
    step("matches", matches)
    step("rankings", rankings)
    step("oprs", oprs)
    step("alliances", alliances)
    step("statbotics teams", sb_teams)
    step("statbotics matches", sb_matches)

    event.last_synced_at = timezone.now()
    event.sync_error = "\n".join(errors)
    event.save(update_fields=["last_synced_at", "sync_error"])
    return event, errors


def refresh_if_stale(event):
    """Called by pages: if data is old, re-sync in the background. Never blocks, never raises."""
    if not is_stale(event) or not settings.TBA_API_KEY:
        return False
    return run_in_background(f"event:{event.key}", _sync_quietly, event.key)


def _sync_quietly(event_key):
    try:
        event, _ = sync_event(event_key)
        ensure_avatars(list(event.event_teams.values_list("team__number", flat=True)), event.year)
    except APIError as exc:
        Event.objects.filter(key=event_key).update(sync_error=str(exc))
