from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Invite, Role, TeamClaim


class TeamClaimForm(forms.ModelForm):
    team_number = forms.IntegerField(label=_("FRC team number"), min_value=1, max_value=99999)
    nickname = forms.CharField(label=_("Team nickname"), max_length=120, required=False)

    class Meta:
        model = TeamClaim
        fields = ["full_name", "position", "evidence"]
        labels = {
            "full_name": _("Your full name"),
            "position": _("Your role on the team"),
            "evidence": _("How can we verify you?"),
        }
        widgets = {"evidence": forms.Textarea(attrs={"rows": 3})}


class InviteForm(forms.ModelForm):
    days_valid = forms.IntegerField(label=_("Valid for (days)"), min_value=1, max_value=120, initial=14)

    class Meta:
        model = Invite
        fields = ["role", "max_uses"]
        labels = {"role": _("Role"), "max_uses": _("Maximum uses")}


class RoleForm(forms.Form):
    role = forms.ChoiceField(choices=Role.choices)


class JoinCodeForm(forms.Form):
    code = forms.CharField(label=_("Invite code"), max_length=12)
