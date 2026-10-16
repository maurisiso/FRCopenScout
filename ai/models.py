from django.conf import settings
from django.db import models


class AIQuery(models.Model):
    """Log of questions and answers. Useful later as training/evaluation data for Phase 2."""

    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="ai_queries")
    event = models.ForeignKey("frcdata.Event", on_delete=models.CASCADE, related_name="ai_queries")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=10)
    question = models.TextField()
    context = models.JSONField()
    answer = models.TextField()
    provider = models.CharField(max_length=40)
    helpful = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
