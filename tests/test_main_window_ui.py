import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.capture_file import load_capture, save_capture
from app.main_window import MainWindow


class MainWindowUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()

    def test_device_and_capture_selectors_have_compact_widths(self):
        self.assertEqual(self.window.port_combo.width(), 220)
        self.assertEqual(self.window.frequency_combo.width(), 180)
        self.assertEqual(self.window.samples_combo.width(), 210)

    def test_measurement_readouts_are_shown_only_when_enabled(self):
        self.assertTrue(self.window.measurement_controls.isHidden())
        self.assertTrue(self.window.cursor_readout.isHidden())
        self.assertTrue(self.window.marker_readout.isHidden())

        self.window._capture_samples = bytearray([0x00, 0xFF, 0x55, 0xAA])
        self.window._capture_frequency_hz = 50_000
        self.window._plot_samples(self.window._capture_samples)
        self.window.cursor_button.setEnabled(True)
        self.window.markers_button.setEnabled(True)
        self.window.cursor_button.setChecked(True)
        self.window.markers_button.setChecked(True)

        self.assertFalse(self.window.measurement_controls.isHidden())
        self.assertFalse(self.window.cursor_readout.isHidden())
        self.assertFalse(self.window.marker_readout.isHidden())
        self.assertFalse(self.window.marker_channel_combo.isHidden())

        self.window.cursor_button.setChecked(False)
        self.assertTrue(self.window.cursor_readout.isHidden())
        self.assertFalse(self.window.measurement_controls.isHidden())

        self.window.markers_button.setChecked(False)
        self.assertTrue(self.window.measurement_controls.isHidden())

    def test_information_button_opens_about_popup_with_developer_contact(self):
        with patch("app.main_window.QMessageBox.about") as show_about:
            self.window.info_button.click()

        show_about.assert_called_once()
        title = show_about.call_args.args[1]
        content = show_about.call_args.args[2]
        self.assertEqual(title, "About STM32 Logic Analyzer")
        self.assertIn("Development build", content)
        self.assertIn("Nguyễn Việt Anh", content)
        self.assertIn("nvietanh28@gmail.com", content)

    def test_clear_dashboard_clears_plot_without_channel_toggle(self):
        self.window._capture_samples = bytearray([0x00, 0xFF, 0x55, 0xAA])
        self.window._capture_frequency_hz = 50_000
        self.window._capture_metadata_available = True
        self.window._plot_samples(self.window._capture_samples)
        self.window.save_button.setEnabled(True)

        self.window._clear_dashboard()
        self.app.processEvents()

        self.assertFalse(self.window._capture_samples)
        self.assertFalse(self.window._capture_metadata_available)
        self.assertFalse(self.window.save_button.isEnabled())
        for curve in self.window.channel_curves:
            x_values, y_values = curve.getData()
            self.assertTrue(x_values is None or len(x_values) == 0)
            self.assertTrue(y_values is None or len(y_values) == 0)

    def test_applies_saved_channel_layout(self):
        items = {
            self.window.channel_list.item(row).data(Qt.ItemDataRole.UserRole):
            self.window.channel_list.item(row)
            for row in range(self.window.channel_list.count())
        }
        items[3].setText("CLOCK")
        items[5].setCheckState(Qt.CheckState.Unchecked)
        self.window.channel_list.takeItem(self.window.channel_list.row(items[3]))
        self.window.channel_list.insertItem(0, items[3])
        self.window.channel_spacing_slider.setValue(24)
        expected_layout = self.window._get_channel_layout()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.la"
            save_capture(path, 50_000, bytes([0x00, 0xFF]), expected_layout)
            capture = load_capture(path)
        self.assertIsNotNone(capture.channel_layout)
        if capture.channel_layout is None:
            self.fail("Version 2 capture did not contain a channel layout")

        items[3].setText("OTHER")
        items[5].setCheckState(Qt.CheckState.Checked)
        self.window.channel_spacing_slider.setValue(15)
        self.window._apply_channel_layout(capture.channel_layout)

        self.assertEqual(self.window._get_channel_layout(), expected_layout)


if __name__ == "__main__":
    unittest.main()
