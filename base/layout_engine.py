"""
layout_engine.py
================

Pure-Python sticker layout engine. No Django, no Pillow: plain numbers in,
plain data out, so it can be unit-tested on its own and reused by the form
validation, the quote endpoint, the PDF/PNG exporter and the result page.

Conventions
-----------
* All lengths are millimetres.
* Origin is the TOP-LEFT corner of the sheet, x grows right, y grows down
  (same as the old ``layout_data['positions']``).
* A placement's ``w`` / ``h`` are the size of the box it occupies on the sheet
  *after* rotation. ``rotation`` is 0 or 90 (degrees, artwork turned clockwise).
* Stickers are treated as their bounding box. Die-cut shape nesting is a later
  step and would replace ``_search``.

What it does
------------
* Fits as many stickers as possible on a sheet, trying the sticker upright and
  rotated 90 degrees, including mixed layouts where a rotated block fills the
  strip left over beside / below the main block.
* Turns a quantity into sheets, a partial last sheet, waste and cost.
* Suggests small size changes that cross a "fits one more row/column" threshold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

ENGINE_VERSION = 1

#: Tolerance (mm) so a mathematically perfect fit is not lost to float noise
#: (e.g. 0.3 / 0.1 == 2.9999999999999996).
EPS = 1e-6

#: How many rows/columns short of the maximum the main block may be when
#: searching mixed layouts. Higher = better packing, slower. 4 is plenty.
DEFAULT_DEPTH = 4

MM_PER_INCH = 25.4

__all__ = [
    "ENGINE_VERSION", "LayoutError", "Sheet", "Placement", "SheetLayout",
    "JobPlan", "SizeSuggestion", "plan_layout", "plan_job", "suggest_sizes",
    "effective_dpi",
]


class LayoutError(ValueError):
    """Input that cannot produce a layout. The message is safe to show to users."""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s or "0"


def _round_down_2(v: float) -> float:
    """Floor to 0.01 mm, tolerant of tiny float noise just below a boundary."""
    return math.floor(v * 100 + 1e-6) / 100


def _r(v: float) -> float:
    return round(v, 3)


def _count_along(avail: float, size: float, gap: float) -> int:
    """How many items of ``size`` with ``gap`` between them fit in ``avail``.

    n items need n*size + (n-1)*gap, so n <= (avail + gap) / (size + gap).
    (The old code used avail / (size + gap), which charged a gap after the
    last item and lost a row/column on tight fits.)
    """
    if size <= 0 or avail + EPS < size:
        return 0
    return int(math.floor((avail + gap + EPS) / (size + gap)))


def effective_dpi(px_w: float, px_h: float, w_mm: float, h_mm: float) -> float:
    """Resolution the artwork will print at when placed at w_mm x h_mm."""
    if w_mm <= 0 or h_mm <= 0:
        raise LayoutError("Sticker size must be greater than zero.")
    return min(px_w / (w_mm / MM_PER_INCH), px_h / (h_mm / MM_PER_INCH))


# --------------------------------------------------------------------------
# data classes
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Sheet:
    """A sheet plus the production constraints that apply to it."""
    width: float
    height: float
    margin_top: float = 0.0
    margin_right: float = 0.0
    margin_bottom: float = 0.0
    margin_left: float = 0.0
    gap_x: float = 0.0   # horizontal gap between stickers
    gap_y: float = 0.0   # vertical gap between stickers

    def __post_init__(self):
        for name in ("width", "height", "margin_top", "margin_right",
                     "margin_bottom", "margin_left", "gap_x", "gap_y"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                raise LayoutError(f"'{name}' must be a number.")
        if self.width <= 0 or self.height <= 0:
            raise LayoutError("Sheet size must be greater than zero.")
        for name in ("margin_top", "margin_right", "margin_bottom",
                     "margin_left", "gap_x", "gap_y"):
            if getattr(self, name) < 0:
                raise LayoutError("Margins and spacing cannot be negative.")
        if self.printable_width <= EPS or self.printable_height <= EPS:
            raise LayoutError(
                f"Margins are too large for a {_fmt(self.width)} x "
                f"{_fmt(self.height)} mm sheet.")

    @property
    def printable_width(self) -> float:
        return self.width - self.margin_left - self.margin_right

    @property
    def printable_height(self) -> float:
        return self.height - self.margin_top - self.margin_bottom

    def to_dict(self) -> Dict[str, float]:
        return {
            "width": _r(self.width), "height": _r(self.height),
            "margin_top": _r(self.margin_top), "margin_right": _r(self.margin_right),
            "margin_bottom": _r(self.margin_bottom), "margin_left": _r(self.margin_left),
            "gap_x": _r(self.gap_x), "gap_y": _r(self.gap_y),
        }


@dataclass(frozen=True)
class Placement:
    x: float
    y: float
    w: float
    h: float
    rotation: int = 0    # 0 or 90
    design: int = 0      # index of the design (multi-design jobs come later)

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    def to_dict(self) -> Dict[str, float]:
        return {"x": _r(self.x), "y": _r(self.y), "w": _r(self.w),
                "h": _r(self.h), "rotation": self.rotation, "design": self.design}


@dataclass(frozen=True)
class SheetLayout:
    sheet: Sheet
    sticker_w: float
    sticker_h: float
    placements: Tuple[Placement, ...]
    layout_kind: str      # 'grid' | 'grid-rotated' | 'mixed'

    @property
    def per_sheet(self) -> int:
        return len(self.placements)

    @property
    def rotated_count(self) -> int:
        return sum(1 for p in self.placements if p.rotation)

    @property
    def sticker_area(self) -> float:
        return self.sticker_w * self.sticker_h

    @property
    def utilization_sheet_pct(self) -> float:
        """Sticker area as % of the whole sheet."""
        return 100.0 * self.per_sheet * self.sticker_area / (
            self.sheet.width * self.sheet.height)

    @property
    def utilization_printable_pct(self) -> float:
        """Sticker area as % of the printable area (inside the margins)."""
        return 100.0 * self.per_sheet * self.sticker_area / (
            self.sheet.printable_width * self.sheet.printable_height)

    def to_dict(self) -> Dict:
        return {
            "engine_version": ENGINE_VERSION,
            "sheet": self.sheet.to_dict(),
            "sticker": {"width": _r(self.sticker_w), "height": _r(self.sticker_h)},
            "per_sheet": self.per_sheet,
            "layout_kind": self.layout_kind,
            "rotated_count": self.rotated_count,
            "utilization_sheet_pct": round(self.utilization_sheet_pct, 2),
            "utilization_printable_pct": round(self.utilization_printable_pct, 2),
            "placements": [p.to_dict() for p in self.placements],
        }


@dataclass(frozen=True)
class JobPlan:
    layout: SheetLayout
    quantity: int
    sheets: int
    last_sheet_count: int          # stickers on the final sheet
    fill_last_sheet: bool          # True = print spare slots as overrun
    printed_total: int             # stickers actually printed
    spare_slots: int               # empty slots on the last sheet (if not filled)
    job_utilization_pct: float     # sticker area / total sheet area, all sheets
    waste_pct: float
    total_cost: Optional[float] = None
    cost_per_sticker: Optional[float] = None

    def placements_for_sheet(self, sheet_no: int) -> Tuple[Placement, ...]:
        """Placements for sheet ``sheet_no`` (1-based)."""
        if not 1 <= sheet_no <= self.sheets:
            raise LayoutError(f"Sheet {sheet_no} does not exist (job has {self.sheets}).")
        if sheet_no < self.sheets or self.fill_last_sheet:
            return self.layout.placements
        return self.layout.placements[: self.last_sheet_count]

    def to_dict(self) -> Dict:
        d = self.layout.to_dict()
        d.update({
            "quantity": self.quantity,
            "sheets": self.sheets,
            "last_sheet_count": self.last_sheet_count,
            "fill_last_sheet": self.fill_last_sheet,
            "printed_total": self.printed_total,
            "spare_slots": self.spare_slots,
            "job_utilization_pct": round(self.job_utilization_pct, 2),
            "waste_pct": round(self.waste_pct, 2),
            "total_cost": None if self.total_cost is None else round(self.total_cost, 2),
            "cost_per_sticker": (None if self.cost_per_sticker is None
                                 else round(self.cost_per_sticker, 4)),
        })
        return d


@dataclass(frozen=True)
class SizeSuggestion:
    kind: str                # 'shrink' | 'enlarge'
    sticker_w: float
    sticker_h: float
    change_mm: float         # change of the varied dimension (negative = smaller)
    per_sheet: int
    sheets: Optional[int]    # None when no quantity was given
    sheets_saved: int
    dpi: Optional[float]     # effective DPI at the new size, if image size known
    low_resolution: bool
    message: str

    def to_dict(self) -> Dict:
        return {
            "kind": self.kind,
            "sticker_w": self.sticker_w, "sticker_h": self.sticker_h,
            "change_mm": round(self.change_mm, 2),
            "per_sheet": self.per_sheet, "sheets": self.sheets,
            "sheets_saved": self.sheets_saved,
            "dpi": None if self.dpi is None else round(self.dpi, 1),
            "low_resolution": self.low_resolution,
            "message": self.message,
        }


# --------------------------------------------------------------------------
# core search
# --------------------------------------------------------------------------

# A cell is (width, height, rotation). A block is one rectangular grid of
# identical cells: (x, y, cell_w, cell_h, rotation, cols, rows), with x/y
# relative to the top-left of the printable area.

def _cells(sticker_w: float, sticker_h: float, allow_rotation: bool):
    cells = [(sticker_w, sticker_h, 0)]
    if allow_rotation and abs(sticker_w - sticker_h) > EPS:
        cells.append((sticker_h, sticker_w, 90))
    return cells


def _grid(region_w: float, region_h: float, cell, gx: float, gy: float):
    c = _count_along(region_w, cell[0], gx)
    r = _count_along(region_h, cell[1], gy)
    return (c, r) if c > 0 and r > 0 else (0, 0)


def _best_fill(region_w: float, region_h: float, cells, gx: float, gy: float):
    """Best single-orientation grid inside a region. Returns (n, cell, cols, rows)."""
    best = (0, None, 0, 0)
    for cell in cells:
        c, r = _grid(region_w, region_h, cell, gx, gy)
        if c * r > best[0]:
            best = (c * r, cell, c, r)
    return best


def _search(pw: float, ph: float, cells, gx: float, gy: float, depth: int):
    """Find the layout with the most stickers. Returns (count, blocks)."""
    best_n, best_blocks = 0, []

    # 1. pure grids
    for cell in cells:
        c, r = _grid(pw, ph, cell, gx, gy)
        if c * r > best_n:
            best_n, best_blocks = c * r, [(0, 0, cell[0], cell[1], cell[2], c, r)]

    # 2. mixed layouts: a main block plus the best grid in the leftover strips
    if len(cells) > 1:
        for cell in cells:
            cw, ch, rot = cell
            max_c = _count_along(pw, cw, gx)
            max_r = _count_along(ph, ch, gy)
            if not max_c or not max_r:
                continue
            for c in range(max_c, max(0, max_c - depth - 1), -1):
                w1 = c * cw + (c - 1) * gx
                rx = w1 + gx
                for r in range(max_r, max(0, max_r - depth - 1), -1):
                    h1 = r * ch + (r - 1) * gy
                    ry = h1 + gy
                    for variant in (0, 1):
                        if variant == 0:   # right strip runs full height
                            right = (rx, 0.0, pw - rx, ph)
                            below = (0.0, ry, w1, ph - ry)
                        else:              # bottom strip runs full width
                            right = (rx, 0.0, pw - rx, h1)
                            below = (0.0, ry, pw, ph - ry)
                        total = c * r
                        blocks = [(0.0, 0.0, cw, ch, rot, c, r)]
                        for (x, y, w, h) in (right, below):
                            if w <= 0 or h <= 0:
                                continue
                            n, ce, cc, rr = _best_fill(w, h, cells, gx, gy)
                            if n:
                                total += n
                                blocks.append((x, y, ce[0], ce[1], ce[2], cc, rr))
                        if total > best_n:
                            best_n, best_blocks = total, blocks
    return best_n, best_blocks


def _validate_sticker(sticker_w: float, sticker_h: float) -> None:
    for v in (sticker_w, sticker_h):
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            raise LayoutError("Sticker size must be a number.")
    if sticker_w <= 0 or sticker_h <= 0:
        raise LayoutError("Sticker size must be greater than zero.")


def _per_sheet(sheet: Sheet, w: float, h: float, allow_rotation: bool,
               depth: int) -> int:
    """Stickers per sheet, or 0 if it does not fit at all (no exceptions)."""
    if w <= 0 or h <= 0:
        return 0
    return _search(sheet.printable_width, sheet.printable_height,
                   _cells(w, h, allow_rotation), sheet.gap_x, sheet.gap_y, depth)[0]


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

def plan_layout(sheet: Sheet, sticker_w: float, sticker_h: float, *,
                allow_rotation: bool = True, depth: int = DEFAULT_DEPTH,
                align: str = "top-left") -> SheetLayout:
    """Best layout for ONE sheet.

    align: 'top-left' keeps all leftover space on the right/bottom (one reusable
    offcut); 'center' splits it evenly around the block.
    """
    _validate_sticker(sticker_w, sticker_h)
    if align not in ("top-left", "center"):
        raise LayoutError("align must be 'top-left' or 'center'.")

    pw, ph = sheet.printable_width, sheet.printable_height
    cells = _cells(sticker_w, sticker_h, allow_rotation)
    n, blocks = _search(pw, ph, cells, sheet.gap_x, sheet.gap_y, depth)

    if n == 0:
        raise LayoutError(
            f"A {_fmt(sticker_w)} x {_fmt(sticker_h)} mm sticker does not fit the "
            f"printable area of {_fmt(pw)} x {_fmt(ph)} mm "
            f"(sheet {_fmt(sheet.width)} x {_fmt(sheet.height)} mm minus margins).")

    placements: List[Placement] = []
    for (bx, by, cw, ch, rot, cols, rows) in blocks:
        for i in range(rows):
            for j in range(cols):
                placements.append(Placement(
                    x=sheet.margin_left + bx + j * (cw + sheet.gap_x),
                    y=sheet.margin_top + by + i * (ch + sheet.gap_y),
                    w=cw, h=ch, rotation=rot))

    if align == "center":
        min_x = min(p.x for p in placements)
        max_x = max(p.right for p in placements)
        min_y = min(p.y for p in placements)
        max_y = max(p.bottom for p in placements)
        dx = sheet.margin_left + (pw - (max_x - min_x)) / 2 - min_x
        dy = sheet.margin_top + (ph - (max_y - min_y)) / 2 - min_y
        placements = [Placement(p.x + dx, p.y + dy, p.w, p.h, p.rotation, p.design)
                      for p in placements]

    # Reading order, so a partial last sheet is simply the first N placements.
    placements.sort(key=lambda p: (round(p.y, 3), round(p.x, 3)))

    if len(blocks) > 1:
        kind = "mixed"
    else:
        kind = "grid-rotated" if blocks[0][4] == 90 else "grid"

    return SheetLayout(sheet=sheet, sticker_w=sticker_w, sticker_h=sticker_h,
                       placements=tuple(placements), layout_kind=kind)


def plan_job(sheet: Sheet, sticker_w: float, sticker_h: float, quantity: int, *,
             allow_rotation: bool = True, depth: int = DEFAULT_DEPTH,
             align: str = "top-left", fill_last_sheet: bool = False,
             sheet_cost: Optional[float] = None) -> JobPlan:
    """Turn a quantity into sheets, waste and (optionally) cost.

    fill_last_sheet=True prints the spare slots on the last sheet as overrun
    (extra stickers) instead of leaving them empty.
    """
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise LayoutError("Quantity must be a whole number of at least 1.")
    if sheet_cost is not None and sheet_cost < 0:
        raise LayoutError("Sheet cost cannot be negative.")

    layout = plan_layout(sheet, sticker_w, sticker_h,
                         allow_rotation=allow_rotation, depth=depth, align=align)
    per = layout.per_sheet
    sheets = math.ceil(quantity / per)
    last = quantity - (sheets - 1) * per
    spare = sheets * per - quantity
    printed = sheets * per if fill_last_sheet else quantity

    job_util = 100.0 * printed * layout.sticker_area / (
        sheets * sheet.width * sheet.height)
    total_cost = None if sheet_cost is None else sheets * sheet_cost

    return JobPlan(
        layout=layout, quantity=quantity, sheets=sheets,
        last_sheet_count=per if fill_last_sheet else last,
        fill_last_sheet=fill_last_sheet, printed_total=printed,
        spare_slots=0 if fill_last_sheet else spare,
        job_utilization_pct=job_util, waste_pct=100.0 - job_util,
        total_cost=total_cost,
        cost_per_sticker=None if total_cost is None else total_cost / quantity)


# --------------------------------------------------------------------------
# size suggestions
# --------------------------------------------------------------------------

_MIN_ENLARGE_MM = 0.5     # ignore "you can grow by 0.2 mm" noise
_BISECT_ITERATIONS = 40


def _make_size(vary: str, base_w: float, base_h: float, t: float):
    if vary == "both":                     # aspect ratio locked
        return t, base_h * t / base_w
    if vary == "width":
        return t, base_h
    return base_w, t                       # 'height'


def suggest_sizes(sheet: Sheet, sticker_w: float, sticker_h: float,
                  quantity: Optional[int] = None, *, lock_ratio: bool = True,
                  max_change_pct: float = 15.0, step: float = 0.1,
                  min_size: float = 1.0, allow_rotation: bool = True,
                  depth: int = DEFAULT_DEPTH,
                  image_px: Optional[Tuple[int, int]] = None,
                  min_dpi: float = 250.0) -> List[SizeSuggestion]:
    """Find nearby sizes that fit more per sheet / save sheets, and how far the
    sticker can grow without costing anything.

    With a quantity, "better" means fewer sheets; without one, more per sheet.
    Suggestions only; the caller must let the customer decide.
    """
    _validate_sticker(sticker_w, sticker_h)
    base_n = _per_sheet(sheet, sticker_w, sticker_h, allow_rotation, depth)
    if base_n == 0:
        raise LayoutError("The sticker does not fit the printable area.")
    base_sheets = math.ceil(quantity / base_n) if quantity else None

    def metric(vary, t):
        w, h = _make_size(vary, sticker_w, sticker_h, t)
        n = _per_sheet(sheet, w, h, allow_rotation, depth)
        s = math.ceil(quantity / n) if (quantity and n) else None
        return n, s

    def is_better(n, s):
        if quantity:
            return s is not None and s < base_sheets
        return n > base_n

    def is_no_worse(n, s):
        if quantity:
            return s is not None and s <= base_sheets
        return n >= base_n

    def build(kind, vary, base_val, t):
        t = _round_down_2(t)
        w, h = _make_size(vary, sticker_w, sticker_h, t)
        if vary == "both":
            w, h = _round_down_2(w), _round_down_2(h)
        n = _per_sheet(sheet, w, h, allow_rotation, depth)
        s = math.ceil(quantity / n) if (quantity and n) else None
        saved = (base_sheets - s) if (quantity and s is not None) else 0
        dpi = effective_dpi(image_px[0], image_px[1], w, h) if image_px else None
        low = dpi is not None and dpi < min_dpi
        change = t - base_val
        what = {"both": "", "width": " (width)", "height": " (height)"}[vary]

        if kind == "shrink":
            msg = (f"Reduce to {_fmt(w)} x {_fmt(h)} mm ({_fmt(-change)} mm smaller"
                   f"{what}) to fit {n} per sheet")
            msg += (f", saving {saved} sheet{'s' if saved != 1 else ''}."
                    if quantity else f" (now {base_n}).")
        else:
            msg = (f"You can enlarge up to {_fmt(w)} x {_fmt(h)} mm"
                   f"{what} and still fit {n} per sheet")
            msg += (f" ({s} sheet{'s' if s != 1 else ''})." if quantity else ".")
        if low:
            msg += (f" Warning: at this size the artwork prints at about "
                    f"{dpi:.0f} DPI.")
        return SizeSuggestion(kind=kind, sticker_w=w, sticker_h=h,
                              change_mm=change, per_sheet=n, sheets=s,
                              sheets_saved=saved, dpi=dpi, low_resolution=low,
                              message=msg)

    out: List[SizeSuggestion] = []
    modes = ["both"] if lock_ratio else ["width", "height"]

    for vary in modes:
        base_val = sticker_h if vary == "height" else sticker_w
        lo = max(min_size, base_val * (1 - max_change_pct / 100.0))
        hi = base_val * (1 + max_change_pct / 100.0)

        # ---- shrink: largest size that beats the current result ----
        prev, found, i = base_val, None, 1
        while True:
            t = base_val - i * step
            if t < lo - 1e-9:
                break
            n, s = metric(vary, t)
            if is_better(n, s):
                found = (t, prev)
                break
            prev, i = t, i + 1
        if found:
            t_pass, t_fail = found
            for _ in range(_BISECT_ITERATIONS):
                mid = (t_pass + t_fail) / 2
                if is_better(*metric(vary, mid)):
                    t_pass = mid
                else:
                    t_fail = mid
            out.append(build("shrink", vary, base_val, t_pass))

        # ---- enlarge: how far can it grow at no extra cost ----
        t_pass, t_fail, i = base_val, None, 1
        while True:
            t = base_val + i * step
            if t > hi + 1e-9:
                break
            if is_no_worse(*metric(vary, t)):
                t_pass = t
            else:
                t_fail = t
                break
            i += 1
        if t_fail is not None:
            for _ in range(_BISECT_ITERATIONS):
                mid = (t_pass + t_fail) / 2
                if is_no_worse(*metric(vary, mid)):
                    t_pass = mid
                else:
                    t_fail = mid
        if t_pass - base_val >= _MIN_ENLARGE_MM:
            out.append(build("enlarge", vary, base_val, t_pass))

    return out
