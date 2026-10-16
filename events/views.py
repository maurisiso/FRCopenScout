import json
import re

from django.conf import settings
from django.contrib import messages
from django.db.models import Count, Max
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from frcdata.clients import APIError
from frcdata.models import Event, EventTeam, FRCTeam, Match
from frcdata.sync import refresh_if_stale, sync_event, sync_team_events
from scouting.forms import MatchNoteForm
from scouting.models import MatchNote, ScoutEntry, ScoutingForm
from scouting.stats import entry_points, event_field_averages, team_summaries
from teams.models import Role
from teams.permissions import team_view

from .alliance_selection import AllianceSelection, SelectionError, default_alliance_count, predict
from .models import AlliancePrediction, TrackedEvent


def _season(request):
    try:
        return int(request.GET.get("season") or settings.DEFAULT_SEASON)
    except ValueError:
        return settings.DEFAULT_SEASON


# --- Team dashboard ---------------------------------------------------------

@team_view(allow_pending=True)
def team_home(request, team, membership):
    if not team.is_approved:
        return render(request, "teams/pending.html", {"team": team, "membership": membership})
    season = _season(request)
    tracked = (TrackedEvent.objects.filter(team=team, event__year=season)
               .select_related("event").order_by("event__start_date"))
    entry_counts = dict(ScoutEntry.objects.filter(team=team, event__year=season)
                        .values_list("event_id").annotate(n=Count("id")))
    for t in tracked:
        t.entry_count = entry_counts.get(t.event_id, 0)
    seasons = sorted({settings.DEFAULT_SEASON, season, *TrackedEvent.objects.filter(team=team)
                      .values_list("event__year", flat=True)}, reverse=True)
    return render(request, "events/team_home.html", {
        "team": team, "membership": membership, "tracked": tracked, "season": season, "seasons": seasons,
        "forms": team.scouting_forms.filter(is_active=True),
        "member_count": team.memberships.count(),
        "tba_configured": bool(settings.TBA_API_KEY),
    })


@require_POST
@team_view(min_role=Role.ADMIN)
def sync_team(request, team, membership):
    season = _season(request)
    try:
        events = sync_team_events(team.number, season)
    except APIError as exc:
        messages.error(request, str(exc))
        return redirect(f"/t/{team.number}/?season={season}")
    for e in events:
        TrackedEvent.objects.get_or_create(team=team, event=e, defaults={"source": TrackedEvent.Source.TBA})
    messages.success(request, _("Found %(n)d events for %(season)s on The Blue Alliance.") % {"n": len(events), "season": season})
    return redirect(f"/t/{team.number}/?season={season}")


@require_POST
@team_view(min_role=Role.ADMIN)
def add_event(request, team, membership):
    key = (request.POST.get("event_key") or "").strip().lower()
    if not re.fullmatch(r"\d{4}[a-z0-9]+", key):
        messages.error(request, _("Event keys look like 2026mxmo (year + event code)."))
        return redirect("team_home", team_number=team.number)
    event = Event.objects.filter(key=key).first()
    if event is None:
        try:
            event, errors = sync_event(key)
        except APIError as exc:
            messages.error(request, str(exc))
            return redirect("team_home", team_number=team.number)
    TrackedEvent.objects.get_or_create(team=team, event=event, defaults={"source": TrackedEvent.Source.MANUAL})
    messages.success(request, _("Added %(name)s.") % {"name": event.name})
    return redirect(f"/t/{team.number}/?season={event.year}")


@require_POST
@team_view(min_role=Role.ADMIN)
def remove_event(request, team, membership, event_key):
    TrackedEvent.objects.filter(team=team, event__key=event_key).delete()
    messages.success(request, _("Event removed from your dashboard. Scouting data is kept."))
    return redirect("team_home", team_number=team.number)


# --- Shared event helpers ---------------------------------------------------

def _event_for(team, event_key):
    return get_object_or_404(Event, key=event_key)


def _match_form(team, event):
    return (team.scouting_forms.filter(kind=ScoutingForm.Kind.MATCH, season=event.year, is_active=True).first()
            or team.scouting_forms.filter(kind=ScoutingForm.Kind.MATCH, is_active=True).first())


def _stats(team, event):
    """(form, fields, summaries, event averages) for the team's main match form at this event."""
    sf = _match_form(team, event)
    if not sf:
        return None, [], {}, {}
    fields = list(sf.fields.all())
    entries = ScoutEntry.objects.filter(team=team, event=event, form=sf)
    summaries = team_summaries(entries, fields)
    return sf, fields, summaries, event_field_averages(summaries, fields)


def _ctx(team, membership, event, tab, **extra):
    return {"team": team, "membership": membership, "event": event, "tab": tab, **extra}


@require_POST
@team_view()
def event_sync(request, team, membership, event_key):
    event = _event_for(team, event_key)
    if event.is_demo:
        messages.info(request, _("This is a demo event; it isn't synced from TBA."))
    else:
        try:
            _, errors = sync_event(event.key)
            if errors:
                messages.warning(request, _("Synced with some problems: %(e)s") % {"e": "; ".join(errors)})
            else:
                messages.success(request, _("Data refreshed from The Blue Alliance and Statbotics."))
        except APIError as exc:
            messages.error(request, str(exc))
    return redirect(request.POST.get("next") or f"/t/{team.number}/e/{event.key}/")


# --- Event overview ---------------------------------------------------------

@team_view()
def event_overview(request, team, membership, event_key):
    event = _event_for(team, event_key)
    sync_errors = refresh_if_stale(event)
    ours = EventTeam.objects.filter(event=event, team__number=team.number).first()
    our_matches = [m for m in event.matches.all() if team.number in m.all_teams]
    upcoming = [m for m in our_matches if not m.is_played][:4]
    recent = [m for m in our_matches if m.is_played][-4:][::-1]
    rankings = EventTeam.objects.filter(event=event).select_related("team").exclude(rank=None).order_by("rank")[:10]
    return render(request, "events/overview.html", _ctx(
        team, membership, event, "overview",
        ours=ours, upcoming=upcoming, recent=recent, rankings=rankings, sync_errors=sync_errors,
        entry_count=ScoutEntry.objects.filter(team=team, event=event).count(),
        note_count=MatchNote.objects.filter(team=team, event=event).count(),
        forms=team.scouting_forms.filter(is_active=True),
        quals_done=event.qualifications_complete,
        team_count=event.event_teams.count(),
    ))


@team_view()
def event_teams(request, team, membership, event_key):
    event = _event_for(team, event_key)
    sf, fields, summaries, averages = _stats(team, event)
    show_fields = [f for f in fields if f.is_numeric or f.field_type == "boolean"][:5]
    rows = []
    for et in EventTeam.objects.filter(event=event).select_related("team"):
        s = summaries.get(et.team.number, {})
        rows.append({"et": et, "n": s.get("n", 0), "points": s.get("points"),
                     "cells": [s.get("fields", {}).get(f.key, {}).get("display", "") for f in show_fields]})
    rows.sort(key=lambda r: (r["et"].rank or 999, r["et"].team.number))
    return render(request, "events/teams.html", _ctx(team, membership, event, "teams", rows=rows, show_fields=show_fields, sf=sf))


@team_view()
def event_team_detail(request, team, membership, event_key, frc_number):
    event = _event_for(team, event_key)
    et = EventTeam.objects.filter(event=event, team__number=frc_number).select_related("team").first()
    sf, fields, summaries, averages = _stats(team, event)
    entries = ScoutEntry.objects.filter(team=team, event=event, scouted_team=frc_number).select_related("form", "scout")
    pit = [e for e in entries if e.form.kind == ScoutingForm.Kind.PIT]
    match_entries = [e for e in entries if e.form.kind == ScoutingForm.Kind.MATCH]
    for e in match_entries:
        e.points = entry_points(e.data, list(e.form.fields.all()))
    matches = [m for m in event.matches.all() if frc_number in m.all_teams]
    notes = MatchNote.objects.filter(team=team, event=event, about_team=frc_number).select_related("author")
    summary = summaries.get(frc_number)
    field_rows = []
    if summary:
        for f in fields:
            s = summary["fields"].get(f.key, {})
            field_rows.append({"field": f, "s": s, "event_avg": averages.get(f.key)})
    return render(request, "events/team_detail.html", _ctx(
        team, membership, event, "us" if frc_number == team.number else "teams", et=et, frc_number=frc_number, summary=summary, field_rows=field_rows,
        match_entries=match_entries, pit=pit, matches=matches, notes=notes,
        max_points=max([e.points for e in match_entries if e.points is not None], default=0),
        is_us=frc_number == team.number,
    ))


@team_view()
def event_matches(request, team, membership, event_key):
    event = _event_for(team, event_key)
    only_ours = request.GET.get("ours") == "1"
    matches = list(event.matches.all())
    if only_ours:
        matches = [m for m in matches if team.number in m.all_teams]
    scouted = {}
    for mk, n in ScoutEntry.objects.filter(team=team, event=event).values_list("match_key").annotate(n=Count("id")):
        scouted[mk] = n
    for m in matches:
        m.scouted = scouted.get(m.key, 0)
        m.ours = m.alliance_of(team.number)
    return render(request, "events/matches.html", _ctx(team, membership, event, "matches", matches=matches, only_ours=only_ours))


@team_view()
def match_detail(request, team, membership, event_key, match_key):
    event = _event_for(team, event_key)
    match = get_object_or_404(Match, key=match_key, event=event)
    sf, fields, summaries, _avgs = _stats(team, event)
    rows = {et.team.number: et for et in EventTeam.objects.filter(event=event, team__number__in=match.all_teams).select_related("team")}

    def side(numbers):
        out = []
        for n in numbers:
            et = rows.get(n)
            s = summaries.get(n, {})
            out.append({"number": n, "et": et, "n": s.get("n", 0), "points": s.get("points")})
        return out

    red, blue = side(match.red_teams), side(match.blue_teams)

    def total(alliance, attr):
        vals = [getattr(r["et"], attr) for r in alliance if r["et"] and getattr(r["et"], attr) is not None]
        return round(sum(vals), 1) if vals else None

    if request.method == "POST" and membership.can_scout:
        form = MatchNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.team, note.event, note.author = team, event, request.user
            note.match = match
            note.match_key = match.key
            note.save()
            messages.success(request, _("Note added."))
            return redirect(request.path)
    else:
        form = MatchNoteForm(initial={"match_key": match.key, "about_team": team.number if team.number in match.all_teams else None})
    entries = ScoutEntry.objects.filter(team=team, event=event, match_key=match.key).select_related("scout", "form")
    return render(request, "events/match_detail.html", _ctx(
        team, membership, event, "matches", match=match, red=red, blue=blue,
        red_epa=total(red, "epa_total"), blue_epa=total(blue, "epa_total"),
        notes=match.notes.select_related("author").filter(team=team), note_form=form, entries=entries,
        ours=match.alliance_of(team.number), match_form=_match_form(team, event),
    ))


# --- Notes ------------------------------------------------------------------

@team_view()
def event_notes(request, team, membership, event_key):
    event = _event_for(team, event_key)
    if request.method == "POST":
        if not membership.can_scout:
            messages.error(request, _("Viewers can't add notes."))
            return redirect(request.path)
        form = MatchNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.team, note.event, note.author = team, event, request.user
            note.match = Match.objects.filter(key=note.match_key, event=event).first()
            note.save()
            messages.success(request, _("Note added."))
            return redirect(request.path)
    else:
        form = MatchNoteForm(initial={"about_team": team.number})
    notes = MatchNote.objects.filter(team=team, event=event).select_related("author")
    cat = request.GET.get("category")
    if cat:
        notes = notes.filter(category=cat)
    about = request.GET.get("about")
    if about and about.isdigit():
        notes = notes.filter(about_team=int(about))
    return render(request, "events/notes.html", _ctx(
        team, membership, event, "notes", notes=notes, note_form=form,
        categories=MatchNote.Category.choices, cat=cat or "", about=about or "",
        match_options=[(m.key, m.label) for m in event.matches.all()],
    ))


@require_POST
@team_view(min_role=Role.SCOUT)
def note_delete(request, team, membership, event_key, note_id):
    note = get_object_or_404(MatchNote, pk=note_id, team=team)
    if membership.is_admin or note.author_id == request.user.id:
        note.delete()
        messages.success(request, _("Note deleted."))
    return redirect(request.POST.get("next") or f"/t/{team.number}/e/{event_key}/notes/")


# --- Our team ---------------------------------------------------------------

@team_view()
def our_team(request, team, membership, event_key):
    return redirect("event_team_detail", team_number=team.number, event_key=event_key, frc_number=team.number)


# --- Alliance selection -----------------------------------------------------

def _pick_scores(event, summaries):
    """
    Score used by the automatic prediction: Statbotics EPA, blended with our own
    scouted points when we have at least 3 entries for that team.
    """
    scores = {}
    for et in EventTeam.objects.filter(event=event).select_related("team"):
        epa = et.epa_total
        s = summaries.get(et.team.number)
        scouted = s["points"] if s and s["n"] >= 3 and s["points"] is not None else None
        if epa is not None and scouted is not None:
            score = 0.6 * epa + 0.4 * scouted
        elif epa is not None:
            score = epa
        elif scouted is not None:
            score = scouted
        else:
            score = -(et.rank or 999) / 100  # no data: prefer higher-ranked teams
        scores[et.team.number] = round(score, 2)
    return scores


def _official_rankings(event):
    ranked = list(EventTeam.objects.filter(event=event).exclude(rank=None).order_by("rank").values_list("team__number", flat=True))
    if ranked:
        return ranked, "tba"
    # Before rankings exist, approximate by EPA so the tool is still usable.
    by_epa = list(EventTeam.objects.filter(event=event).order_by("-epa_total", "team__number").values_list("team__number", flat=True))
    return by_epa, "epa"


def _parse_rank_text(text, valid):
    nums = [int(x) for x in re.findall(r"\d+", text or "")]
    seen, out = set(), []
    for n in nums:
        if n in valid and n not in seen:
            out.append(n)
            seen.add(n)
    return out


@team_view()
def alliances(request, team, membership, event_key):
    event = _event_for(team, event_key)
    sf, fields, summaries, _avgs = _stats(team, event)
    rankings, rank_source = _official_rankings(event)
    team_count = len(rankings)
    num = int(request.GET.get("alliances") or default_alliance_count(team_count))
    rounds = int(request.GET.get("rounds") or (3 if event.is_championship_division else 2))
    scores = _pick_scores(event, summaries)
    prediction = predict(rankings, scores, num_alliances=num, rounds=rounds) if team_count >= 2 else None
    official = list(event.alliances.all())

    our_place = None
    if prediction:
        for i, a in enumerate(prediction.alliances, 1):
            if team.number in a:
                our_place = {"alliance": i, "slot": a.index(team.number)}
    saved = AlliancePrediction.objects.filter(team=team, event=event).select_related("author")
    return render(request, "events/alliances.html", _ctx(
        team, membership, event, "alliances",
        prediction=prediction, scores=scores, rankings=rankings, rank_source=rank_source, num=num, rounds=rounds,
        official=official, our_place=our_place, saved=saved, quals_done=event.qualifications_complete,
        sim=_sim_context(team, event, rankings, [], num, rounds, scores),
    ))


def _sim_context(team, event, rankings, actions, num, rounds, scores, error=None, prediction_id=None, name=""):
    sel = AllianceSelection(rankings=rankings, num_alliances=num, rounds=rounds)
    applied = []
    for a in actions:
        try:
            sel.apply(a)
            applied.append(a)
        except SelectionError as exc:
            error = str(exc)
            break
    return {
        "sel": sel, "actions_json": json.dumps(applied), "rankings_text": ", ".join(map(str, rankings)),
        "num": num, "rounds": rounds, "error": error, "scores": scores, "prediction_id": prediction_id, "name": name,
        "board": [{"teams": a, "empty": range(max(0, rounds + 1 - len(a))), "current": i == sel.current_alliance}
                  for i, a in enumerate(sel.alliances)],
        "available": sel.available() if not sel.is_complete else [],
        "lower_captains": set(sel.lower_captains()),
        "rank_of": {t: i + 1 for i, t in enumerate(rankings)},
    }


@require_POST
@team_view()
def alliance_sim(request, team, membership, event_key):
    """HTMX endpoint for the interactive alliance-selection simulator."""
    event = _event_for(team, event_key)
    sf, fields, summaries, _avgs = _stats(team, event)
    scores = _pick_scores(event, summaries)
    valid = set(EventTeam.objects.filter(event=event).values_list("team__number", flat=True))
    rankings = _parse_rank_text(request.POST.get("rankings"), valid) or _official_rankings(event)[0]
    num = max(2, min(8, int(request.POST.get("num") or 8)))
    rounds = max(1, min(3, int(request.POST.get("rounds") or 2)))
    try:
        actions = json.loads(request.POST.get("actions") or "[]")
    except json.JSONDecodeError:
        actions = []
    team_choice = request.POST.get("team")
    # Clicking a team button submits that team; the "mode" selector says pick or decline.
    op = request.POST.get("op") or (request.POST.get("mode", "pick") if team_choice else None)
    error = None
    prediction_id = request.POST.get("prediction_id") or None
    name = request.POST.get("name", "")

    if op == "reset_rankings":
        rankings = _official_rankings(event)[0]
        actions = []
    elif op == "reset":
        actions = []
    elif op == "undo":
        actions = actions[:-1]
    elif op in ("pick", "decline") and team_choice:
        actions.append({"type": op, "team": int(team_choice)})
    elif op in ("auto", "auto_all", "save"):
        ctx = _sim_context(team, event, rankings, actions, num, rounds, scores)
        sel = ctx["sel"]
        if op == "auto" and not sel.is_complete:
            actions.append({"type": "pick", "team": _best(sel, scores)})
        elif op == "auto_all":
            while not sel.is_complete:
                t = _best(sel, scores)
                sel.pick(t)
                actions.append({"type": "pick", "team": t})
        elif op == "save":
            if not membership.can_scout:
                error = _("Viewers can't save predictions.")
            else:
                name = name.strip() or _("My prediction")
                obj = AlliancePrediction.objects.filter(pk=prediction_id, team=team).first() if prediction_id else None
                obj = obj or AlliancePrediction(team=team, event=event, author=request.user)
                obj.name, obj.rankings, obj.num_alliances, obj.rounds = name, rankings, num, rounds
                obj.actions = json.loads(ctx["actions_json"])
                obj.save()
                prediction_id = obj.pk
    elif op == "load":
        obj = get_object_or_404(AlliancePrediction, pk=request.POST.get("load_id"), team=team)
        rankings, num, rounds, actions = obj.rankings, obj.num_alliances, obj.rounds, obj.actions
        prediction_id, name = obj.pk, obj.name

    ctx = _sim_context(team, event, rankings, actions, num, rounds, scores, error, prediction_id, name)
    if op == "save" and not error:
        ctx["saved_msg"] = _("Saved.")
    return render(request, "events/_alliance_sim.html", {"team": team, "event": event, "membership": membership, "sim": ctx})


def _best(sel, scores):
    rank_index = {t: i for i, t in enumerate(sel.rankings)}
    return max(sel.available(), key=lambda t: (scores.get(t, float("-inf")), -rank_index[t]))


@require_POST
@team_view(min_role=Role.SCOUT)
def prediction_delete(request, team, membership, event_key, prediction_id):
    AlliancePrediction.objects.filter(pk=prediction_id, team=team).delete()
    return redirect("event_alliances", team_number=team.number, event_key=event_key)


# --- Team info database (across all events) ---------------------------------

@team_view()
def scouted_teams(request, team, membership):
    rows = (ScoutEntry.objects.filter(team=team).values("scouted_team")
            .annotate(n=Count("id"), events=Count("event", distinct=True), last=Max("created_at")).order_by("scouted_team"))
    names = dict(FRCTeam.objects.filter(number__in=[r["scouted_team"] for r in rows]).values_list("number", "nickname"))
    note_counts = dict(MatchNote.objects.filter(team=team).exclude(about_team=None).values_list("about_team").annotate(n=Count("id")))
    q = request.GET.get("q", "").strip()
    out = []
    for r in rows:
        r["name"] = names.get(r["scouted_team"], "")
        r["notes"] = note_counts.get(r["scouted_team"], 0)
        if q and q not in str(r["scouted_team"]) and q.lower() not in r["name"].lower():
            continue
        out.append(r)
    return render(request, "events/scouted_teams.html", {"team": team, "membership": membership, "rows": out, "q": q})


@team_view()
def scouted_team_detail(request, team, membership, frc_number):
    frc = FRCTeam.objects.filter(number=frc_number).first()
    entries = ScoutEntry.objects.filter(team=team, scouted_team=frc_number).select_related("event", "form", "scout")
    by_event = {}
    for e in entries:
        by_event.setdefault(e.event, {"match": [], "pit": []})[e.form.kind].append(e)
    blocks = []
    for event, groups in sorted(by_event.items(), key=lambda kv: kv[0].start_date or kv[0].key, reverse=True):
        et = EventTeam.objects.filter(event=event, team__number=frc_number).first()
        summary = None
        if groups["match"]:
            form = groups["match"][0].form
            summary = team_summaries(groups["match"], list(form.fields.all())).get(frc_number)
        blocks.append({"event": event, "et": et, "summary": summary, "pit": groups["pit"], "count": len(groups["match"])})
    notes = MatchNote.objects.filter(team=team, about_team=frc_number).select_related("event", "author")
    return render(request, "events/scouted_team_detail.html", {
        "team": team, "membership": membership, "frc": frc, "frc_number": frc_number, "blocks": blocks, "notes": notes,
    })
