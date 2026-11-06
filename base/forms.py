# forms.py
#
# Server-side validation for a job, replacing the hand-parsed float(request.POST...)
# and the silent redirects. Also holds make_plan(): the single place where the
# form's values become a layout (used by both the quote and the real submit, so
# what the customer is quoted is exactly what gets printed).

from django import forms
from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.forms import formset_factory

from .layout_engine import LayoutError, Sheet
from .models import PaperSize, PrintProfile
from .multi_engine import Design as EngineDesign
from .multi_engine import plan_multi_job

MAX_FORM_DESIGNS = getattr(settings, "LAYOUT_MAX_DESIGNS", 20)
MAX_UPLOAD_MB = getattr(settings, "LAYOUT_MAX_UPLOAD_MB", 25)
MAX_PIXELS = getattr(settings, "LAYOUT_MAX_PIXELS", 75_000_000)
ALLOWED_EXTENSIONS = ["png", "jpg", "jpeg", "webp", "tif", "tiff", "gif", "bmp"]

ORIENTATION_CHOICES = [("auto", "Automatic (best fit)"), ("portrait", "Portrait"),
                       ("landscape", "Landscape")]

_NUM = {"class": "form-control", "step": "any"}


def _num(**kw):
    return forms.NumberInput(attrs={**_NUM, "class": "form-control len-field", **kw})


# --------------------------------------------------------------------------
# one design
# --------------------------------------------------------------------------

class DesignForm(forms.Form):
    image = forms.ImageField(
        label="Image",
        validators=[FileExtensionValidator(ALLOWED_EXTENSIONS)],
        widget=forms.ClearableFileInput(attrs={"class": "d-none design-file", "accept": "image/*"}))
   
    width_mm = forms.FloatField(label="Width", min_value=1, max_value=2000,
                                widget=_num(min="1", max="2000"))
    height_mm = forms.FloatField(label="Height", min_value=1, max_value=2000,
                                 widget=_num(min="1", max="2000"))
    quantity = forms.IntegerField(label="Quantity", min_value=1, max_value=1_000_000,
                                  widget=forms.NumberInput(attrs={"class": "form-control",
                                                                  "min": "1", "value": "1"}))
    # filled in by the page after the image is read (used for the DPI hints in quotes;
    # the real values are re-read from the file on submit)
    px_w = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)
    px_h = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)
    # blank for a brand-new design; set (by the edit page) to the StickerDesign this
    # row represents. Inert for a normal new job - the view never reads it there.
    design_id = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def clean_image(self):
        f = self.cleaned_data["image"]
        if f is None:                       # quotes are requested without an image
            return f
        if f.size > MAX_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(f"The image is larger than {MAX_UPLOAD_MB} MB.")
        w, h = f.image.size
        if w * h > MAX_PIXELS:
            raise forms.ValidationError("The image has too many pixels; please reduce its size.")
        return f


class QuoteDesignForm(DesignForm):
    """Same fields, but no image is needed to get a quote."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image"].required = False


class EditDesignForm(DesignForm):
    """Same fields, but the image is optional - a row with a design_id (an
    existing design) may be resubmitted without a file, meaning "keep the
    current artwork". A row with no design_id (a brand-new one added during
    this edit) still needs an image; the view checks that, since it depends
    on whether design_id was actually supplied, not on any DB lookup."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image"].required = False

    def clean(self):
        cd = super().clean()
        if not cd.get("design_id") and not cd.get("image") and "image" not in self.errors:
            self.add_error("image", "Choose an image for this design.")
        return cd


_DesignFormSet = formset_factory(DesignForm, extra=0, min_num=1, validate_min=True,
                                 max_num=MAX_FORM_DESIGNS, validate_max=True)
_QuoteFormSet = formset_factory(QuoteDesignForm, extra=0, min_num=1, validate_min=True,
                                max_num=MAX_FORM_DESIGNS, validate_max=True)
_EditFormSet = formset_factory(EditDesignForm, extra=0, min_num=1, validate_min=True,
                               max_num=MAX_FORM_DESIGNS, validate_max=True)


def design_formset(data=None, files=None, quote=False, editing=False, initial=None):
    cls = _QuoteFormSet if quote else _EditFormSet if editing else _DesignFormSet
    return cls(data, files, prefix="designs", initial=initial)


# --------------------------------------------------------------------------
# the job
# --------------------------------------------------------------------------

_MARGINS = ("margin_top", "margin_right", "margin_bottom", "margin_left")


class JobForm(forms.Form):
    layout_name = forms.CharField(label="Job name", max_length=100, required=False,
                                  widget=forms.TextInput(attrs={"class": "form-control"}))
    paper_size = forms.ModelChoiceField(
        label="Sheet size", queryset=PaperSize.objects.none(), required=False, empty_label=None,
        widget=forms.Select(attrs={"class": "form-select"}))
    use_custom_paper = forms.BooleanField(label="Use a custom sheet size", required=False)
    custom_paper_width = forms.FloatField(label="Custom width", required=False,
                                          min_value=20, max_value=3000, widget=_num())
    custom_paper_height = forms.FloatField(label="Custom height", required=False,
                                           min_value=20, max_value=3000, widget=_num())
    paper_orientation = forms.ChoiceField(label="Orientation", choices=ORIENTATION_CHOICES,
                                          required=False, initial="auto",
                                          widget=forms.Select(attrs={"class": "form-select"}))
    margin_top = forms.FloatField(label="Top margin", required=False, min_value=0,
                                  max_value=200, widget=_num(min="0"))
    margin_right = forms.FloatField(label="Right margin", required=False, min_value=0,
                                    max_value=200, widget=_num(min="0"))
    margin_bottom = forms.FloatField(label="Bottom margin", required=False, min_value=0,
                                     max_value=200, widget=_num(min="0"))
    margin_left = forms.FloatField(label="Left margin", required=False, min_value=0,
                                   max_value=200, widget=_num(min="0"))
    horizontal_spacing = forms.FloatField(label="Horizontal spacing", required=False,
                                          min_value=0, max_value=100, widget=_num(min="0"))
    vertical_spacing = forms.FloatField(label="Vertical spacing", required=False,
                                        min_value=0, max_value=100, widget=_num(min="0"))
    allow_rotation = forms.BooleanField(label="Allow turning stickers 90°", required=False,
                                        initial=True)
    group_by_design = forms.BooleanField(label="Keep each design together", required=False,
                                         initial=True)

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile or PrintProfile.get_default()
        self.fields["paper_size"].queryset = PaperSize.objects.filter(is_active=True)
        p = self.profile
        defaults = {"margin_top": p.margin_top, "margin_right": p.margin_right,
                    "margin_bottom": p.margin_bottom, "margin_left": p.margin_left,
                    "horizontal_spacing": p.gap_x, "vertical_spacing": p.gap_y,
                    "allow_rotation": p.allow_rotation, "group_by_design": p.group_by_design}
        self._defaults = defaults
        for name, value in defaults.items():
            self.fields[name].initial = value

    def clean(self):
        cd = super().clean()
        if cd.get("use_custom_paper"):
            if not cd.get("custom_paper_width") or not cd.get("custom_paper_height"):
                if "custom_paper_width" not in self.errors and "custom_paper_height" not in self.errors:
                    raise forms.ValidationError("Enter the custom sheet's width and height.")
        elif not cd.get("paper_size") and "paper_size" not in self.errors:
            raise forms.ValidationError("Choose a sheet size.")
        # blank margin/spacing fields fall back to the shop's profile
        for name in (*_MARGINS, "horizontal_spacing", "vertical_spacing"):
            if cd.get(name) is None and name not in self.errors:
                cd[name] = self._defaults[name]
        if not cd.get("paper_orientation"):
            cd["paper_orientation"] = "auto"
        return cd


# --------------------------------------------------------------------------
# turning validated values into a layout
# --------------------------------------------------------------------------

def make_plan(job, designs, align="top-left"):
    """job: JobForm.cleaned_data; designs: list of design cleaned_data dicts.

    Returns a dict: plan, sheet, orientation, paper_size, sheet_cost.
    Raises LayoutError with a message that is safe to show to the customer.
    """
    if job.get("use_custom_paper"):
        paper, w, h = None, job["custom_paper_width"], job["custom_paper_height"]
    else:
        paper = job["paper_size"]
        w, h = paper.width_mm, paper.height_mm
    lo, hi = min(w, h), max(w, h)
    choice = job.get("paper_orientation") or "auto"
    options = ["portrait", "landscape"] if choice == "auto" else [choice]

    engine_designs = [
        EngineDesign(width=d["width_mm"], height=d["height_mm"], quantity=d["quantity"],
                     name=d.get("name") or f"Design {i + 1}")
        for i, d in enumerate(designs)]
    cost = float(paper.cost_per_sheet) if paper and paper.cost_per_sheet is not None else None

    best, first_error = None, None
    for orientation in options:
        sw, sh = (lo, hi) if orientation == "portrait" else (hi, lo)
        try:
            sheet = Sheet(sw, sh, job["margin_top"], job["margin_right"], job["margin_bottom"],
                          job["margin_left"], job["horizontal_spacing"], job["vertical_spacing"])
            plan = plan_multi_job(sheet, engine_designs, allow_rotation=job["allow_rotation"],
                                  group_by_design=job["group_by_design"], align=align,
                                  sheet_cost=cost)
        except LayoutError as exc:
            first_error = first_error or exc
            continue
        key = (plan.sheet_count, 0 if orientation == "portrait" else 1)   # fewest sheets wins
        if best is None or key < best[0]:
            best = (key, plan, sheet, orientation)
    if best is None:
        raise first_error
    _, plan, sheet, orientation = best
    return {"plan": plan, "sheet": sheet, "orientation": orientation,
            "paper_size": paper, "sheet_cost": cost}


def collect_errors(form, formset):
    """Flat list of readable messages from a JobForm and a design formset."""
    out = []
    out += [str(e) for e in form.non_field_errors()]
    for name, errs in form.errors.items():
        if name == "__all__":
            continue
        label = form.fields[name].label or name
        out += [f"{label}: {e}" for e in errs]
    out += [str(e) for e in formset.non_form_errors()]
    for i, f in enumerate(formset.forms):
        for name, errs in f.errors.items():
            label = f.fields[name].label if name in f.fields else name
            out += [f"Design {i + 1} - {label}: {e}" for e in errs]
    return out
