"""
Keep live events fresh while a competition is running.

    python manage.py refresh_events            # sync every tracked event happening today, once
    python manage.py refresh_events --loop 300 # ...and repeat every 5 minutes (leave it running)
    python manage.py refresh_events --all      # sync every tracked event of the default season

Run it in a second terminal during a regional so pages never wait for TBA.
"""
import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from frcdata.clients import APIError
from frcdata.models import Event
from frcdata.sync import sync_event


class Command(BaseCommand):
    help = "Sync tracked events that are happening now (optionally in a loop)."

    def add_arguments(self, parser):
        parser.add_argument("--loop", type=int, default=0, help="Repeat every N seconds.")
        parser.add_argument("--all", action="store_true", help="All tracked events this season, not just live ones.")

    def handle(self, *args, **opts):
        while True:
            self.run_once(opts["all"])
            if not opts["loop"]:
                return
            time.sleep(max(60, opts["loop"]))

    def run_once(self, all_events):
        today = timezone.localdate()
        qs = Event.objects.filter(is_demo=False, trackers__isnull=False).distinct()
        if all_events:
            qs = qs.filter(year=settings.DEFAULT_SEASON)
        else:
            qs = qs.filter(start_date__lte=today + timedelta(days=1), end_date__gte=today - timedelta(days=1))
        events = list(qs)
        if not events:
            self.stdout.write(f"[{timezone.localtime():%H:%M}] No live tracked events.")
        for event in events:
            try:
                _, errors = sync_event(event.key)
                msg = f"[{timezone.localtime():%H:%M}] {event.key}: ok"
                self.stdout.write(self.style.SUCCESS(msg) if not errors else self.style.WARNING(f"{msg} ({'; '.join(errors)})"))
            except APIError as exc:
                self.stdout.write(self.style.ERROR(f"{event.key}: {exc}"))
