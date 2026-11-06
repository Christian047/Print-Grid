"""Tests for layout_engine.py. No Django needed:  python -m unittest test_layout_engine -v"""
import json
import random
import unittest

from layout_engine import (
    EPS, LayoutError, Sheet, effective_dpi, plan_job, plan_layout, suggest_sizes,
    _count_along, _cells, _search,
)


def assert_valid(test, layout, tol=1e-6):
    """Every placement is inside the printable area, and no two placements
    overlap or sit closer than the required gap."""
    s = layout.sheet
    left, top = s.margin_left, s.margin_top
    right, bottom = s.width - s.margin_right, s.height - s.margin_bottom
    ps = layout.placements
    for p in ps:
        test.assertGreaterEqual(p.x, left - tol)
        test.assertGreaterEqual(p.y, top - tol)
        test.assertLessEqual(p.right, right + tol)
        test.assertLessEqual(p.bottom, bottom + tol)
        test.assertIn((round(p.w, 6), round(p.h, 6)),
                      {(round(layout.sticker_w, 6), round(layout.sticker_h, 6)),
                       (round(layout.sticker_h, 6), round(layout.sticker_w, 6))})
    for i in range(len(ps)):
        for j in range(i + 1, len(ps)):
            a, b = ps[i], ps[j]
            apart = (a.right + s.gap_x <= b.x + tol or b.right + s.gap_x <= a.x + tol or
                     a.bottom + s.gap_y <= b.y + tol or b.bottom + s.gap_y <= a.y + tol)
            test.assertTrue(apart, f"placements {i} and {j} overlap or violate gap")


class FitMath(unittest.TestCase):
    def test_last_item_needs_no_gap(self):
        # 4 x 45 + 3 x 2 = 186 -> exactly 4 fit. Old formula gave 3.
        self.assertEqual(_count_along(186, 45, 2), 4)
        self.assertEqual(int(186 // (45 + 2)), 3)

    def test_float_noise_does_not_lose_a_sticker(self):
        self.assertEqual(int(0.3 // 0.1), 2)          # plain float floor is wrong
        self.assertEqual(_count_along(0.3, 0.1, 0), 3)
        self.assertEqual(_count_along(190.5, 63.5, 0), 3)

    def test_too_big_is_zero(self):
        self.assertEqual(_count_along(50, 50.5, 2), 0)
        self.assertEqual(_count_along(-5, 10, 0), 0)

    def test_exact_fit_layout(self):
        sheet = Sheet(206, 100, 10, 10, 10, 10, 2, 2)      # printable 186 x 80
        lay = plan_layout(sheet, 45, 30)
        assert_valid(self, lay)
        first_row = [p for p in lay.placements if abs(p.y - lay.placements[0].y) < 1e-9]
        self.assertGreaterEqual(len(first_row), 4)         # 4 x 45 + 3 x 2 = 186
        self.assertGreaterEqual(lay.per_sheet, 8)          # at least 4 cols x 2 rows


class Rotation(unittest.TestCase):
    def test_rotation_chosen_when_better(self):
        # printable 100 x 30. Upright 30x10: 3x3=9. Rotated 10x30: 10x1=10.
        lay = plan_layout(Sheet(100, 30), 30, 10)
        self.assertEqual(lay.per_sheet, 10)
        self.assertEqual(lay.layout_kind, "grid-rotated")
        self.assertTrue(all(p.rotation == 90 for p in lay.placements))
        assert_valid(self, lay)

    def test_rotation_can_be_disabled(self):
        lay = plan_layout(Sheet(100, 30), 30, 10, allow_rotation=False)
        self.assertEqual(lay.per_sheet, 9)
        self.assertEqual(lay.layout_kind, "grid")

    def test_sticker_that_only_fits_rotated(self):
        lay = plan_layout(Sheet(50, 300), 200, 20)
        self.assertEqual(lay.layout_kind, "grid-rotated")

    def test_mixed_layout_beats_pure_grids(self):
        # found by brute force: pure grids give 8, mixed gives 10
        sheet = Sheet(100, 277, gap_x=2, gap_y=2)
        lay = plan_layout(sheet, 58, 38)
        self.assertEqual(lay.per_sheet, 10)
        self.assertEqual(lay.layout_kind, "mixed")
        assert_valid(self, lay)
        pure = max(_search(100, 277, [c], 2, 2, 4)[0] for c in _cells(58, 38, True))
        self.assertEqual(pure, 8)

    def test_never_worse_than_pure_grid(self):
        rng = random.Random(7)
        for _ in range(300):
            sheet = Sheet(rng.choice([100, 210, 297, 320]), rng.choice([150, 297, 450]),
                          gap_x=rng.choice([0, 2]), gap_y=rng.choice([0, 2]))
            w, h = rng.randint(8, 70), rng.randint(8, 70)
            cells = _cells(w, h, True)
            pure = max(_search(sheet.width, sheet.height, [c], sheet.gap_x, sheet.gap_y, 4)[0]
                       for c in cells)
            try:
                got = plan_layout(sheet, w, h).per_sheet
            except LayoutError:
                self.assertEqual(pure, 0)
                continue
            self.assertGreaterEqual(got, pure)


class Property(unittest.TestCase):
    def test_random_layouts_are_always_production_safe(self):
        rng = random.Random(42)
        checked = 0
        for _ in range(400):
            sheet = Sheet(
                rng.choice([100, 148, 210, 297, 320, 450]),
                rng.choice([100, 210, 297, 420, 480]),
                rng.choice([0, 3, 10]), rng.choice([0, 3, 10]),
                rng.choice([0, 3, 10]), rng.choice([0, 3, 10]),
                rng.choice([0, 1.5, 2, 5]), rng.choice([0, 1.5, 2, 5]))
            w = round(rng.uniform(8, 90), 2)
            h = round(rng.uniform(8, 90), 2)
            for align in ("top-left", "center"):
                try:
                    lay = plan_layout(sheet, w, h, align=align)
                except LayoutError:
                    continue
                assert_valid(self, lay)
                checked += 1
        self.assertGreater(checked, 300)

    def test_centering_keeps_layout_valid_and_centered(self):
        sheet = Sheet(210, 297, 10, 10, 10, 10, 2, 2)
        lay = plan_layout(sheet, 50, 50, align="center")
        assert_valid(self, lay)
        left = min(p.x for p in lay.placements) - sheet.margin_left
        right = (sheet.width - sheet.margin_right) - max(p.right for p in lay.placements)
        self.assertAlmostEqual(left, right, places=6)

    def test_reading_order(self):
        lay = plan_layout(Sheet(100, 100), 20, 20)
        keys = [(round(p.y, 3), round(p.x, 3)) for p in lay.placements]
        self.assertEqual(keys, sorted(keys))


class Jobs(unittest.TestCase):
    # printable 120 x 70, 10 mm squares, no gap -> 12 x 7 = 84 per sheet
    sheet = Sheet(120, 70)

    def test_quantity_to_sheets_with_partial_last_sheet(self):
        job = plan_job(self.sheet, 10, 10, 500)
        self.assertEqual(job.layout.per_sheet, 84)
        self.assertEqual(job.sheets, 6)
        self.assertEqual(job.last_sheet_count, 80)
        self.assertEqual(job.spare_slots, 4)
        self.assertEqual(job.printed_total, 500)
        self.assertAlmostEqual(job.job_utilization_pct, 500 * 100 / (6 * 8400) * 100, places=6)
        self.assertAlmostEqual(job.waste_pct, 100 - job.job_utilization_pct, places=9)

    def test_partial_sheet_uses_first_n_placements(self):
        job = plan_job(self.sheet, 10, 10, 500)
        self.assertEqual(len(job.placements_for_sheet(1)), 84)
        self.assertEqual(len(job.placements_for_sheet(6)), 80)
        self.assertEqual(job.placements_for_sheet(6), job.layout.placements[:80])
        with self.assertRaises(LayoutError):
            job.placements_for_sheet(7)

    def test_fill_last_sheet_prints_overrun(self):
        job = plan_job(self.sheet, 10, 10, 500, fill_last_sheet=True)
        self.assertEqual(job.printed_total, 504)
        self.assertEqual(job.last_sheet_count, 84)
        self.assertEqual(len(job.placements_for_sheet(6)), 84)

    def test_exact_multiple_has_full_last_sheet(self):
        job = plan_job(self.sheet, 10, 10, 168)
        self.assertEqual((job.sheets, job.last_sheet_count, job.spare_slots), (2, 84, 0))

    def test_single_sticker(self):
        job = plan_job(self.sheet, 10, 10, 1)
        self.assertEqual((job.sheets, job.last_sheet_count), (1, 1))

    def test_cost(self):
        job = plan_job(self.sheet, 10, 10, 500, sheet_cost=2.5)
        self.assertEqual(job.total_cost, 15.0)
        self.assertAlmostEqual(job.cost_per_sticker, 0.03)

    def test_json_serialisable(self):
        d = plan_job(self.sheet, 10, 10, 500, sheet_cost=2.5).to_dict()
        json.dumps(d)                                   # must not raise
        self.assertEqual(d["placements"][0]["design"], 0)
        self.assertEqual(d["engine_version"], 1)


class Validation(unittest.TestCase):
    def test_bad_inputs_raise_readable_errors(self):
        with self.assertRaises(LayoutError):
            Sheet(0, 100)
        with self.assertRaises(LayoutError):
            Sheet(100, 100, margin_left=-1)
        with self.assertRaises(LayoutError) as cm:
            Sheet(100, 100, 50, 0, 50, 0)
        self.assertIn("Margins are too large", str(cm.exception))
        with self.assertRaises(LayoutError):
            Sheet(float("nan"), 100)
        with self.assertRaises(LayoutError):
            plan_layout(Sheet(100, 100), 0, 10)
        for bad in (0, -3, 2.5, True, "5"):
            with self.assertRaises(LayoutError):
                plan_job(Sheet(100, 100), 10, 10, bad)

    def test_too_large_message_names_the_sizes(self):
        with self.assertRaises(LayoutError) as cm:
            plan_layout(Sheet(210, 297, 10, 10, 10, 10), 300, 250)
        self.assertIn("300 x 250", str(cm.exception))
        self.assertIn("190 x 277", str(cm.exception))


class Suggestions(unittest.TestCase):
    sheet = Sheet(100, 100)

    def test_shrink_to_next_threshold(self):
        # 26 mm -> 3x3 = 9. At 25 mm -> 4x4 = 16.
        out = suggest_sizes(self.sheet, 26, 26)
        shrink = [s for s in out if s.kind == "shrink"]
        self.assertEqual(len(shrink), 1)
        self.assertAlmostEqual(shrink[0].sticker_w, 25.0, places=2)
        self.assertEqual(shrink[0].per_sheet, 16)
        # the suggested size really does fit that many
        self.assertEqual(plan_layout(self.sheet, shrink[0].sticker_w,
                                     shrink[0].sticker_h).per_sheet, 16)

    def test_enlarge_headroom(self):
        # 30 mm -> 3x3. Up to 33.33 mm still 3x3.
        out = suggest_sizes(self.sheet, 30, 30)
        enlarge = [s for s in out if s.kind == "enlarge"]
        self.assertEqual(len(enlarge), 1)
        self.assertAlmostEqual(enlarge[0].sticker_w, 33.33, places=2)
        self.assertEqual(enlarge[0].per_sheet, 9)
        self.assertEqual(plan_layout(self.sheet, 33.33, 33.33).per_sheet, 9)

    def test_quantity_makes_suggestions_about_sheets(self):
        # 100 stickers at 26 mm: 9/sheet -> 12 sheets. At 25 mm: 16/sheet -> 7 sheets.
        out = suggest_sizes(self.sheet, 26, 26, quantity=100)
        shrink = next(s for s in out if s.kind == "shrink")
        self.assertEqual(shrink.sheets, 7)
        self.assertEqual(shrink.sheets_saved, 5)
        self.assertIn("saving 5 sheets", shrink.message)

    def test_no_suggestion_outside_the_allowed_range(self):
        # 33 mm -> 9. Next threshold is 25 mm (-24%), beyond the 15% default.
        out = suggest_sizes(self.sheet, 33, 33)
        self.assertFalse([s for s in out if s.kind == "shrink"])

    def test_low_resolution_warning(self):
        # 600 px wide artwork enlarged to 33.33 mm = ~457 DPI: fine.
        # 200 px wide artwork enlarged to 33.33 mm = ~152 DPI: warn.
        ok = suggest_sizes(self.sheet, 30, 30, image_px=(600, 600))
        bad = suggest_sizes(self.sheet, 30, 30, image_px=(200, 200))
        self.assertFalse(any(s.low_resolution for s in ok))
        self.assertTrue(any(s.low_resolution and "DPI" in s.message for s in bad))

    def test_unlocked_ratio_suggests_per_dimension(self):
        out = suggest_sizes(Sheet(100, 100), 26, 26, lock_ratio=False)
        shrinks = [s for s in out if s.kind == "shrink"]
        self.assertEqual(len(shrinks), 2)
        self.assertTrue(any(s.sticker_w < 26 and s.sticker_h == 26 for s in shrinks))
        self.assertTrue(any(s.sticker_h < 26 and s.sticker_w == 26 for s in shrinks))

    def test_suggestions_never_lie(self):
        rng = random.Random(3)
        for _ in range(60):
            sheet = Sheet(rng.choice([150, 210, 320]), rng.choice([200, 297, 450]),
                          5, 5, 5, 5, rng.choice([0, 2]), rng.choice([0, 2]))
            w, h = round(rng.uniform(15, 80), 1), round(rng.uniform(15, 80), 1)
            q = rng.choice([None, 50, 500])
            try:
                out = suggest_sizes(sheet, w, h, q)
            except LayoutError:
                continue
            base = plan_layout(sheet, w, h).per_sheet
            for s in out:
                real = plan_layout(sheet, s.sticker_w, s.sticker_h).per_sheet
                self.assertEqual(real, s.per_sheet)
                if s.kind == "shrink" and q is None:
                    self.assertGreater(real, base)
                if s.kind == "enlarge" and q is None:
                    self.assertGreaterEqual(real, base)


class Dpi(unittest.TestCase):
    def test_effective_dpi(self):
        self.assertAlmostEqual(effective_dpi(300, 300, 25.4, 25.4), 300)
        self.assertAlmostEqual(effective_dpi(600, 300, 25.4, 25.4), 300)   # weakest axis
        with self.assertRaises(LayoutError):
            effective_dpi(300, 300, 0, 10)


if __name__ == "__main__":
    unittest.main()
