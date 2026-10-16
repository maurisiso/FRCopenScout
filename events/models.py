from django.conf import settings
from django.db import models

from frcdata.models import Event
from teams.models import Team


class TrackedEvent(models.Model):
    """An event that appears on a team's dashboard (attending, or added manually to scout)."""

    class Source(models.TextChoices):
        TBA = "tba", "The Blue Alliance"
        MANUAL = "manual", "Added manually"

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="tracked_events")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="trackers")
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.TBA)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("team", "event")]
        ordering = ["event__start_date"]

    def __str__(self):
        return f"{self.team.number} → {self.event.key}"


class AlliancePrediction(models.Model):
    """A user's own alliance-selection prediction, stored as a replayable list of actions."""

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="alliance_predictions")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="alliance_predictions")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    name = models.CharField(max_length=80)
    rankings = models.JSONField(default=list, help_text="Ranking order used when the prediction was made.")
    num_alliances = models.PositiveIntegerField(default=8)
    rounds = models.PositiveIntegerField(default=2)
    actions = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.name} ({self.event.key})"
