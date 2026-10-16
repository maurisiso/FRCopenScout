"""
Local cache of public FRC data pulled from The Blue Alliance (TBA) and Statbotics.

We keep a copy in our own database so pages load fast, work when the venue
Wi-Fi is bad, and so we don't hammer the public APIs.
"""
from django.db import models

COMP_LEVEL_ORDER = {"qm": 0, "ef": 1, "qf": 2, "sf": 3, "f": 4}


class FRCTeam(models.Model):
    number = models.PositiveIntegerField(unique=True)
    nickname = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state_prov = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=120, blank=True)
    rookie_year = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["number"]

    def __str__(self):
        return f"{self.number} {self.nickname}".strip()

    @property
    def key(self):
        return f"frc{self.number}"


class Event(models.Model):
    key = models.CharField(max_length=32, unique=True)  # e.g. "2026mxmo"
    year = models.PositiveIntegerField(db_index=True)
    name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=120, blank=True)
    event_type = models.IntegerField(null=True, blank=True)  # TBA EventType enum (0 = Regional, 1 = District, ...)
    event_type_string = models.CharField(max_length=60, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state_prov = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=120, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    week = models.IntegerField(null=True, blank=True)
    district_key = models.CharField(max_length=32, blank=True)
    is_demo = models.BooleanField(default=False, help_text="Fake event created by `seed_demo` (never synced).")
    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_error = models.TextField(blank=True)
    teams = models.ManyToManyField(FRCTeam, through="EventTeam", related_name="events")

    class Meta:
        ordering = ["start_date", "key"]

    def __str__(self):
        return f"{self.name} ({self.key})"

    @property
    def display_name(self):
        return self.short_name or self.name

    @property
    def is_championship_division(self):
        return self.event_type == 3  # TBA: CMP_DIVISION

    @property
    def qualifications_complete(self):
        quals = self.matches.filter(comp_level="qm")
        return quals.exists() and not quals.filter(red_score__isnull=True).exists()


class EventTeam(models.Model):
    """A team attending an event, plus its stats at that event."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="event_teams")
    team = models.ForeignKey(FRCTeam, on_delete=models.CASCADE, related_name="event_entries")
    # TBA rankings
    rank = models.PositiveIntegerField(null=True, blank=True)
    wins = models.PositiveIntegerField(default=0)
    losses = models.PositiveIntegerField(default=0)
    ties = models.PositiveIntegerField(default=0)
    matches_played = models.PositiveIntegerField(default=0)
    ranking_score = models.FloatField(null=True, blank=True)
    # Statbotics EPA ("expected points added": how many points this robot adds per match)
    epa_total = models.FloatField(null=True, blank=True)
    epa_auto = models.FloatField(null=True, blank=True)
    epa_teleop = models.FloatField(null=True, blank=True)
    epa_endgame = models.FloatField(null=True, blank=True)
    # TBA OPR (offensive power rating), a classic alternative metric
    opr = models.FloatField(null=True, blank=True)
    statbotics_raw = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [("event", "team")]
        ordering = ["rank", "team__number"]

    def __str__(self):
        return f"{self.team.number} @ {self.event.key}"

    @property
    def record(self):
        return f"{self.wins}-{self.losses}-{self.ties}"


class Match(models.Model):
    key = models.CharField(max_length=40, unique=True)  # e.g. "2026mxmo_qm12"
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="matches")
    comp_level = models.CharField(max_length=4)  # qm, ef, qf, sf, f
    set_number = models.PositiveIntegerField(default=1)
    match_number = models.PositiveIntegerField()
    sort_order = models.PositiveIntegerField(default=0, db_index=True)
    red_teams = models.JSONField(default=list)  # [254, 1678, 118]
    blue_teams = models.JSONField(default=list)
    red_score = models.IntegerField(null=True, blank=True)
    blue_score = models.IntegerField(null=True, blank=True)
    winning_alliance = models.CharField(max_length=4, blank=True)  # "red", "blue", "" (tie / not played)
    scheduled_time = models.DateTimeField(null=True, blank=True)
    predicted_time = models.DateTimeField(null=True, blank=True)
    actual_time = models.DateTimeField(null=True, blank=True)
    # Statbotics prediction
    pred_red_win_prob = models.FloatField(null=True, blank=True)
    pred_red_score = models.FloatField(null=True, blank=True)
    pred_blue_score = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["sort_order"]
        verbose_name_plural = "matches"

    def __str__(self):
        return self.key

    def save(self, *args, **kwargs):
        self.sort_order = COMP_LEVEL_ORDER.get(self.comp_level, 9) * 100000 + self.set_number * 1000 + self.match_number
        super().save(*args, **kwargs)

    @property
    def is_played(self):
        return self.red_score is not None and self.red_score >= 0

    @property
    def label(self):
        if self.comp_level == "qm":
            return f"Q{self.match_number}"
        if self.comp_level == "f":
            return f"F{self.match_number}"
        if self.comp_level == "sf":
            # Since 2023 the double-elimination bracket uses sf sets 1..13, one match each.
            return f"M{self.set_number}" if self.match_number == 1 else f"SF{self.set_number}-{self.match_number}"
        return f"{self.comp_level.upper()}{self.set_number}-{self.match_number}"

    def alliance_of(self, team_number):
        if team_number in self.red_teams:
            return "red"
        if team_number in self.blue_teams:
            return "blue"
        return None

    @property
    def all_teams(self):
        return list(self.red_teams) + list(self.blue_teams)


class EventAlliance(models.Model):
    """Official playoff alliances as published by TBA after alliance selection."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="alliances")
    number = models.PositiveIntegerField()
    picks = models.JSONField(default=list)  # [captain, pick1, pick2, (pick3)]
    declines = models.JSONField(default=list)
    backup = models.JSONField(null=True, blank=True)

    class Meta:
        unique_together = [("event", "number")]
        ordering = ["number"]
