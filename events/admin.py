from django.contrib import admin

from .models import AlliancePrediction, TrackedEvent

admin.site.register(TrackedEvent)
admin.site.register(AlliancePrediction)
