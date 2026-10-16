"""
Builds the structured "context" the AI assistant reasons over.

This is the contract between the scouting app and the AI: whatever model we
plug in later (Phase 2) receives exactly these dictionaries. Keeping them
game-agnostic (EPA, ranks, records, our own scouting summaries, notes) is
what lets one model work across different FRC seasons.
"""
from frcdata.models import EventTeam
from scouting.models import MatchNote, ScoutEntry, ScoutingForm
from scouting.stats import event_field_averages, team_summaries


def _match_form(team, event):
    return (team.scouting_forms.filter(kind=ScoutingForm.Kind.MATCH, season=event.year, is_active=True).first()
            or team.scouting_forms.filter(kind=ScoutingForm.Kind.MATCH).first())


def scouting_summaries(team, event):
    sf = _match_form(team, event)
    if not sf:
        return None, {}, {}
    fields = list(sf.fields.all())
    entries = ScoutEntry.objects.filter(team=team, event=event, form=sf)
    summaries = team_summaries(entries, fields)
    return sf, summaries, event_field_averages(summaries, fields)


def _team_block(et, summaries, notes_by_team):
    s = summaries.get(et.team.number) if et else None
    return {
        "team": et.team.number,
        "name": et.team.nickname,
        "rank": et.rank,
        "record": et.record,
        "ranking_score": et.ranking_score,
        "epa": {"total": et.epa_total, "auto": et.epa_auto, "teleop": et.epa_teleop, "endgame": et.epa_endgame},
        "opr": et.opr,
        "scouting": None if not s else {
            "entries": s["n"],
            "est_points": s["points"],
            "fields": {k: v.get("display") for k, v in s["fields"].items() if v.get("display")},
        },
        "notes": notes_by_team.get(et.team.number, [])[:5],
    }


def _notes_by_team(team, event):
    out = {}
    for n in MatchNote.objects.filter(team=team, event=event).order_by("-created_at")[:200]:
        if n.about_team:
            out.setdefault(n.about_team, []).append(f"[{n.match_key or '-'} {n.category}] {n.text[:200]}")
    return out


def event_team_rows(event):
    return {et.team.number: et for et in EventTeam.objects.filter(event=event).select_related("team")}


def match_context(team, event, match):
    rows = event_team_rows(event)
    _, summaries, _ = scouting_summaries(team, event)
    notes = _notes_by_team(team, event)
    ours = match.alliance_of(team.number)

    def alliance(numbers):
        return [_team_block(rows[n], summaries, notes) if n in rows else {"team": n} for n in numbers]

    return {
        "kind": "match",
        "our_team": team.number,
        "our_alliance": ours,
        "event": {"key": event.key, "name": event.name, "year": event.year},
        "match": {
            "key": match.key, "label": match.label, "played": match.is_played,
            "red_score": match.red_score, "blue_score": match.blue_score,
            "statbotics_red_win_prob": match.pred_red_win_prob,
            "statbotics_pred": {"red": match.pred_red_score, "blue": match.pred_blue_score},
        },
        "red": alliance(match.red_teams),
        "blue": alliance(match.blue_teams),
    }


def team_context(team, event, frc_number):
    rows = event_team_rows(event)
    sf, summaries, averages = scouting_summaries(team, event)
    notes = _notes_by_team(team, event)
    et = rows.get(frc_number)
    matches = []
    for m in event.matches.all():
        side = m.alliance_of(frc_number)
        if not side:
            continue
        mine, theirs = (m.red_score, m.blue_score) if side == "red" else (m.blue_score, m.red_score)
        matches.append({"label": m.label, "alliance": side, "played": m.is_played, "score": mine, "opp_score": theirs,
                        "won": None if not m.is_played else m.winning_alliance == side})
    field_meta = {f.key: {"label": f.label, "type": f.field_type, "phase": f.phase} for f in (sf.fields.all() if sf else [])}

    def epa_rank(attr):
        vals = sorted([getattr(r, attr) for r in rows.values() if getattr(r, attr) is not None], reverse=True)
        v = getattr(et, attr) if et else None
        return (vals.index(v) + 1, len(vals)) if v is not None and v in vals else None

    return {
        "kind": "team",
        "our_team": team.number,
        "subject_team": frc_number,
        "event": {"key": event.key, "name": event.name, "year": event.year, "teams": len(rows)},
        "team": _team_block(et, summaries, notes) if et else {"team": frc_number},
        "epa_ranks": {k: epa_rank(f"epa_{k}") for k in ("total", "auto", "teleop", "endgame")},
        "scouting_detail": summaries.get(frc_number, {}).get("fields", {}),
        "event_field_averages": averages,
        "field_meta": field_meta,
        "matches": matches,
    }
