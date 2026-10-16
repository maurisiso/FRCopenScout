"""
Check that your API keys and settings work, and that the live API responses
still have the shape our parsers expect.

    python manage.py check_apis
    python manage.py check_apis --team 1234 --event 2025mxmo
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from frcdata import parsing
from frcdata.clients import APIError, StatboticsClient, TBAClient


class Command(BaseCommand):
    help = "Diagnose TBA, Statbotics and Google sign-in configuration."

    def add_arguments(self, parser):
        parser.add_argument("--team", type=int, default=254, help="Team number to test with (default 254).")
        parser.add_argument("--event", help="Event key to test with, e.g. 2025mxmo.")
        parser.add_argument("--year", type=int, default=None, help="Season (default: DEFAULT_SEASON).")

    # -- output helpers -----------------------------------------------------
    def ok(self, msg):
        self.stdout.write(self.style.SUCCESS(f"  [OK]   {msg}"))

    def warn(self, msg):
        self.stdout.write(self.style.WARNING(f"  [WARN] {msg}"))

    def fail(self, msg):
        self.failures += 1
        self.stdout.write(self.style.ERROR(f"  [FAIL] {msg}"))

    def section(self, title):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{title}"))

    # -----------------------------------------------------------------------
    def handle(self, *args, **opts):
        self.failures = 0
        team, event_key = opts["team"], opts["event"]
        year = opts["year"] or settings.DEFAULT_SEASON
        self.check_settings()
        self.check_tba(team, year, event_key)
        self.check_statbotics(team, year, event_key)
        self.check_google()
        self.stdout.write("")
        if self.failures:
            self.stdout.write(self.style.ERROR(f"{self.failures} problem(s) found."))
        else:
            self.stdout.write(self.style.SUCCESS("Everything looks good."))

    def check_settings(self):
        self.section("Settings")
        env = Path(settings.BASE_DIR) / ".env"
        if env.exists():
            self.ok(".env file found")
        else:
            self.fail(".env file not found. Copy .env.example to .env and put your keys there.")
        example = Path(settings.BASE_DIR) / ".env.example"
        if example.exists():
            for line in example.read_text(encoding="utf-8").splitlines():
                name, _, value = line.partition("=")
                if name in ("TBA_API_KEY", "GOOGLE_CLIENT_SECRET", "GOOGLE_CLIENT_ID") and value.strip():
                    self.fail(f".env.example contains a value for {name}. Keys belong ONLY in .env "
                              "(.env.example is uploaded to GitHub).")
        if settings.SECRET_KEY.startswith("dev-insecure") or settings.SECRET_KEY.startswith("change-me"):
            self.warn("DJANGO_SECRET_KEY is the default. Fine for local testing; change it before deploying.")
        else:
            self.ok("DJANGO_SECRET_KEY is set")

    def check_tba(self, team, year, event_key):
        self.section("The Blue Alliance")
        tba = TBAClient()
        if not tba.configured:
            self.fail("TBA_API_KEY is empty in .env")
            return
        try:
            status = tba.status()
            self.ok(f"API key accepted (TBA current season: {status.get('current_season')}, "
                    f"datafeed down: {status.get('is_datafeed_down')})")
        except APIError as exc:
            self.fail(str(exc))
            return
        try:
            t = tba.team(team)
            if t:
                self.ok(f"Team {team}: {t.get('nickname')} ({t.get('city')}, {t.get('country')})")
            else:
                self.warn(f"Team {team} not found on TBA")
            events = tba.team_events(team, year)
            self.ok(f"Team {team} has {len(events)} event(s) in {year}")
            if events:
                parsed = parsing.parse_event(events[0])
                if parsed["name"] and parsed["start_date"]:
                    self.ok(f"Event format OK ({events[0]['key']}: {parsed['name']})")
                else:
                    self.fail(f"Unexpected event format: {sorted(events[0].keys())}")
                event_key = event_key or events[-1]["key"]
        except APIError as exc:
            self.fail(str(exc))
        if not event_key:
            return
        try:
            matches = tba.event_matches(event_key)
            self.ok(f"{event_key}: {len(matches)} matches")
            if matches:
                m = parsing.parse_match(matches[0])
                if len(m["red_teams"]) >= 2 and len(m["blue_teams"]) >= 2:
                    self.ok(f"Match format OK ({matches[0]['key']}: red {m['red_teams']} vs blue {m['blue_teams']})")
                else:
                    self.fail(f"Unexpected match format: {sorted(matches[0].keys())}")
                if any(x.get("score_breakdown") for x in matches):
                    self.ok("Score breakdowns available")
            ranks = parsing.parse_rankings(tba.event_rankings(event_key))
            self.ok(f"{event_key}: rankings for {len(ranks)} teams") if ranks else self.warn("No rankings yet for this event")
        except (APIError, KeyError, TypeError) as exc:
            self.fail(f"{event_key}: {exc}")

    def check_statbotics(self, team, year, event_key):
        self.section("Statbotics (official python package)")
        try:
            import statbotics  # noqa: F401
            from importlib.metadata import version

            self.ok(f"statbotics package {version('statbotics')} installed")
        except ImportError:
            self.fail("statbotics package missing: run  pip install -r requirements.txt")
            return
        sb = StatboticsClient()
        try:
            ty = sb.team_year(team, year) or sb.team_year(team, year - 1)
            if not ty:
                self.warn(f"No Statbotics season data for {team}")
            else:
                p = parsing.parse_statbotics_team_year(ty)
                if p["epa"] is not None:
                    self.ok(f"Team {team} {ty.get('year')}: EPA {p['epa']:.1f}, world rank {p['world_rank']}")
                else:
                    self.fail(f"Season EPA not found. epa keys: {sorted((ty.get('epa') or {}).keys())}")
            if event_key:
                rows = sb.team_events(event_key)
                if not rows:
                    self.warn(f"Statbotics has no team data for {event_key} yet")
                else:
                    p = parsing.parse_statbotics_team_event(rows[0])
                    if p["epa_total"] is not None:
                        extra = [k for k in p["epa_breakdown"] if k not in ("total_points", "auto_points", "teleop_points", "endgame_points")]
                        self.ok(f"{event_key}: EPA for {len(rows)} teams; game-specific fields: {', '.join(extra[:6]) or 'none'}")
                    else:
                        self.fail(f"Team-event EPA not found. epa keys: {sorted((rows[0].get('epa') or {}).keys())}")
                matches = sb.matches(event_key)
                with_pred = sum(1 for m in matches if parsing.parse_statbotics_match(m)["pred_red_win_prob"] is not None)
                self.ok(f"{event_key}: {len(matches)} matches, {with_pred} with win predictions")
        except APIError as exc:
            self.fail(str(exc))

    def check_google(self):
        self.section("Google sign-in")
        cid, secret = settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
        if not cid or not secret:
            self.warn("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set: the Google button stays hidden.")
            return
        if cid.endswith(".apps.googleusercontent.com"):
            self.ok("Client ID looks valid")
        else:
            self.fail("GOOGLE_CLIENT_ID should end with .apps.googleusercontent.com")
        if len(secret) < 20:
            self.warn("GOOGLE_CLIENT_SECRET looks too short")
        else:
            self.ok("Client secret is set")
        from allauth.socialaccount.models import SocialApp

        if SocialApp.objects.filter(provider="google").exists():
            self.fail("A Google 'Social application' also exists in the admin. Delete it: the keys from .env are "
                      "enough, and having both makes login crash (MultipleObjectsReturned).")
        self.stdout.write("         In Google Cloud Console > Credentials > your OAuth client, add these exactly:")
        self.stdout.write("           Authorized JavaScript origins: http://localhost:8000  and  http://127.0.0.1:8000")
        self.stdout.write("           Authorized redirect URIs:      http://localhost:8000/accounts/google/login/callback/")
        self.stdout.write("                                          http://127.0.0.1:8000/accounts/google/login/callback/")
