from datetime import timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .forms import InviteForm, JoinCodeForm, RoleForm, TeamClaimForm
from .models import Invite, Membership, Role, Team, TeamClaim
from .permissions import team_view


@login_required
def dashboard(request):
    """Landing page after login: your teams, pending requests, join with a code."""
    memberships = request.user.memberships.select_related("team")
    if memberships.count() == 1 and memberships[0].team.is_approved and not request.GET.get("all"):
        return redirect("team_home", team_number=memberships[0].team.number)
    return render(request, "teams/dashboard.html", {
        "memberships": memberships,
        "claims": request.user.team_claims.filter(status=TeamClaim.Status.PENDING).select_related("team"),
        "join_form": JoinCodeForm(),
    })


@login_required
def register_team(request):
    """A mentor/coach asks to manage a team. Staff must approve it."""
    if request.method == "POST":
        form = TeamClaimForm(request.POST)
        if form.is_valid():
            number = form.cleaned_data["team_number"]
            with transaction.atomic():
                team, created = Team.objects.get_or_create(
                    number=number, defaults={"nickname": form.cleaned_data["nickname"]}
                )
                if team.status == Team.Status.REJECTED:
                    team.status = Team.Status.PENDING
                    team.save()
                if TeamClaim.objects.filter(user=request.user, team=team, status=TeamClaim.Status.PENDING).exists():
                    messages.info(request, _("You already have a pending request for this team."))
                    return redirect("dashboard")
                claim = form.save(commit=False)
                claim.user = request.user
                claim.team = team
                claim.save()
            if not created and team.is_approved:
                messages.info(request, _(
                    "Team %(n)s is already on the platform. Your request was sent to our staff, but the fastest way "
                    "in is to ask one of your team's admins for an invite code."
                ) % {"n": number})
            else:
                messages.success(request, _("Request sent! Our staff will verify you and approve the team soon."))
            return redirect("dashboard")
    else:
        form = TeamClaimForm()
    return render(request, "teams/register.html", {"form": form})


@login_required
def join(request, code=None):
    code = (code or request.POST.get("code") or request.GET.get("code") or "").strip().upper()
    invite = Invite.objects.select_related("team").filter(code=code).first()
    if not invite or not invite.is_usable or not invite.team.is_approved:
        messages.error(request, _("That invite code is invalid or has expired."))
        return redirect("dashboard")
    if request.method == "POST":
        membership, created = Membership.objects.get_or_create(
            user=request.user, team=invite.team, defaults={"role": invite.role}
        )
        if created:
            Invite.objects.filter(pk=invite.pk).update(uses=invite.uses + 1)
            messages.success(request, _("Welcome to team %(n)s!") % {"n": invite.team.number})
        else:
            messages.info(request, _("You are already a member of this team."))
        return redirect("team_home", team_number=invite.team.number)
    return render(request, "teams/join.html", {"invite": invite})


@team_view(min_role=Role.ADMIN, allow_pending=True)
def members(request, team, membership):
    invite_form = InviteForm()
    if request.method == "POST":
        invite_form = InviteForm(request.POST)
        if invite_form.is_valid():
            if not team.is_approved:
                messages.error(request, _("You can invite members once your team is approved."))
            else:
                invite = invite_form.save(commit=False)
                invite.team = team
                invite.created_by = request.user
                invite.expires_at = timezone.now() + timedelta(days=invite_form.cleaned_data["days_valid"])
                invite.save()
                messages.success(request, _("Invite created: %(code)s") % {"code": invite.code})
            return redirect("team_members", team_number=team.number)
    invites = team.invites.filter(active=True, expires_at__gt=timezone.now())
    join_base = request.build_absolute_uri(reverse("join_code", args=["CODE"])).replace("CODE/", "")
    return render(request, "teams/members.html", {
        "team": team,
        "membership": membership,
        "members": team.memberships.select_related("user").order_by("role", "user__email"),
        "invites": invites,
        "invite_form": invite_form,
        "role_choices": Role.choices,
        "join_base": join_base,
    })


def _admin_count(team):
    return team.memberships.filter(role=Role.ADMIN).count()


@require_POST
@team_view(min_role=Role.ADMIN)
def change_role(request, team, membership, member_id):
    target = get_object_or_404(Membership, pk=member_id, team=team)
    form = RoleForm(request.POST)
    if form.is_valid():
        new_role = form.cleaned_data["role"]
        if target.role == Role.ADMIN and new_role != Role.ADMIN and _admin_count(team) <= 1:
            messages.error(request, _("A team needs at least one admin."))
        else:
            target.role = new_role
            target.save()
            messages.success(request, _("Role updated."))
    return redirect("team_members", team_number=team.number)


@require_POST
@team_view(min_role=Role.ADMIN)
def remove_member(request, team, membership, member_id):
    """Admins can remove (kick) any member at any time."""
    target = get_object_or_404(Membership, pk=member_id, team=team)
    if target.role == Role.ADMIN and _admin_count(team) <= 1:
        messages.error(request, _("You can't remove the last admin."))
    else:
        target.delete()
        messages.success(request, _("%(user)s was removed from the team.") % {"user": target.user.name})
    return redirect("team_members", team_number=team.number)


@require_POST
@team_view(min_role=Role.ADMIN)
def revoke_invite(request, team, membership, invite_id):
    Invite.objects.filter(pk=invite_id, team=team).update(active=False)
    messages.success(request, _("Invite revoked."))
    return redirect("team_members", team_number=team.number)


@require_POST
@team_view(allow_pending=True)
def leave_team(request, team, membership):
    if membership.role == Role.ADMIN and _admin_count(team) <= 1 and team.memberships.count() > 1:
        messages.error(request, _("Promote another admin before leaving."))
        return redirect("team_members", team_number=team.number)
    membership.delete()
    messages.success(request, _("You left team %(n)s.") % {"n": team.number})
    return redirect("profile")


@staff_member_required
def approvals(request):
    """Platform staff: verify that people claiming a team are real mentors/coaches."""
    if request.method == "POST":
        claim = get_object_or_404(TeamClaim, pk=request.POST.get("claim_id"), status=TeamClaim.Status.PENDING)
        note = request.POST.get("note", "")
        if request.POST.get("decision") == "approve":
            claim.approve(request.user, note)
            messages.success(request, _("Approved %(user)s as admin of %(n)s.") % {"user": claim.user, "n": claim.team.number})
        else:
            claim.reject(request.user, note)
            messages.info(request, _("Request rejected."))
        return redirect("staff_approvals")
    pending = TeamClaim.objects.filter(status=TeamClaim.Status.PENDING).select_related("user", "team")
    recent = TeamClaim.objects.exclude(status=TeamClaim.Status.PENDING).select_related("user", "team", "reviewed_by")[:20]
    for claim in pending:
        claim.existing_admins = claim.team.memberships.filter(role=Role.ADMIN).select_related("user")
        claim.user_teams = claim.user.memberships.select_related("team")
    stats = Team.objects.values("status").annotate(n=Count("id"))
    return render(request, "teams/approvals.html", {"pending": pending, "recent": recent, "stats": stats})


@team_view(min_role=Role.ADMIN)
def contributions(request, team, membership):
    """Admins: how much each scout has contributed (entries, pit entries, notes, events)."""
    from django.db.models import Count, Max, Q

    from frcdata.models import Event
    from scouting.models import MatchNote, ScoutEntry, ScoutingForm

    entries = ScoutEntry.objects.filter(team=team)
    notes = MatchNote.objects.filter(team=team)
    seasons = sorted(set(entries.values_list("event__year", flat=True)), reverse=True)
    season = request.GET.get("season")
    event_key = request.GET.get("event")
    if season and season.isdigit():
        entries = entries.filter(event__year=int(season))
        notes = notes.filter(event__year=int(season))
    if event_key:
        entries = entries.filter(event__key=event_key)
        notes = notes.filter(event__key=event_key)

    stats = {r["scout"]: r for r in entries.values("scout").annotate(
        match=Count("id", filter=Q(form__kind=ScoutingForm.Kind.MATCH)),
        pit=Count("id", filter=Q(form__kind=ScoutingForm.Kind.PIT)),
        events=Count("event", distinct=True),
        last=Max("created_at"),
    )}
    note_counts = dict(notes.values_list("author").annotate(n=Count("id")))
    members = {m.user_id: m for m in team.memberships.select_related("user")}
    user_ids = set(members) | {k for k in stats if k} | {k for k in note_counts if k}
    from django.contrib.auth import get_user_model

    users = {u.id: u for u in get_user_model().objects.filter(id__in=user_ids)}
    rows = []
    for uid in user_ids:
        s = stats.get(uid, {})
        total = s.get("match", 0) + s.get("pit", 0)
        rows.append({
            "user": users.get(uid), "membership": members.get(uid),
            "match": s.get("match", 0), "pit": s.get("pit", 0), "notes": note_counts.get(uid, 0),
            "events": s.get("events", 0), "last": s.get("last"), "total": total,
        })
    rows.sort(key=lambda r: (-(r["total"] + r["notes"]), str(r["user"])))
    top = max([r["total"] + r["notes"] for r in rows], default=0)
    totals = {k: sum(r[k] for r in rows) for k in ("match", "pit", "notes")}
    event_ids = ScoutEntry.objects.filter(team=team).values_list("event_id", flat=True).distinct()
    return render(request, "teams/contributions.html", {
        "team": team, "membership": membership, "rows": rows, "top": top, "totals": totals,
        "seasons": seasons, "season": season or "", "event_key": event_key or "",
        "events": Event.objects.filter(id__in=event_ids).order_by("-start_date"),
        "unassigned": stats.get(None, {}).get("match", 0) + stats.get(None, {}).get("pit", 0),
    })
