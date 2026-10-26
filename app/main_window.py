from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QAbstractItemView,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
import pyqtgraph as pg
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QMouseEvent
from serial.tools import list_ports
import numpy as np

from .device_worker import DeviceWorker
from .capture_file import (
    ChannelLayout,
    ChannelSetting,
    load_capture,
    save_capture,
)
from .protocol import Packet, PacketType
from .waveform import find_channel_edges, format_time


FREQUENCIES = [
    1, 2, 5, 10, 20, 50, 100, 200, 500,
    1_000, 2_000, 5_000, 10_000, 20_000,
    50_000, 100_000, 200_000, 500_000, 1_000_000, 2_000_000,
]

SAMPLE_COUNTS = [
    100, 200, 500, 1_000, 2_000, 5_000, 10_000,
    20_000, 50_000, 100_000,
]

BUTTON_WIDTH = 107
SELECTOR_WIDTH = BUTTON_WIDTH * 2 + 6
DEVICE_BUTTON_WIDTH = BUTTON_WIDTH


class TimeAxisItem(pg.AxisItem):
    def __init__(self, **kwargs):
        super().__init__(orientation="bottom", **kwargs)
        self.frequency_hz: int | None = None

    def set_frequency(self, frequency_hz: int | None) -> None:
        self.frequency_hz = frequency_hz
        self.setLabel("bottom", "Time" if frequency_hz else "Sample index")
        self.picture = None
        self.update()

    def tickStrings(self, values, scale, spacing):
        if self.frequency_hz is None:
            return [f"{value:g}" for value in values]

        times = [value / self.frequency_hz for value in values]
        max_time = max((abs(value) for value in times), default=0.0)
        if max_time < 1e-6:
            multiplier, unit = 1e9, "ns"
        elif max_time < 1e-3:
            multiplier, unit = 1e6, "us"
        elif max_time < 1:
            multiplier, unit = 1e3, "ms"
        else:
            multiplier, unit = 1.0, "s"

        return [f"{value * multiplier:g} {unit}" for value in times]


class ReorderableChannelList(QListWidget):
    orderChanged = Signal()

    def __init__(self):
        super().__init__()
        self._pressed_row = -1
        self._pressed_position = None
        self._reorder_drag_active = False
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def _is_reorder_handle_position(self, position) -> bool:
        row = self.indexAt(position).row()
        if row < 0:
            return False
        item_rect = self.visualItemRect(self.item(row))
        return position.x() >= item_rect.left() + 26

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            position = event.position().toPoint()
            self._pressed_row = (
                self.indexAt(position).row()
                if self._is_reorder_handle_position(position)
                else -1
            )
            self._pressed_position = position if self._pressed_row >= 0 else None
            self._reorder_drag_active = False
            if self._pressed_row >= 0:
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        position = event.position().toPoint()
        if (
            self._pressed_row >= 0
            and event.buttons() & Qt.MouseButton.LeftButton
            and self._pressed_position is not None
        ):
            distance = (
                position - self._pressed_position
            ).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self._reorder_drag_active = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        elif not event.buttons():
            cursor = (
                Qt.CursorShape.OpenHandCursor
                if self._is_reorder_handle_position(position)
                else Qt.CursorShape.ArrowCursor
            )
            self.setCursor(cursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._reorder_drag_active and self._pressed_row >= 0:
            target_row = self.indexAt(event.position().toPoint()).row()
            if target_row >= 0:
                target_rect = self.visualItemRect(self.item(target_row))
                if event.position().y() >= target_rect.center().y():
                    target_row += 1
            else:
                target_row = self.count()

            source_row = self._pressed_row
            if target_row > source_row:
                target_row -= 1
            if target_row != source_row:
                item = self.takeItem(source_row)
                self.insertItem(target_row, item)
                self.setCurrentItem(item)
                self.orderChanged.emit()
        else:
            super().mouseReleaseEvent(event)

        self._pressed_row = -1
        self._pressed_position = None
        self._reorder_drag_active = False
        self.setCursor(
            Qt.CursorShape.OpenHandCursor
            if self._is_reorder_handle_position(event.position().toPoint())
            else Qt.CursorShape.ArrowCursor
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("STM32 Logic Analyzer")
        self.resize(1320, 800)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        device_row = self._make_device_row()
        device_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(device_row)
        capture_row = self._make_capture_row()
        capture_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(capture_row)
        layout.addLayout(self._make_action_row())
        layout.addLayout(self._make_test_row())
        layout.addWidget(self._make_marker_row())

        self.status_label = QLabel("Disconnected")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_font = self.status_label.font()
        status_font.setPointSize(status_font.pointSize() + 2)
        status_font.setBold(True)
        self.status_label.setFont(status_font)
        self.status_title = QLabel("STATUS")
        self.status_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = self.status_title.font()
        title_font.setPointSize(title_font.pointSize() + 2)
        title_font.setBold(True)
        self.status_title.setFont(title_font)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.progress.setFixedWidth(140)

        self.device_worker: DeviceWorker | None = None
        self._is_connected = False
        self._pending_config: tuple[int, int] | None = None
        self._desired_config: tuple[int, int] | None = None
        self._configured_config: tuple[int, int] | None = None
        self._worker_error_message: str | None = None
        self._capture_active = False
        self._capture_samples = bytearray()
        self._capture_frequency_hz: int | None = None
        self._capture_metadata_available = False
        self._plot_window_samples = 4096
        self._marker_channel = 0
        self._marker_snap_active = False
        self._marker_edges_cache: list[tuple[int, bool]] = []
        self._marker_edges_cache_key: tuple[int, int, int] | None = None
        self._config_timeout_timer = QTimer(self)
        self._config_timeout_timer.setSingleShot(True)
        self._config_timeout_timer.timeout.connect(self._on_config_timeout)
        self._plot_timer = QTimer(self)
        self._plot_timer.setInterval(250)
        self._plot_timer.timeout.connect(self._refresh_capture_plot)

        status_row = QHBoxLayout()
        status_row.addStretch(1)
        status_row.addWidget(self.status_title)
        status_row.addWidget(self.status_label, 3)
        status_row.addStretch(1)
        status_row.addWidget(self.progress)
        layout.addLayout(status_row)

        self.channel_list = self._make_channel_controls()
        self.channel_panel_toggle = QToolButton()
        self.channel_panel_toggle.setFixedWidth(28)
        self.channel_panel_toggle.setArrowType(Qt.ArrowType.LeftArrow)
        self.channel_panel_toggle.setToolTip("Hide channels panel")
        self.channel_panel_toggle.setAccessibleName("Hide channels panel")
        self.plot_area = pg.GraphicsLayoutWidget()
        self.plot_area.setBackground("#202124")
        waveform_row = QHBoxLayout()
        waveform_row.addWidget(self.channel_panel_toggle, 0)
        waveform_row.addWidget(self.channel_controls, 0)
        waveform_row.addWidget(self.plot_area, 1)
        layout.addLayout(waveform_row, 1)

        self._create_channel_plots()
        self.demo_button.clicked.connect(self._show_demo_waveform)
        self.refresh_button.clicked.connect(self._refresh_ports)
        self.connect_button.clicked.connect(self._toggle_connection)
        self.frequency_combo.currentIndexChanged.connect(
            self._on_frequency_changed
        )
        self.samples_combo.currentIndexChanged.connect(
            self._on_configuration_changed
        )
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self._start_capture)
        self.save_button.clicked.connect(self._save_capture)
        self.open_button.clicked.connect(self._open_capture)
        self.info_button.clicked.connect(self._show_information)
        self.zoom_in_button.clicked.connect(lambda: self._zoom_x(0.7))
        self.zoom_out_button.clicked.connect(lambda: self._zoom_x(1.4))
        self.fit_button.clicked.connect(self._fit_waveform)
        self.clear_button.clicked.connect(self._clear_dashboard)
        self.cursor_button.toggled.connect(self._toggle_cursor)
        self.markers_button.toggled.connect(self._toggle_markers)
        self.marker_channel_combo.currentIndexChanged.connect(
            self._on_marker_channel_changed
        )
        self.channel_list.itemChanged.connect(self._on_channel_item_changed)
        self.channel_list.orderChanged.connect(
            self._on_channel_order_changed
        )
        self.channel_panel_toggle.clicked.connect(
            self._toggle_channel_panel
        )
        self.channel_spacing_slider.valueChanged.connect(
            self._on_channel_spacing_changed
        )
        self.marker_a_line.sigPositionChanged.connect(
            lambda: self._on_marker_moved(self.marker_a_line)
        )
        self.marker_b_line.sigPositionChanged.connect(
            lambda: self._on_marker_moved(self.marker_b_line)
        )
        self.save_button.setEnabled(False)
        self.cursor_button.setEnabled(False)
        self.markers_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        self._refresh_ports()

    def _show_information(self):
        QMessageBox.about(
            self,
            "About STM32 Logic Analyzer",
            "<b>STM32 Logic Analyzer</b><br>"
            "Development build<br><br>"
            "An 8-channel desktop logic analyzer for capturing and inspecting "
            "digital signals from an STM32F103C8T6 via USB CDC.<br><br>"
            "Features include waveform viewing, cursor and edge-snapped "
            "marker measurements, and saving or opening capture files "
            "in .la format.<br><br>"
            "Developer: Nguyễn Việt Anh<br>"
            "Email: <a href=\"mailto:nvietanh28@gmail.com\">"
            "nvietanh28@gmail.com</a>",
        )

    def _make_device_row(self):
        row = QHBoxLayout()

        self.port_combo = QComboBox()
        self.port_combo.addItem("Select COM port")
        self.port_combo.setFixedWidth(SELECTOR_WIDTH)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setFixedWidth(DEVICE_BUTTON_WIDTH)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setFixedWidth(DEVICE_BUTTON_WIDTH)

        row.addWidget(self.port_combo)
        row.addSpacing(12)
        device_actions = QHBoxLayout()
        device_actions.setSpacing(6)
        device_actions.addWidget(self.refresh_button)
        device_actions.addWidget(self.connect_button)
        row.addLayout(device_actions)
        return row

    def _make_capture_row(self):
        row = QHBoxLayout()

        self.frequency_combo = QComboBox()
        self.frequency_combo.setFixedWidth(SELECTOR_WIDTH)
        self.frequency_combo.addItem("Select frequency")
        for frequency in FREQUENCIES:
            self.frequency_combo.addItem(f"{frequency:,} Hz", frequency)

        self.samples_combo = QComboBox()
        self.samples_combo.setFixedWidth(SELECTOR_WIDTH)
        self.samples_combo.addItem("Select sample count")
        self._populate_sample_options(SAMPLE_COUNTS)

        row.addWidget(self.frequency_combo)
        row.addSpacing(12)
        row.addWidget(self.samples_combo)
        return row

    def _make_action_row(self):
        row = QHBoxLayout()

        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.cursor_button = QPushButton("Cursor")
        self.cursor_button.setCheckable(True)
        self.markers_button = QPushButton("Markers A/B")
        self.markers_button.setCheckable(True)
        self.zoom_in_button = QPushButton("Zoom +")
        self.zoom_out_button = QPushButton("Zoom -")
        self.fit_button = QPushButton("Fit")
        self.clear_button = QPushButton("Clear")
        self._set_waveform_navigation_enabled(False)

        self.save_button = QPushButton("Save")
        self.open_button = QPushButton("Open")
        self.info_button = QPushButton("Information")

        for button in (
            self.start_button,
            self.stop_button,
            self.zoom_in_button,
            self.zoom_out_button,
            self.fit_button,
            self.clear_button,
            self.cursor_button,
            self.markers_button,
            self.save_button,
            self.open_button,
            self.info_button,
        ):
            button.setFixedWidth(BUTTON_WIDTH)

        for left_button, right_button in (
            (self.start_button, self.stop_button),
            (self.zoom_in_button, self.zoom_out_button),
            (self.fit_button, self.clear_button),
            (self.cursor_button, self.markers_button),
        ):
            button_pair = QHBoxLayout()
            button_pair.setSpacing(6)
            button_pair.addWidget(left_button)
            button_pair.addWidget(right_button)
            row.addLayout(button_pair)
            row.addSpacing(12)

        row.addStretch(1)
        row.addWidget(self.save_button)
        row.addSpacing(6)
        row.addWidget(self.open_button)
        row.addSpacing(6)
        row.addWidget(self.info_button)
        return row

    def _make_test_row(self):
        row = QHBoxLayout()
        self.demo_button = QPushButton("Test waveform")
        self.demo_button.setFixedWidth(BUTTON_WIDTH)
        row.addWidget(self.demo_button)
        row.addStretch(1)
        return row

    def _make_marker_row(self):
        self.measurement_controls = QWidget()
        row = QHBoxLayout(self.measurement_controls)
        row.setContentsMargins(0, 0, 0, 0)

        self.cursor_readout = QLabel("Cursor: off")
        self.marker_channel_combo = QComboBox()
        for channel in range(8):
            self.marker_channel_combo.addItem(f"CH{channel}", channel)
        self.marker_readout = QLabel("Markers: off")
        self.marker_channel_label = QLabel("Snap channel:")
        self.marker_channel_combo.setEnabled(False)

        row.addWidget(self.cursor_readout)
        row.addSpacing(12)
        row.addWidget(self.marker_channel_label)
        row.addWidget(self.marker_channel_combo)
        row.addWidget(self.marker_readout, 1)
        self.measurement_controls.hide()
        self.cursor_readout.hide()
        self.marker_channel_label.hide()
        self.marker_channel_combo.hide()
        self.marker_readout.hide()
        return self.measurement_controls

    def _make_channel_controls(self) -> QListWidget:
        self.channel_controls = QGroupBox("Channels")
        self.channel_controls.setMaximumWidth(230)
        controls_layout = QVBoxLayout(self.channel_controls)
        self.channel_list = ReorderableChannelList()
        self.channel_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.channel_list.setMaximumWidth(190)
        self.channel_list.setMinimumWidth(120)

        for channel in range(8):
            item = QListWidgetItem(f"CH{channel}")
            item.setData(Qt.ItemDataRole.UserRole, channel)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsEditable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip("Hold the left mouse button and drag to reorder")
            self.channel_list.addItem(item)

        instructions = QLabel(
            "Hold and drag to reorder; uncheck to hide; "
            "double-click to rename."
        )
        instructions.setWordWrap(True)
        controls_layout.addWidget(instructions)
        controls_layout.addWidget(self.channel_list, 1)

        controls_layout.addWidget(QLabel("Vertical spacing"))
        self.channel_spacing_slider = QSlider(Qt.Orientation.Horizontal)
        self.channel_spacing_slider.setRange(11, 30)
        self.channel_spacing_slider.setValue(15)
        self.channel_spacing_slider.setToolTip(
            "Adjust vertical distance between visible channels"
        )
        controls_layout.addWidget(self.channel_spacing_slider)
        return self.channel_list

    def _toggle_channel_panel(self):
        visible = not self.channel_controls.isVisible()
        self.channel_controls.setVisible(visible)
        if visible:
            self.channel_panel_toggle.setArrowType(Qt.ArrowType.LeftArrow)
            self.channel_panel_toggle.setToolTip("Hide channels panel")
            self.channel_panel_toggle.setAccessibleName("Hide channels panel")
        else:
            self.channel_panel_toggle.setArrowType(Qt.ArrowType.RightArrow)
            self.channel_panel_toggle.setToolTip("Show channels panel")
            self.channel_panel_toggle.setAccessibleName("Show channels panel")

    def _channel_rows(self) -> list[tuple[int, str]]:
        rows = []
        for row in range(self.channel_list.count()):
            item = self.channel_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                channel = item.data(Qt.ItemDataRole.UserRole)
                name = item.text().strip() or f"CH{channel}"
                rows.append((channel, name))
        return rows

    def _refresh_channel_layout(self):
        rows = self._channel_rows()
        pitch = self.channel_spacing_slider.value() / 10.0
        tick_labels = []

        for curve in self.channel_curves:
            curve.setVisible(False)

        visible_count = len(rows)
        for display_row, (channel, name) in enumerate(rows):
            lane_bottom = (visible_count - display_row - 1) * pitch
            curve = self.channel_curves[channel]
            curve.setVisible(True)
            curve.setData(
                self._plot_x_values,
                lane_bottom + self._plot_channel_bits[channel] * 0.8,
            )
            tick_labels.append((lane_bottom + 0.4, name))

        self.logic_plot.getAxis("left").setTicks([tick_labels])
        if visible_count:
            self.logic_plot.setYRange(
                -0.35,
                max(1.0, (visible_count - 1) * pitch + 1.05),
                padding=0,
            )
        else:
            self.logic_plot.setYRange(-0.5, 1.0, padding=0)

        for line in self.channel_separators:
            self.logic_plot.removeItem(line)
        self.channel_separators.clear()
        for row in range(visible_count - 1):
            separator_y = (visible_count - row - 2) * pitch + 0.95
            line = pg.InfiniteLine(
                pos=separator_y,
                angle=0,
                movable=False,
                pen=pg.mkPen("#3A3D42", width=1),
            )
            self.logic_plot.addItem(line)
            self.channel_separators.append(line)

        selected_channel = self.marker_channel_combo.currentData()
        self.marker_channel_combo.blockSignals(True)
        self.marker_channel_combo.clear()
        for channel in range(8):
            item = self._channel_item_for(channel)
            display_name = item.text().strip() or f"CH{channel}"
            self.marker_channel_combo.addItem(display_name, channel)
        selected_index = self.marker_channel_combo.findData(selected_channel)
        if selected_index >= 0:
            self.marker_channel_combo.setCurrentIndex(selected_index)
        self.marker_channel_combo.blockSignals(False)
        if selected_channel is not None:
            self._marker_channel = selected_channel
        self._marker_edges_cache_key = None

    def _channel_item_for(self, channel: int) -> QListWidgetItem:
        for row in range(self.channel_list.count()):
            item = self.channel_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == channel:
                return item
        raise ValueError(f"Unknown channel index: {channel}")

    def _on_channel_item_changed(self, _item: QListWidgetItem):
        self._refresh_channel_layout()
        self._update_marker_readout()

    def _on_channel_order_changed(self, *_args):
        self._refresh_channel_layout()

    def _on_channel_spacing_changed(self, _value: int):
        self._refresh_channel_layout()

    def _refresh_ports(self):
        selected_port = self.port_combo.currentData()
        self.port_combo.clear()
        self.port_combo.addItem("Select COM port", None)

        for port in list_ports.comports():
            description = f"{port.device} - {port.description}"
            self.port_combo.addItem(description, port.device)

        selected_index = self.port_combo.findData(selected_port)
        if selected_index >= 0:
            self.port_combo.setCurrentIndex(selected_index)

    def _populate_sample_options(self, sample_counts):
        selected_samples = self.samples_combo.currentData()
        self.samples_combo.blockSignals(True)
        self.samples_combo.clear()
        self.samples_combo.addItem("Select sample count", None)

        for sample_count in sample_counts:
            self.samples_combo.addItem(f"{sample_count:,}", sample_count)

        selected_index = self.samples_combo.findData(selected_samples)
        if selected_index >= 0:
            self.samples_combo.setCurrentIndex(selected_index)
        self.samples_combo.blockSignals(False)

    def _on_frequency_changed(self, _index):
        frequency = self.frequency_combo.currentData()
        if frequency is not None and frequency >= 500_000:
            allowed_samples = [
                count for count in SAMPLE_COUNTS if count <= 10_000
            ]
        else:
            allowed_samples = SAMPLE_COUNTS

        self._populate_sample_options(allowed_samples)
        self._on_configuration_changed()

    def _on_configuration_changed(self, _index=None):
        if self._capture_active:
            return

        frequency = self.frequency_combo.currentData()
        sample_count = self.samples_combo.currentData()

        if frequency is None or sample_count is None:
            self._desired_config = None
            self._configured_config = None
            self.start_button.setEnabled(False)
            return

        self._desired_config = (frequency, sample_count)
        if self._configured_config != self._desired_config:
            self._configured_config = None
            self.start_button.setEnabled(False)
            self.progress.setValue(0)
            if self._is_connected:
                self._send_configuration_if_ready()

    def _send_configuration_if_ready(self):
        if (
            not self._is_connected
            or self.device_worker is None
            or self._desired_config is None
            or self._pending_config is not None
            or self._desired_config == self._configured_config
        ):
            return

        frequency, sample_count = self._desired_config
        self._pending_config = self._desired_config
        self._config_timeout_timer.start(3000)
        self.status_label.setText(
            f"Configuring {frequency:,} Hz / {sample_count:,} samples..."
        )
        self.device_worker.configure(frequency, sample_count)

    def _toggle_connection(self):
        if self.device_worker is not None:
            if self._capture_active:
                self.status_label.setText(
                    "Capture active; wait for completion before disconnecting"
                )
                return

            self.status_label.setText("Disconnecting...")
            self.connect_button.setEnabled(False)
            self.device_worker.request_stop()
            return

        port_name = self.port_combo.currentData()
        if port_name is None:
            self.status_label.setText("Select a COM port first")
            return

        self.connect_button.setEnabled(False)
        self.status_label.setText(f"Connecting to {port_name}...")
        self._worker_error_message = None
        worker = DeviceWorker(port_name)
        self.device_worker = worker
        worker.connected.connect(self._on_connected)
        worker.packet_received.connect(self._on_packet_received)
        worker.error.connect(self._on_worker_error)
        worker.disconnected.connect(self._on_disconnected)
        worker.finished.connect(self._on_worker_finished)
        worker.start()

    def _on_connected(self, port_name):
        self._is_connected = True
        self.port_combo.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.frequency_combo.setEnabled(True)
        self.samples_combo.setEnabled(True)
        self.connect_button.setText("Disconnect")
        self.connect_button.setEnabled(True)
        self.status_label.setText(f"Connected to {port_name}")
        self._send_configuration_if_ready()

    def _on_disconnected(self):
        self._is_connected = False
        self._capture_active = False
        self._plot_timer.stop()
        self._config_timeout_timer.stop()
        self._pending_config = None
        self._configured_config = None
        self.frequency_combo.setEnabled(True)
        self.samples_combo.setEnabled(True)
        self.start_button.setEnabled(False)
        self.port_combo.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.connect_button.setText("Connect")
        if self._worker_error_message is None:
            self.status_label.setText("Disconnected")
        else:
            self.status_label.setText(
                f"Disconnected: {self._worker_error_message}"
            )

    def _on_worker_finished(self):
        worker = self.sender()
        if worker is self.device_worker:
            self.device_worker = None
        self.connect_button.setEnabled(True)

    def _on_worker_error(self, message):
        self._worker_error_message = message
        self.status_label.setText(f"Connection error: {message}")

    def _on_packet_received(self, packet: Packet):
        if packet.packet_type == PacketType.CONFIG_OK:
            if self._pending_config is None:
                self.status_label.setText("Unexpected CONFIG_OK packet")
                return

            self._config_timeout_timer.stop()
            self._configured_config = self._pending_config
            self._pending_config = None

            if self._configured_config == self._desired_config:
                frequency, sample_count = self._configured_config
                self.status_label.setText(
                    f"Configured: {frequency:,} Hz / {sample_count:,} samples"
                )
                self.start_button.setEnabled(self._is_connected)
            else:
                self._send_configuration_if_ready()
            return

        if packet.packet_type == PacketType.CAPTURE_STARTED:
            if self._desired_config is None:
                self.status_label.setText(
                    "Received CAPTURE_STARTED without a selected configuration"
                )
                return

            self._capture_samples.clear()
            self._marker_edges_cache_key = None
            self._capture_frequency_hz = self._desired_config[0]
            self.time_axis.set_frequency(self._capture_frequency_hz)
            self._capture_active = True
            self.frequency_combo.setEnabled(False)
            self.samples_combo.setEnabled(False)
            self.connect_button.setEnabled(False)
            self.start_button.setEnabled(False)
            self.progress.setValue(0)
            self.status_label.setText("Capturing: 0 samples received")
            self._plot_timer.start()
            return

        if packet.packet_type in (
            PacketType.STREAM_DATA,
            PacketType.SNAPSHOT_DATA,
        ):
            self._handle_data_packet(packet)
            return

        if packet.packet_type == PacketType.CAPTURE_DONE:
            self._handle_capture_done(packet)
            return

        if packet.packet_type == PacketType.ERROR:
            error_names = {
                0x01: "Device is not configured",
                0x02: "Invalid configuration",
                0x03: "Snapshot sample limit exceeded",
                0x04: "Capture failed to start",
                0x05: "USB transmit error",
                0x06: "DMA overrun",
            }
            error_code = packet.payload[0]
            self._config_timeout_timer.stop()
            self._pending_config = None
            self._configured_config = None
            self._capture_active = False
            self._plot_timer.stop()
            self.frequency_combo.setEnabled(True)
            self.samples_combo.setEnabled(True)
            self.connect_button.setEnabled(self._is_connected)
            self.start_button.setEnabled(False)
            self.status_label.setText(
                f"Device error 0x{error_code:02X}: "
                f"{error_names.get(error_code, 'Unknown error')}"
            )

    def _start_capture(self):
        if (
            not self._is_connected
            or self.device_worker is None
            or self._configured_config is None
            or self._configured_config != self._desired_config
            or self._capture_active
        ):
            return

        self._capture_samples.clear()
        self._capture_frequency_hz = None
        self._capture_metadata_available = False
        self._marker_edges_cache_key = None
        self._set_waveform_navigation_enabled(False)
        self.save_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        self.cursor_button.setEnabled(False)
        self.cursor_button.setChecked(False)
        self.cursor_line.setVisible(False)
        self.markers_button.setEnabled(False)
        self.markers_button.setChecked(False)
        self.marker_a_line.setVisible(False)
        self.marker_b_line.setVisible(False)
        self.marker_channel_combo.setEnabled(False)
        self.cursor_readout.setText("Cursor: off")
        self.marker_readout.setText("Markers: off")
        self._clear_waveform()
        self.progress.setValue(0)
        self.status_label.setText("Starting capture...")
        self.start_button.setEnabled(False)
        self.device_worker.start_capture()

    def _handle_data_packet(self, packet: Packet):
        if not self._capture_active or self._desired_config is None:
            self.status_label.setText(
                f"Ignoring data packet {packet.sequence:02X} outside capture"
            )
            return

        frequency, target_samples = self._desired_config
        expected_type = (
            PacketType.SNAPSHOT_DATA
            if frequency >= 500_000
            else PacketType.STREAM_DATA
        )
        if packet.packet_type != expected_type:
            self._fail_capture(
                f"Expected {expected_type.name}, received "
                f"{packet.packet_type.name}"
            )
            return

        received = len(self._capture_samples) + len(packet.payload)
        if received > target_samples:
            self._fail_capture(
                f"Received more than configured samples "
                f"({received}/{target_samples})"
            )
            return

        self._capture_samples.extend(packet.payload)
        self._set_waveform_navigation_enabled(True)
        progress = received * 100 // target_samples
        self.progress.setValue(progress)

    def _handle_capture_done(self, packet: Packet):
        if not self._capture_active or self._desired_config is None:
            self.status_label.setText("Unexpected CAPTURE_DONE packet")
            return

        reported_samples = int.from_bytes(packet.payload, byteorder="little")
        received_samples = len(self._capture_samples)
        _, target_samples = self._desired_config

        self._capture_active = False
        self._plot_timer.stop()
        self._set_capture_controls_enabled(True)
        self._refresh_capture_plot(show_all=True)

        if (
            reported_samples != received_samples
            or received_samples != target_samples
        ):
            self.start_button.setEnabled(False)
            self.status_label.setText(
                "Capture count mismatch: "
                f"received {received_samples:,}/{target_samples:,}, "
                f"device reported {reported_samples:,}"
            )
            return

        self.progress.setValue(100)
        self._capture_frequency_hz = self._desired_config[0]
        self.time_axis.set_frequency(self._capture_frequency_hz)
        self._capture_metadata_available = True
        self.save_button.setEnabled(True)
        self.clear_button.setEnabled(True)
        self.cursor_button.setEnabled(bool(self._capture_samples))
        self.markers_button.setEnabled(bool(self._capture_samples))
        self.status_label.setText(
            f"Complete: {received_samples:,} samples received"
        )
        self.start_button.setEnabled(
            self._is_connected
            and self._configured_config == self._desired_config
        )

    def _fail_capture(self, message: str):
        self._capture_active = False
        self._plot_timer.stop()
        self._set_capture_controls_enabled(True)
        self.start_button.setEnabled(False)
        self._capture_metadata_available = False
        self.save_button.setEnabled(False)
        self.clear_button.setEnabled(bool(self._capture_samples))
        self.cursor_button.setEnabled(bool(self._capture_samples))
        self.markers_button.setEnabled(bool(self._capture_samples))
        self.status_label.setText(f"Capture failed: {message}")

    def _set_capture_controls_enabled(self, enabled: bool):
        self.frequency_combo.setEnabled(enabled)
        self.samples_combo.setEnabled(enabled)
        self.connect_button.setEnabled(enabled and self._is_connected)
        self.open_button.setEnabled(enabled)

    def _refresh_capture_plot(self, show_all: bool = False):
        if not self._capture_samples:
            return

        total_samples = len(self._capture_samples)
        if self._capture_active and self._desired_config is not None:
            _, target_samples = self._desired_config
            self.status_label.setText(
                f"Capturing: {total_samples:,} / {target_samples:,} samples"
            )

        start_index = (
            0 if show_all else max(0, total_samples - self._plot_window_samples)
        )
        visible_samples = self._capture_samples[start_index:]
        self._plot_samples(visible_samples, start_index=start_index)

        if show_all:
            self.logic_plot.setXRange(0, max(1, total_samples), padding=0)
        else:
            self.logic_plot.setXRange(
                start_index,
                max(start_index + 1, total_samples),
                padding=0,
            )

    def _clear_waveform(self):
        self._plot_x_values = np.array([], dtype=np.int64)
        self._plot_channel_bits = [
            np.array([], dtype=np.float64) for _ in range(8)
        ]
        for curve in self.channel_curves:
            curve.setData([], [])
        self._refresh_channel_layout()

    def _get_channel_layout(self) -> ChannelLayout:
        settings = []
        for order in range(self.channel_list.count()):
            item = self.channel_list.item(order)
            channel = item.data(Qt.ItemDataRole.UserRole)
            name = item.text().strip() or f"CH{channel}"
            settings.append(
                ChannelSetting(
                    channel=channel,
                    name=name,
                    visible=item.checkState() == Qt.CheckState.Checked,
                    order=order,
                )
            )

        return ChannelLayout(
            channels=tuple(settings),
            vertical_spacing=self.channel_spacing_slider.value(),
        )

    def _apply_channel_layout(self, channel_layout: ChannelLayout):
        ordered_settings = sorted(
            channel_layout.channels,
            key=lambda setting: setting.order,
        )
        self.channel_list.blockSignals(True)
        self.channel_list.setUpdatesEnabled(False)
        self.channel_spacing_slider.blockSignals(True)
        try:
            for target_row, setting in enumerate(ordered_settings):
                item = self._channel_item_for(setting.channel)
                current_row = self.channel_list.row(item)
                if current_row != target_row:
                    self.channel_list.takeItem(current_row)
                    self.channel_list.insertItem(target_row, item)
                item.setText(setting.name)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if setting.visible
                    else Qt.CheckState.Unchecked
                )
            self.channel_spacing_slider.setValue(
                channel_layout.vertical_spacing
            )
        finally:
            self.channel_list.setUpdatesEnabled(True)
            self.channel_list.blockSignals(False)
            self.channel_spacing_slider.blockSignals(False)
        self._refresh_channel_layout()

    def _save_capture(self):
        if (
            not self._capture_metadata_available
            or self._capture_frequency_hz is None
            or not self._capture_samples
        ):
            QMessageBox.information(
                self,
                "No capture",
                "Complete a capture or open a capture file before saving.",
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save capture",
            (
                f"capture_{self._capture_frequency_hz}Hz_"
                f"{len(self._capture_samples)}samples.la"
            ),
            "Logic Analyzer Capture (*.la)",
        )
        if not path:
            return

        if not path.lower().endswith(".la"):
            path += ".la"

        try:
            save_capture(
                path,
                self._capture_frequency_hz,
                bytes(self._capture_samples),
                self._get_channel_layout(),
            )
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return

        self.status_label.setText(f"Saved capture: {path}")

    def _open_capture(self):
        if self._capture_active:
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open capture",
            "",
            "Logic Analyzer Capture (*.la)",
        )
        if not path:
            return

        try:
            capture = load_capture(path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return

        self._capture_samples = bytearray(capture.samples)
        self._capture_frequency_hz = capture.frequency_hz
        self._marker_edges_cache_key = None
        self._set_waveform_navigation_enabled(bool(self._capture_samples))
        if capture.channel_layout is not None:
            self._apply_channel_layout(capture.channel_layout)
        self.time_axis.set_frequency(capture.frequency_hz)
        self._capture_metadata_available = True
        self.progress.setValue(100)
        self._refresh_capture_plot(show_all=True)
        self.save_button.setEnabled(True)
        self.clear_button.setEnabled(True)
        self.cursor_button.setEnabled(bool(self._capture_samples))
        self.markers_button.setEnabled(bool(self._capture_samples))
        self.status_label.setText(
            f"Loaded {len(capture.samples):,} samples at "
            f"{capture.frequency_hz:,} Hz"
        )

    def _on_config_timeout(self):
        if self._pending_config is None:
            return

        frequency, sample_count = self._pending_config
        self._pending_config = None
        self._configured_config = None
        self.start_button.setEnabled(False)
        self.status_label.setText(
            f"No configure response for {frequency:,} Hz / "
            f"{sample_count:,} samples"
        )

    def closeEvent(self, event):
        if self.device_worker is not None:
            self.device_worker.request_stop()
            self.device_worker.wait(2000)
        event.accept()

    def _create_channel_plots(self):
        self.time_axis = TimeAxisItem()
        self.logic_plot = self.plot_area.addPlot(
            row=0,
            col=0,
            axisItems={"bottom": self.time_axis},
        )
        self.time_axis.set_frequency(None)
        self.logic_plot.showGrid(x=True, y=False, alpha=0.25)
        self.logic_plot.setMouseEnabled(x=True, y=False)

        view = self.logic_plot.getViewBox()
        view.enableAutoRange(x=False, y=False)

        self.channel_curves = []
        colors = [
            "#4FC3F7", "#81C784", "#FFB74D", "#E57373",
            "#BA68C8", "#4DB6AC", "#F06292", "#DCE775",
        ]

        for channel in range(8):
            curve = self.logic_plot.plot(
                [],
                [],
                pen=pg.mkPen(colors[channel], width=1.6),
                name=f"CH{channel}",
            )
            self.channel_curves.append(curve)

        self._plot_x_values = np.array([], dtype=np.int64)
        self._plot_channel_bits = [
            np.array([], dtype=np.float64) for _ in range(8)
        ]
        self.channel_separators = []
        self._refresh_channel_layout()
        self.logic_plot.setXRange(0, 100, padding=0)

        self.cursor_line = pg.InfiniteLine(
            pos=0,
            angle=90,
            movable=True,
            pen=pg.mkPen("#FFFFFF", width=1, style=pg.QtCore.Qt.PenStyle.DashLine),
        )
        self.cursor_line.setVisible(False)
        self.cursor_line.sigPositionChanged.connect(self._update_cursor_readout)
        self.logic_plot.addItem(self.cursor_line)

        self.marker_a_line = pg.InfiniteLine(
            pos=0,
            angle=90,
            movable=True,
            pen=pg.mkPen("#FFFFFF", width=1, style=Qt.PenStyle.DashLine),
            label="A",
            labelOpts={"position": 0.1, "color": "#FFFFFF"},
        )
        self.marker_b_line = pg.InfiniteLine(
            pos=0,
            angle=90,
            movable=True,
            pen=pg.mkPen("#FF5252", width=1, style=Qt.PenStyle.DashLine),
            label="B",
            labelOpts={"position": 0.9, "color": "#FF5252"},
        )
        self.marker_a_line.setVisible(False)
        self.marker_b_line.setVisible(False)
        self.logic_plot.addItem(self.marker_a_line)
        self.logic_plot.addItem(self.marker_b_line)

        self.plot_area.ci.layout.setContentsMargins(8, 8, 8, 8)

    def _show_demo_waveform(self):
        if self._capture_active:
            return

        sample_count = 256
        samples = bytearray()
    
        # Mỗi kênh đổi trạng thái với chu kỳ khác nhau.
        for index in range(sample_count):
            sample = 0
    
            for channel in range(8):
                half_period = 1 << channel
                if (index // half_period) % 2:
                    sample |= 1 << channel
    
            samples.append(sample)
    
        self._capture_samples = samples
        self._capture_frequency_hz = None
        self._capture_metadata_available = False
        self._marker_edges_cache_key = None
        self._set_waveform_navigation_enabled(True)
        self.time_axis.set_frequency(None)
        self.save_button.setEnabled(False)
        self.clear_button.setEnabled(True)
        self.cursor_button.setEnabled(True)
        self.markers_button.setEnabled(True)
        self.cursor_button.setChecked(False)
        self.markers_button.setChecked(False)
        self.cursor_line.setVisible(False)
        self.marker_a_line.setVisible(False)
        self.marker_b_line.setVisible(False)
        self.cursor_readout.setText("Cursor: off")
        self.marker_readout.setText("Markers: off")
        self.marker_channel_combo.setEnabled(False)
        self._plot_samples(samples)
        self.logic_plot.setXRange(0, len(samples), padding=0)
        self.status_label.setText("Demo waveform (simulated data)")
        self.progress.setValue(100)

    def _set_waveform_navigation_enabled(self, enabled: bool):
        self.zoom_in_button.setEnabled(enabled)
        self.zoom_out_button.setEnabled(enabled)
        self.fit_button.setEnabled(enabled)

    def _zoom_x(self, factor: float):
        if not self._capture_samples:
            return

        view = self.logic_plot.getViewBox()
        current_range = view.viewRange()[0]
        center = (current_range[0] + current_range[1]) / 2
        half_width = (current_range[1] - current_range[0]) * factor / 2
        max_sample = len(self._capture_samples)
        half_width = min(half_width, max_sample / 2)
        half_width = max(half_width, 0.5)
        left = max(0, center - half_width)
        right = min(max_sample, center + half_width)

        if right - left < half_width * 2:
            if left == 0:
                right = min(max_sample, half_width * 2)
            elif right == max_sample:
                left = max(0, max_sample - half_width * 2)

        self.logic_plot.setXRange(left, max(left + 1, right), padding=0)

    def _fit_waveform(self):
        if self._capture_samples:
            self.logic_plot.setXRange(
                0,
                max(1, len(self._capture_samples)),
                padding=0,
            )
        else:
            self.logic_plot.setXRange(0, 100, padding=0)

    def _toggle_cursor(self, enabled: bool):
        if not self._capture_samples:
            self.cursor_button.setChecked(False)
            self._update_measurement_controls_visibility()
            return

        self.cursor_line.setVisible(enabled)
        if enabled:
            self.cursor_line.setBounds((0, len(self._capture_samples)))
            left, right = self.logic_plot.getViewBox().viewRange()[0]
            sample_index = min(
                max(round((left + right) / 2), 0),
                len(self._capture_samples) - 1,
            )
            self.cursor_line.setPos(sample_index)
            self._update_cursor_readout()
        else:
            self.cursor_readout.setText("Cursor: off")
        self._update_measurement_controls_visibility()

    def _update_measurement_controls_visibility(self):
        cursor_enabled = self.cursor_button.isChecked()
        markers_enabled = self.markers_button.isChecked()
        self.cursor_readout.setVisible(cursor_enabled)
        self.marker_channel_label.setVisible(markers_enabled)
        self.marker_channel_combo.setVisible(markers_enabled)
        self.marker_readout.setVisible(markers_enabled)
        self.measurement_controls.setVisible(
            cursor_enabled or markers_enabled
        )

    def _update_cursor_readout(self):
        if not self.cursor_button.isChecked() or not self._capture_samples:
            return

        sample_index = round(self.cursor_line.value())
        sample_index = min(
            max(sample_index, 0),
            len(self._capture_samples) - 1,
        )
        sample_value = self._capture_samples[sample_index]
        detail = (
            format_time(sample_index / self._capture_frequency_hz)
            if self._capture_frequency_hz is not None
            else "time unavailable for simulated data"
        )
        self.cursor_readout.setText(
            f"Cursor: sample {sample_index:,} | {detail} | "
            f"value 0x{sample_value:02X}"
        )

    def _toggle_markers(self, enabled: bool):
        if not self._capture_samples:
            self.markers_button.setChecked(False)
            self._update_measurement_controls_visibility()
            return

        self.marker_a_line.setVisible(enabled)
        self.marker_b_line.setVisible(enabled)
        self.marker_channel_combo.setEnabled(enabled)
        if not enabled:
            self.marker_readout.setText("Markers: off")
            self._update_measurement_controls_visibility()
            return

        left, right = self.logic_plot.getViewBox().viewRange()[0]
        if right <= left:
            left, right = 0, len(self._capture_samples)
        self.marker_a_line.setBounds((0, len(self._capture_samples) - 1))
        self.marker_b_line.setBounds((0, len(self._capture_samples) - 1))
        self.marker_a_line.setPos(left + (right - left) * 0.25)
        self.marker_b_line.setPos(left + (right - left) * 0.75)
        self._snap_marker(self.marker_a_line)
        self._snap_marker(self.marker_b_line)
        self._update_marker_readout()
        self._update_measurement_controls_visibility()

    def _on_marker_channel_changed(self, index: int):
        channel = self.marker_channel_combo.itemData(index)
        if channel is None:
            return

        self._marker_channel = channel
        self._marker_edges_cache_key = None
        if self.markers_button.isChecked():
            self._snap_marker(self.marker_a_line)
            self._snap_marker(self.marker_b_line)
            self._update_marker_readout()

    def _on_marker_moved(self, marker: pg.InfiniteLine):
        if self._marker_snap_active or not self.markers_button.isChecked():
            return

        self._snap_marker(marker)
        self._update_marker_readout()

    def _snap_marker(self, marker: pg.InfiniteLine):
        if not self._capture_samples:
            return

        requested_index = min(
            max(round(marker.value()), 0),
            len(self._capture_samples) - 1,
        )
        edges = self._get_marker_edges()
        if not edges:
            snapped_index = requested_index
        else:
            plot_width = max(
                self.logic_plot.getViewBox().sceneBoundingRect().width(),
                1.0,
            )
            view_range = self.logic_plot.getViewBox().viewRange()[0]
            samples_per_pixel = (
                view_range[1] - view_range[0]
            ) / plot_width
            snap_distance = max(1, int(samples_per_pixel * 12))
            nearest_edge, _ = min(
                edges,
                key=lambda edge: abs(edge[0] - requested_index),
            )
            snapped_index = (
                nearest_edge
                if abs(nearest_edge - requested_index) <= snap_distance
                else requested_index
            )

        self._marker_snap_active = True
        marker.setPos(snapped_index)
        self._marker_snap_active = False

    def _update_marker_readout(self):
        if not self.markers_button.isChecked() or not self._capture_samples:
            return

        index_a = min(
            max(round(self.marker_a_line.value()), 0),
            len(self._capture_samples) - 1,
        )
        index_b = min(
            max(round(self.marker_b_line.value()), 0),
            len(self._capture_samples) - 1,
        )
        edges = self._get_marker_edges()
        edge_map = dict(edges)
        delta_samples = abs(index_b - index_a)
        delta_text = f"{delta_samples:,} samples"
        if self._capture_frequency_hz is not None:
            delta_text += (
                f", {format_time(delta_samples / self._capture_frequency_hz)}"
            )

        def describe_marker(name: str, index: int) -> str:
            direction = edge_map.get(index)
            edge_name = (
                "rising" if direction else "falling"
            ) if direction is not None else "not on edge"
            return f"{name}={index:,} ({edge_name})"

        channel_item = self._channel_item_for(self._marker_channel)
        channel_name = channel_item.text().strip() or f"CH{self._marker_channel}"
        self.marker_readout.setText(
            f"{channel_name}: "
            f"{describe_marker('A', index_a)}, "
            f"{describe_marker('B', index_b)} | Δ={delta_text}"
        )

    def _get_marker_edges(self) -> list[tuple[int, bool]]:
        cache_key = (
            id(self._capture_samples),
            len(self._capture_samples),
            self._marker_channel,
        )
        if self._marker_edges_cache_key != cache_key:
            self._marker_edges_cache = find_channel_edges(
                self._capture_samples,
                self._marker_channel,
            )
            self._marker_edges_cache_key = cache_key
        return self._marker_edges_cache

    def _clear_dashboard(self):
        if self._capture_active:
            return

        self._capture_samples.clear()
        self._capture_frequency_hz = None
        self._capture_metadata_available = False
        self._marker_edges_cache_key = None
        self._set_waveform_navigation_enabled(False)
        self._clear_waveform()
        self.time_axis.set_frequency(None)
        self.cursor_line.setVisible(False)
        self.marker_a_line.setVisible(False)
        self.marker_b_line.setVisible(False)
        self.cursor_button.setChecked(False)
        self.markers_button.setChecked(False)
        self.marker_channel_combo.setEnabled(False)
        self.cursor_button.setEnabled(False)
        self.markers_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.progress.setValue(0)
        self.cursor_readout.setText("Cursor: off")
        self.marker_readout.setText("Markers: off")
        self.logic_plot.setXRange(0, 100, padding=0)
        self.status_label.setText("Dashboard cleared")
    
    
    def _plot_samples(self, samples, start_index: int = 0):
        if not samples:
            return

        sample_values = np.frombuffer(samples, dtype=np.uint8)
        self._plot_x_values = np.repeat(
            np.arange(start_index, start_index + len(sample_values)),
            2,
        )
        self._plot_x_values[1::2] += 1

        for channel, curve in enumerate(self.channel_curves):
            is_high = (sample_values >> channel) & 1
            self._plot_channel_bits[channel] = np.repeat(is_high, 2)

        self._refresh_channel_layout()