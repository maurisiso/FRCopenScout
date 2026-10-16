"""
Pure functions that turn raw API JSON into plain dicts for our models.
Kept separate from the network code so they are easy to unit-test.
"""
from datetime import date, datetime, timezone


def dig(data, *paths, default=None):
    """
    Safely read a nested value. Tries each dotted path in order and returns the
    first one that exists, e.g. dig(d, "epa.total_points.mean", "epa.mean").
    APIs change field names between seasons, so we always allow fallbacks.
    """
    for path in paths:
        cur = data
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur and cur[part] is not None:
                cur = cur[part]
            else:
                ok = False
                break
        if ok:
            return cur
    return default


def team_number(team_key):
    """'frc254' -> 254"""
    if team_key is None:
        return None
    return int(str(team_key).replace("frc", "").rstrip("BCDE")) if str(team_key) else None


def _date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _ts(value):
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def parse_event(data):
    return {
        "year": data.get("year"),
        "name": data.get("name") or data.get("key"),
        "short_name": data.get("short_name") or "",
        "event_type": data.get("event_type"),
        "event_type_string": data.get("event_type_string") or "",
        "city": data.get("city") or "",
        "state_prov": data.get("state_prov") or "",
        "country": data.get("country") or "",
        "start_date": _date(data.get("start_date")),
        "end_date": _date(data.get("end_date")),
        "week": data.get("week"),
        "district_key": dig(data, "district.key", default="") or "",
        "playoff_type": data.get("playoff_type"),
        "webcasts": data.get("webcasts") or [],
        "website": (data.get("website") or "")[:200],
    }


def parse_team(data):
    return {
        "nickname": data.get("nickname") or "",
        "city": data.get("city") or "",
        "state_prov": data.get("state_prov") or "",
        "country": data.get("country") or "",
        "rookie_year": data.get("rookie_year"),
    }


def parse_match(data):
    red = dig(data, "alliances.red", default={}) or {}
    blue = dig(data, "alliances.blue", default={}) or {}
    red_score = red.get("score")
    blue_score = blue.get("score")
    return {
        "comp_level": data.get("comp_level", "qm"),
        "set_number": data.get("set_number") or 1,
        "match_number": data.get("match_number") or 0,
        "red_teams": [team_number(k) for k in red.get("team_keys", [])],
        "blue_teams": [team_number(k) for k in blue.get("team_keys", [])],
        # TBA uses -1 for "not played yet"
        "red_score": red_score if red_score is not None and red_score >= 0 else None,
        "blue_score": blue_score if blue_score is not None and blue_score >= 0 else None,
        "winning_alliance": data.get("winning_alliance") or "",
        "scheduled_time": _ts(data.get("time")),
        "predicted_time": _ts(data.get("predicted_time")),
        "actual_time": _ts(data.get("actual_time")),
        "score_breakdown": data.get("score_breakdown"),
        "videos": data.get("videos") or [],
    }


def parse_rankings(data):
    """Returns {team_number: {...ranking fields}}."""
    out = {}
    for row in (data or {}).get("rankings", []) or []:
        rec = row.get("record") or {}
        sort_orders = row.get("sort_orders") or []
        out[team_number(row["team_key"])] = {
            "rank": row.get("rank"),
            "wins": rec.get("wins", 0),
            "losses": rec.get("losses", 0),
            "ties": rec.get("ties", 0),
            "matches_played": row.get("matches_played", 0),
            "ranking_score": sort_orders[0] if sort_orders else None,
        }
    return out


# Statbotics v3 shape (team_event / team_year):
#   {"epa": {"total_points": 41.2, "norm": 1712, "breakdown": {"total_points": 41.2, "auto_points": ...,
#            "teleop_points": ..., "endgame_points": ..., <game-specific components>},
#            "stats": {"start": ..., "pre_elim": ..., "mean": ..., "max": ...}}, "record": {...}}
# Older responses used {"total_points": {"mean": ..}}, so we keep fallbacks.
def parse_statbotics_team_event(data):
    breakdown = dig(data, "epa.breakdown", default={}) or {}
    return {
        "epa_total": dig(data, "epa.breakdown.total_points", "epa.total_points.mean", "epa.total_points", "epa_end"),
        "epa_auto": dig(data, "epa.breakdown.auto_points", "auto_epa_end"),
        "epa_teleop": dig(data, "epa.breakdown.teleop_points", "teleop_epa_end"),
        "epa_endgame": dig(data, "epa.breakdown.endgame_points", "endgame_epa_end"),
        "epa_start": dig(data, "epa.stats.start"),
        "epa_norm": dig(data, "epa.norm"),
        "epa_breakdown": {k: round(v, 2) for k, v in breakdown.items() if isinstance(v, (int, float))},
    }


def parse_statbotics_team_year(data):
    breakdown = dig(data, "epa.breakdown", default={}) or {}
    rec = dig(data, "record", default={}) or {}
    return {
        "epa": dig(data, "epa.breakdown.total_points", "epa.total_points.mean", "epa.total_points"),
        "epa_norm": dig(data, "epa.norm"),
        "epa_breakdown": {k: round(v, 2) for k, v in breakdown.items() if isinstance(v, (int, float))},
        "world_rank": dig(data, "epa.ranks.total.rank"),
        "world_percentile": dig(data, "epa.ranks.total.percentile"),
        "world_count": dig(data, "epa.ranks.total.team_count"),
        "country_rank": dig(data, "epa.ranks.country.rank"),
        "country_count": dig(data, "epa.ranks.country.team_count"),
        "district_rank": dig(data, "epa.ranks.district.rank"),
        "district_count": dig(data, "epa.ranks.district.team_count"),
        "wins": rec.get("wins") or 0,
        "losses": rec.get("losses") or 0,
        "ties": rec.get("ties") or 0,
    }


def parse_statbotics_match(data):
    return {
        "pred_red_win_prob": dig(data, "pred.red_win_prob", "epa_win_prob"),
        "pred_red_score": dig(data, "pred.red_score", "red_epa_pred"),
        "pred_blue_score": dig(data, "pred.blue_score", "blue_epa_pred"),
    }


def parse_alliances(data):
    out = []
    for i, row in enumerate(data or [], start=1):
        backup = row.get("backup") or None
        out.append({
            "number": i,
            "picks": [team_number(k) for k in row.get("picks", [])],
            "declines": [team_number(k) for k in row.get("declines", []) or []],
            "backup": {"in": team_number(backup.get("in")), "out": team_number(backup.get("out"))} if backup else None,
        })
    return out
