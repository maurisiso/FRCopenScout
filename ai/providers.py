"""
AI providers. The app only ever calls `get_provider().answer(question, context)`.

* StubProvider   - rule-based tips computed from the numbers. Works today with no model.
* OllamaProvider - sends the same context to a local LLM served by Ollama (Phase 2).

To add your own trained model later, write a class with an `answer` method and
register it in PROVIDERS.
"""
import json
import logging
import math

import requests
from django.conf import settings

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an expert FIRST Robotics Competition strategist helping a team during an event. "
    "You receive JSON with Statbotics EPA (expected points a robot adds per match, split into auto/teleop/endgame), "
    "TBA rankings, the team's own scouting summaries and pit/match notes. Base every claim on that data, cite "
    "numbers, say when data is thin (few scouting entries), and give short, actionable advice. "
    "Answer in the same language as the question."
)


def _f(x, nd=1):
    return "?" if x is None else f"{x:.{nd}f}"


def _sum_epa(alliance, part="total"):
    vals = [t.get("epa", {}).get(part) for t in alliance if t.get("epa")]
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


class StubProvider:
    name = "built-in rules"

    def answer(self, question, context):
        kind = context.get("kind")
        if kind == "match":
            return self._match(context)
        if kind == "team":
            return self._team(context)
        return "I don't have enough data to answer that yet."

    # ----------------------------------------------------------------
    def _match(self, c):
        ours = c.get("our_alliance")
        red, blue = c["red"], c["blue"]
        lines = []
        r_epa, b_epa = _sum_epa(red), _sum_epa(blue)
        prob = c["match"].get("statbotics_red_win_prob")
        if prob is None and r_epa is not None and b_epa is not None:
            prob = 1 / (1 + math.exp(-(r_epa - b_epa) / 12))  # rough logistic on EPA gap
        if r_epa is not None and b_epa is not None:
            lines.append(f"Expected score from EPA: Red {_f(r_epa)} vs Blue {_f(b_epa)}.")
        if prob is not None:
            fav = "Red" if prob >= 0.5 else "Blue"
            lines.append(f"Favourite: {fav} ({_f(max(prob, 1 - prob) * 100, 0)}% win chance).")

        if ours:
            mine, theirs = (red, blue) if ours == "red" else (blue, red)
            lines.append("")
            lines.append(f"Plan for your alliance ({ours.title()}):")
            for part in ("auto", "teleop", "endgame"):
                a, b = _sum_epa(mine, part), _sum_epa(theirs, part)
                if a is not None and b is not None:
                    diff = a - b
                    tag = "advantage" if diff > 1 else ("behind" if diff < -1 else "even")
                    lines.append(f"- {part.title()}: {_f(a)} vs {_f(b)} ({tag}).")
            scorers = sorted([t for t in mine if t.get("epa", {}).get("teleop") is not None],
                             key=lambda t: t["epa"]["teleop"], reverse=True)
            if scorers:
                lines.append(f"- Primary scorer: {scorers[0]['team']} (teleop EPA {_f(scorers[0]['epa']['teleop'])}).")
            if len(scorers) == 3:
                weakest = scorers[-1]
                lines.append(f"- Consider {weakest['team']} for defense/support if it frees space for the scorers.")
            threats = sorted([t for t in theirs if t.get("epa", {}).get("total") is not None],
                             key=lambda t: t["epa"]["total"], reverse=True)
            if threats:
                lines.append(f"- Biggest threat: {threats[0]['team']} (EPA {_f(threats[0]['epa']['total'])}). "
                             "Defending them likely costs them more points than it costs you.")
        flagged = [t for t in red + blue if t.get("notes")]
        if flagged:
            lines.append("")
            lines.append("Notes from your scouts:")
            for t in flagged:
                lines.append(f"- {t['team']}: {t['notes'][0]}")
        thin = [str(t["team"]) for t in red + blue if not (t.get("scouting") or {}).get("entries")]
        if thin:
            lines.append("")
            lines.append(f"No scouting data yet for: {', '.join(thin)}. Advice above relies on EPA only.")
        return "\n".join(lines)

    def _team(self, c):
        t = c.get("team", {})
        lines = []
        epa = t.get("epa") or {}
        ranks = c.get("epa_ranks") or {}
        if epa.get("total") is not None:
            lines.append(f"Team {c['subject_team']}: EPA {_f(epa['total'])}, rank {t.get('rank') or '?'} ({t.get('record', '')}).")
            for part in ("auto", "teleop", "endgame"):
                r = ranks.get(part)
                if r:
                    lines.append(f"- {part.title()} EPA {_f(epa.get(part))}: #{r[0]} of {r[1]} at this event.")
        detail = c.get("scouting_detail") or {}
        avgs = c.get("event_field_averages") or {}
        meta = c.get("field_meta") or {}
        strengths, weaknesses = [], []
        for key, s in detail.items():
            if s.get("avg") is not None and key in avgs and avgs[key]:
                ratio = s["avg"] / avgs[key]
                label = meta.get(key, {}).get("label", key)
                if ratio >= 1.2:
                    strengths.append(f"{label}: {s['avg']:g} vs event avg {avgs[key]:g}")
                elif ratio <= 0.8:
                    weaknesses.append(f"{label}: {s['avg']:g} vs event avg {avgs[key]:g}")
            if s.get("type") == "boolean" and "disabl" in key and s.get("rate"):
                weaknesses.append(f"Disabled/died in {s['rate']}% of scouted matches - check wiring, battery and radio.")
        if strengths:
            lines.append("")
            lines.append("Strengths (from your scouting):")
            lines += [f"- {s}" for s in strengths]
        if weaknesses:
            lines.append("")
            lines.append("Where to improve:")
            lines += [f"- {w}" for w in weaknesses]
        if ranks:
            weakest = min((p for p in ("auto", "teleop", "endgame") if ranks.get(p)),
                          key=lambda p: -ranks[p][0] / ranks[p][1], default=None)
            if weakest:
                lines.append("")
                lines.append(f"Biggest relative gap by EPA is {weakest}. Practising that phase likely gains the most points.")
        played = [m for m in c.get("matches", []) if m["played"]]
        if played:
            wins = sum(1 for m in played if m["won"])
            lines.append("")
            lines.append(f"Played {len(played)} matches, won {wins}.")
        if t.get("notes"):
            lines.append("")
            lines.append("Recent notes:")
            lines += [f"- {n}" for n in t["notes"][:3]]
        if not detail:
            lines.append("")
            lines.append("No scouting entries for this team yet - scout a few matches for more specific tips.")
        return "\n".join(lines) or "Not enough data yet."


class OllamaProvider:
    """Calls a local model through Ollama's HTTP API (https://ollama.com)."""

    name = "local model (Ollama)"

    def answer(self, question, context):
        payload = {
            "model": settings.OLLAMA_MODEL,
            "stream": False,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"DATA:\n{json.dumps(context, default=str)}\n\nQUESTION: {question}"},
            ],
        }
        try:
            resp = requests.post(f"{settings.OLLAMA_URL}/api/chat", json=payload, timeout=120)
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            log.warning("Ollama failed, falling back to rules: %s", exc)
            return "(Local model unavailable, showing rule-based tips.)\n\n" + StubProvider().answer(question, context)


PROVIDERS = {"stub": StubProvider, "ollama": OllamaProvider}


def get_provider():
    return PROVIDERS.get(settings.AI_PROVIDER, StubProvider)()
