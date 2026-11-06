"""
pdf_export.py
=============
Turns a saved job (layout_data + artwork files) into a print-ready PDF or a PNG
picture of one sheet. Replaces generate_pdf / generate_png in the old views.py
and utils.py.

* PDF: one page per physical sheet, at the exact sheet size. Each design's image
  is embedded once and reused on every page. JPEG data is passed through
  untouched, transparency is kept (mask), rotation is real 90-degree rotation.
  Nothing is printed on the sheet except the stickers (no footer/watermark).
* PNG: raster picture of one sheet. Used for the on-screen preview (with faint
  guide boxes) and for downloads (no guides, up to 300 DPI).

Rotation convention (same as the layout engine): ``rotation == 90`` means the
artwork is turned 90 degrees CLOCKWISE; the placement's w/h are the box after
rotation.
"""

import io

from PIL import Image, ImageDraw, ImageOps

try:
    from .layout_engine import LayoutError
except ImportError:                     # standalone use
    from layout_engine import LayoutError

MM = 25.4
ASSUMED_DPI = 300
SUSPECT_DPI = (72, 96)          # common "screen default" values that rarely mean anything
MAX_SIDE_PX = 9000              # longest side of a rendered PNG
MAX_PDF_PAGES = 1000

_LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
_CLOCKWISE = getattr(Image, "Transpose", Image).ROTATE_270

# preview-only colours (never used in the PDF or in a downloaded PNG)
_WASTE_FILL = (255, 241, 204)     # pale amber: unused space inside the printable area
_WASTE_BORDER = (224, 161, 0)     # amber, dashed: printable-area boundary
_STICKER_OUTLINE = (205, 205, 205)


def _dashed_rect(draw, box, color, dash=6, gap=4, width=1):
    """A rectangle outline made of dashes, since PIL has no built-in dashed line."""
    x0, y0, x1, y1 = box
    for y in (y0, y1):
        x = x0
        while x < x1:
            draw.line([(x, y), (min(x + dash, x1), y)], fill=color, width=width)
            x += dash + gap
    for x in (x0, x1):
        y = y0
        while y < y1:
            draw.line([(x, y), (x, min(y + dash, y1))], fill=color, width=width)
            y += dash + gap


# --------------------------------------------------------------------------
# reading images
# --------------------------------------------------------------------------

def _exif_orientation(img):
    try:
        return img.getexif().get(0x0112, 1)
    except Exception:
        return 1


def image_facts(fileobj):
    """Pixel size, DPI and colour mode of an uploaded image.

    Pixel size is reported as it will PRINT (EXIF rotation applied). Raises
    LayoutError if the file is not a readable image. Rewinds the file.
    """
    try:
        img = Image.open(fileobj)
        w, h = img.size
        mode = img.mode
        dpi = img.info.get("dpi")
        orient = _exif_orientation(img)
        alpha = mode in ("RGBA", "LA", "PA") or "transparency" in img.info
    except Exception as exc:
        raise LayoutError("That file is not a readable image.") from exc
    finally:
        try:
            fileobj.seek(0)
        except Exception:
            pass

    if orient in (5, 6, 7, 8):
        w, h = h, w

    file_dpi = None
    try:
        if dpi and 10 <= float(dpi[0]) <= 5000 and 10 <= float(dpi[1]) <= 5000:
            file_dpi = round(float(dpi[0]), 1)
    except (TypeError, ValueError, IndexError):
        pass

    if file_dpi and round(file_dpi) not in SUSPECT_DPI:
        used, status = file_dpi, "file"
    elif file_dpi:
        used, status = ASSUMED_DPI, "suspect"
    else:
        used, status = ASSUMED_DPI, "unknown"
    return {"px_w": w, "px_h": h, "file_dpi": file_dpi, "dpi_used": used,
            "dpi_status": status, "color_mode": mode, "has_alpha": alpha}


def load_artwork(source):
    """PIL image ready for compositing: EXIF rotation applied, RGB or RGBA."""
    img = ImageOps.exif_transpose(Image.open(source))
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        return img.convert("RGBA")
    return img.convert("RGB")


def fit_dpi(sheet_w_mm, sheet_h_mm, dpi):
    """Lower the DPI if the picture would be larger than MAX_SIDE_PX."""
    longest = max(sheet_w_mm, sheet_h_mm) / MM
    return max(30, min(int(dpi), int(MAX_SIDE_PX / longest)))


# --------------------------------------------------------------------------
# PNG of one sheet
# --------------------------------------------------------------------------

def render_sheet_png(sheet_w, sheet_h, placements, load, dpi=100, guides=False,
                     margin_top=0, margin_right=0, margin_bottom=0, margin_left=0):
    """Return PNG bytes of one sheet.

    placements: dicts with x, y, w, h (mm), rotation (0/90), design (index).
    load(design_index) -> PIL image (called once per design, then released).
    guides: when True, shades unused space inside the printable area and draws
    a dashed line at the printable-area boundary, so a customer can see at a
    glance how much of the sheet is unused. Preview only; never used for the
    PDF or for a downloaded PNG.
    """
    dpi = fit_dpi(sheet_w, sheet_h, dpi)
    k = dpi / MM
    width, height = round(sheet_w * k), round(sheet_h * k)
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)

    if guides:
        box = (round(margin_left * k), round(margin_top * k),
               round((sheet_w - margin_right) * k), round((sheet_h - margin_bottom) * k))
        if box[2] > box[0] and box[3] > box[1]:
            draw.rectangle(box, fill=_WASTE_FILL)      # stickers are pasted on top below,
            _dashed_rect(draw, box, _WASTE_BORDER)      # so only genuinely unused space stays shaded

    by_design = {}
    for p in placements:
        by_design.setdefault(p["design"], []).append(p)

    for design, plist in by_design.items():
        art = load(design)
        cache = {}
        for p in plist:
            x0, y0 = round(p["x"] * k), round(p["y"] * k)
            bw, bh = max(1, round(p["w"] * k)), max(1, round(p["h"] * k))
            key = (bw, bh, p["rotation"])
            if key not in cache:
                src = art.transpose(_CLOCKWISE) if p["rotation"] == 90 else art
                s = min(bw / src.width, bh / src.height)     # fit inside the box
                nw, nh = max(1, round(src.width * s)), max(1, round(src.height * s))
                cache[key] = (src.resize((nw, nh), _LANCZOS), nw, nh)
            img, nw, nh = cache[key]
            canvas.paste(img, (x0 + (bw - nw) // 2, y0 + (bh - nh) // 2),
                         img if img.mode == "RGBA" else None)
            if guides:
                draw.rectangle([x0, y0, x0 + bw - 1, y0 + bh - 1], outline=_STICKER_OUTLINE)
        del art, cache

    buf = io.BytesIO()
    canvas.save(buf, "PNG", dpi=(dpi, dpi))
    return buf.getvalue()


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

def _pdf_reader(raw):
    """ImageReader for reportlab, converting only when it has to."""
    from reportlab.lib.utils import ImageReader
    img = Image.open(io.BytesIO(raw))
    mode = img.mode
    alpha = mode in ("RGBA", "LA", "PA") or "transparency" in img.info
    needs_convert = (
        _exif_orientation(img) != 1
        or mode not in ("RGB", "RGBA", "L", "LA", "CMYK")
        or ("transparency" in img.info and mode not in ("RGBA", "LA")))
    if needs_convert:
        art = load_artwork(io.BytesIO(raw))
        buf = io.BytesIO()
        art.save(buf, "PNG")
        raw, alpha = buf.getvalue(), art.mode == "RGBA"
    return ImageReader(io.BytesIO(raw)), alpha


def build_pdf(sheet_w, sheet_h, pages, read_bytes, title="Sticker layout"):
    """PDF bytes. pages: list of placement lists (one per physical sheet).
    read_bytes(design_index) -> the original image file bytes."""
    from reportlab.pdfgen import canvas as rl_canvas

    if len(pages) > MAX_PDF_PAGES:
        raise LayoutError(
            f"This job has {len(pages)} sheets, more than one PDF can hold "
            f"({MAX_PDF_PAGES}). Split the order into smaller jobs.")
    k = 72 / MM
    page_w, page_h = sheet_w * k, sheet_h * k
    readers = {}

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_w, page_h))
    c.setTitle(title)
    c.setAuthor("PrintGrid")
    for placements in pages:
        for p in placements:
            di = p["design"]
            if di not in readers:
                readers[di] = _pdf_reader(read_bytes(di))
            reader, alpha = readers[di]
            mask = "auto" if alpha else None
            x, y_top = p["x"] * k, page_h - p["y"] * k
            bw, bh = p["w"] * k, p["h"] * k
            if p["rotation"] == 90:
                # turn 90 degrees clockwise about the box's top-left corner
                c.saveState()
                c.translate(x, y_top)
                c.rotate(-90)
                c.drawImage(reader, 0, 0, width=bh, height=bw, mask=mask,
                            preserveAspectRatio=True, anchor="c")
                c.restoreState()
            else:
                c.drawImage(reader, x, y_top - bh, width=bw, height=bh, mask=mask,
                            preserveAspectRatio=True, anchor="c")
        c.showPage()
    c.save()
    return buf.getvalue()


# --------------------------------------------------------------------------
# job wrappers (duck-typed: need .layout_data and .designs.all() with .image)
# --------------------------------------------------------------------------

def _read_design_bytes(design):
    design.image.open("rb")
    try:
        return design.image.read()
    finally:
        design.image.close()


def _require_plan(job):
    data = job.layout_data
    if not data or data.get("format") != "sheets-v1":
        raise LayoutError("This job has no layout to export.")
    return data


def pdf_for_job(job):
    data = _require_plan(job)
    designs = list(job.designs.all())
    pages = []
    for sp in data["sheets"]:
        pages.extend([sp["placements"]] * sp["repeat"])
    return build_pdf(data["sheet"]["width"], data["sheet"]["height"], pages,
                     lambda i: _read_design_bytes(designs[i]), title=job.name or "Sticker layout")


def png_for_job(job, sheet_no, dpi=100, guides=False):
    data = _require_plan(job)
    designs = list(job.designs.all())
    s = data["sheet"]
    for sp in data["sheets"]:
        if sp["first_sheet"] <= sheet_no < sp["first_sheet"] + sp["repeat"]:
            return render_sheet_png(
                s["width"], s["height"], sp["placements"],
                lambda i: load_artwork(io.BytesIO(_read_design_bytes(designs[i]))),
                dpi=dpi, guides=guides, margin_top=s["margin_top"],
                margin_right=s["margin_right"], margin_bottom=s["margin_bottom"],
                margin_left=s["margin_left"])
    raise LayoutError(f"Sheet {sheet_no} does not exist.")
