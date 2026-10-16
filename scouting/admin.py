from django.contrib import admin

from .models import FormField, MatchNote, ScoutEntry, ScoutingForm


class FormFieldInline(admin.TabularInline):
    model = FormField
    extra = 0


@admin.register(ScoutingForm)
class ScoutingFormAdmin(admin.ModelAdmin):
    list_display = ("name", "team", "kind", "season", "is_active")
    list_filter = ("season", "kind")
    inlines = [FormFieldInline]


@admin.register(ScoutEntry)
class ScoutEntryAdmin(admin.ModelAdmin):
    list_display = ("team", "event", "match_key", "scouted_team", "scout", "created_at", "synced_offline")
    list_filter = ("event", "team")
    search_fields = ("match_key", "scouted_team")


@admin.register(MatchNote)
class MatchNoteAdmin(admin.ModelAdmin):
    list_display = ("team", "event", "match_key", "about_team", "category", "created_at")
    list_filter = ("category", "event")
