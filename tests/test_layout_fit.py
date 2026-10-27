import unittest

from ariadne2.desk import layout


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
