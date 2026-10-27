import itertools
import unittest

from ariadne2.desk import layout, wires


def _segments(poly):
    return list(zip(poly, poly[1:]))


def _cross(s, t):
    # Proper intersection of two segments (shared endpoints don't count).
    (a, b), (c, d) = s, t
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (v > 1e-6) - (v < -1e-6)
    return (orient(a, b, c) * orient(a, b, d) < 0 and
            orient(c, d, a) * orient(c, d, b) < 0)


class RouteTest(unittest.TestCase):
    def setUp(self):
        rects = dict(layout.DEFAULT)
        self.core = rects.pop("core")
        self.targets = rects
        self.routes = wires.route(self.core, self.targets)

    def test_every_widget_gets_a_wire_from_the_core(self):
        self.assertEqual(set(self.routes), set(self.targets))
        bottom = self.core[1] + self.core[3]
        for poly in self.routes.values():
            self.assertAlmostEqual(poly[0][1], bottom)

    def test_wires_end_on_their_widget_edge(self):
        for name, poly in self.routes.items():
            x, y, w, h = self.targets[name]
            ex, ey = poly[-1]
            on_edge = (abs(ex - x) < 1 or abs(ex - x - w) < 1 or
                       abs(ey - y) < 1 or abs(ey - y - h) < 1)
            self.assertTrue(on_edge, name)

    def test_default_layout_wires_never_cross(self):
        for (n1, p1), (n2, p2) in itertools.combinations(self.routes.items(), 2):
            for s in _segments(p1):
                for t in _segments(p2):
                    self.assertFalse(_cross(s, t), f"{n1} crosses {n2}")

    def test_panel_fitted_layout_wires_never_cross(self):
        rects = layout.fit(layout.DEFAULT, (0, 0, 3440, 1366), scale=True)
        core = rects.pop("core")
        routes = wires.route(core, rects)
        for (n1, p1), (n2, p2) in itertools.combinations(routes.items(), 2):
            for s in _segments(p1):
                for t in _segments(p2):
                    self.assertFalse(_cross(s, t), f"{n1} crosses {n2}")

    def test_corners_are_45_degrees_or_straight(self):
        for poly in self.routes.values():
            for (a, b) in _segments(poly):
                dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
                self.assertTrue(dx < 0.01 or dy < 0.01 or abs(dx - dy) < 0.01)

    def test_segment_of_polyline(self):
        poly = [(0, 0), (10, 0), (10, 10)]
        self.assertEqual(wires.length(poly), 20)
        self.assertEqual(wires.segment(poly, 5, 15), [(5, 0), (10, 0), (10, 5)])


class FitTest(unittest.TestCase):
    def test_scaled_defaults_stay_inside_area(self):
        area = (0, 0, 3440, 1366)
        for x, y, w, h in layout.fit(layout.DEFAULT, area, scale=True).values():
            self.assertLessEqual(y + h, 1366)
            self.assertGreaterEqual(y, 0)

    def test_unscaled_rect_is_pushed_out_from_under_a_panel(self):
        got = layout.fit({"a": (2680, 1300, 736, 336)}, (0, 0, 3440, 1392))
        self.assertEqual(got["a"][1] + got["a"][3], 1392)


if __name__ == "__main__":
    unittest.main()
