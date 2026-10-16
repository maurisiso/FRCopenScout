from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from frcdata.models import Event, Match
from teams.permissions import team_view

from .context import match_context, team_context
from .models import AIQuery
from .providers import get_provider


@require_POST
@team_view()
def ask(request, team, membership, event_key):
    """HTMX endpoint: returns an HTML fragment with the assistant's answer."""
    event = get_object_or_404(Event, key=event_key)
    kind = request.POST.get("kind")
    question = (request.POST.get("question") or "").strip()[:1000]
    if kind == "match":
        match = get_object_or_404(Match, key=request.POST.get("match_key"), event=event)
        context = match_context(team, event, match)
        question = question or "How should we play this match?"
    elif kind == "team":
        number = int(request.POST.get("team") or team.number)
        context = team_context(team, event, number)
        question = question or "What are this team's strengths and how can it improve?"
    else:
        return HttpResponseBadRequest("unknown kind")
    provider = get_provider()
    answer = provider.answer(question, context)
    q = AIQuery.objects.create(team=team, event=event, user=request.user, kind=kind, question=question,
                               context=context, answer=answer, provider=provider.name)
    return render(request, "ai/answer.html", {"answer": answer, "question": question, "provider": provider.name, "q": q, "team": team})


@require_POST
@team_view()
def feedback(request, team, membership, query_id):
    q = get_object_or_404(AIQuery, pk=query_id, team=team)
    q.helpful = request.POST.get("helpful") == "1"
    q.save(update_fields=["helpful"])
    return render(request, "ai/feedback_thanks.html")
