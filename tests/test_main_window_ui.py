import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.capture_file import load_capture, save_capture
from app.main_window import BUTTON_WIDTH, MainWindow, SELECTOR_WIDTH
from app.protocol import Packet, PacketType, TriggerMode


class MainWindowUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()

    def test_device_and_capture_selectors_have_compact_widths(self):
        selector_width = self.window.port_combo.width()
        self.assertEqual(selector_width, SELECTOR_WIDTH)
        self.assertEqual(self.window.frequency_combo.width(), selector_width)
        self.assertEqual(self.window.samples_combo.width(), selector_width)
        self.assertEqual(
            self.window.refresh_button.width()
            + self.window.connect_button.width()
            + 6,
            selector_width,
        )
        for left_button, right_button in (
            (self.window.start_button, self.window.stop_button),
            (self.window.zoom_in_button, self.window.zoom_out_button),
            (self.window.fit_button, self.window.clear_button),
            (self.window.cursor_button, self.window.markers_button),
        ):
            self.assertEqual(
                left_button.width() + right_button.width() + 6,
                selector_width,
            )

    def test_all_action_buttons_have_equal_width(self):
        buttons = (
            self.window.refresh_button,
            self.window.connect_button,
            self.window.start_button,
            self.window.stop_button,
            self.window.zoom_in_button,
            self.window.zoom_out_button,
            self.window.fit_button,
            self.window.clear_button,
            self.window.cursor_button,
            self.window.markers_button,
            self.window.demo_button,
            self.window.save_button,
            self.window.open_button,
            self.window.info_button,
        )
        self.assertTrue(all(button.width() == BUTTON_WIDTH for button in buttons))

    def test_device_actions_and_sample_selector_stay_next_to_their_selectors(self):
        self.window.show()
        self.app.processEvents()

        central_widget = self.window.centralWidget()
        device_gap = (
            self.window.refresh_button.mapTo(central_widget, self.window.refresh_button.rect().topLeft()).x()
            - self.window.port_combo.mapTo(central_widget, self.window.port_combo.rect().topRight()).x()
        )
        frequency_gap = (
            self.window.samples_combo.mapTo(central_widget, self.window.samples_combo.rect().topLeft()).x()
            - self.window.frequency_combo.mapTo(central_widget, self.window.frequency_combo.rect().topRight()).x()
        )
        zoom_pair_gap = (
            self.window.zoom_in_button.mapTo(central_widget, self.window.zoom_in_button.rect().topLeft()).x()
            - self.window.stop_button.mapTo(central_widget, self.window.stop_button.rect().topRight()).x()
        )
        self.assertEqual(device_gap, zoom_pair_gap)
        self.assertEqual(frequency_gap, zoom_pair_gap)

        self.assertGreaterEqual(
            self.window.refresh_button.x(),
            self.window.port_combo.x() + self.window.port_combo.width(),
        )
        self.assertLess(
            self.window.refresh_button.x(),
            self.window.port_combo.x() + self.window.port_combo.width() + 20,
        )
        self.assertGreaterEqual(
            self.window.samples_combo.x(),
            self.window.frequency_combo.x() + self.window.frequency_combo.width(),
        )
        self.assertLess(
            self.window.samples_combo.x(),
            self.window.frequency_combo.x()
            + self.window.frequency_combo.width()
            + 20,
        )

    def test_markers_button_is_disabled_until_waveform_data_exists(self):
        self.assertFalse(self.window.cursor_button.isEnabled())
        self.assertFalse(self.window.markers_button.isEnabled())
        self.assertFalse(self.window.zoom_in_button.isEnabled())
        self.assertFalse(self.window.zoom_out_button.isEnabled())
        self.assertFalse(self.window.fit_button.isEnabled())

        self.window._show_demo_waveform()
        self.assertTrue(self.window.cursor_button.isEnabled())
        self.assertTrue(self.window.markers_button.isEnabled())
        self.assertTrue(self.window.zoom_in_button.isEnabled())
        self.assertTrue(self.window.zoom_out_button.isEnabled())
        self.assertTrue(self.window.fit_button.isEnabled())

        self.window._clear_dashboard()
        self.assertFalse(self.window.cursor_button.isEnabled())
        self.assertFalse(self.window.markers_button.isEnabled())
        self.assertFalse(self.window.zoom_in_button.isEnabled())
        self.assertFalse(self.window.zoom_out_button.isEnabled())
        self.assertFalse(self.window.fit_button.isEnabled())

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

    def test_stop_reenables_capture_actions_after_stopping(self):
        self.window._is_connected = True
        self.window._capture_active = True
        self.window._desired_config = (100_000, 3)
        self.window._configured_config = (100_000, 3)
        self.window._capture_samples = bytearray([0x00, 0xFF, 0x55])
        self.window.progress.setValue(0)
        self.window._capture_metadata_available = True
        self.window.start_button.setEnabled(False)
        self.window.stop_button.setEnabled(True)
        self.window.clear_button.setEnabled(False)
        self.window.cursor_button.setEnabled(False)
        self.window.markers_button.setEnabled(False)
        self.window.save_button.setEnabled(False)
        self.window.device_worker = type(
            "DummyWorker",
            (),
            {
                "stop_capture": lambda _self: None,
                "request_stop": lambda _self: None,
                "wait": lambda _self, *_args, **_kwargs: None,
            },
        )()

        self.window._stop_capture()
        self.window._handle_capture_done(type("Packet", (), {"payload": (3).to_bytes(4, "little")})())

        self.assertFalse(self.window.stop_button.isEnabled())
        self.assertTrue(self.window.start_button.isEnabled())
        self.assertTrue(self.window.clear_button.isEnabled())
        self.assertTrue(self.window.cursor_button.isEnabled())
        self.assertTrue(self.window.markers_button.isEnabled())
        self.assertTrue(self.window.save_button.isEnabled())
        self.assertEqual(self.window.progress.value(), 100)

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

    def _make_dummy_worker(self):
        return type(
            "DummyWorker",
            (),
            {
                "sent": [],
                "start_capture": lambda _self: _self.sent.append("START"),
                "stop_capture": lambda _self: _self.sent.append("STOP"),
                "trigger": lambda _self, ch, mode, pre=0, timeout=0: _self.sent.append(f"TRIGGER {ch} {mode} {pre} {timeout}"),
                "configure": lambda _self, f, s: _self.sent.append(f"CONFIGURE {f} {s}"),
                "request_stop": lambda _self: None,
                "wait": lambda _self, *_args, **_kwargs: None,
            },
        )()

    def test_triggered_capture_accepts_data_after_trigger_fired(self):
        self.window._is_connected = True
        self.window.device_worker = self._make_dummy_worker()
        self.window._desired_config = (100_000, 1000)
        self.window._pending_config = (100_000, 1000)
        self.window._on_packet_received(Packet(PacketType.CONFIG_OK, 0, b""))
        self.window._on_packet_received(Packet(PacketType.TRIGGER_OK, 1, b""))

        self.window._start_capture()
        self.window._on_packet_received(Packet(PacketType.TRIGGER_ARMED, 2, b""))
        self.assertTrue(self.window._trigger_armed)
        self.assertFalse(self.window._capture_active)
        self.assertTrue(self.window.stop_button.isEnabled())
        self.assertFalse(self.window.frequency_combo.isEnabled())

        self.window._on_packet_received(
            Packet(PacketType.TRIGGER_FIRED, 3, (250).to_bytes(4, "little"))
        )
        self.assertFalse(self.window._trigger_armed)
        self.assertTrue(self.window._capture_active)
        self.assertTrue(self.window._plot_timer.isActive())
        self.assertEqual(self.window._trigger_sample_index, 250)
        self.assertTrue(self.window.trigger_line.isVisible())

        self.window._on_packet_received(Packet(PacketType.STREAM_DATA, 4, bytes([0x55] * 1000)))
        self.assertEqual(len(self.window._capture_samples), 1000)

        self.window._on_packet_received(
            Packet(PacketType.CAPTURE_DONE, 5, (1000).to_bytes(4, "little"))
        )
        self.assertFalse(self.window._capture_active)
        self.assertEqual(
            self.window.status_label.text(),
            "Complete: 1,000 samples received (Trigger @ 250)",
        )
        self.assertTrue(self.window.save_button.isEnabled())
        self.assertTrue(self.window.apply_trigger_button.isEnabled())

    def test_stop_while_trigger_armed_sends_stop_and_accepts_zero_samples(self):
        worker = self._make_dummy_worker()
        self.window._is_connected = True
        self.window.device_worker = worker
        self.window._desired_config = (100_000, 1000)
        self.window._pending_config = (100_000, 1000)
        self.window._on_packet_received(Packet(PacketType.CONFIG_OK, 0, b""))

        self.window._start_capture()
        self.window._on_packet_received(Packet(PacketType.TRIGGER_ARMED, 1, b""))
        self.window._stop_capture()

        self.assertEqual(worker.sent, ["START", "STOP"])

        self.window._on_packet_received(
            Packet(PacketType.CAPTURE_STOPPED, 2, (0).to_bytes(4, "little"))
        )
        self.assertFalse(self.window._trigger_armed)
        self.assertFalse(self.window._capture_active)
        self.assertFalse(self.window.stop_button.isEnabled())
        self.assertTrue(self.window.start_button.isEnabled())
        self.assertTrue(self.window.apply_trigger_button.isEnabled())
        self.assertFalse(self.window.save_button.isEnabled())
        self.assertEqual(self.window.status_label.text(), "Stopped before trigger: 0 samples")

    def test_trigger_timeout_and_error_packet_reenable_controls(self):
        self.window._is_connected = True
        self.window.device_worker = self._make_dummy_worker()
        self.window._desired_config = (100_000, 1000)
        self.window._pending_config = (100_000, 1000)
        self.window._on_packet_received(Packet(PacketType.CONFIG_OK, 0, b""))

        self.window._start_capture()
        self.window._on_packet_received(Packet(PacketType.TRIGGER_ARMED, 1, b""))
        self.window._on_packet_received(Packet(PacketType.TRIGGER_TIMEOUT, 2, b""))
        self.assertFalse(self.window._trigger_armed)
        self.assertFalse(self.window.stop_button.isEnabled())
        self.assertTrue(self.window.start_button.isEnabled())
        self.assertTrue(self.window.apply_trigger_button.isEnabled())

        self.window._start_capture()
        self.window._on_packet_received(Packet(PacketType.ERROR, 3, bytes([0x04])))
        self.assertFalse(self.window._capture_active)
        self.assertFalse(self.window._trigger_armed)
        self.assertFalse(self.window.stop_button.isEnabled())
        self.assertFalse(self.window._start_timeout_timer.isActive())
        self.assertTrue(self.window.apply_trigger_button.isEnabled())
        self.assertTrue(self.window.frequency_combo.isEnabled())

    def test_connect_syncs_trigger_after_config_and_tracks_active_status(self):
        worker = self._make_dummy_worker()
        self.window.device_worker = worker
        f_idx = self.window.frequency_combo.findData(100_000)
        s_idx = self.window.samples_combo.findData(1000)
        self.window.frequency_combo.setCurrentIndex(f_idx)
        self.window.samples_combo.setCurrentIndex(s_idx)

        self.window._on_connected("COM4")
        self.assertEqual(worker.sent, ["STOP", "CONFIGURE 100000 1000"])
        self.assertFalse(self.window.start_button.isEnabled())

        # Stale STOP reply from connect cleanup should be ignored cleanly.
        self.window._on_packet_received(
            Packet(PacketType.CAPTURE_STOPPED, 0, (0).to_bytes(4, "little"))
        )

        # CONFIG_OK triggers automatic UI trigger sync without colliding on USB CDC.
        self.window._on_packet_received(Packet(PacketType.CONFIG_OK, 1, b""))
        self.assertEqual(
            worker.sent,
            [
                "STOP",
                "CONFIGURE 100000 1000",
                f"TRIGGER 0 {TriggerMode.NONE} 0 0",
            ],
        )
        self.assertFalse(self.window.start_button.isEnabled())

        self.window._on_packet_received(Packet(PacketType.TRIGGER_OK, 2, b""))
        self.assertTrue(self.window.start_button.isEnabled())
        self.assertEqual(self.window.status_label.text(), "Trigger disabled (NONE)")

        # Apply CH1 RISING with 20% pre-trigger and 2s timeout, verify active status.
        self.window.trigger_channel_combo.setCurrentIndex(1)
        self.window.trigger_mode_combo.setCurrentIndex(
            self.window.trigger_mode_combo.findData(TriggerMode.RISING)
        )
        self.window.trigger_pre_combo.setCurrentIndex(
            self.window.trigger_pre_combo.findData(20)
        )
        self.window.trigger_timeout_combo.setCurrentIndex(
            self.window.trigger_timeout_combo.findData(2000)
        )
        self.window._apply_trigger_config()
        self.window._on_packet_received(Packet(PacketType.TRIGGER_OK, 3, b""))
        self.assertEqual(
            self.window.status_label.text(),
            "Trigger active: CH1 Rising (Pre 20%, Timeout 2s)",
        )

        self.window.trigger_channel_combo.setCurrentIndex(0)
        self.assertIn("Apply trigger", self.window.status_label.text())

    def test_connect_without_selected_config_immediately_syncs_trigger(self):
        worker = self._make_dummy_worker()
        self.window.device_worker = worker
        self.window._desired_config = None
        self.window._on_connected("COM4")
        self.assertEqual(
            worker.sent,
            ["STOP", f"TRIGGER 0 {TriggerMode.NONE} 0 0"],
        )


if __name__ == "__main__":
    unittest.main()
