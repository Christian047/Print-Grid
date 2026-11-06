"""
multi_engine.py
===============

Several designs, each with its own size and quantity, on standard sheets.
Extends ``layout_engine`` (which is not modified) and returns ONE result type,
``MultiJobPlan``, for every job, including the default single-design job.

Goal: fewest sheets, each as full as possible (people cut with scissors, so any
arrangement is allowed; a gap between stickers is still kept).

How a job is solved
-------------------
1. One design                      -> ``plan_job`` (the tuned grid + rotated strips).
2. Several designs of ONE size     -> the same grid, slots handed out design by
   (e.g. 2 A, 3 B, 5 C at 50x50)      design in reading order. Optimal.
3. Designs of different sizes:
   a. Bulk: any design with at least one full sheet's worth gets dedicated
      full-density sheets (its own grid). Fast, neat, and cannot be beaten.
   b. The remainders (each smaller than one sheet) are packed together with a
      free-rectangle packer (MaxRects), trying several orderings and placement
      rules and keeping the best.
   c. Compared with "each remainder on its own sheet"; the better one wins, so
      the result is never worse than planning every design separately.

``group_by_design=True`` (default) keeps each design's stickers together in the
packing order, which makes sorting after cutting easier. ``False`` also tries
global orderings for the tightest packing.

Same conventions as layout_engine: millimetres, origin top-left, y down,
``Placement.design`` is the index into the designs list, ``rotation`` is 0/90
relative to the DESIGN'S OWN width x height.

Limits: bounding boxes only (no die-cut shapes); no overrun-fill for
multi-design jobs; size suggestions are single-design only.
"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Tuple

try:                                    # normal use, inside the Django app
    from .layout_engine import (
        ENGINE_VERSION, EPS, LayoutError, Placement, Sheet, plan_job,
        plan_layout, _fmt, _r,
    )
except ImportError:                     # run as a plain script / tests
    from layout_engine import (
        ENGINE_VERSION, EPS, LayoutError, Placement, Sheet, plan_job,
        plan_layout, _fmt, _r,
    )

__all__ = ["Design", "SheetPlan", "MultiJobPlan", "plan_multi_job"]

MAX_DESIGNS = 100
HEURISTICS = ("bl", "bssf", "baf", "blsf")     # 'bl' first: gives neat rows
_EFFORT_CANDIDATES = {1: 8, 2: 40, 3: 200}     # max packing attempts per job
_BASE_ITEMS = 400                              # above this, attempts are scaled down
_SHUFFLES = 20                                 # extra random orders in tight mode


# --------------------------------------------------------------------------
# data classes
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Design:
    width: float
    height: float
    quantity: int
    name: str = ""

    def __post_init__(self):
        for v in (self.width, self.height):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise LayoutError("Sticker size must be a number.")
        if self.width <= 0 or self.height <= 0:
            raise LayoutError("Sticker size must be greater than zero.")
        if (isinstance(self.quantity, bool) or not isinstance(self.quantity, int)
                or self.quantity < 1):
            raise LayoutError("Quantity must be a whole number of at least 1.")


@dataclass(frozen=True)
class SheetPlan:
    """One sheet layout, used ``repeat`` times in a row (identical sheets)."""
    first_sheet: int                 # 1-based number of the first sheet it covers
    repeat: int
    kind: str                        # 'grid' | 'packed'
    placements: Tuple[Placement, ...]
    sheet_area: float

    @property
    def last_sheet(self) -> int:
        return self.first_sheet + self.repeat - 1

    @property
    def count(self) -> int:
        return len(self.placements)

    @property
    def utilization_sheet_pct(self) -> float:
        return 100.0 * sum(p.w * p.h for p in self.placements) / self.sheet_area

    def to_dict(self) -> Dict:
        return {
            "first_sheet": self.first_sheet, "repeat": self.repeat,
            "kind": self.kind, "count": self.count,
            "utilization_sheet_pct": round(self.utilization_sheet_pct, 2),
            "placements": [p.to_dict() for p in self.placements],
        }


@dataclass(frozen=True)
class MultiJobPlan:
    sheet: Sheet
    designs: Tuple[Design, ...]
    per_sheet_alone: Tuple[int, ...]     # capacity if the design had a sheet to itself
    sheets: Tuple[SheetPlan, ...]
    strategy: str
    sheet_count: int
    placed: Tuple[int, ...]              # stickers placed, per design
    total_stickers: int
    job_utilization_pct: float
    waste_pct: float
    total_cost: Optional[float] = None
    cost_per_sticker: Optional[float] = None

    def placements_for_sheet(self, sheet_no: int) -> Tuple[Placement, ...]:
        if not 1 <= sheet_no <= self.sheet_count:
            raise LayoutError(
                f"Sheet {sheet_no} does not exist (job has {self.sheet_count}).")
        for sp in self.sheets:
            if sp.first_sheet <= sheet_no <= sp.last_sheet:
                return sp.placements
        raise LayoutError("Sheet not found.")           # unreachable

    def design_name(self, index: int) -> str:
        return self.designs[index].name or f"Design {index + 1}"

    def to_dict(self) -> Dict:
        return {
            "format": "sheets-v1",
            "engine_version": ENGINE_VERSION,
            "sheet": self.sheet.to_dict(),
            "designs": [
                {"index": i, "name": self.design_name(i), "width": _r(d.width),
                 "height": _r(d.height), "quantity": d.quantity,
                 "per_sheet_alone": self.per_sheet_alone[i], "placed": self.placed[i]}
                for i, d in enumerate(self.designs)],
            "strategy": self.strategy,
            "sheet_count": self.sheet_count,
            "total_stickers": self.total_stickers,
            "job_utilization_pct": round(self.job_utilization_pct, 2),
            "waste_pct": round(self.waste_pct, 2),
            "total_cost": None if self.total_cost is None else round(self.total_cost, 2),
            "cost_per_sticker": (None if self.cost_per_sticker is None
                                 else round(self.cost_per_sticker, 4)),
            "sheets": [sp.to_dict() for sp in self.sheets],
        }


# --------------------------------------------------------------------------
# MaxRects free-rectangle packer
# --------------------------------------------------------------------------
# Gaps are handled by inflation: an item of w x h is packed as (w+gx) x (h+gy)
# into a bin of (printable_w+gx) x (printable_h+gy). Two inflated boxes that
# do not overlap are at least gx apart horizontally OR gy apart vertically,
# which is exactly the minimum-gap rule the rest of the app uses.

def _prune(free):
    out = []
    for i, (ax, ay, aw, ah) in enumerate(free):
        inside = False
        for j, (bx, by, bw, bh) in enumerate(free):
            if i == j:
                continue
            if (ax >= bx - EPS and ay >= by - EPS and
                    ax + aw <= bx + bw + EPS and ay + ah <= by + bh + EPS):
                b_in_a = (bx >= ax - EPS and by >= ay - EPS and
                          bx + bw <= ax + aw + EPS and by + bh <= ay + ah + EPS)
                if not b_in_a or j < i:      # identical twins: keep the first
                    inside = True
                    break
        if not inside:
            out.append((ax, ay, aw, ah))
    return out


class _MaxRects:
    def __init__(self, width: float, height: float):
        self.free = [(0.0, 0.0, width, height)]

    def find(self, w, h, gx, gy, heur, allow_rot):
        """Best spot for a w x h item. Returns (score, x, y, iw, ih, rotated)."""
        orients = [(w + gx, h + gy, False)]
        if allow_rot and abs(w - h) > EPS:
            orients.append((h + gx, w + gy, True))
        best = None
        for (fx, fy, fw, fh) in self.free:
            for (iw, ih, rot) in orients:
                if iw > fw + EPS or ih > fh + EPS:
                    continue
                lh, lv = fw - iw, fh - ih
                if heur == "bl":
                    score = (fy + ih, fx)
                elif heur == "bssf":
                    score = (min(lh, lv), max(lh, lv))
                elif heur == "blsf":
                    score = (max(lh, lv), min(lh, lv))
                else:                                   # 'baf'
                    score = (fw * fh - iw * ih, min(lh, lv))
                if best is None or score < best[0]:
                    best = (score, fx, fy, iw, ih, rot)
        return best

    def place(self, x, y, w, h):
        new = []
        for (fx, fy, fw, fh) in self.free:
            if x >= fx + fw - EPS or x + w <= fx + EPS or y >= fy + fh - EPS or y + h <= fy + EPS:
                new.append((fx, fy, fw, fh))
                continue
            if x > fx + EPS:
                new.append((fx, fy, x - fx, fh))
            if x + w < fx + fw - EPS:
                new.append((x + w, fy, fx + fw - (x + w), fh))
            if y > fy + EPS:
                new.append((fx, fy, fw, y - fy))
            if y + h < fy + fh - EPS:
                new.append((fx, y + h, fw, fy + fh - (y + h)))
        self.free = _prune(new)


def _pack_items(sheet: Sheet, items, heur: str, allow_rot: bool):
    """Pack items (design, w, h) onto as many sheets as needed, one sheet at a
    time, in the given order. Returns a list of sheets; each sheet is a list of
    (design, x, y, w, h, rotated) with x/y relative to the printable area."""
    pw, ph = sheet.printable_width, sheet.printable_height
    gx, gy = sheet.gap_x, sheet.gap_y
    remaining = list(items)
    sheets = []
    while remaining:
        bin_ = _MaxRects(pw + gx, ph + gy)
        placed, left, failed = [], [], set()
        for it in remaining:
            d, w, h = it
            if (w, h) in failed:                 # free space only shrinks
                left.append(it)
                continue
            found = bin_.find(w, h, gx, gy, heur, allow_rot)
            if found is None:
                failed.add((w, h))
                left.append(it)
                continue
            _, x, y, iw, ih, rot = found
            bin_.place(x, y, iw, ih)
            placed.append((d, x, y, iw - gx, ih - gy, rot))
        if not placed:
            raise LayoutError("A sticker does not fit on an empty sheet.")
        sheets.append(placed)
        remaining = left
    return sheets


def _candidate_orders(rem, grouped: bool):
    """Yield distinct item orderings. ``rem`` = [(design, w, h, count), ...]."""
    n = len(rem)
    seen = set()

    def emit(items):
        key = tuple(d for d, _, _ in items)
        if key in seen:
            return None
        seen.add(key)
        return items

    def by_design(order):
        return [(d, w, h) for k in order for (d, w, h, c) in [rem[k]] for _ in range(c)]

    idx = list(range(n))
    keys = [
        lambda k: -(rem[k][1] * rem[k][2]),               # largest area first
        lambda k: -max(rem[k][1], rem[k][2]),             # longest side first
        lambda k: -rem[k][1],                             # widest first
        lambda k: -rem[k][2],                             # tallest first
        lambda k: k,                                      # as entered
    ]
    orders = [sorted(idx, key=kf) for kf in keys]
    if n <= 4:
        orders += [list(p) for p in itertools.permutations(idx)]
    for order in orders:
        items = emit(by_design(order))
        if items is not None:
            yield items

    if not grouped:
        flat = by_design(idx)
        for kf in (lambda t: -(t[1] * t[2]), lambda t: -max(t[1], t[2]),
                   lambda t: -t[1], lambda t: -t[2]):
            items = emit(sorted(flat, key=kf))
            if items is not None:
                yield items
        rng = random.Random(20240921)                     # fixed seed: repeatable
        for _ in range(_SHUFFLES):
            items = flat[:]
            rng.shuffle(items)
            items = emit(items)
            if items is not None:
                yield items


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _rotation_for(design: Design, p: Placement) -> int:
    if abs(design.width - design.height) <= EPS:
        return 0
    return 0 if (abs(p.w - design.width) <= EPS and abs(p.h - design.height) <= EPS) else 90


def _same_size(designs: Sequence[Design], allow_rotation: bool) -> bool:
    w0, h0 = designs[0].width, designs[0].height
    for d in designs[1:]:
        exact = abs(d.width - w0) <= EPS and abs(d.height - h0) <= EPS
        swapped = abs(d.width - h0) <= EPS and abs(d.height - w0) <= EPS
        if not (exact or (swapped and allow_rotation)):
            return False
    return True


def _center(placements: List[Placement], sheet: Sheet) -> List[Placement]:
    min_x, max_x = min(p.x for p in placements), max(p.right for p in placements)
    min_y, max_y = min(p.y for p in placements), max(p.bottom for p in placements)
    dx = sheet.margin_left + (sheet.printable_width - (max_x - min_x)) / 2 - min_x
    dy = sheet.margin_top + (sheet.printable_height - (max_y - min_y)) / 2 - min_y
    return [replace(p, x=p.x + dx, y=p.y + dy) for p in placements]


def _reading_order(placements) -> Tuple[Placement, ...]:
    return tuple(sorted(placements, key=lambda p: (round(p.y, 3), round(p.x, 3))))


class _Assembler:
    """Collects sheets in order, merging consecutive identical ones."""
    def __init__(self, sheet: Sheet):
        self.sheet_area = sheet.width * sheet.height
        self.items: List[list] = []          # [kind, placements, repeat]

    def add(self, kind: str, placements: Tuple[Placement, ...], repeat: int = 1):
        if repeat < 1:
            return
        if self.items and self.items[-1][0] == kind and self.items[-1][1] == placements:
            self.items[-1][2] += repeat
        else:
            self.items.append([kind, placements, repeat])

    def build(self) -> Tuple[SheetPlan, ...]:
        out, n = [], 1
        for kind, pl, rep in self.items:
            out.append(SheetPlan(n, rep, kind, pl, self.sheet_area))
            n += rep
        return tuple(out)


def _finish(sheet, designs, per_alone, asm, strategy, expected, sheet_cost):
    sheets = asm.build()
    sheet_count = sum(sp.repeat for sp in sheets)
    placed = [0] * len(designs)
    used_area = 0.0
    for sp in sheets:
        for p in sp.placements:
            placed[p.design] += sp.repeat
            used_area += p.w * p.h * sp.repeat
    if tuple(placed) != tuple(expected):                 # internal safety net
        raise RuntimeError(f"Planner bug: placed {placed}, expected {list(expected)}")
    util = 100.0 * used_area / (sheet_count * sheet.width * sheet.height)
    total_cost = None if sheet_cost is None else sheet_count * sheet_cost
    total = sum(placed)
    return MultiJobPlan(
        sheet=sheet, designs=tuple(designs), per_sheet_alone=tuple(per_alone),
        sheets=sheets, strategy=strategy, sheet_count=sheet_count,
        placed=tuple(placed), total_stickers=total, job_utilization_pct=util,
        waste_pct=100.0 - util, total_cost=total_cost,
        cost_per_sticker=None if total_cost is None else total_cost / total)


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

def plan_multi_job(sheet: Sheet, designs: Sequence[Design], *,
                   allow_rotation: bool = True, group_by_design: bool = True,
                   align: str = "top-left", effort: int = 2,
                   sheet_cost: Optional[float] = None,
                   fill_last_sheet: bool = False) -> MultiJobPlan:
    """Plan a whole job. Works for one design or many.

    effort: 1 = quick, 2 = default, 3 = try harder (more packing attempts).
    fill_last_sheet: single-design jobs only (prints spare slots as overrun).
    """
    designs = tuple(designs)
    if not designs:
        raise LayoutError("Add at least one design.")
    if len(designs) > MAX_DESIGNS:
        raise LayoutError(f"A job can have at most {MAX_DESIGNS} designs.")
    if not all(isinstance(d, Design) for d in designs):
        raise LayoutError("designs must be Design objects.")
    if align not in ("top-left", "center"):
        raise LayoutError("align must be 'top-left' or 'center'.")
    if effort not in _EFFORT_CANDIDATES:
        raise LayoutError("effort must be 1, 2 or 3.")
    if fill_last_sheet and len(designs) > 1:
        raise LayoutError("Filling the last sheet is only available for single-design jobs.")
    if sheet_cost is not None and sheet_cost < 0:
        raise LayoutError("Sheet cost cannot be negative.")

    def label(i):
        return designs[i].name or f"Design {i + 1}"

    # capacity of each design alone on a sheet (also validates that it fits)
    layouts = []
    for i, d in enumerate(designs):
        try:
            layouts.append(plan_layout(sheet, d.width, d.height,
                                       allow_rotation=allow_rotation, align=align))
        except LayoutError as e:
            raise LayoutError(f"{label(i)}: {e}") from None
    per_alone = [lay.per_sheet for lay in layouts]
    quantities = [d.quantity for d in designs]
    asm = _Assembler(sheet)

    # ---- 1. single design ------------------------------------------------
    if len(designs) == 1:
        d = designs[0]
        job = plan_job(sheet, d.width, d.height, d.quantity,
                       allow_rotation=allow_rotation, align=align,
                       fill_last_sheet=fill_last_sheet)
        per = job.layout.per_sheet
        full = job.sheets if job.last_sheet_count == per else job.sheets - 1
        asm.add("grid", job.layout.placements, full)
        if full < job.sheets:
            asm.add("grid", job.placements_for_sheet(job.sheets), 1)
        expected = [job.printed_total]
        return _finish(sheet, designs, per_alone, asm, "single design: grid",
                       expected, sheet_cost)

    # ---- 2. several designs, all one size --------------------------------
    if _same_size(designs, allow_rotation):
        lay = layouts[0]
        per = lay.per_sheet
        seq = [i for i, q in enumerate(quantities) for _ in range(q)]
        for start in range(0, len(seq), per):
            chunk = seq[start:start + per]
            pl = tuple(replace(p, design=di, rotation=_rotation_for(designs[di], p))
                       for p, di in zip(lay.placements, chunk))
            asm.add("grid", pl, 1)
        return _finish(sheet, designs, per_alone, asm,
                       "same-size designs: grid, slots by design", quantities, sheet_cost)

    # ---- 3. different sizes: bulk sheets + packed remainders -------------
    remainders = []
    for i, d in enumerate(designs):
        full, rem = divmod(d.quantity, per_alone[i])
        if full:
            pl = tuple(replace(p, design=i) for p in layouts[i].placements)
            asm.add("grid", pl, full)
        if rem:
            remainders.append((i, d.width, d.height, rem))
    bulk_note = "bulk sheets" if asm.items else "no bulk sheets"

    if not remainders:
        return _finish(sheet, designs, per_alone, asm,
                       f"different sizes: {bulk_note} only", quantities, sheet_cost)

    def rem_key(placed_sheets):
        n = len(placed_sheets)
        last_area = sum(w * h for (_, _, _, w, h, _) in placed_sheets[-1])
        rows = len({round(t[2], 1) for s in placed_sheets for t in s})
        return (n, round(last_area, 3), rows)

    n_items = sum(c for (_, _, _, c) in remainders)
    budget = max(2, int(_EFFORT_CANDIDATES[effort] * min(1.0, _BASE_ITEMS / n_items)))
    pw, ph = sheet.printable_width, sheet.printable_height
    lower = math.ceil(sum(w * h * c for (_, w, h, c) in remainders) / (pw * ph) - 1e-9)

    best, best_key, best_label, tried = None, None, "", 0
    done = False
    for items in _candidate_orders(remainders, group_by_design):
        for heur in HEURISTICS:
            if tried >= budget:
                done = True
                break
            packed = _pack_items(sheet, items, heur, allow_rotation)
            tried += 1
            key = rem_key(packed)
            if best_key is None or key < best_key:
                best, best_key, best_label = packed, key, f"MaxRects/{heur}"
        if done or (best_key[0] <= lower and tried >= min(budget, 8)):
            break

    # candidate: every remainder on its own sheet (guarantees "never worse than
    # planning each design separately")
    separate = []
    for (i, w, h, c) in remainders:
        first = layouts[i].placements[:c]
        separate.append([(i, p.x - sheet.margin_left, p.y - sheet.margin_top,
                          p.w, p.h, p.rotation == 90) for p in first])
    sep_key = rem_key(separate)
    if sep_key < best_key:
        best, best_label = separate, "one sheet per design"

    for placed_sheet in best:
        pl = [Placement(sheet.margin_left + x, sheet.margin_top + y, w, h,
                        90 if rot else 0, d) for (d, x, y, w, h, rot) in placed_sheet]
        if align == "center":
            pl = _center(pl, sheet)
        asm.add("packed", _reading_order(pl), 1)

    return _finish(
        sheet, designs, per_alone, asm,
        f"different sizes: {bulk_note} + packed remainders ({best_label}, "
        f"{'grouped' if group_by_design else 'tight'}, {tried} attempts)",
        quantities, sheet_cost)
