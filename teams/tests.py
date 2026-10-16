from django.test import TestCase

from accounts.models import User

from .models import Invite, Membership, Role, Team, TeamClaim


class TeamFlowTests(TestCase):
    def setUp(self):
        self.mentor = User.objects.create_user("mentor@example.com", "pw-12345-x")
        self.staff = User.objects.create_user("staff@example.com", "pw-12345-x", is_staff=True)
        self.student = User.objects.create_user("student@example.com", "pw-12345-x")

    def test_register_requires_staff_approval(self):
        self.client.force_login(self.mentor)
        self.client.post("/teams/register/", {"team_number": 4321, "nickname": "Bots", "full_name": "M",
                                              "position": "mentor", "evidence": "website"})
        team = Team.objects.get(number=4321)
        self.assertEqual(team.status, Team.Status.PENDING)
        self.assertEqual(self.client.get("/t/4321/e/2026x/").status_code, 403)  # not a member yet
        claim = TeamClaim.objects.get()
        self.client.force_login(self.staff)
        self.client.post("/staff/approvals/", {"claim_id": claim.id, "decision": "approve"})
        team.refresh_from_db()
        self.assertTrue(team.is_approved)
        self.assertTrue(Membership.objects.filter(user=self.mentor, team=team, role=Role.ADMIN).exists())

    def test_non_staff_cannot_approve(self):
        self.client.force_login(self.mentor)
        r = self.client.get("/staff/approvals/")
        self.assertNotEqual(r.status_code, 200)

    def _approved_team(self):
        team = Team.objects.create(number=1111, status=Team.Status.APPROVED)
        Membership.objects.create(user=self.mentor, team=team, role=Role.ADMIN)
        return team

    def test_invite_join_and_kick(self):
        team = self._approved_team()
        invite = Invite.objects.create(team=team, role=Role.SCOUT)
        self.client.force_login(self.student)
        self.client.post(f"/join/{invite.code}/")
        m = Membership.objects.get(user=self.student, team=team)
        self.assertEqual(m.role, Role.SCOUT)
        # Student can't kick
        self.client.post(f"/t/1111/members/{m.id}/remove/")
        self.assertTrue(Membership.objects.filter(pk=m.pk).exists())
        # Admin can
        self.client.force_login(self.mentor)
        self.client.post(f"/t/1111/members/{m.id}/remove/")
        self.assertFalse(Membership.objects.filter(pk=m.pk).exists())

    def test_last_admin_protected(self):
        team = self._approved_team()
        self.client.force_login(self.mentor)
        m = Membership.objects.get(user=self.mentor)
        self.client.post(f"/t/1111/members/{m.id}/role/", {"role": "viewer"})
        m.refresh_from_db()
        self.assertEqual(m.role, Role.ADMIN)

    def test_user_can_be_in_multiple_teams(self):
        t1 = self._approved_team()
        t2 = Team.objects.create(number=2222, status=Team.Status.APPROVED)
        Membership.objects.create(user=self.mentor, team=t2, role=Role.SCOUT)
        self.client.force_login(self.mentor)
        page = self.client.get("/me/").content.decode()
        self.assertIn("1111", page)
        self.assertIn("2222", page)
