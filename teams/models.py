import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Team(models.Model):
    """An FRC team registered on the platform. Identified by its FRC number."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending approval")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    number = models.PositiveIntegerField(unique=True)
    nickname = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["number"]

    def __str__(self):
        return f"{self.number} {self.nickname}".strip()

    @property
    def tba_key(self):
        return f"frc{self.number}"

    @property
    def is_approved(self):
        return self.status == self.Status.APPROVED


class Role(models.TextChoices):
    ADMIN = "admin", _("Admin")
    SCOUT = "scout", _("Scout")
    VIEWER = "viewer", _("Viewer")


ROLE_LEVEL = {Role.VIEWER: 1, Role.SCOUT: 2, Role.ADMIN: 3}


class Membership(models.Model):
    """A user belongs to a team with one role. Users can belong to many teams."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.SCOUT)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "team")]
        ordering = ["team__number"]

    def __str__(self):
        return f"{self.user} @ {self.team.number} ({self.role})"

    def has_role(self, minimum):
        return ROLE_LEVEL[self.role] >= ROLE_LEVEL[minimum]

    @property
    def is_admin(self):
        return self.role == Role.ADMIN

    @property
    def can_scout(self):
        return self.has_role(Role.SCOUT)


class TeamClaim(models.Model):
    """
    A request to become an admin of a team ("I am a mentor/coach of team 1234").
    Platform staff review these in the Approvals page or the Django admin.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    class Position(models.TextChoices):
        MENTOR = "mentor", _("Mentor")
        COACH = "coach", _("Coach")
        TEACHER = "teacher", _("Teacher / sponsor")
        OTHER = "other", _("Other")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_claims")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="claims")
    position = models.CharField(max_length=10, choices=Position.choices)
    full_name = models.CharField(max_length=120)
    evidence = models.TextField(
        help_text=_("How can we verify you? e.g. team website listing, school email, FIRST dashboard role.")
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    reviewer_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} claims {self.team.number} ({self.status})"

    def approve(self, reviewer, note=""):
        self.status = self.Status.APPROVED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.reviewer_note = note
        self.save()
        team = self.team
        if team.status != Team.Status.APPROVED:
            team.status = Team.Status.APPROVED
            team.approved_at = timezone.now()
            team.save()
        Membership.objects.update_or_create(user=self.user, team=team, defaults={"role": Role.ADMIN})

    def reject(self, reviewer, note=""):
        self.status = self.Status.REJECTED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.reviewer_note = note
        self.save()
        team = self.team
        # A team nobody has ever been approved for goes back to "rejected".
        if team.status == Team.Status.PENDING and not team.memberships.filter(role=Role.ADMIN).exists():
            if not team.claims.filter(status=self.Status.PENDING).exists():
                team.status = Team.Status.REJECTED
                team.save()


def _new_code():
    return secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")[:8].upper()


def _default_expiry():
    return timezone.now() + timedelta(days=14)


class Invite(models.Model):
    """A shareable code/link that lets someone join a team with a given role."""

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="invites")
    code = models.CharField(max_length=12, unique=True, default=_new_code)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.SCOUT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_expiry)
    max_uses = models.PositiveIntegerField(default=30)
    uses = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} → {self.team.number} ({self.role})"

    @property
    def is_usable(self):
        return self.active and self.uses < self.max_uses and self.expires_at > timezone.now()
