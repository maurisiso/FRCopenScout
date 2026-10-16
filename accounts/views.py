from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from .forms import ProfileForm


@login_required
def profile(request):
    """User page: profile settings + every team the user belongs to."""
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, _("Profile saved."))
            return redirect("profile")
    else:
        form = ProfileForm(instance=request.user)
    memberships = request.user.memberships.select_related("team").order_by("team__number")
    claims = request.user.team_claims.select_related("team").order_by("-created_at")
    return render(request, "accounts/profile.html", {"form": form, "memberships": memberships, "claims": claims})
