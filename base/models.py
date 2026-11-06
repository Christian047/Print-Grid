# models.py
#
# Additive rebuild of the original models:
#   * PaperSize        - same table, plus is_active and cost_per_sheet
#   * StickerLayout    - same table. It is now the JOB: sheet + rules + results.
#                        Old rows keep working (new columns are nullable/defaulted)
#   * StickerDesign    - NEW. One row per design in a job (image, size, quantity)
#   * PrintProfile     - NEW. The shop's default margins / spacing / options
#
# Jobs are addressed by an unguessable `token` (no login needed). Old layouts
# have no token until ensure_token() is called on them.

import os
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse

from .layout_engine import ENGINE_VERSION, LayoutError, Sheet, effective_dpi
from .multi_engine import Design as EngineDesign
from .multi_engine import plan_multi_job

RESULT_FORMAT = "sheets-v1"     # value of layout_data["format"] for new jobs


def design_upload_path(instance, filename):
    """Random file name, so uploaded artwork can't be found by guessing."""
    ext = os.path.splitext(filename)[1].lower()
    if not (ext[1:].isalnum() and len(ext) <= 6):
        ext = ""
    return f"stickers/{uuid.uuid4().hex}{ext}"


# --------------------------------------------------------------------------
# Paper
# --------------------------------------------------------------------------

class PaperSize(models.Model):
    name = models.CharField(max_length=50)
    width_mm = models.FloatField()
    height_mm = models.FloatField()
    # NEW: hide a size instead of deleting it (a size used by jobs can't be deleted)
    is_active = models.BooleanField(default=True)
    # NEW: optional price of one sheet, used for cost-per-sticker figures
    cost_per_sheet = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)])

    # (name, width_mm, height_mm). Duplicates of the old list removed; common
    # print-shop sizes (SRA3, SRA4, A3+, A2) added.
    DEFAULTS = [
        ("A4", 210, 297), ("A3", 297, 420), ("A5", 148, 210), ("A6", 105, 148),
        ("A2", 420, 594), ("SRA3", 320, 450), ("SRA4", 225, 320),
        ("A3+ (13x19 in)", 329, 483), ("US Letter", 215.9, 279.4),
        ("Legal", 215.9, 355.6), ("Tabloid", 279.4, 431.8), ("B5", 176, 250),
        ("4x6 Photo", 101.6, 152.4), ("5x7 Photo", 127, 177.8),
        ("Executive", 184.15, 266.7), ("Statement", 139.7, 215.9),
        ("Index Card 3x5", 76.2, 127), ("Index Card 5x8", 127, 203.2),
    ]

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.width_mm}mm × {self.height_mm}mm)"

    @classmethod
    def ensure_defaults(cls):
        """Create any standard size that is missing (matched by name). Cheap when
        nothing is missing, so it can be called from the index view."""
        names = [n for n, _, _ in cls.DEFAULTS]
        have = set(cls.objects.filter(name__in=names).values_list("name", flat=True))
        for name, w, h in cls.DEFAULTS:
            if name not in have:
                cls.objects.create(name=name, width_mm=w, height_mm=h)


# --------------------------------------------------------------------------
# Shop defaults
# --------------------------------------------------------------------------

class PrintProfile(models.Model):
    """Margins, spacing and options a shop uses every time. New jobs copy these
    values (so an old job never changes when the profile is edited)."""
    name = models.CharField(max_length=60, default="Default")
    is_default = models.BooleanField(default=False)
    margin_top = models.FloatField(default=5, validators=[MinValueValidator(0)])
    margin_right = models.FloatField(default=5, validators=[MinValueValidator(0)])
    margin_bottom = models.FloatField(default=5, validators=[MinValueValidator(0)])
    margin_left = models.FloatField(default=5, validators=[MinValueValidator(0)])
    gap_x = models.FloatField("horizontal spacing", default=2, validators=[MinValueValidator(0)])
    gap_y = models.FloatField("vertical spacing", default=2, validators=[MinValueValidator(0)])
    allow_rotation = models.BooleanField(default=True)
    group_by_design = models.BooleanField(default=True)
    align = models.CharField(max_length=10, default="top-left",
                             choices=[("top-left", "Top-left"), ("center", "Centered")])

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:                       # only one default at a time
            PrintProfile.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)

    @classmethod
    def get_default(cls):
        prof = cls.objects.filter(is_default=True).first() or cls.objects.first()
        if prof is None:
            prof = cls.objects.create(name="Default", is_default=True)
        return prof


# --------------------------------------------------------------------------
# Job
# --------------------------------------------------------------------------

class StickerLayout(models.Model):
    STATUS_PENDING = "pending"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [(STATUS_PENDING, "Pending"), (STATUS_READY, "Ready"),
                      (STATUS_FAILED, "Failed")]
    ORIENTATION_CHOICES = [("portrait", "Portrait"), ("landscape", "Landscape")]
    ALIGN_CHOICES = [("top-left", "Top-left"), ("center", "Centered")]

    # ---- original fields (unchanged, except the legacy ones are now optional) ----
    name = models.CharField(max_length=100, default="Untitled Layout")
    created_at = models.DateTimeField(auto_now_add=True)
    # PROTECT: deleting a paper size no longer deletes the jobs that used it
    paper_size = models.ForeignKey(PaperSize, on_delete=models.PROTECT, null=True, blank=True)
    sticker_width = models.FloatField(null=True, blank=True)       # legacy single design
    sticker_height = models.FloatField(null=True, blank=True)      # legacy single design
    margin_top = models.FloatField(default=10)
    margin_right = models.FloatField(default=10)
    margin_bottom = models.FloatField(default=10)
    margin_left = models.FloatField(default=10)
    horizontal_spacing = models.FloatField(default=2)
    vertical_spacing = models.FloatField(default=2)
    original_image = models.ImageField(upload_to="stickers/", blank=True)  # legacy single design
    layout_data = models.JSONField(null=True, blank=True)

    # ---- identity / privacy ----
    # No default on purpose (a fixed default would give every OLD row the same
    # value and break uniqueness). save() fills it in for new jobs.
    token = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    # Lets the home page show only THIS browser's recent jobs
    session_key = models.CharField(max_length=40, blank=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ---- the sheet (final orientation-resolved size, mm) ----
    sheet_width_mm = models.FloatField(null=True, blank=True)
    sheet_height_mm = models.FloatField(null=True, blank=True)
    orientation = models.CharField(max_length=10, choices=ORIENTATION_CHOICES, default="portrait")

    # ---- rules used for this job (copied from the PrintProfile) ----
    allow_rotation = models.BooleanField(default=True)
    group_by_design = models.BooleanField(default=True)
    align = models.CharField(max_length=10, choices=ALIGN_CHOICES, default="top-left")
    fill_last_sheet = models.BooleanField(default=False)
    sheet_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # ---- outcome ----
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING,
                              db_index=True)
    status_message = models.TextField(blank=True)          # why it failed, in plain words
    warnings = models.JSONField(default=list, blank=True)  # non-fatal notes (e.g. low DPI)
    total_stickers = models.PositiveIntegerField(null=True, blank=True)
    sheet_count = models.PositiveIntegerField(null=True, blank=True)
    utilization_pct = models.FloatField(null=True, blank=True)   # sticker area / sheet area
    waste_pct = models.FloatField(null=True, blank=True)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    strategy = models.CharField(max_length=200, blank=True)
    engine_version = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.status})"

    # ---- identity ----
    def save(self, *args, **kwargs):
        if self._state.adding and not self.token:
            self.token = uuid.uuid4()
        super().save(*args, **kwargs)

    def ensure_token(self):
        """Give an old layout a link token (old rows have none)."""
        if not self.token:
            self.token = uuid.uuid4()
            self.save(update_fields=["token"])
        return self.token

    def get_absolute_url(self):
        # url name 'result' (path with <uuid:token>) is added in the urls step
        return reverse("result", args=[self.ensure_token()])

    @property
    def is_legacy(self):
        """True for layouts created by the old single-design app."""
        return bool(self.layout_data) and self.layout_data.get("format") != RESULT_FORMAT

    @property
    def display_status(self):
        """Old layouts are finished work; show them as ready, not 'pending'."""
        return self.STATUS_READY if self.is_legacy else self.status

    # ---- building the engine input ----
    def sheet_dims(self):
        """(width, height) in mm of the sheet as it is fed to the printer."""
        if self.sheet_width_mm and self.sheet_height_mm:
            return self.sheet_width_mm, self.sheet_height_mm
        if self.paper_size_id:
            w, h = self.paper_size.width_mm, self.paper_size.height_mm
            lo, hi = min(w, h), max(w, h)
            return (hi, lo) if self.orientation == "landscape" else (lo, hi)
        if self.layout_data and self.layout_data.get("paper_width"):        # legacy
            return self.layout_data["paper_width"], self.layout_data["paper_height"]
        raise LayoutError("Choose a paper size.")

    def to_sheet(self):
        w, h = self.sheet_dims()
        return Sheet(width=w, height=h, margin_top=self.margin_top,
                     margin_right=self.margin_right, margin_bottom=self.margin_bottom,
                     margin_left=self.margin_left, gap_x=self.horizontal_spacing,
                     gap_y=self.vertical_spacing)

    def to_engine_designs(self):
        return [EngineDesign(width=d.width_mm, height=d.height_mm,
                             quantity=d.quantity, name=d.display_name)
                for d in self.designs.all()]

    # ---- running the planner ----
    def dpi_warnings(self):
        floor = getattr(settings, "LAYOUT_MIN_DPI", 250)
        out = []
        for d in self.designs.all():
            dpi = d.effective_dpi()
            if dpi is not None and dpi < floor:
                out.append(f"{d.display_name} will print at about {dpi:.0f} DPI at "
                           f"{d.width_mm:g} × {d.height_mm:g} mm (recommended: {floor}+).")
        return out

    def apply_plan(self, plan):
        """Copy a MultiJobPlan's results onto this job (does not save)."""
        self.layout_data = plan.to_dict()
        self.total_stickers = plan.total_stickers
        self.sheet_count = plan.sheet_count
        self.utilization_pct = round(plan.job_utilization_pct, 2)
        self.waste_pct = round(plan.waste_pct, 2)
        self.total_cost = (None if plan.total_cost is None
                           else Decimal(str(round(plan.total_cost, 2))))
        self.strategy = plan.strategy
        self.engine_version = ENGINE_VERSION
        self.status = self.STATUS_READY
        self.status_message = ""
        self.warnings = self.dpi_warnings()

    def mark_failed(self, message):
        self.status = self.STATUS_FAILED
        self.status_message = message

    def compute_plan(self, save=True):
        """Run the planner for this job. A user-fixable problem (a sticker too big,
        margins too large...) marks the job failed with a readable message.
        Anything else is a bug and is allowed to raise."""
        if self.is_legacy:
            raise ValueError("Old layouts cannot be recomputed; create a new job.")
        plan = None
        try:
            plan = plan_multi_job(
                self.to_sheet(), self.to_engine_designs(),
                allow_rotation=self.allow_rotation, group_by_design=self.group_by_design,
                align=self.align, fill_last_sheet=self.fill_last_sheet,
                sheet_cost=None if self.sheet_cost is None else float(self.sheet_cost))
        except LayoutError as exc:
            self.mark_failed(str(exc))
        else:
            self.apply_plan(plan)
        if save:
            self.save()
        return plan


class StickerDesign(models.Model):
    """One design in a job: its artwork, printed size and quantity."""
    layout = models.ForeignKey(StickerLayout, on_delete=models.CASCADE, related_name="designs")
    position = models.PositiveSmallIntegerField(default=0)      # = placement["design"]
    name = models.CharField(max_length=100, blank=True)
    image = models.ImageField(upload_to=design_upload_path)
    width_mm = models.FloatField(validators=[MinValueValidator(0.1)])
    height_mm = models.FloatField(validators=[MinValueValidator(0.1)])
    quantity = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(10_000_000)])
    # facts read from the upload (for the resolution check and de-duplication)
    pixel_width = models.PositiveIntegerField(null=True, blank=True)
    pixel_height = models.PositiveIntegerField(null=True, blank=True)
    source_dpi = models.FloatField(null=True, blank=True)
    color_mode = models.CharField(max_length=10, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["layout", "position"], name="unique_design_position"),
        ]

    def __str__(self):
        return f"{self.display_name} ×{self.quantity}"

    @property
    def display_name(self):
        return self.name or f"Design {self.position + 1}"

    def effective_dpi(self):
        """DPI the artwork prints at, or None if the pixel size is unknown."""
        if not (self.pixel_width and self.pixel_height):
            return None
        return effective_dpi(self.pixel_width, self.pixel_height, self.width_mm, self.height_mm)


# --------------------------------------------------------------------------
# File clean-up: delete the image file when its row is deleted
# --------------------------------------------------------------------------

@receiver(post_delete, sender=StickerDesign)
def _delete_design_file(sender, instance, **kwargs):
    if instance.image:
        instance.image.delete(save=False)


@receiver(post_delete, sender=StickerLayout)
def _delete_legacy_file(sender, instance, **kwargs):
    if instance.original_image:
        instance.original_image.delete(save=False)
