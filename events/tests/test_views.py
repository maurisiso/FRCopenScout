from datetime import date, timedelta

from django.test import TestCase

from accounts.models import User
from frcdata.models import Event, EventTeam, FRCTeam, Match
from scouting.models import ScoutEntry, ScoutingForm
from teams.models import Membership, Role, Team


class EventPageTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(number=7725, status=Team.Status.APPROVED)
        self.admin = User.objects.create_user("a@example.com", "pw-12345-x")
        self.scout = User.objects.create_user("s@example.com", "pw-12345-x")
        Membership.objects.create(user=self.admin, team=self.team, role=Role.ADMIN)
        Membership.objects.create(user=self.scout, team=self.team, role=Role.SCOUT)
        today = date.today()
        self.event = Event.objects.create(key="2026tst", year=2026, name="Test", start_date=today + timedelta(days=5),
                                          end_date=today + timedelta(days=7), is_demo=True)
        for n in (7725, 111, 222):
            EventTeam.objects.create(event=self.event, team=FRCTeam.objects.create(number=n))

    def test_event_status(self):
        self.assertEqual(self.event.status, "upcoming")
        self.event.start_date = date.today() - timedelta(days=1)
        self.assertEqual(self.event.status, "live")
        self.event.end_date = date.today() - timedelta(days=1)
        self.event.start_date = date.today() - timedelta(days=3)
        self.assertEqual(self.event.status, "ended")

    def test_pit_form_created_and_checklist(self):
        self.client.force_login(self.scout)
        r = self.client.get("/t/7725/e/2026tst/pit/")
        self.assertEqual(r.status_code, 200)
        pit = ScoutingForm.objects.get(team=self.team, kind="pit")
        self.assertTrue(pit.fields.filter(key="drivetrain").exists())
        self.assertContains(r, "0 / 3")
        ScoutEntry.objects.create(team=self.team, event=self.event, form=pit, scouted_team=111, data={})
        r = self.client.get("/t/7725/e/2026tst/pit/")
        self.assertContains(r, "1 / 3")
        # Only one pit form even after several visits
        self.client.get("/t/7725/e/2026tst/pit/")
        self.assertEqual(ScoutingForm.objects.filter(team=self.team, kind="pit").count(), 1)

    def test_match_scouting_disabled_without_schedule(self):
        form = ScoutingForm.objects.create(team=self.team, name="M", kind="match", season=2026)
        self.client.force_login(self.scout)
        r = self.client.get("/t/7725/e/2026tst/")
        self.assertContains(r, 'aria-disabled="true"')
        r = self.client.get(f"/t/7725/e/2026tst/scout/{form.id}/")
        self.assertRedirects(r, "/t/7725/e/2026tst/pit/")
        Match.objects.create(key="2026tst_qm1", event=self.event, comp_level="qm", match_number=1,
                             red_teams=[7725, 111, 222], blue_teams=[1, 2, 3])
        r = self.client.get(f"/t/7725/e/2026tst/scout/{form.id}/")
        self.assertEqual(r.status_code, 200)

    def test_activity_tab_admin_only(self):
        pit = ScoutingForm.default_pit_form(self.team, 2026)
        ScoutEntry.objects.create(team=self.team, event=self.event, form=pit, scouted_team=111, data={}, scout=self.scout)
        self.client.force_login(self.scout)
        self.assertEqual(self.client.get("/t/7725/activity/").status_code, 403)
        self.client.force_login(self.admin)
        r = self.client.get("/t/7725/activity/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "s@example.com")

    def test_team_switcher_lists_all_teams(self):
        other = Team.objects.create(number=4444, status=Team.Status.APPROVED)
        Membership.objects.create(user=self.admin, team=other, role=Role.VIEWER)
        self.client.force_login(self.admin)
        r = self.client.get("/t/7725/")
        self.assertContains(r, 'class="team-menu"')
        self.assertContains(r, "/t/4444/")
