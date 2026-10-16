import json
import uuid

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User
from frcdata.models import Event, Match
from teams.models import Membership, Role, Team

from .models import FormField, ScoutEntry, ScoutingForm


class ScoutingTestBase(TestCase):
    def setUp(self):
        self.team = Team.objects.create(number=1234, status=Team.Status.APPROVED)
        self.user = User.objects.create_user("scout@example.com", "pw-12345-x")
        Membership.objects.create(user=self.user, team=self.team, role=Role.SCOUT)
        self.event = Event.objects.create(key="2026test", year=2026, name="Test")
        self.match = Match.objects.create(key="2026test_qm1", event=self.event, comp_level="qm", match_number=1,
                                          red_teams=[1, 2, 3], blue_teams=[4, 5, 6])
        self.form = ScoutingForm.objects.create(team=self.team, name="M", kind="match", season=2026)
        FormField.objects.create(form=self.form, key="cycles", label="Cycles", field_type="counter", min_value=0, max_value=20)
        FormField.objects.create(form=self.form, key="climb", label="Climb", field_type="choice", options=["No", "Yes"], required=True)
        self.client.force_login(self.user)

    def payload(self, **kw):
        e = {"client_uuid": str(uuid.uuid4()), "team": 1234, "event": "2026test", "form": self.form.id,
             "match_key": "2026test_qm1", "scouted_team": 5, "data": {"cycles": 4, "climb": "Yes"}}
        e.update(kw)
        return e

    def post(self, entries):
        return self.client.post("/api/scouting/sync/", data=json.dumps({"entries": entries}), content_type="application/json")


class SyncApiTests(ScoutingTestBase):
    def test_entry_saved_and_retry_is_duplicate(self):
        e = self.payload()
        r = self.post([e]).json()
        self.assertEqual(r["results"][0]["status"], "ok")
        saved = ScoutEntry.objects.get()
        self.assertEqual(saved.alliance, "blue")
        self.assertEqual(saved.data, {"cycles": 4, "climb": "Yes"})
        r = self.post([e]).json()
        self.assertEqual(r["results"][0]["status"], "duplicate")
        self.assertEqual(ScoutEntry.objects.count(), 1)

    def test_validation_errors_are_per_entry(self):
        good = self.payload()
        bad = self.payload(data={"cycles": 99})
        r = self.post([good, bad]).json()["results"]
        self.assertEqual(r[0]["status"], "ok")
        self.assertEqual(r[1]["status"], "error")

    def test_viewer_cannot_scout(self):
        Membership.objects.filter(user=self.user).update(role=Role.VIEWER)
        r = self.post([self.payload()]).json()["results"]
        self.assertEqual(r[0]["status"], "error")

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.post([self.payload()]).status_code, 401)

    def test_other_team_cannot_use_form(self):
        other = Team.objects.create(number=99, status=Team.Status.APPROVED)
        Membership.objects.create(user=self.user, team=other, role=Role.SCOUT)
        r = self.post([self.payload(team=99)]).json()["results"]
        self.assertEqual(r[0]["status"], "error")  # form belongs to 1234, not 99


class FieldCleanTests(ScoutingTestBase):
    def test_counter_and_boolean(self):
        f = self.form.fields.get(key="cycles")
        self.assertEqual(f.clean_value("3"), 3)
        with self.assertRaises(ValidationError):
            f.clean_value(-1)
        b = FormField(form=self.form, key="x", label="X", field_type="boolean")
        self.assertTrue(b.clean_value("true"))
        self.assertFalse(b.clean_value(False))
