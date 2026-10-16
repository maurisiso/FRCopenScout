from django.contrib import admin

from .models import AIQuery


@admin.register(AIQuery)
class AIQueryAdmin(admin.ModelAdmin):
    list_display = ("team", "event", "kind", "question", "provider", "helpful", "created_at")
    list_filter = ("kind", "provider", "helpful")
