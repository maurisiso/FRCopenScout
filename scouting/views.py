import csv
import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from frcdata.models import Event, Match
from teams.models import Membership, Role, Team
from teams.permissions import team_view

from .forms import FormFieldForm, ScoutingFormForm
from .models import FormField, ScoutEntry, ScoutingForm
from .templates_starter import STARTER_MATCH_FIELDS, STARTER_PIT_FIELDS


# --- Form builder (admins) --------------------------------------------------

@team_view()
def form_list(request, team, membership):
    forms = team.scouting_forms.prefetch_related("fields")
    return render(request, "scouting/form_list.html", {"team": team, "membership": membership, "forms": forms})


@team_view(min_role=Role.ADMIN)
def form_create(request, team, membership):
    if request.method == "POST":
        form = ScoutingFormForm(request.POST)
        if form.is_valid():
            sf = form.save(commit=False)
            sf.team = team
            sf.save()
            if form.cleaned_data["use_starter"]:
                starter = STARTER_MATCH_FIELDS if sf.kind == ScoutingForm.Kind.MATCH else STARTER_PIT_FIELDS
                for i, spec in enumerate(starter):
                    FormField.objects.create(form=sf, order=i, **spec)
            messages.success(request, _("Form created. Now customize its fields."))
            return redirect("form_edit", team_number=team.number, form_id=sf.id)
    else:
        form = ScoutingFormForm()
    return render(request, "scouting/form_create.html", {"team": team, "membership": membership, "form": form})


@team_view(min_role=Role.ADMIN)
def form_edit(request, team, membership, form_id):
    sf = get_object_or_404(ScoutingForm, pk=form_id, team=team)
    settings_form = ScoutingFormForm(instance=sf)
    settings_form.fields.pop("use_starter")
    field_form = FormFieldForm()
    if request.method == "POST":
        if "save_settings" in request.POST:
            settings_form = ScoutingFormForm(request.POST, instance=sf)
            settings_form.fields.pop("use_starter")
            if settings_form.is_valid():
                settings_form.save()
                messages.success(request, _("Form saved."))
                return redirect("form_edit", team_number=team.number, form_id=sf.id)
        else:
            field_form = FormFieldForm(request.POST, instance=FormField(form=sf))
            if field_form.is_valid():
                f = field_form.save(commit=False)
                f.order = (sf.fields.aggregate(m=Max("order"))["m"] or 0) + 1
                try:
                    f.save()
                    sf.save()  # bump updated_at so offline pages refresh
                    messages.success(request, _("Field added."))
                    return redirect("form_edit", team_number=team.number, form_id=sf.id)
                except IntegrityError:
                    field_form.add_error("key", _("Another field already uses this key."))
    return render(request, "scouting/form_edit.html", {
        "team": team, "membership": membership, "sf": sf, "fields": sf.fields.all(),
        "settings_form": settings_form, "field_form": field_form, "entry_count": sf.entries.count(),
    })


@team_view(min_role=Role.ADMIN)
def field_edit(request, team, membership, form_id, field_id):
    sf = get_object_or_404(ScoutingForm, pk=form_id, team=team)
    field = get_object_or_404(FormField, pk=field_id, form=sf)
    old_key = field.key
    if request.method == "POST":
        form = FormFieldForm(request.POST, instance=field)
        if form.is_valid():
            try:
                with transaction.atomic():
                    f = form.save()
                    if f.key != old_key:
                        # Keep existing answers attached to the renamed key.
                        for entry in sf.entries.all():
                            if old_key in entry.data:
                                entry.data[f.key] = entry.data.pop(old_key)
                                entry.save(update_fields=["data"])
                    sf.save()
                messages.success(request, _("Field updated."))
                return redirect("form_edit", team_number=team.number, form_id=sf.id)
            except IntegrityError:
                form.add_error("key", _("Another field already uses this key."))
    else:
        form = FormFieldForm(instance=field)
    return render(request, "scouting/field_edit.html", {"team": team, "membership": membership, "sf": sf, "field": field, "form": form})


@require_POST
@team_view(min_role=Role.ADMIN)
def field_action(request, team, membership, form_id, field_id):
    sf = get_object_or_404(ScoutingForm, pk=form_id, team=team)
    field = get_object_or_404(FormField, pk=field_id, form=sf)
    action = request.POST.get("action")
    if action == "delete":
        field.delete()
        messages.success(request, _("Field deleted. Existing answers are kept in the raw data."))
    elif action in ("up", "down"):
        fields = list(sf.fields.all())
        i = fields.index(field)
        j = i - 1 if action == "up" else i + 1
        if 0 <= j < len(fields):
            fields[i], fields[j] = fields[j], fields[i]
            for n, f in enumerate(fields):
                if f.order != n:
                    f.order = n
                    f.save(update_fields=["order"])
    sf.save()
    return redirect("form_edit", team_number=team.number, form_id=sf.id)


# --- Scouting (offline-capable) ---------------------------------------------

@team_view(min_role=Role.SCOUT)
def scout_page(request, team, membership, event_key, form_id):
    """
    The page scouts use in the stands. Everything it needs (form definition,
    match schedule, team list) is embedded as JSON so it keeps working offline
    once it has been opened one time with a connection.
    """
    event = get_object_or_404(Event, key=event_key)
    sf = get_object_or_404(ScoutingForm, pk=form_id, team=team)
    if sf.kind == ScoutingForm.Kind.MATCH and not event.matches.exists():
        messages.info(request, _("The match schedule isn't published yet. Pit scouting is available in the meantime."))
        return redirect("pit_list", team_number=team.number, event_key=event.key)
    matches = [
        {"key": m.key, "label": m.label, "red": m.red_teams, "blue": m.blue_teams}
        for m in event.matches.all()
    ]
    teams = sorted(event.event_teams.values_list("team__number", flat=True))
    payload = {
        "team": team.number,
        "event": event.key,
        "form": sf.as_schema(),
        "matches": matches,
        "teams": teams,
        "scout": request.user.name,
        "i18n": {
            "yes": _("Yes"), "no": _("No"), "pit": _("Pit"),
            "syncing": _("Uploading…"), "synced": _("All entries uploaded"),
            "offline_saved": _("Offline — saved on this device"), "signin": _("Sign in again to upload"),
            "saved": _("Saved"), "discard": _("Discard"), "confirm_discard": _("Discard this entry?"),
            "need_team": _("Choose a team"), "need_match": _("Choose a match"), "required": _("required"),
            "phases": {"prematch": _("Pre-match"), "auto": _("Autonomous"), "teleop": _("Teleop"),
                       "endgame": _("Endgame"), "general": _("General")},
        },
    }
    return render(request, "scouting/scout.html", {
        "team": team, "membership": membership, "event": event, "sf": sf, "payload": payload,
    })


def _json_error(msg, status=400):
    return JsonResponse({"ok": False, "error": msg}, status=status)


@require_POST
def sync_api(request):
    """
    Receives entries queued on a scout's phone.

    Body: {"entries": [{client_uuid, team, event, form, match_key, scouted_team, data, recorded_at}]}
    Each entry is processed independently and the reply says which ones were stored,
    so the phone can safely retry: a repeated client_uuid is reported as "duplicate".
    """
    if not request.user.is_authenticated:
        return _json_error("not_authenticated", status=401)
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return _json_error("invalid_json")
    results = []
    for raw in body.get("entries", [])[:200]:
        uid = raw.get("client_uuid")
        try:
            results.append({"client_uuid": uid, **_store_entry(request.user, raw)})
        except ValidationError as exc:
            results.append({"client_uuid": uid, "status": "error", "error": "; ".join(exc.messages)})
    return JsonResponse({"ok": True, "results": results})


def _store_entry(user, raw):
    team = Team.objects.filter(number=raw.get("team"), status=Team.Status.APPROVED).first()
    if team is None:
        raise ValidationError("Unknown team")
    membership = Membership.objects.filter(user=user, team=team).first()
    if membership is None or not membership.can_scout:
        raise ValidationError("You can't scout for this team")
    if ScoutEntry.objects.filter(team=team, client_uuid=raw.get("client_uuid")).exists():
        return {"status": "duplicate"}
    event = Event.objects.filter(key=raw.get("event")).first()
    if event is None:
        raise ValidationError("Unknown event")
    sf = ScoutingForm.objects.filter(pk=raw.get("form"), team=team).prefetch_related("fields").first()
    if sf is None:
        raise ValidationError("Unknown form")
    try:
        scouted = int(raw.get("scouted_team"))
    except (TypeError, ValueError):
        raise ValidationError("Missing team number")

    answers = raw.get("data") or {}
    clean, errors = {}, []
    for field in sf.fields.all():
        try:
            clean[field.key] = field.clean_value(answers.get(field.key))
        except ValidationError as exc:
            errors.extend(exc.messages)
    if errors:
        raise ValidationError(errors)

    match_key = (raw.get("match_key") or "").strip()
    match = Match.objects.filter(key=match_key).first() if match_key else None
    if sf.kind == ScoutingForm.Kind.MATCH and not match_key:
        raise ValidationError("Match is required")
    alliance = match.alliance_of(scouted) if match else ""
    recorded = parse_datetime(raw.get("recorded_at") or "") if raw.get("recorded_at") else None
    try:
        ScoutEntry.objects.create(
            team=team, event=event, form=sf, match=match, match_key=match_key, scouted_team=scouted,
            alliance=alliance or "", data=clean, scout=user, client_uuid=raw.get("client_uuid"),
            recorded_at=recorded, synced_offline=bool(raw.get("offline")),
        )
    except (IntegrityError, ValidationError, ValueError):
        if ScoutEntry.objects.filter(team=team, client_uuid=raw.get("client_uuid")).exists():
            return {"status": "duplicate"}
        raise ValidationError("Could not save entry")
    return {"status": "ok"}


# --- Entries list / export ---------------------------------------------------

@team_view()
def entries(request, team, membership, event_key):
    event = get_object_or_404(Event, key=event_key)
    qs = ScoutEntry.objects.filter(team=team, event=event).select_related("scout", "form", "match")
    team_filter = request.GET.get("team")
    if team_filter and team_filter.isdigit():
        qs = qs.filter(scouted_team=int(team_filter))
    form_filter = request.GET.get("form")
    if form_filter and form_filter.isdigit():
        qs = qs.filter(form_id=int(form_filter))

    if request.GET.get("format") == "csv":
        return _csv(qs, team, event)
    return render(request, "scouting/entries.html", {
        "team": team, "membership": membership, "event": event, "entries": qs[:500],
        "forms": team.scouting_forms.all(), "team_filter": team_filter or "", "form_filter": form_filter or "",
        "tab": "entries",
    })


def _csv(qs, team, event):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{team.number}_{event.key}_scouting.csv"'
    keys = []
    for e in qs:
        for k in e.data:
            if k not in keys:
                keys.append(k)
    w = csv.writer(resp)
    w.writerow(["match", "team", "alliance", "form", "scout", "recorded_at"] + keys)
    for e in qs:
        w.writerow([e.match_key, e.scouted_team, e.alliance, e.form.name, e.scout.name if e.scout else "",
                    (e.recorded_at or e.created_at).isoformat()] +
                   [json.dumps(e.data.get(k)) if isinstance(e.data.get(k), list) else e.data.get(k, "") for k in keys])
    return resp


@require_POST
@team_view(min_role=Role.SCOUT)
def entry_delete(request, team, membership, event_key, entry_id):
    entry = get_object_or_404(ScoutEntry, pk=entry_id, team=team)
    if membership.is_admin or entry.scout_id == request.user.id:
        entry.delete()
        messages.success(request, _("Entry deleted."))
    else:
        messages.error(request, _("Only admins or the original scout can delete an entry."))
    return redirect("event_entries", team_number=team.number, event_key=event_key)
