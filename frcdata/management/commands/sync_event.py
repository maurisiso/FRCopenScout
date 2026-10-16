from django.core.management.base import BaseCommand, CommandError

from frcdata.clients import APIError
from frcdata.sync import sync_event


class Command(BaseCommand):
    help = "Download an event from TBA + Statbotics. Example: python manage.py sync_event 2025txhou"

    def add_arguments(self, parser):
        parser.add_argument("event_keys", nargs="+")

    def handle(self, *args, **opts):
        for key in opts["event_keys"]:
            try:
                event, errors = sync_event(key)
            except APIError as exc:
                raise CommandError(str(exc))
            self.stdout.write(self.style.SUCCESS(
                f"{event.key}: {event.event_teams.count()} teams, {event.matches.count()} matches"
            ))
            for e in errors:
                self.stdout.write(self.style.WARNING(f"  ! {e}"))
