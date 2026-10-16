"""
Helpers that every team-scoped view uses to check access.

Usage:
    @team_view(min_role=Role.SCOUT)
    def my_view(request, team, membership, ...):
        ...
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from .models import Membership, Role, Team


def team_view(min_role=Role.VIEWER, allow_pending=False):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, team_number, *args, **kwargs):
            team = get_object_or_404(Team, number=team_number)
            membership = Membership.objects.filter(user=request.user, team=team).first()
            if membership is None:
                raise PermissionDenied("You are not a member of this team.")
            if not team.is_approved and not allow_pending:
                return render(request, "teams/pending.html", {"team": team, "membership": membership}, status=403)
            if not membership.has_role(min_role):
                raise PermissionDenied("Your role does not allow this action.")
            request.team = team
            request.membership = membership
            return view(request, team, membership, *args, **kwargs)

        return wrapper

    return decorator
