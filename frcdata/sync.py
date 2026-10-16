"""
Functions that download data from TBA / Statbotics and store it locally.

Each step is wrapped so that one failing API (e.g. Statbotics is down) does
not stop the others. Errors are collected and saved on the Event.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import parsing
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
        return None
    frc_team = get_or_create_frc_team(team_number)
    season, _ = TeamSeason.objects.update_or_create(
        team=frc_team, year=year, defaults={**parsing.parse_statbotics_team_year(data), "raw": data}
    )
    return season


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
    """Called by pages: re-sync quietly if data is old. Never raises."""
    if not is_stale(event) or not settings.TBA_API_KEY:
        return []
    try:
        _, errors = sync_event(event.key)
        return errors
    except APIError as exc:
        return [str(exc)]
