# views.py - rebuilt around layout_engine / multi_engine.
#
# Flow: upload design(s) -> live quote -> calculate -> result page -> download.
# Jobs are reached by an unguessable token; there is no login. Every failure the
# customer can fix comes back as a readable message (no more silent redirects).

import hashlib
import logging
import re

from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import pdf_export
from .forms import (MAX_PIXELS, MAX_UPLOAD_MB, JobForm, collect_errors, design_formset,
                    make_plan)
from .layout_engine import LayoutError, effective_dpi, suggest_sizes
from .models import PaperSize, PrintProfile, StickerDesign, StickerLayout

logger = logging.getLogger("app")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _recent_jobs(request):
    key = request.session.session_key
    if not key:
        return []
    return list(StickerLayout.objects.filter(session_key=key, token__isnull=False)
                .exclude(status=StickerLayout.STATUS_FAILED)[:5])


def _render_index(request, form, formset, errors=None, edit_job=None):
    return render(request, "base/index2.html", {
        "form": form, "formset": formset, "errors": errors or [],
        "paper_sizes": PaperSize.objects.filter(is_active=True),
        "recent_jobs": [] if edit_job else _recent_jobs(request),
        "max_upload_mb": MAX_UPLOAD_MB,
        "edit_job": edit_job,
    })


def _get_job(token):
    job = get_object_or_404(StickerLayout, token=token)
    if job.is_legacy:                       # old single-design layouts are admin-only
        raise Http404
    return job


def _require_ready(job):
    if job.status != StickerLayout.STATUS_READY or not job.layout_data:
        raise Http404


def _int_param(request, name, low, high, default):
    try:
        return max(low, min(high, int(request.GET.get(name, default))))
    except (TypeError, ValueError):
        return default


def _safe_filename(name, ext):
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "").strip("_") or "layout"
    return f"{stem[:60]}.{ext}"


def _single_design_suggestions(sheet, design_cd, image_px=None):
    """Size suggestions only make sense when there is one design."""
    try:
        return [s.to_dict() for s in suggest_sizes(
            sheet, design_cd["width_mm"], design_cd["height_mm"], design_cd["quantity"],
            image_px=image_px)]
    except LayoutError:
        return []


def _facts_and_hash(upload):
    """Read the real pixel size/DPI from an upload and hash its bytes, without
    trusting anything the browser claimed. Rewinds the file afterwards."""
    facts = pdf_export.image_facts(upload)
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return facts, digest.hexdigest()


def _job_initial(job):
    """Prefill the create/edit form from a job's CURRENT saved values."""
    initial = {
        "layout_name": job.name, "paper_orientation": job.orientation,
        "margin_top": job.margin_top, "margin_right": job.margin_right,
        "margin_bottom": job.margin_bottom, "margin_left": job.margin_left,
        "horizontal_spacing": job.horizontal_spacing, "vertical_spacing": job.vertical_spacing,
        "allow_rotation": job.allow_rotation, "group_by_design": job.group_by_design,
    }
    if job.paper_size_id:
        initial["paper_size"], initial["use_custom_paper"] = job.paper_size_id, False
    else:
        # A custom sheet has no PaperSize row; feeding the job's own (already
        # oriented) dimensions back in round-trips correctly on re-save.
        initial["use_custom_paper"] = True
        initial["custom_paper_width"] = job.sheet_width_mm
        initial["custom_paper_height"] = job.sheet_height_mm
    return initial


def _design_initial(d):
    """Prefill one design row. thumb_url (not a real form field) tells the
    template to show the CURRENT artwork and make the file optional."""
    return {"design_id": d.id, "name": d.name, "width_mm": d.width_mm, "height_mm": d.height_mm,
           "quantity": d.quantity, "px_w": d.pixel_width, "px_h": d.pixel_height,
           "thumb_url": d.image.url}


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------

@require_GET
def index(request):
    PaperSize.ensure_defaults()
    return _render_index(request, JobForm(profile=PrintProfile.get_default()), design_formset())


@require_POST
def detect_sticker_size(request):
    """Read size/DPI from an uploaded image so the customer doesn't type it."""
    f = request.FILES.get("sticker_image")
    if not f:
        return JsonResponse({"success": False, "error": "No image was received."}, status=400)
    if f.size > MAX_UPLOAD_MB * 1024 * 1024:
        return JsonResponse({"success": False,
                             "error": f"The image is larger than {MAX_UPLOAD_MB} MB."}, status=400)
    try:
        facts = pdf_export.image_facts(f)
    except LayoutError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    if facts["px_w"] * facts["px_h"] > MAX_PIXELS:
        return JsonResponse({"success": False,
                             "error": "The image has too many pixels; please reduce its size."},
                            status=400)

    dpi = facts["dpi_used"]
    w_mm, h_mm = facts["px_w"] / dpi * 25.4, facts["px_h"] / dpi * 25.4
    if facts["dpi_status"] == "file":
        message = f"Detected {facts['px_w']} × {facts['px_h']} px at {dpi:g} DPI."
    else:
        message = (f"Detected {facts['px_w']} × {facts['px_h']} px. The file has no reliable DPI, "
                   f"so {dpi} DPI is assumed. Please check the size below.")
    return JsonResponse({
        "success": True, "px": {"w": facts["px_w"], "h": facts["px_h"]},
        "dpi_used": dpi, "dpi_status": facts["dpi_status"], "color_mode": facts["color_mode"],
        "mm": {"w": round(w_mm, 2), "h": round(h_mm, 2)}, "message": message})


@require_POST
def quote(request):
    """Numbers only (no drawing): what the current settings would produce."""
    form = JobForm(request.POST, profile=PrintProfile.get_default())
    formset = design_formset(request.POST, quote=True)
    form_ok, set_ok = form.is_valid(), formset.is_valid()
    if not (form_ok and set_ok):
        return JsonResponse({"ok": False, "errors": collect_errors(form, formset)})
    designs = [f.cleaned_data for f in formset.forms if f.cleaned_data]
    try:
        made = make_plan(form.cleaned_data, designs, align=form.profile.align)
    except LayoutError as exc:
        return JsonResponse({"ok": False, "errors": [str(exc)]})

    plan = made["plan"]
    warnings = []
    for i, d in enumerate(designs):
        if d.get("px_w") and d.get("px_h"):
            dpi = effective_dpi(d["px_w"], d["px_h"], d["width_mm"], d["height_mm"])
            if dpi < 250:
                name = d.get("name") or f"Design {i + 1}"
                warnings.append(f"{name} would print at about {dpi:.0f} DPI (250+ recommended).")
    suggestions = []
    if len(designs) == 1:
        px = (designs[0]["px_w"], designs[0]["px_h"]) if designs[0].get("px_w") and designs[0].get("px_h") else None
        suggestions = _single_design_suggestions(made["sheet"], designs[0], px)

    solo_fit = []
    for i, d in enumerate(designs):
        label = d.get("name") or ("the sticker" if len(designs) == 1 else f"Design {i + 1}")
        solo_fit.append({"name": label, "count": plan.per_sheet_alone[i]})

    sheet = made["sheet"]
    return JsonResponse({
        "ok": True,
        "sheets": plan.sheet_count, "total_stickers": plan.total_stickers,
        "per_sheet_alone": list(plan.per_sheet_alone),
        "utilization_pct": round(plan.job_utilization_pct, 1),
        "waste_pct": round(plan.waste_pct, 1),
        "orientation": made["orientation"],
        "sheet_mm": [sheet.width, sheet.height],
        "total_cost": plan.total_cost, "cost_per_sticker": plan.cost_per_sticker,
        "warnings": warnings, "suggestions": suggestions, "solo_fit": solo_fit,
    })


@require_POST
def calculate_layout(request):
    profile = PrintProfile.get_default()
    form = JobForm(request.POST, profile=profile)
    formset = design_formset(request.POST, request.FILES)
    form_ok, set_ok = form.is_valid(), formset.is_valid()
    if not (form_ok and set_ok):
        return _render_index(request, form, formset, collect_errors(form, formset))

    design_forms = [f for f in formset.forms if f.cleaned_data]
    try:
        made = make_plan(form.cleaned_data, [f.cleaned_data for f in design_forms],
                         align=profile.align)
    except LayoutError as exc:
        return _render_index(request, form, formset, [str(exc)])

    if not request.session.session_key:
        request.session.create()
    cd, sheet, plan = form.cleaned_data, made["sheet"], made["plan"]

    with transaction.atomic():
        job = StickerLayout.objects.create(
            name=cd.get("layout_name") or "Untitled job",
            paper_size=made["paper_size"],
            sheet_width_mm=sheet.width, sheet_height_mm=sheet.height,
            orientation=made["orientation"],
            margin_top=sheet.margin_top, margin_right=sheet.margin_right,
            margin_bottom=sheet.margin_bottom, margin_left=sheet.margin_left,
            horizontal_spacing=sheet.gap_x, vertical_spacing=sheet.gap_y,
            allow_rotation=cd["allow_rotation"], group_by_design=cd["group_by_design"],
            align=profile.align, sheet_cost=made["sheet_cost"],
            session_key=request.session.session_key)
        for i, f in enumerate(design_forms):
            dcd = f.cleaned_data
            upload = dcd["image"]
            facts, sha = _facts_and_hash(upload)
            design = StickerDesign(
                layout=job, position=i, name=dcd.get("name", ""), width_mm=dcd["width_mm"],
                height_mm=dcd["height_mm"], quantity=dcd["quantity"],
                pixel_width=facts["px_w"], pixel_height=facts["px_h"],
                source_dpi=facts["file_dpi"], color_mode=facts["color_mode"][:10],
                sha256=sha)
            design.image.save(upload.name, upload, save=False)
            design.save()
        job.apply_plan(plan)
        job.save()
    logger.info("job %s created: %s sheets, %s stickers", job.token, job.sheet_count,
                job.total_stickers)
    return redirect("result", token=job.token)


def _sync_job_designs(job, design_forms):
    """Create/update/delete StickerDesign rows to match a submitted, already-
    validated formset, in submission order (positions become 0..N-1).

    Removed rows are deleted FIRST, before anything is renumbered, so a kept
    row can never collide with a not-yet-deleted removed row's old position."""
    kept_ids = {f.cleaned_data["design_id"] for f in design_forms if f.cleaned_data.get("design_id")}
    job.designs.exclude(id__in=kept_ids).delete()
    for i, f in enumerate(design_forms):
        dcd = f.cleaned_data
        design_id = dcd.get("design_id")
        design = get_object_or_404(StickerDesign, id=design_id, layout=job) if design_id else StickerDesign(layout=job)
        design.position = i
        design.name = dcd.get("name", "")
        design.width_mm, design.height_mm, design.quantity = dcd["width_mm"], dcd["height_mm"], dcd["quantity"]
        if dcd.get("image"):
            upload = dcd["image"]
            facts, sha = _facts_and_hash(upload)
            if design.image:
                design.image.delete(save=False)
            design.image.save(upload.name, upload, save=False)
            design.pixel_width, design.pixel_height = facts["px_w"], facts["px_h"]
            design.source_dpi, design.color_mode = facts["file_dpi"], facts["color_mode"][:10]
            design.sha256 = sha
        design.save()


def _resolve_sheet_dims_simple(cd):
    """A quick, non-validating sheet-size resolution used only when make_plan()
    has already failed - just enough to save SOMETHING sensible on the job, so
    the customer's edit isn't silently discarded and shows up again for them
    to fix. (The real, auto-orientation-exploring resolution lives in make_plan.)"""
    if cd.get("use_custom_paper"):
        paper_obj, w, h = None, cd["custom_paper_width"], cd["custom_paper_height"]
    else:
        paper_obj, w, h = cd["paper_size"], cd["paper_size"].width_mm, cd["paper_size"].height_mm
    lo, hi = min(w, h), max(w, h)
    orientation = "landscape" if cd.get("paper_orientation") == "landscape" else "portrait"
    sw, sh = (hi, lo) if orientation == "landscape" else (lo, hi)
    return paper_obj, sw, sh, orientation


def _apply_job_fields(job, cd, paper_size, sw, sh, orientation, margin_top, margin_right,
                      margin_bottom, margin_left, gap_x, gap_y, sheet_cost):
    job.name = cd.get("layout_name") or job.name
    job.paper_size = paper_size
    job.sheet_width_mm, job.sheet_height_mm = sw, sh
    job.orientation = orientation
    job.margin_top, job.margin_right = margin_top, margin_right
    job.margin_bottom, job.margin_left = margin_bottom, margin_left
    job.horizontal_spacing, job.vertical_spacing = gap_x, gap_y
    job.allow_rotation, job.group_by_design = cd["allow_rotation"], cd["group_by_design"]
    job.sheet_cost = sheet_cost


@require_http_methods(["GET", "POST"])
def job_edit(request, token):
    """The same create-job page, reused to edit an existing job in place.

    Existing designs are prefilled with their real, already-saved artwork, so
    revisiting this page never requires re-choosing a file that was already
    uploaded - only a design added during THIS visit (and not yet submitted)
    needs one, which is an unavoidable browser limit, not a data loss.

    A submission that doesn't physically fit is still SAVED (marking the job
    failed, with the customer's own numbers kept) rather than silently
    rejected, so nothing they typed is lost and the result page's "Edit this
    job" link can bring them straight back to the exact thing that needs
    fixing."""
    job = _get_job(token)
    profile = PrintProfile.get_default()   # only supplies fallbacks JobForm needs internally

    if request.method == "POST":
        form = JobForm(request.POST, profile=profile)
        formset = design_formset(request.POST, request.FILES, editing=True)
        if not (form.is_valid() and formset.is_valid()):
            return _render_index(request, form, formset, collect_errors(form, formset), edit_job=job)

        design_forms = [f for f in formset.forms if f.cleaned_data]
        cd = form.cleaned_data
        try:
            made = make_plan(cd, [f.cleaned_data for f in design_forms], align=job.align)
        except LayoutError as exc:
            paper_obj, sw, sh, orientation = _resolve_sheet_dims_simple(cd)
            cost = float(paper_obj.cost_per_sheet) if paper_obj and paper_obj.cost_per_sheet is not None else None
            with transaction.atomic():
                _sync_job_designs(job, design_forms)
                _apply_job_fields(job, cd, paper_obj, sw, sh, orientation, cd["margin_top"],
                                  cd["margin_right"], cd["margin_bottom"], cd["margin_left"],
                                  cd["horizontal_spacing"], cd["vertical_spacing"], cost)
                job.mark_failed(str(exc))
                job.save()
            return redirect("result", token=token)

        sheet, plan = made["sheet"], made["plan"]
        with transaction.atomic():
            _sync_job_designs(job, design_forms)
            _apply_job_fields(job, cd, made["paper_size"], sheet.width, sheet.height, made["orientation"],
                              sheet.margin_top, sheet.margin_right, sheet.margin_bottom, sheet.margin_left,
                              sheet.gap_x, sheet.gap_y, made["sheet_cost"])
            job.apply_plan(plan)
            job.save()
        return redirect("result", token=token)

    form = JobForm(profile=profile, initial=_job_initial(job))
    formset = design_formset(editing=True, initial=[_design_initial(d) for d in job.designs.all()])
    return _render_index(request, form, formset, edit_job=job)


@require_GET
def result(request, token):
    job = _get_job(token)
    designs = list(job.designs.all())                      # DB truth: always shown, editable regardless of status
    ready = job.status == StickerLayout.STATUS_READY and bool(job.layout_data)
    solo_fit = [d["per_sheet_alone"] for d in job.layout_data["designs"]] if ready else [None] * len(designs)

    ctx = {
        "job": job,
        "designs": [
            {"id": d.id, "name": d.display_name, "width": d.width_mm, "height": d.height_mm,
             "quantity": d.quantity, "per_sheet_alone": solo_fit[i],
             "dpi": (round(d.effective_dpi()) if d.effective_dpi() else None)}
            for i, d in enumerate(designs)],
    }
    if ready:
        data = job.layout_data
        ctx["sheets"] = [
            {"first": sp["first_sheet"], "last": sp["first_sheet"] + sp["repeat"] - 1,
             "repeat": sp["repeat"], "count": sp["count"], "util": sp["utilization_sheet_pct"]}
            for sp in data["sheets"]]
        if len(designs) == 1:
            d = designs[0]
            px = (d.pixel_width, d.pixel_height) if d.pixel_width and d.pixel_height else None
            ctx["suggestions"] = _single_design_suggestions(
                job.to_sheet(), {"width_mm": d.width_mm, "height_mm": d.height_mm,
                                 "quantity": d.quantity}, px)
    return render(request, "base/result.html", ctx)


@require_GET
def sheet_image(request, token, sheet_no):
    job = _get_job(token)
    _require_ready(job)
    dpi = _int_param(request, "dpi", 30, 300, 100)
    try:
        png = pdf_export.png_for_job(job, sheet_no, dpi=dpi,
                                     guides=request.GET.get("guides", "1") == "1")
    except LayoutError:
        raise Http404
    response = HttpResponse(png, content_type="image/png")
    response["Cache-Control"] = "private, max-age=3600"
    return response


@require_GET
def download_layout(request, token):
    job = _get_job(token)
    _require_ready(job)
    fmt = request.GET.get("format", "pdf")
    try:
        if fmt == "pdf":
            body, ctype, ext = pdf_export.pdf_for_job(job), "application/pdf", "pdf"
        elif fmt == "png":
            n = _int_param(request, "sheet", 1, job.sheet_count, 1)
            dpi = _int_param(request, "dpi", 72, 600, 300)
            body = pdf_export.png_for_job(job, n, dpi=dpi, guides=False)
            ctype, ext = "image/png", "png"
        else:
            return JsonResponse({"success": False, "error": "Unsupported format."}, status=400)
    except LayoutError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    response = HttpResponse(body, content_type=ctype)
    response["Content-Disposition"] = f'attachment; filename="{_safe_filename(job.name, ext)}"'
    return response
