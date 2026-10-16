from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from accounts import urls as account_urls
from ai import views as ai_views
from events import views as ev
from scouting import views as sc
from teams import views as tv

from . import views as core

# Everything under /t/<team_number>/ is scoped to one team and checks membership.
team_patterns = [
    path("", ev.team_home, name="team_home"),
    path("members/", tv.members, name="team_members"),
    path("members/<int:member_id>/role/", tv.change_role, name="team_change_role"),
    path("members/<int:member_id>/remove/", tv.remove_member, name="team_remove_member"),
    path("invites/<int:invite_id>/revoke/", tv.revoke_invite, name="team_revoke_invite"),
    path("leave/", tv.leave_team, name="team_leave"),
    path("activity/", tv.contributions, name="team_contributions"),
    path("events/sync/", ev.sync_team, name="team_sync_events"),
    path("events/add/", ev.add_event, name="team_add_event"),
    path("events/<str:event_key>/remove/", ev.remove_event, name="team_remove_event"),
    path("forms/", sc.form_list, name="form_list"),
    path("forms/new/", sc.form_create, name="form_create"),
    path("forms/<int:form_id>/", sc.form_edit, name="form_edit"),
    path("forms/<int:form_id>/fields/<int:field_id>/", sc.field_edit, name="field_edit"),
    path("forms/<int:form_id>/fields/<int:field_id>/action/", sc.field_action, name="field_action"),
    path("scouted/", ev.scouted_teams, name="scouted_teams"),
    path("scouted/<int:frc_number>/", ev.scouted_team_detail, name="scouted_team_detail"),
    # Regional / event dashboard
    path("e/<str:event_key>/", ev.event_overview, name="event_overview"),
    path("e/<str:event_key>/sync/", ev.event_sync, name="event_sync"),
    path("e/<str:event_key>/teams/", ev.event_teams, name="event_teams"),
    path("e/<str:event_key>/teams/<int:frc_number>/", ev.event_team_detail, name="event_team_detail"),
    path("e/<str:event_key>/us/", ev.our_team, name="event_our_team"),
    path("e/<str:event_key>/matches/", ev.event_matches, name="event_matches"),
    path("e/<str:event_key>/matches/<str:match_key>/", ev.match_detail, name="match_detail"),
    path("e/<str:event_key>/notes/", ev.event_notes, name="event_notes"),
    path("e/<str:event_key>/notes/<int:note_id>/delete/", ev.note_delete, name="note_delete"),
    path("e/<str:event_key>/alliances/", ev.alliances, name="event_alliances"),
    path("e/<str:event_key>/alliances/sim/", ev.alliance_sim, name="alliance_sim"),
    path("e/<str:event_key>/alliances/<int:prediction_id>/delete/", ev.prediction_delete, name="prediction_delete"),
    path("e/<str:event_key>/scout/<int:form_id>/", sc.scout_page, name="scout_page"),
    path("e/<str:event_key>/pit/", ev.pit_list, name="pit_list"),
    path("e/<str:event_key>/entries/", sc.entries, name="event_entries"),
    path("e/<str:event_key>/entries/<int:entry_id>/delete/", sc.entry_delete, name="entry_delete"),
    path("e/<str:event_key>/ai/", ai_views.ask, name="ai_ask"),
    path("ai/<int:query_id>/feedback/", ai_views.feedback, name="ai_feedback"),
]

urlpatterns = [
    path("", core.home, name="home"),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("me/", include(account_urls)),
    path("i18n/", include("django.conf.urls.i18n")),
    path("dashboard/", tv.dashboard, name="dashboard"),
    path("teams/register/", tv.register_team, name="team_register"),
    path("join/", tv.join, name="join"),
    path("join/<str:code>/", tv.join, name="join_code"),
    path("staff/approvals/", tv.approvals, name="staff_approvals"),
    path("t/<int:team_number>/", include(team_patterns)),
    path("api/scouting/sync/", sc.sync_api, name="scouting_sync_api"),
    # Progressive Web App (offline support). The service worker must be served
    # from the site root so it can control every page.
    path("sw.js", core.service_worker, name="service_worker"),
    path("manifest.webmanifest", core.manifest, name="manifest"),
    path("offline/", TemplateView.as_view(template_name="offline.html"), name="offline"),
]
