"""
Turn raw scouting entries into per-team statistics.

Nothing here uses AI: it's averages, rates and counts that any scout can verify.
"""
from collections import Counter, defaultdict
from statistics import mean, pstdev

from .models import FormField


def entry_points(entry_data, fields):
    """Estimated points for one entry, from fields that have a 'points each' value."""
    total, used = 0.0, False
    for f in fields:
        if f.points is None:
            continue
        v = entry_data.get(f.key)
        if v is None:
            continue
        if f.field_type == FormField.FieldType.BOOLEAN:
            v = 1 if v else 0
        try:
            total += float(v) * f.points
            used = True
        except (TypeError, ValueError):
            continue
    return round(total, 1) if used else None


def summarize_field(field, values):
    values = [v for v in values if v is not None]
    out = {"key": field.key, "label": field.label, "type": field.field_type, "n": len(values)}
    if not values:
        return out
    t = field.field_type
    if field.is_numeric:
        nums = [float(v) for v in values if isinstance(v, (int, float))]
        if nums:
            out.update(avg=round(mean(nums), 2), max=max(nums), min=min(nums), sd=round(pstdev(nums), 2))
            out["display"] = f"{out['avg']:g}"
    elif t == FormField.FieldType.BOOLEAN:
        rate = sum(1 for v in values if v) / len(values)
        out.update(rate=round(rate * 100))
        out["display"] = f"{out['rate']}%"
    elif t in (FormField.FieldType.CHOICE, FormField.FieldType.MULTI):
        c = Counter()
        for v in values:
            c.update(v if isinstance(v, list) else [v])
        out["counts"] = dict(c.most_common())
        top = c.most_common(1)
        out["display"] = f"{top[0][0]} ({top[0][1]}/{len(values)})" if top else ""
    else:
        out["texts"] = [v for v in values if v][-5:]
        out["display"] = f"{len(out['texts'])} notes"
    return out


def team_summaries(entries, fields):
    """
    Returns {team_number: {"n": count, "points": avg est. points, "fields": {key: summary}}}.
    `entries` is an iterable of ScoutEntry, `fields` a list of FormField.
    """
    by_team = defaultdict(list)
    for e in entries:
        by_team[e.scouted_team].append(e)
    result = {}
    for team, rows in by_team.items():
        pts = [p for p in (entry_points(r.data, fields) for r in rows) if p is not None]
        result[team] = {
            "n": len(rows),
            "points": round(mean(pts), 1) if pts else None,
            "points_sd": round(pstdev(pts), 1) if len(pts) > 1 else None,
            "fields": {f.key: summarize_field(f, [r.data.get(f.key) for r in rows]) for f in fields},
        }
    return result


def event_field_averages(summaries, fields):
    """Average of each numeric field across all scouted teams (to compare a team against the event)."""
    out = {}
    for f in fields:
        vals = [s["fields"][f.key].get("avg") for s in summaries.values() if s["fields"].get(f.key, {}).get("avg") is not None]
        if vals:
            out[f.key] = round(mean(vals), 2)
    return out
