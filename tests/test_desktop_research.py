from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from private_quant_lab.trading.desktop_research import (
    DesktopResearchError, PyAutoGUIDesktop, load_reference, run_step, validate_reference,
)


def reference(name):
    return {"name": name, "screen_size": [800, 600], "region": [100, 100, 20, 20]}


class FakeDesktop:
    def __init__(self):
        self.clicks = []
        self.targets = [(110, 110)]
        self.destination_before = []
        self.destination_after = [(300, 300)]
        self.guard = [(120, 120)]

    def locate(self, value):
        if value["name"] == "export_button":
            return self.targets
        if value["name"] == "holdings_view":
            return self.guard
        return self.destination_after if self.clicks else self.destination_before

    def click(self, point):
        self.clicks.append(point)


class DesktopStepTests(unittest.TestCase):
    def setUp(self):
        self.desktop = FakeDesktop()

    def run_step(self, **kwargs):
        return run_step(self.desktop, reference("export_button"), reference("export_dialog"),
                        reference("holdings_view"), **kwargs)

    def test_default_preview_never_clicks_or_confirms(self):
        result = self.run_step(confirm=lambda *args: self.fail("unexpected confirmation"))
        self.assertEqual(result["status"], "preview")
        self.assertEqual(self.desktop.clicks, [])

    def test_single_click_and_postcondition(self):
        result = self.run_step(execute=True, confirm=lambda *args: True)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(self.desktop.clicks), 1)

    def test_missing_and_ambiguous_target(self):
        for matches in ([], [(1, 1), (2, 2)]):
            self.desktop.targets = matches
            with self.assertRaises(DesktopResearchError):
                self.run_step(execute=True, confirm=lambda *args: True)
        self.assertFalse(self.desktop.clicks)

    def test_missing_guard_or_wrong_page(self):
        self.desktop.guard = []
        with self.assertRaises(DesktopResearchError):
            self.run_step()
        with self.assertRaises(DesktopResearchError):
            run_step(self.desktop, reference("export_button"), reference("export_dialog"))
        self.assertFalse(self.desktop.clicks)

    def test_no_confirmation_no_click(self):
        for confirm in (None, lambda *args: False):
            with self.assertRaises(DesktopResearchError):
                self.run_step(execute=True, confirm=confirm)
        self.assertFalse(self.desktop.clicks)

    def test_movement_during_confirmation_blocks_click(self):
        def confirm(*args):
            self.desktop.targets = [(111, 110)]
            return True
        with self.assertRaises(DesktopResearchError):
            self.run_step(execute=True, confirm=confirm)
        self.assertFalse(self.desktop.clicks)

    def test_already_at_destination_no_click(self):
        self.desktop.destination_before = [(300, 300)]
        with self.assertRaises(DesktopResearchError):
            self.run_step(execute=True, confirm=lambda *args: True)
        self.assertFalse(self.desktop.clicks)

    def test_timeout_does_not_repeat_click(self):
        self.desktop.destination_after = []
        ticks = iter([0, 0, 2])
        with self.assertRaisesRegex(DesktopResearchError, "clicked once"):
            self.run_step(execute=True, confirm=lambda *args: True, timeout=1,
                          clock=lambda: next(ticks), sleep=lambda _: None)
        self.assertEqual(len(self.desktop.clicks), 1)

    def test_ambiguous_postcondition_stops(self):
        self.desktop.destination_after = [(1, 1), (2, 2)]
        with self.assertRaisesRegex(DesktopResearchError, "ambiguous"):
            self.run_step(execute=True, confirm=lambda *args: True)
        self.assertEqual(len(self.desktop.clicks), 1)

    def test_rejects_unknown_actions_and_invalid_coordinates(self):
        for name in ("buy", "sell", "cancel_order", "save", "../export_button"):
            with self.assertRaises(DesktopResearchError):
                validate_reference(reference(name))
        for region in ([0, 0, 900, 20], [-1, 0, 20, 20], [0, 0, True, 10]):
            with self.assertRaises(DesktopResearchError):
                validate_reference(dict(reference("holdings_tab"), region=region))
        with self.assertRaises(DesktopResearchError):
            run_step(self.desktop, reference("holdings_view"), reference("export_dialog"))


class DesktopImageTests(unittest.TestCase):
    def setUp(self):
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            self.skipTest("install desktop-research extra for synthetic image tests")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.desktop = PyAutoGUIDesktop.__new__(PyAutoGUIDesktop)
        self.desktop.directory = Path(self.directory.name)
        self.desktop.Image = Image
        self.frame = Image.new("RGB", (800, 600), "white")
        draw = ImageDraw.Draw(self.frame)
        draw.rectangle((105, 103, 115, 118), fill="red")
        draw.line((100, 100, 119, 119), fill="black")
        self.desktop.frame = lambda: self.frame
        self.value = self.desktop.capture("export_button", [100, 100, 20, 20])

    def test_crop_only_and_roundtrip(self):
        self.assertEqual(load_reference(self.directory.name, "export_button"), self.value)
        with self.desktop.Image.open(self.desktop.directory / "export_button.png") as image:
            self.assertEqual(image.size, (20, 20))
        self.assertEqual(self.desktop.locate(self.value), [(110, 110)])

    def test_multiple_matches_are_detected(self):
        crop = self.frame.crop((100, 100, 120, 120))
        self.frame.paste(crop, (122, 100))
        self.assertEqual(len(self.desktop.locate(self.value)), 2)

    def test_size_changes_and_existing_templates_rejected(self):
        with self.assertRaises(DesktopResearchError):
            self.desktop.capture("export_button", [100, 100, 20, 20])
        self.frame = self.desktop.Image.new("RGB", (400, 300))
        with self.assertRaises(DesktopResearchError):
            self.desktop.locate(self.value)

    def test_absent_image_and_blank_calibration(self):
        self.frame.paste("white", (0, 0, 800, 600))
        self.assertEqual(self.desktop.locate(self.value), [])
        with self.assertRaises(DesktopResearchError):
            self.desktop.capture("export_dialog", [100, 100, 20, 20])

    def test_retina_coordinates_are_normalized(self):
        self.desktop.gui = SimpleNamespace(
            failSafeCheck=lambda: None, size=lambda: (800, 600),
            screenshot=lambda: self.desktop.Image.new("RGB", (1600, 1200)),
        )
        self.assertEqual(PyAutoGUIDesktop.frame(self.desktop).size, (800, 600))

    def test_inconsistent_display_scaling_stops(self):
        self.desktop.gui = SimpleNamespace(
            failSafeCheck=lambda: None, size=lambda: (800, 600),
            screenshot=lambda: self.desktop.Image.new("RGB", (1600, 600)),
        )
        with self.assertRaises(DesktopResearchError):
            PyAutoGUIDesktop.frame(self.desktop)


if __name__ == "__main__":
    unittest.main()
