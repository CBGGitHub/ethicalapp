"""The Converter's "✂ Trim video" tab: keep part of a video, optionally smaller, rotated or without sound."""
import os
import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox, QProgressBar, QPushButton, QSlider, QVBoxLayout, QWidget)
from PySide6.QtCore import QUrl

import convert_core as cc

VIDEO_FILTER = "Videos (*.mp4 *.mov *.mkv *.avi *.webm *.wmv *.m4v *.mts *.m2ts *.3gp *.flv *.mpg *.mpeg);;All files (*)"


def clock(t):
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return (f"{int(h)}:{int(m):02d}:{s:04.1f}" if h else f"{int(m)}:{s:04.1f}")


class TrimTab(QWidget):
    frame_ready = Signal(float, bytes)
    progress = Signal(float)
    finished = Signal(bool, str)

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.path = None
        self.duration = 0.0
        self.cancel = threading.Event()
        self.busy = False
        self._want = None                 # newest time the preview should show
        self._fetching = False
        self.setAcceptDrops(True)
        self.frame_ready.connect(self._show_frame)
        self.progress.connect(lambda p: self.bar.setValue(int(p)))
        self.finished.connect(self._done)

        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        top = QHBoxLayout()
        self.open_btn = QPushButton("📂  Open a video…")
        self.open_btn.clicked.connect(self.open_dialog)
        top.addWidget(self.open_btn)
        self.name = QLabel("…or drop a video here.")
        self.name.setWordWrap(True)
        top.addWidget(self.name, 1)
        left.addLayout(top)
        self.preview = QLabel("No video yet")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(420, 236)
        self.preview.setStyleSheet("background: #1e1f22; color: #aaa; border-radius: 6px;")
        left.addWidget(self.preview, 1)
        srow = QHBoxLayout()
        self.pos_label = QLabel("0:00.0")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._scrubbed)
        srow.addWidget(self.slider, 1)
        srow.addWidget(self.pos_label)
        left.addLayout(srow)
        lay.addLayout(left, 3)

        right = QGridLayout()
        right.setVerticalSpacing(8)
        self.start = QDoubleSpinBox()
        self.end = QDoubleSpinBox()
        for sb in (self.start, self.end):
            sb.setDecimals(1)
            sb.setSuffix(" s")
            sb.setSingleStep(0.5)
            sb.setEnabled(False)
            sb.valueChanged.connect(self._range_changed)
        set_start = QPushButton("⇤ Start here")
        set_start.setToolTip("Use the frame on the slider as the start")
        set_start.clicked.connect(lambda: self.start.setValue(self.slider.value() / 10))
        set_end = QPushButton("End here ⇥")
        set_end.setToolTip("Use the frame on the slider as the end")
        set_end.clicked.connect(lambda: self.end.setValue(self.slider.value() / 10))
        self.set_buttons = [set_start, set_end]
        right.addWidget(QLabel("Start"), 0, 0)
        right.addWidget(self.start, 0, 1)
        right.addWidget(set_start, 0, 2)
        right.addWidget(QLabel("End"), 1, 0)
        right.addWidget(self.end, 1, 1)
        right.addWidget(set_end, 1, 2)
        self.keep = QLabel("")
        self.keep.setStyleSheet("font-weight: 600;")
        right.addWidget(self.keep, 2, 0, 1, 3)
        self.mode = QComboBox()
        self.mode.addItem("Fast – no quality loss (cuts at the nearest keyframe)", False)
        self.mode.addItem("Exact – cuts on the exact frame (slower)", True)
        right.addWidget(QLabel("Cut"), 3, 0)
        right.addWidget(self.mode, 3, 1, 1, 2)
        self.size = QComboBox()
        for label, h in (("Keep the size", 0), ("1080p", 1080), ("720p", 720), ("480p", 480)):
            self.size.addItem(label, h)
        right.addWidget(QLabel("Size"), 4, 0)
        right.addWidget(self.size, 4, 1, 1, 2)
        self.rotate = QComboBox()
        for label, deg in (("Don't rotate", 0), ("90° right", 90), ("90° left", 270), ("180°", 180)):
            self.rotate.addItem(label, deg)
        right.addWidget(QLabel("Rotate"), 5, 0)
        right.addWidget(self.rotate, 5, 1, 1, 2)
        self.mute = QCheckBox("Remove the sound")
        right.addWidget(self.mute, 6, 1, 1, 2)
        self.note = QLabel("Changing the size or rotating always uses Exact.")
        self.note.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        self.note.setWordWrap(True)
        right.addWidget(self.note, 7, 0, 1, 3)
        self.bar = QProgressBar()
        self.bar.setValue(0)
        right.addWidget(self.bar, 8, 0, 1, 3)
        brow = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel.set)
        self.save_btn = QPushButton("✂  Save trimmed video")
        self.save_btn.setEnabled(False)
        self.save_btn.setMinimumHeight(36)
        self.save_btn.setStyleSheet("QPushButton { background: #2e7d32; color: white; font-weight: bold; border-radius: 5px;"
                                    " padding: 6px 14px; } QPushButton:disabled { background: #9e9e9e; }")
        self.save_btn.clicked.connect(self.save)
        brow.addWidget(self.cancel_btn)
        brow.addWidget(self.save_btn, 1)
        right.addLayout(brow, 9, 0, 1, 3)
        right.setRowStretch(10, 1)
        lay.addLayout(right, 2)

    # ---- loading
    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open a video", os.path.expanduser("~"), VIDEO_FILTER)
        if p:
            self.load(p)

    def load(self, path):
        info = cc.probe(path)
        if not info.get("video") or info.get("duration", 0) <= 0:
            QMessageBox.warning(self, "Trim video", f"{os.path.basename(path)} doesn't look like a video.")
            return
        self.path, self.duration = path, info["duration"]
        self.name.setText(f"<b>{os.path.basename(path)}</b><br>{clock(self.duration)} · {info['width']}×{info['height']}")
        for sb in (self.start, self.end):
            sb.blockSignals(True)
            sb.setRange(0, round(self.duration, 1))
            sb.setEnabled(True)
            sb.blockSignals(False)
        self.start.setValue(0)
        self.end.setValue(round(self.duration, 1))
        self.slider.setRange(0, int(self.duration * 10))
        self.slider.setEnabled(True)
        self.slider.setValue(0)
        self.save_btn.setEnabled(True)
        self._range_changed()
        self._request(0.0)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.load(urls[0])

    # ---- preview frames (fetched in the background, newest request wins)
    def _scrubbed(self, v):
        self.pos_label.setText(clock(v / 10))
        self._request(v / 10)

    def _request(self, t):
        self._want = t
        if not self._fetching:
            self._fetch_next()

    def _fetch_next(self):
        if self._want is None or not self.path:
            self._fetching = False
            return
        t, self._want, path = self._want, None, self.path
        self._fetching = True

        def work():
            self.frame_ready.emit(t, cc.video_frame(path, min(t, max(0.0, self.duration - 0.05))))
        threading.Thread(target=work, daemon=True).start()

    def _show_frame(self, t, data):
        pm = QPixmap()
        if data and pm.loadFromData(data):
            self.preview.setPixmap(pm.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._fetching = False
        QTimer.singleShot(0, self._fetch_next)

    def _range_changed(self):
        s, e = self.start.value(), self.end.value()
        if e <= s:
            self.keep.setText("⚠ The end must be after the start.")
            self.save_btn.setEnabled(False)
        else:
            self.keep.setText(f"Keeping {clock(s)} → {clock(e)}  ({clock(e - s)})")
            self.save_btn.setEnabled(bool(self.path) and not self.busy)
        sender = self.sender()
        if sender in (self.start, self.end):
            self.slider.blockSignals(True)
            self.slider.setValue(int(sender.value() * 10))
            self.slider.blockSignals(False)
            self.pos_label.setText(clock(sender.value()))
            self._request(sender.value())

    # ---- saving
    def save(self):
        if not self.path or self.busy:
            return
        folder = None
        if self.win.other_folder.isChecked() and self.win.folder_edit.text().strip():
            folder = self.win.folder_edit.text().strip()
            os.makedirs(folder, exist_ok=True)
        s, e = self.start.value(), self.end.value()
        opts = dict(exact=self.mode.currentData(), max_h=self.size.currentData(), rotate=self.rotate.currentData(),
                    mute=self.mute.isChecked())
        self.busy = True
        self.cancel.clear()
        self.save_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.bar.setValue(0)
        path = self.path

        def work():
            try:
                dst = cc.trim_video(path, s, e, folder, self.progress.emit, self.cancel, **opts)
                self.finished.emit(True, dst)
            except cc.Cancelled:
                self.finished.emit(False, "Cancelled.")
            except Exception as ex:                       # FFmpeg problems etc. - show them
                self.finished.emit(False, str(ex))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, ok, msg):
        self.busy = False
        self.cancel_btn.setEnabled(False)
        self._range_changed()
        if ok:
            self.bar.setValue(100)
            size = os.path.getsize(msg)
            self.keep.setText(f"✓ Saved {os.path.basename(msg)} ({cc.human(size)})")
            if self.win.open_when_done.isChecked():
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(msg)))
        else:
            self.bar.setValue(0)
            if msg != "Cancelled.":
                QMessageBox.warning(self, "Trim video", msg)
            else:
                self.keep.setText("Cancelled.")
