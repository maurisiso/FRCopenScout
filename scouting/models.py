"""
Custom scouting forms.

Every season has a different game, so instead of hard-coding columns like
"notes scored in speaker", each team designs its own form: a ScoutingForm with
a list of FormFields. Answers are stored as JSON ({field_key: value}) in a
ScoutEntry. This means a new game never needs a database migration.
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from frcdata.models import Event, Match
from teams.models import Team


class ScoutingForm(models.Model):
    class Kind(models.TextChoices):
        MATCH = "match", _("Match scouting (one robot, one match)")
        PIT = "pit", _("Pit scouting (one robot, once per event)")

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="scouting_forms")
    name = models.CharField(_("name"), max_length=100)
    kind = models.CharField(_("type"), max_length=10, choices=Kind.choices, default=Kind.MATCH)
    season = models.PositiveIntegerField(_("season"), default=settings.DEFAULT_SEASON)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-season", "kind", "name"]

    def __str__(self):
        return f"{self.name} ({self.season})"

    def as_schema(self):
        """JSON description of the form, used by the offline scouting page."""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "fields": [f.as_schema() for f in self.fields.all()],
            "updated": self.updated_at.isoformat(),
        }


class FormField(models.Model):
    class FieldType(models.TextChoices):
        COUNTER = "counter", _("Counter (+/- buttons)")
        NUMBER = "number", _("Number")
        BOOLEAN = "boolean", _("Yes / No")
        CHOICE = "choice", _("Single choice")
        MULTI = "multi", _("Multiple choice")
        RATING = "rating", _("Rating (1-5)")
        TEXT = "text", _("Text")

    class Phase(models.TextChoices):
        PREMATCH = "prematch", _("Pre-match")
        AUTO = "auto", _("Autonomous")
        TELEOP = "teleop", _("Teleop")
        ENDGAME = "endgame", _("Endgame")
        GENERAL = "general", _("General")

    NUMERIC_TYPES = {FieldType.COUNTER, FieldType.NUMBER, FieldType.RATING}

    form = models.ForeignKey(ScoutingForm, on_delete=models.CASCADE, related_name="fields")
    key = models.SlugField(_("key"), max_length=50, help_text=_("Short id used in exports, e.g. auto_coral_l4"))
    label = models.CharField(_("label"), max_length=100)
    field_type = models.CharField(_("data type"), max_length=10, choices=FieldType.choices, default=FieldType.COUNTER)
    phase = models.CharField(_("phase"), max_length=10, choices=Phase.choices, default=Phase.TELEOP)
    help_text = models.CharField(_("help text"), max_length=200, blank=True)
    options = models.JSONField(_("options"), default=list, blank=True, help_text=_("For choice fields"))
    min_value = models.IntegerField(_("minimum"), null=True, blank=True)
    max_value = models.IntegerField(_("maximum"), null=True, blank=True)
    points = models.FloatField(
        _("points each"), null=True, blank=True,
        help_text=_("Optional: game points per unit, used to estimate scouted points."),
    )
    required = models.BooleanField(_("required"), default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        unique_together = [("form", "key")]

    def __str__(self):
        return f"{self.label} [{self.field_type}]"

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = slugify(self.label).replace("-", "_")[:50] or "field"
        super().save(*args, **kwargs)

    @property
    def is_numeric(self):
        return self.field_type in self.NUMERIC_TYPES

    def as_schema(self):
        return {
            "key": self.key,
            "label": self.label,
            "type": self.field_type,
            "phase": self.phase,
            "help": self.help_text,
            "options": self.options or [],
            "min": self.min_value,
            "max": self.max_value,
            "required": self.required,
        }

    def clean_value(self, raw):
        """Validate/convert one submitted answer. Raises ValidationError."""
        t = self.field_type
        if raw in (None, "", []):
            if self.required:
                raise ValidationError(_("%(label)s is required") % {"label": self.label})
            return None
        if t in (self.FieldType.COUNTER, self.FieldType.NUMBER, self.FieldType.RATING):
            try:
                value = float(raw)
            except (TypeError, ValueError):
                raise ValidationError(_("%(label)s must be a number") % {"label": self.label})
            if value.is_integer():
                value = int(value)
            lo = 1 if t == self.FieldType.RATING else self.min_value
            hi = 5 if t == self.FieldType.RATING else self.max_value
            if lo is not None and value < lo or hi is not None and value > hi:
                raise ValidationError(_("%(label)s is out of range") % {"label": self.label})
            return value
        if t == self.FieldType.BOOLEAN:
            return raw in (True, "true", "on", "1", 1, "yes")
        if t == self.FieldType.CHOICE:
            if raw not in (self.options or []):
                raise ValidationError(_("%(label)s: invalid option") % {"label": self.label})
            return raw
        if t == self.FieldType.MULTI:
            values = raw if isinstance(raw, list) else [raw]
            return [v for v in values if v in (self.options or [])]
        return str(raw)[:2000]


class ScoutEntry(models.Model):
    """One scout's observations of one robot (in one match, or in the pits)."""

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="scout_entries")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="scout_entries")
    form = models.ForeignKey(ScoutingForm, on_delete=models.PROTECT, related_name="entries")
    match = models.ForeignKey(Match, null=True, blank=True, on_delete=models.SET_NULL, related_name="scout_entries")
    match_key = models.CharField(max_length=40, blank=True, db_index=True)
    scouted_team = models.PositiveIntegerField(db_index=True)
    alliance = models.CharField(max_length=4, blank=True)
    data = models.JSONField(default=dict)
    scout = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="scout_entries")
    client_uuid = models.UUIDField(default=uuid.uuid4, help_text="Generated on the phone; makes offline sync safe to retry.")
    recorded_at = models.DateTimeField(null=True, blank=True, help_text="When the scout saved it on their device.")
    created_at = models.DateTimeField(auto_now_add=True)
    synced_offline = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("team", "client_uuid")]
        verbose_name_plural = "scout entries"

    def __str__(self):
        return f"{self.scouted_team} {self.match_key or 'pit'} by {self.scout}"


class MatchNote(models.Model):
    """Free-text notes about a match: robot issues, radio problems, strategy, etc."""

    class Category(models.TextChoices):
        ROBOT = "robot", _("Robot issue (disabled, broken, tipped)")
        COMMS = "comms", _("Radio / connection")
        STRATEGY = "strategy", _("Strategy")
        DRIVE = "drive", _("Driving")
        PENALTY = "penalty", _("Penalties / fouls")
        GOOD = "good", _("What went well")
        OTHER = "other", _("Other")

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="match_notes")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="match_notes")
    match = models.ForeignKey(Match, null=True, blank=True, on_delete=models.SET_NULL, related_name="notes")
    match_key = models.CharField(max_length=40, blank=True, db_index=True)
    about_team = models.PositiveIntegerField(null=True, blank=True, help_text="Which robot the note is about.")
    category = models.CharField(max_length=10, choices=Category.choices, default=Category.OTHER)
    text = models.TextField()
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.category}] {self.match_key}: {self.text[:40]}"
