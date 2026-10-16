def my_teams(request):
    """Expose the signed-in user's teams to every template (for the nav menu)."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    return {
        "nav_memberships": user.memberships.select_related("team").order_by("team__number"),
        "current_team": getattr(request, "team", None),
    }
