from django.contrib import admin

from .models import Event, EventAlliance, EventTeam, FRCTeam, Match


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "year", "event_type_string", "start_date", "is_demo", "last_synced_at")
    list_filter = ("year", "is_demo", "event_type_string")
    search_fields = ("key", "name")


@admin.register(FRCTeam)
class FRCTeamAdmin(admin.ModelAdmin):
    list_display = ("number", "nickname", "city", "country")
    search_fields = ("number", "nickname")


@admin.register(EventTeam)
class EventTeamAdmin(admin.ModelAdmin):
    list_display = ("event", "team", "rank", "epa_total", "opr")
    list_filter = ("event__year",)
    search_fields = ("event__key", "team__number")


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("key", "red_teams", "blue_teams", "red_score", "blue_score")
    search_fields = ("key",)


admin.site.register(EventAlliance)
