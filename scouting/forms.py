from django import forms
from django.utils.translation import gettext_lazy as _

from .models import FormField, MatchNote, ScoutingForm


class ScoutingFormForm(forms.ModelForm):
    use_starter = forms.BooleanField(label=_("Start from the generic template"), required=False, initial=True)

    class Meta:
        model = ScoutingForm
        fields = ["name", "kind", "season", "is_active"]


class FormFieldForm(forms.ModelForm):
    options_text = forms.CharField(
        label=_("Options (one per line)"), required=False, widget=forms.Textarea(attrs={"rows": 3})
    )

    class Meta:
        model = FormField
        fields = ["label", "key", "field_type", "phase", "help_text", "min_value", "max_value", "points", "required"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["key"].required = False
        if self.instance and self.instance.pk:
            self.fields["options_text"].initial = "\n".join(self.instance.options or [])

    def clean(self):
        data = super().clean()
        opts = [o.strip() for o in (data.get("options_text") or "").splitlines() if o.strip()]
        if data.get("field_type") in (FormField.FieldType.CHOICE, FormField.FieldType.MULTI) and len(opts) < 2:
            self.add_error("options_text", _("Choice fields need at least two options."))
        data["options"] = opts
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.options = self.cleaned_data.get("options", [])
        if commit:
            obj.save()
        return obj


class MatchNoteForm(forms.ModelForm):
    class Meta:
        model = MatchNote
        fields = ["match_key", "about_team", "category", "text"]
        labels = {"match_key": _("Match"), "about_team": _("About team #"), "category": _("Category"), "text": _("Note")}
        widgets = {"text": forms.Textarea(attrs={"rows": 3})}
