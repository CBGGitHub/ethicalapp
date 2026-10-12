"""Ethical Converter - convert, compress, combine and (un)zip files in batches."""
import os
import subprocess
import sys
import threading
import time

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPlainTextEdit,
                               QProgressBar, QPushButton, QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QTabWidget, QToolButton, QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert_core as cc  # noqa: E402
import download_core as dc  # noqa: E402
from suite_common import SETTINGS_ORG, SUITE_NAME, make_app  # noqa: E402
from suite_common import add_guide_action  # noqa: E402
from i18n import N_, add_items, tr  # noqa: E402

APP_NAME = "Ethical Converter"
COL_FILE, COL_TYPE, COL_SIZE, COL_TARGET, COL_STATUS, COL_RESULT = range(6)
TYPE_COLORS = {"audio": "#7B3FA0", "video": "#C0392B", "image": "#1E8449", "document": "#2471A3",
               "archive": "#B7950B", "other": "#666666"}


class Runner(QObject):
    """Runs jobs one after another; heavy ones in a background thread."""
    progress = Signal(int, float)
    finished_job = Signal(int, bool, str, list)
    all_done = Signal()

    def __init__(self):
        super().__init__()
        self.cancel = threading.Event()
        self.queue = []
        self.running = False
        self.finished_job.connect(lambda *_: QTimer.singleShot(0, self._next))

    def start(self, jobs):
        self.queue = list(jobs)
        self.cancel.clear()
        self.running = True
        self._next()

    def stop(self):
        self.cancel.set()

    def _next(self):
        if not self.queue or self.cancel.is_set():
            if self.running:
                self.running = False
                self.queue = []
                self.all_done.emit()
            return
        row, fn, gui = self.queue.pop(0)
        if gui:
            self._run(row, fn)
        else:
            threading.Thread(target=self._run, args=(row, fn), daemon=True).start()

    def _run(self, row, fn):
        try:
            outs = fn(lambda pct: self.progress.emit(row, float(pct)), self.cancel)
            self.finished_job.emit(row, True, "Done", outs or [])
        except cc.Cancelled:
            self.finished_job.emit(row, False, "Cancelled", [])
        except Exception as ex:
            self.finished_job.emit(row, False, str(ex) or ex.__class__.__name__, [])


class FileTable(QTableWidget):
    def __init__(self, win):
        super().__init__(0, 6)
        self.win = win
        self.setHorizontalHeaderLabels([tr("File"), tr("Type"), tr("Size"), tr("Convert to"), tr("Status"), tr("Result")])
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(COL_FILE, QHeaderView.Stretch)
        for c, w in ((COL_TYPE, 80), (COL_SIZE, 80), (COL_TARGET, 230), (COL_STATUS, 170), (COL_RESULT, 140)):
            hh.setSectionResizeMode(c, QHeaderView.Interactive)
            self.setColumnWidth(c, w)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setAlternatingRowColors(True)
        self.setStyleSheet("QTableWidget { font-size: 13px; }")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dropEvent(self, e):
        self.win.add_paths([u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()])
        e.acceptProposedAction()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.rowCount() == 0:
            from PySide6.QtGui import QPainter
            p = QPainter(self.viewport())
            p.setPen(QColor("#888"))
            f = QFont()
            f.setPointSize(14)
            p.setFont(f)
            p.drawText(self.viewport().rect(), Qt.AlignCenter,
                       tr("Drag files or folders here\n\nor click  “Add Files…”\n\n"
                          "Audio · Video · Pictures · PDF · Word · PowerPoint · Excel · Zip"))


class DownloadTab(QWidget):
    """Paste links (YouTube, X/Twitter, TikTok, Vimeo…) and download video or audio - with safety checks."""
    progress = Signal(int, float, str)
    finished_one = Signal(int, bool, str, list, list)
    info_ready = Signal(int, object)

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cancel = threading.Event()
        self.queue = []
        self.running = False
        self.progress.connect(self._on_progress)
        self.finished_one.connect(self._on_finished)
        self.info_ready.connect(self._on_info)

        self.links = QPlainTextEdit()
        self.links.setPlaceholderText(tr("Paste one or more links here, one per line — "
                                         "e.g.\nhttps://www.youtube.com/watch?v=…\nhttps://x.com/…/status/…\nhttps://vimeo.com/…"))
        self.links.setMaximumHeight(90)
        lrow = QHBoxLayout()
        paste = QPushButton(tr("📋 Paste"))
        paste.clicked.connect(self._paste)
        check = QPushButton(tr("🔎 Check Links"))
        check.setToolTip(tr("Look up the titles without downloading"))
        check.clicked.connect(self.check_links)
        lrow.addWidget(paste)
        lrow.addWidget(check)
        lrow.addStretch()

        opts = QHBoxLayout()
        self.what = QComboBox()
        self.what.addItems(["Video", "Audio only"])
        self.what.currentIndexChanged.connect(self._mode_changed)
        self.quality = QComboBox()
        self.quality.addItems(list(dc.QUALITIES))
        self.quality.setCurrentText("1080p")
        self.container = QComboBox()
        self.container.addItems(["MP4 (plays everywhere)", "Best quality (MKV)"])
        self.audio_fmt = QComboBox()
        self.audio_fmt.addItems(["MP3", "M4A", "OPUS", "WAV", "FLAC"])
        for label, w in (("Download:", self.what), ("Quality:", self.quality), ("Format:", self.container),
                         ("Audio format:", self.audio_fmt)):
            opts.addWidget(QLabel(label))
            opts.addWidget(w)
        self.playlist = QCheckBox(tr("Whole playlist / channel list (max 200)"))
        opts.addWidget(self.playlist)
        opts.addStretch()

        safe = QHBoxLayout()
        self.scan = QCheckBox(tr("Virus-scan every download with Microsoft Defender"))
        self.scan.setChecked(True)
        if not dc.defender_path():
            self.scan.setChecked(False)
            self.scan.setEnabled(False)
            self.scan.setText(tr("Virus scan: Microsoft Defender not available on this PC"))
        self.add_to_list = QCheckBox(tr("Add finished downloads to the file list (to convert / compress)"))
        safe.addWidget(self.scan)
        safe.addWidget(self.add_to_list)
        safe.addStretch()

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Link", "Title", "Status", "Saved as"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(2, 230)
        self.table.setColumnWidth(3, 220)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)

        btns = QHBoxLayout()
        note = QLabel(tr("🛡 Safety: only web links; files are quarantined, must be genuine audio/video (programs, "
                         "archives and web pages are blocked), then virus-scanned before they're saved. Nothing "
                         "downloaded is ever opened or run.<br>⚖ Only download videos you have the right to — your "
                         "own, or ones the creator allows (e.g. Creative Commons). Many sites' terms, including "
                         "YouTube's, don't allow downloading."))
        note.setWordWrap(True)
        note.setTextFormat(Qt.RichText)
        note.setStyleSheet("color: #555; font-size: 12px;")
        upd = QPushButton(tr("Update Downloader"))
        upd.setToolTip(tr("Websites change often - updating keeps downloads working"))
        upd.clicked.connect(self.update_downloader)
        self.cancel_btn = QPushButton(tr("Cancel"))
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel.set)
        self.go = QPushButton(tr("⬇  Download"))
        self.go.setMinimumHeight(40)
        self.go.setMinimumWidth(160)
        self.go.setStyleSheet("QPushButton { background: #1565c0; color: white; font-size: 15px; font-weight: bold;"
                              " border-radius: 5px; padding: 6px 18px; } QPushButton:disabled { background: #9e9e9e; }")
        self.go.clicked.connect(self.start)
        btns.addWidget(note, 1)
        btns.addWidget(upd)
        btns.addWidget(self.cancel_btn)
        btns.addWidget(self.go)

        lay = QVBoxLayout(self)
        lay.addWidget(self.links)
        lay.addLayout(lrow)
        lay.addLayout(opts)
        lay.addLayout(safe)
        lay.addWidget(self.table, 1)
        lay.addLayout(btns)
        self._mode_changed()

    def _mode_changed(self, *_):
        audio = self.what.currentIndex() == 1
        self.quality.setEnabled(not audio)
        self.container.setEnabled(not audio)
        self.audio_fmt.setEnabled(audio)

    def _paste(self):
        from PySide6.QtGui import QGuiApplication
        text = QGuiApplication.clipboard().text().strip()
        if text:
            cur = self.links.toPlainText().strip()
            self.links.setPlainText((cur + "\n" if cur else "") + text)

    def _urls(self):
        return [u.strip() for u in self.links.toPlainText().split() if u.strip()]

    def _fill_rows(self):
        urls = self._urls()
        self.table.setRowCount(0)
        for u in urls:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(u))
            self.table.setItem(r, 1, QTableWidgetItem(""))
            bar = QProgressBar()
            bar.setFormat(tr("Waiting"))
            bar.setValue(0)
            self.table.setCellWidget(r, 2, bar)
            self.table.setItem(r, 3, QTableWidgetItem(""))
        return urls

    def check_links(self):
        urls = self._fill_rows()
        for r, u in enumerate(urls):
            self.table.cellWidget(r, 2).setFormat(tr("Checking…"))
            threading.Thread(target=self._info_worker, args=(r, u), daemon=True).start()

    def _info_worker(self, r, u):
        try:
            self.info_ready.emit(r, dc.get_info(u))
        except Exception as ex:
            self.info_ready.emit(r, ex)

    def _on_info(self, r, info):
        if r >= self.table.rowCount():
            return
        bar = self.table.cellWidget(r, 2)
        if isinstance(info, Exception):
            bar.setFormat("✖ " + str(info).replace("ERROR: ", "")[:120])
            bar.setToolTip(str(info))
            return
        dur = info.get("duration")
        extra = f" · {int(dur) // 60}:{int(dur) % 60:02d}" if dur else ""
        extra += f" · {info['count']} videos" if info.get("playlist") else ""
        self.table.item(r, 1).setText(f"{info['title']}" + (f"  —  {info['uploader']}" if info['uploader'] else "") + extra)
        bar.setFormat(tr("Ready ({v})").format(v=info['site']))

    def start(self):
        urls = self._urls()
        if not urls:
            QMessageBox.information(self, APP_NAME, tr("Paste a link first."))
            return
        if self.table.rowCount() != len(urls) or any(self.table.item(r, 0).text() != u for r, u in enumerate(urls)):
            self._fill_rows()
        folder = self.win.download_folder()
        audio = self.what.currentIndex() == 1
        kw = dict(mode="audio" if audio else "video", quality=dc.QUALITIES[self.quality.currentText()],
                  audio_format=self.audio_fmt.currentText().lower(),
                  container="mp4" if self.container.currentIndex() == 0 else "mkv",
                  playlist=self.playlist.isChecked(), scan=self.scan.isChecked())
        self.queue = [(r, u) for r, u in enumerate(urls)]
        self.cancel.clear()
        self.running = True
        self.saved_all = []
        self.go.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.folder, self.kw = folder, kw
        self._next()

    def _next(self):
        if not self.queue or self.cancel.is_set():
            self.running = False
            self.go.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            if self.cancel.is_set():
                for r, _ in self.queue:
                    self.table.cellWidget(r, 2).setFormat(tr("Cancelled"))
                self.queue = []
            if self.saved_all:
                if self.add_to_list.isChecked():
                    self.win.add_paths(self.saved_all)
                if self.win.open_when_done.isChecked() and not self.cancel.is_set():
                    try:
                        subprocess.Popen(["explorer", "/select,", os.path.normpath(self.saved_all[0])])
                    except Exception:
                        pass
            return
        r, u = self.queue.pop(0)
        self.table.cellWidget(r, 2).setFormat(tr("Starting…"))
        threading.Thread(target=self._worker, args=(r, u), daemon=True).start()

    def _worker(self, r, u):
        try:
            saved, notes = dc.download(u, self.folder, progress=lambda p, t: self.progress.emit(r, p, t),
                                       cancel=self.cancel, **self.kw)
            self.finished_one.emit(r, True, "", saved, notes)
        except cc.Cancelled:
            self.finished_one.emit(r, False, "Cancelled", [], [])
        except dc.Blocked as ex:
            self.finished_one.emit(r, False, "🛡 " + str(ex), [], [])
        except Exception as ex:
            self.finished_one.emit(r, False, str(ex) or ex.__class__.__name__, [], [])

    def _on_progress(self, r, pct, text):
        bar = self.table.cellWidget(r, 2)
        if bar is None:
            return
        if pct < 0:
            bar.setRange(0, 0)   # busy indicator
        else:
            bar.setRange(0, 100)
            bar.setValue(int(pct))
        bar.setFormat(text)

    def _on_finished(self, r, ok, msg, saved, notes):
        bar = self.table.cellWidget(r, 2)
        bar.setRange(0, 100)
        if ok:
            bar.setValue(100)
            scanned = self.kw["scan"] and "Defender scan unavailable" not in notes
            bar.setFormat(tr("✔ Done") + (tr(" · scanned clean") if scanned else ""))
            bar.setStyleSheet("QProgressBar::chunk { background: #43a047; }")
            blocked = [n for n in notes if n != "Defender scan unavailable"]
            item = self.table.item(r, 3)
            item.setText(os.path.basename(saved[0]) + (tr("  (+{v} more)").format(v=len(saved) - 1) if len(saved) > 1 else ""))
            item.setToolTip("\n".join(saved + blocked))
            if not self.table.item(r, 1).text():
                self.table.item(r, 1).setText(os.path.splitext(os.path.basename(saved[0]))[0])
            self.saved_all.extend(saved)
        else:
            bar.setValue(0)
            bar.setFormat(("✖ " if msg != "Cancelled" else "") + tr(msg)[:150])
            bar.setToolTip(msg)
            bar.setStyleSheet("QProgressBar { color: #b71c1c; }")
        QTimer.singleShot(0, self._next)

    def update_downloader(self):
        self.go.setEnabled(False)
        self.win.statusBar().showMessage(tr("Updating the downloader…"))

        def work():
            ok, msg = dc.update_downloader()
            QTimer.singleShot(0, lambda: (self.go.setEnabled(True), self.win.statusBar().clearMessage(),
                                          QMessageBox.information(self, APP_NAME, msg)))
        threading.Thread(target=work, daemon=True).start()


class ConverterWindow(QMainWindow):
    def __init__(self, paths=None):
        super().__init__()
        self.settings = QSettings(SETTINGS_ORG, APP_NAME)
        self.files = []
        self.runner = Runner()
        self.runner.progress.connect(self._on_progress)
        self.runner.finished_job.connect(self._on_finished)
        self.runner.all_done.connect(self._on_all_done)
        self.outputs = []
        self.included = set()
        self.setWindowTitle(APP_NAME)
        self.resize(1250, 780)
        self.setAcceptDrops(True)

        self.table = FileTable(self)
        top = QHBoxLayout()
        for text, slot in ((tr("Add Files…"), self.add_files_dialog), (tr("Add Folder…"), self.add_folder_dialog),
                           (tr("Remove"), self.remove_selected), (tr("Clear"), self.clear)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            top.addWidget(b)
        top.addStretch()
        self.count_label = QLabel()
        top.addWidget(self.count_label)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._convert_tab(), tr("  Convert  "))
        self.tabs.addTab(self._compress_tab(), tr("  Compress (make smaller)  "))
        self.tabs.addTab(self._combine_tab(), tr("  Combine  "))
        self.tabs.addTab(self._archive_tab(), tr("  Zip / Unzip  "))
        from trim_tab import TrimTab     # tabs 0-3 are the list-based jobs; the ones after have their own page
        self.trim_tab = TrimTab(self)
        self.tabs.addTab(self.trim_tab, tr("  ✂ Trim video  "))
        self.download_tab = None
        if dc.available():   # public builds don't include the downloader
            self.download_tab = DownloadTab(self)
            self.tabs.addTab(self.download_tab, tr("  ⬇ Download from Link  "))
        self.tabs.currentChanged.connect(lambda _: self._refresh_rows())
        self.tabs.currentChanged.connect(self._tab_switched)

        out = QGroupBox(tr("Save results to"))
        ol = QHBoxLayout(out)
        self.same_folder = QRadioButton(tr("Same folder as each file"))
        self.other_folder = QRadioButton(tr("This folder:"))
        self.same_folder.setChecked(self.settings.value("out_mode", "same") == "same")
        self.other_folder.setChecked(not self.same_folder.isChecked())
        self.folder_edit = QLineEdit(self.settings.value("out_folder", os.path.join(os.path.expanduser("~"), "Desktop")))
        browse = QPushButton(tr("Browse…"))
        browse.clicked.connect(self._pick_folder)
        self.open_when_done = QCheckBox(tr("Open the folder when finished"))
        self.open_when_done.setChecked(self.settings.value("open_done", "true") == "true")
        for w in (self.same_folder, self.other_folder, self.folder_edit, browse, self.open_when_done):
            ol.addWidget(w)

        bottom = QHBoxLayout()
        self.overall = QProgressBar()
        self.overall.setTextVisible(True)
        self.overall.setFormat(tr("Ready"))
        self.overall.setValue(0)
        bottom.addWidget(self.overall, 1)
        self.cancel_btn = QPushButton(tr("Cancel"))
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.runner.stop)
        self.start_btn = QPushButton(tr("▶  Start"))
        self.start_btn.setMinimumHeight(40)
        self.start_btn.setMinimumWidth(160)
        self.start_btn.setStyleSheet("QPushButton { background: #2e7d32; color: white; font-size: 15px; font-weight: bold;"
                                     " border-radius: 5px; padding: 6px 18px; } QPushButton:disabled { background: #9e9e9e; }")
        self.start_btn.clicked.connect(self.start)
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.start_btn)

        central = QWidget()
        lay = QVBoxLayout(central)
        self.files_box = QWidget()
        fl = QVBoxLayout(self.files_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addLayout(top)
        fl.addWidget(self.table, 1)
        self.bottom_box = QWidget()
        self.bottom_box.setLayout(bottom)
        bottom.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.files_box, 1)
        lay.addWidget(self.tabs)
        lay.addWidget(out)
        lay.addWidget(self.bottom_box)
        self.main_layout = lay
        self.setCentralWidget(central)

        mb = self.menuBar()
        f = mb.addMenu(tr("&File"))
        for text, slot, sc in ((tr("Add &Files…"), self.add_files_dialog, "Ctrl+O"),
                               (tr("Add F&older…"), self.add_folder_dialog, None),
                               (tr("&Clear List"), self.clear, None), (tr("E&xit"), self.close, None)):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if sc:
                a.setShortcut(QKeySequence(sc))
            f.addAction(a)
        h = mb.addMenu(tr("&Help"))
        add_guide_action(self, h, "conv-basics")
        a = QAction(tr("&What can it convert?"), self)
        a.triggered.connect(self.show_help)
        h.addAction(a)
        a = QAction(tr("&About"), self)
        a.triggered.connect(lambda: QMessageBox.about(
            self, APP_NAME, tr("<b>{APP_NAME}</b><br>Part of {SUITE_NAME}.<br><br>Audio and video conversion uses "
                               "<a href='https://ffmpeg.org'>FFmpeg</a> (free software, GPL licence).").format(APP_NAME=APP_NAME, SUITE_NAME=SUITE_NAME)))
        h.addAction(a)
        self.del_action = QAction(self)
        self.del_action.setShortcut(QKeySequence.Delete)
        self.del_action.triggered.connect(self.remove_selected)
        self.addAction(self.del_action)
        self._update_count()
        if paths:
            self.add_paths(paths)

    # ------------------------------------------------------------ tabs
    def _convert_tab(self):
        w = QWidget()
        g = QHBoxLayout(w)
        left = QFormLayout()
        self.set_all = QComboBox()
        self.set_all.setMinimumWidth(260)
        self.set_all.activated.connect(lambda _: self._apply_set_all())
        left.addRow(tr("Set all files to:"), self.set_all)
        hint = QLabel(tr("Each file can also have its own format in the “Convert to” column."))
        hint.setStyleSheet("color: #666;")
        left.addRow(hint)
        g.addLayout(left, 1)
        mid = QFormLayout()
        self.video_quality = QComboBox()
        add_items(self.video_quality, cc.VIDEO_QUALITY, "Balanced")
        self.max_height = QComboBox()
        add_items(self.max_height, [N_("Keep original size"), "4K (2160p)", "1080p", "720p", "480p", "360p"])
        self.audio_bitrate = QComboBox()
        self.audio_bitrate.addItems(cc.AUDIO_BITRATES)
        self.audio_bitrate.setCurrentText("192k")
        mid.addRow(tr("Video quality:"), self.video_quality)
        mid.addRow(tr("Video size:"), self.max_height)
        mid.addRow(tr("Audio quality:"), self.audio_bitrate)
        g.addLayout(mid, 1)
        right = QFormLayout()
        self.image_quality = QSpinBox()
        self.image_quality.setRange(1, 100)
        self.image_quality.setValue(90)
        self.image_max = QComboBox()
        add_items(self.image_max, [N_("Keep original size"), "3840 px", "2560 px", "1920 px", "1280 px", "800 px",
                                   "512 px", "256 px"])
        pic_row = QHBoxLayout()
        self.picture_edit = QLineEdit()
        self.picture_edit.setPlaceholderText(tr("Black background"))
        pb = QToolButton()
        pb.setText("…")
        pb.clicked.connect(self._pick_picture)
        pic_row.addWidget(self.picture_edit)
        pic_row.addWidget(pb)
        self.gif_width = QSpinBox()
        self.gif_width.setRange(64, 1920)
        self.gif_width.setValue(480)
        self.gif_width.setSuffix(tr(" px wide"))
        self.pdf_dpi = QSpinBox()
        self.pdf_dpi.setRange(50, 600)
        self.pdf_dpi.setValue(150)
        self.pdf_dpi.setSuffix(tr(" dpi"))
        right.addRow(tr("Picture quality:"), self.image_quality)
        right.addRow(tr("Picture max size:"), self.image_max)
        right.addRow(tr("Picture for audio → MP4:"), pic_row)
        right.addRow(tr("GIF size:"), self.gif_width)
        right.addRow(tr("PDF → images:"), self.pdf_dpi)
        g.addLayout(right, 1)
        return w

    def _compress_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.level_group = QButtonGroup(self)
        for i, (name, desc) in enumerate(((tr("Light"), tr("best quality, a bit smaller")),
                                          (tr("Balanced"), tr("good quality, much smaller")),
                                          (tr("Strong"), tr("smallest file, lower quality"))), start=1):
            rb = QRadioButton(f"{name} — {desc}")
            self.level_group.addButton(rb, i)
            row.addWidget(rb)
            if i == 2:
                rb.setChecked(True)
        row.addStretch()
        v.addLayout(row)
        info = QLabel(tr("Videos → smaller MP4 (H.264, can lower the resolution) · Audio → lower bitrate (WAV/FLAC "
                         "become MP3) · Pictures → smaller JPG/PNG/WebP · PDFs → shrinks pictures & fonts · "
                         "Word/Excel/PowerPoint → shrinks the pictures inside · Anything else → zipped (Strong "
                         "uses 7z)."))
        info.setWordWrap(True)
        info.setStyleSheet("color: #555;")
        v.addWidget(info)
        return w

    def _combine_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        self.combine_kind = QComboBox()
        self.combine_kind.addItems([tr("Pictures and PDFs → one PDF"), tr("Audio files → one audio file (MP3)"),
                                    tr("Videos → one video (MP4)")])
        self.combine_name = QLineEdit("Combined")
        f.addRow(tr("Combine:"), self.combine_kind)
        f.addRow(tr("New file name:"), self.combine_name)
        hint = QLabel(tr("Files are joined in the order of the list. Use ▲ ▼ to reorder."))
        hint.setStyleSheet("color: #666;")
        row = QHBoxLayout()
        for text, d in (("▲ " + tr("Move up"), -1), ("▼ " + tr("Move down"), 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, d=d: self.move_row(d))
            row.addWidget(b)
        row.addWidget(hint)
        row.addStretch()
        f.addRow(row)
        return w

    def _archive_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        self.archive_mode = QComboBox()
        self.archive_mode.addItems([tr("Pack all files into one ZIP"), tr("Pack all files into one 7z (smaller)"),
                                    tr("Extract (unpack) the archives in the list")])
        self.archive_name = QLineEdit("Archive")
        f.addRow(tr("Do:"), self.archive_mode)
        f.addRow(tr("Archive name:"), self.archive_name)
        self.archive_mode.currentIndexChanged.connect(lambda _: self._refresh_rows())
        hint = QLabel(tr("Extract supports .zip, .7z, .tar, .tar.gz/.tgz, .tar.bz2, .tar.xz, .gz, .bz2, .xz"))
        hint.setStyleSheet("color: #666;")
        f.addRow(hint)
        return w

    def _tab_switched(self, i):
        downloading = self.tabs.widget(i) is self.download_tab
        own_page = downloading or self.tabs.widget(i) is self.trim_tab     # these tabs have their own file + button
        self.files_box.setVisible(not own_page)
        self.bottom_box.setVisible(not own_page)
        self.main_layout.setStretchFactor(self.tabs, 1 if own_page else 0)
        self.same_folder.setText(tr("My Downloads folder") if downloading else tr("Same folder as each file"))

    def download_folder(self):
        """Downloads go to the chosen folder, or the user's Downloads folder."""
        if self.other_folder.isChecked() and self.folder_edit.text().strip():
            d = self.folder_edit.text().strip()
        else:
            d = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(d, exist_ok=True)
        return d

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("Save results to"), self.folder_edit.text())
        if d:
            self.folder_edit.setText(d)
            self.other_folder.setChecked(True)

    def _pick_picture(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("Picture for the video"), "", tr("Images (*.png *.jpg *.jpeg *.webp "
                                                                                 "*.bmp)"))
        if f:
            self.picture_edit.setText(f)

    # ------------------------------------------------------------ file list
    def add_files_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("Add files"), self.settings.value("last_dir", ""))
        if files:
            self.settings.setValue("last_dir", os.path.dirname(files[0]))
            self.add_paths(files)

    def add_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, tr("Add folder"), self.settings.value("last_dir", ""))
        if d:
            self.add_paths([d])

    def add_paths(self, paths):
        new = []
        for p in paths:
            if os.path.isdir(p):
                if self.tabs.currentIndex() == 3 and self.archive_mode.currentIndex() < 2:
                    new.append(p)  # zip a whole folder
                    continue
                for dp, _, names in os.walk(p):
                    new.extend(os.path.join(dp, n) for n in sorted(names))
            elif os.path.isfile(p):
                new.append(p)
        known = {f["path"] for f in self.files}
        for p in new:
            if p in known:
                continue
            known.add(p)
            self._add_row(p)
        self._refresh_set_all()
        self._update_count()

    def _add_row(self, path):
        row = self.table.rowCount()
        self.table.insertRow(row)
        is_dir = os.path.isdir(path)
        cat = "folder" if is_dir else cc.category(path)
        item = QTableWidgetItem(os.path.basename(path.rstrip("\\/")))
        item.setToolTip(path)
        self.table.setItem(row, COL_FILE, item)
        t = QTableWidgetItem(cat.title())
        t.setForeground(QColor(TYPE_COLORS.get(cat, "#666")))
        f = t.font()
        f.setBold(True)
        t.setFont(f)
        self.table.setItem(row, COL_TYPE, t)
        size = 0 if is_dir else os.path.getsize(path)
        self.table.setItem(row, COL_SIZE, QTableWidgetItem("" if is_dir else cc.human(size)))
        bar = QProgressBar()
        bar.setValue(0)
        bar.setFormat(tr("Waiting"))
        bar.setTextVisible(True)
        self.table.setCellWidget(row, COL_STATUS, bar)
        self.table.setItem(row, COL_RESULT, QTableWidgetItem(""))
        self.files.append({"path": path, "cat": cat, "size": size,
                           "target": None if is_dir else cc.default_target(path)})
        self._refresh_row(row)

    def _make_combo(self, r):
        f = self.files[r]
        targets = {} if f["cat"] == "folder" else cc.targets_for(f["path"])
        combo = QComboBox()
        if targets:
            add_items(combo, targets, f["target"])           # shown translated, kept as the English target name
        else:
            combo.addItem(tr("(nothing to convert)"))
        combo.setEnabled(bool(targets))
        combo.currentIndexChanged.connect(
            lambda i, f=f, c=combo: f.__setitem__("target", c.itemData(i)) if c.itemData(i) in targets else None)
        return combo

    def _refresh_rows(self):
        for r in range(self.table.rowCount()):
            self._refresh_row(r)
        self._refresh_set_all()

    def _refresh_row(self, r):
        task = self.tabs.currentIndex()
        task = 0 if task >= 4 else task   # trim/download tabs hide the list; show it as for Convert
        f = self.files[r]
        if task == 0:
            self.table.setItem(r, COL_TARGET, QTableWidgetItem(""))
            if self.table.cellWidget(r, COL_TARGET) is None:
                self.table.setCellWidget(r, COL_TARGET, self._make_combo(r))
        else:
            if self.table.cellWidget(r, COL_TARGET) is not None:
                self.table.removeCellWidget(r, COL_TARGET)
            text = {1: tr(cc.compress_kind(f["path"])) if f["cat"] != "folder" else tr("Zip it"),
                    2: tr("Join"), 3: tr("Pack") if self.archive_mode.currentIndex() < 2 else
                    (tr("Extract") if f["cat"] == "archive" else tr("(not an archive)"))}[task]
            self.table.setItem(r, COL_TARGET, QTableWidgetItem("   " + text))

    def _refresh_set_all(self):
        cur = self.set_all.currentData()
        self.set_all.clear()
        seen = []
        for f in self.files:
            if f["cat"] == "folder":
                continue
            for t in cc.targets_for(f["path"]):
                if t not in seen:
                    seen.append(t)
        self.set_all.addItem(tr("(choose…)"), None)
        add_items(self.set_all, seen)
        if cur in seen:
            self.set_all.setCurrentIndex(self.set_all.findData(cur))

    def _apply_set_all(self):
        t = self.set_all.currentData()
        if t is None:
            return
        n = 0
        for r, f in enumerate(self.files):
            if f["cat"] != "folder" and t in cc.targets_for(f["path"]):
                f["target"] = t
                combo = self.table.cellWidget(r, COL_TARGET)
                if combo is not None:
                    combo.setCurrentIndex(combo.findData(t))
                n += 1
        self.statusBar().showMessage(tr("Set {n} file(s) to {t}").format(n=n, t=t), 4000)

    def remove_selected(self):
        if self.runner.running:
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
            del self.files[r]
        self._refresh_set_all()
        self._update_count()

    def clear(self):
        if self.runner.running:
            return
        self.table.setRowCount(0)
        self.files = []
        self._refresh_set_all()
        self._update_count()
        self.overall.setValue(0)
        self.overall.setFormat(tr("Ready"))

    def move_row(self, d):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if len(rows) != 1:
            return
        r = rows[0]
        j = r + d
        if not 0 <= j < len(self.files):
            return
        old = list(self.files)
        old[r], old[j] = old[j], old[r]
        self.table.setRowCount(0)
        self.files = []
        for f in old:
            self._add_row(f["path"])
            self.files[-1]["target"] = f["target"]
            self._refresh_row(len(self.files) - 1)
        self.table.selectRow(j)

    def _update_count(self):
        total = sum(f["size"] for f in self.files)
        self.count_label.setText(tr("{v} file(s) · {v2}").format(v=len(self.files), v2=cc.human(total)) if self.files else "")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths([u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()])

    # ------------------------------------------------------------ running
    def _opts(self):
        mh = self.max_height.currentData()
        im = self.image_max.currentData()
        return dict(video_quality=self.video_quality.currentData(),
                    max_height={"4K (2160p)": 2160, "1080p": 1080, "720p": 720, "480p": 480, "360p": 360}.get(mh),
                    audio_bitrate=self.audio_bitrate.currentText(), image_quality=self.image_quality.value(),
                    image_max=int(im.split()[0]) if im[0].isdigit() else None, picture=self.picture_edit.text().strip(),
                    gif_width=self.gif_width.value(), pdf_dpi=self.pdf_dpi.value())

    def _folder(self):
        if self.same_folder.isChecked():
            return None
        d = self.folder_edit.text().strip()
        os.makedirs(d, exist_ok=True)
        return d

    def start(self):
        if not self.files:
            QMessageBox.information(self, APP_NAME, tr("Add some files first (drag them into the list)."))
            return
        try:
            folder = self._folder()
        except OSError as ex:
            QMessageBox.warning(self, APP_NAME, tr("Can't use that output folder:\n{ex}").format(ex=ex))
            return
        self.settings.setValue("out_mode", "same" if self.same_folder.isChecked() else "other")
        self.settings.setValue("out_folder", self.folder_edit.text())
        self.settings.setValue("open_done", "true" if self.open_when_done.isChecked() else "false")
        task = self.tabs.currentIndex()
        opts = self._opts()
        jobs = []
        self.outputs = []
        for r in range(self.table.rowCount()):
            bar = self.table.cellWidget(r, COL_STATUS)
            bar.setValue(0)
            bar.setFormat(tr("Waiting"))
            bar.setStyleSheet("")
            self.table.item(r, COL_RESULT).setText("")
        files = [f["path"] for f in self.files]
        if task == 0:
            for r, f in enumerate(self.files):
                target = f["target"]
                if not target:
                    self._mark(r, False, tr("Skipped - nothing to convert"))
                    continue
                jobs.append((r, lambda prog, cancel, p=f["path"], t=target: cc.run_convert(p, t, folder, opts, prog, cancel),
                             cc.needs_gui_thread(f["path"], "convert")))
        elif task == 1:
            level = self.level_group.checkedId()
            for r, f in enumerate(self.files):
                if f["cat"] == "folder":
                    jobs.append((r, lambda prog, cancel, p=f["path"]: cc.make_archive(
                        [p], cc.unique_path(os.path.join(folder or os.path.dirname(p.rstrip("\\/")),
                                                         os.path.basename(p.rstrip("\\/")) + ".zip")), "zip", prog, cancel), False))
                else:
                    jobs.append((r, lambda prog, cancel, p=f["path"]: cc.run_compress(p, level, folder, prog, cancel), False))
        elif task == 2:
            kind = self.combine_kind.currentIndex()
            ext = [".pdf", ".mp3", ".mp4"][kind]
            name = (self.combine_name.text().strip() or tr("Combined")) + ext
            dst = cc.unique_path(os.path.join(folder or os.path.dirname(files[0]), name))
            wanted = [("image", "document"), ("audio", "video"), ("video",)][kind]
            use = [p for p in files if cc.category(p) in wanted and (kind != 0 or cc.category(p) == "image"
                                                                       or p.lower().endswith(".pdf"))]
            if len(use) < 1:
                QMessageBox.information(self, APP_NAME, tr("None of the files in the list can be combined that way."))
                return
            fn = cc.combine_pdf if kind == 0 else cc.join_media
            self.included = set(use)
            jobs.append((files.index(use[0]), lambda prog, cancel: fn(use, dst, prog, cancel), False))
        else:
            mode = self.archive_mode.currentIndex()
            if mode < 2:
                ext = ".zip" if mode == 0 else ".7z"
                dst = cc.unique_path(os.path.join(folder or os.path.dirname(files[0].rstrip("\\/")),
                                                  (self.archive_name.text().strip() or "Archive") + ext))
                self.included = set(files)
                jobs.append((0, lambda prog, cancel: cc.make_archive(files, dst, ext[1:], prog, cancel), False))
            else:
                for r, f in enumerate(self.files):
                    if f["cat"] == "archive":
                        jobs.append((r, lambda prog, cancel, p=f["path"]: cc.extract_archive(p, folder, prog, cancel), False))
                    else:
                        self._mark(r, False, tr("Skipped - not an archive"))
        if not jobs:
            QMessageBox.information(self, APP_NAME, tr("There's nothing to do for these files."))
            return
        self.total_jobs = len(jobs)
        self.done_jobs = 0
        self.failed = 0
        self.t0 = time.time()
        self.single_job = task in (2, 3) and not (task == 3 and self.archive_mode.currentIndex() == 2)
        if self.single_job:
            self.lead_row = jobs[0][0]
            for r, f in enumerate(self.files):
                inc = f["path"] in self.included
                self.table.cellWidget(r, COL_STATUS).setFormat(tr("Working…") if r == self.lead_row else
                                                               tr("Included") if inc else tr("— not included"))
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.tabs.setEnabled(False)
        self.overall.setValue(0)
        self.overall.setFormat(tr("0 of {total_jobs}").format(total_jobs=self.total_jobs))
        self.runner.start(jobs)

    def _on_progress(self, row, pct):
        bar = self.table.cellWidget(row, COL_STATUS)
        if bar is not None:
            bar.setValue(int(pct))
            bar.setFormat(f"{pct:.0f}%")
        frac = (self.done_jobs + pct / 100) / max(self.total_jobs, 1)
        self.overall.setValue(int(frac * 100))

    def _mark(self, row, ok, msg):
        bar = self.table.cellWidget(row, COL_STATUS)
        bar.setValue(100 if ok else 0)
        bar.setFormat(tr("✔ Done") if ok else ("✖ " + msg if msg not in ("Cancelled",) else tr("Cancelled")))
        bar.setToolTip(msg)
        bar.setStyleSheet("QProgressBar::chunk { background: #43a047; }" if ok else
                          "QProgressBar { color: #b71c1c; }")

    def _on_finished(self, row, ok, msg, outs):
        self.done_jobs += 1
        if not ok:
            self.failed += 1
        self._mark(row, ok, msg)
        if self.single_job and ok:
            for r, f in enumerate(self.files):
                if r != row and f["path"] in self.included:
                    self.table.cellWidget(r, COL_STATUS).setFormat(tr("✔ Included"))
        if ok and outs:
            self.outputs.extend(outs)
            size = sum(os.path.getsize(o) for o in outs if os.path.isfile(o))
            item = self.table.item(row, COL_RESULT)
            src_size = self.files[row]["size"] if not self.single_job else sum(f["size"] for f in self.files)
            text = cc.human(size) if size else os.path.basename(outs[0])
            if size and src_size and self.tabs.currentIndex() == 1:
                if size >= src_size * 0.98:
                    # not worth keeping: remove the copy and say so
                    for o in outs:
                        if os.path.isfile(o):
                            os.remove(o)
                        self.outputs.remove(o)
                    self.table.cellWidget(row, COL_STATUS).setFormat(tr("✔ Already small"))
                    item.setText(tr("kept original (no new file)"))
                    item.setToolTip(tr("This file couldn't be made noticeably smaller."))
                    self.overall.setValue(int(self.done_jobs / max(self.total_jobs, 1) * 100))
                    self.overall.setFormat(tr("{done_jobs} of {total_jobs}").format(done_jobs=self.done_jobs, total_jobs=self.total_jobs))
                    return
                saved = int((1 - size / src_size) * 100)
                text += "  " + tr("({saved}% smaller)").format(saved=saved)
            if len(outs) > 1:
                text += "  · " + tr("{n} files").format(n=len(outs))
            item.setText(text)
            item.setToolTip("\n".join(outs))
        elif not ok:
            self.table.item(row, COL_RESULT).setText("")
        self.overall.setValue(int(self.done_jobs / max(self.total_jobs, 1) * 100))
        self.overall.setFormat(tr("{done_jobs} of {total_jobs}").format(done_jobs=self.done_jobs, total_jobs=self.total_jobs))

    def _on_all_done(self):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.tabs.setEnabled(True)
        secs = time.time() - self.t0
        cancelled = self.runner.cancel.is_set()
        ok = self.done_jobs - self.failed
        self.overall.setValue(100 if not cancelled else self.overall.value())
        self.overall.setFormat((tr("Cancelled - ") if cancelled else tr("Finished - ")) +
                               tr("{ok} done").format(ok=ok) + (tr(", {failed} failed").format(failed=self.failed) if self.failed else "") + tr(" in {secs:.0f}s").format(secs=secs))
        if self.outputs and self.open_when_done.isChecked() and not cancelled:
            target = self.outputs[0]
            try:
                if os.path.isdir(target):
                    os.startfile(target)
                else:
                    subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
            except Exception:
                pass

    def show_help(self):
        QMessageBox.information(self, tr("What can it convert?"), (
            tr("AUDIO (mp3, wav, flac, m4a, ogg, opus, aiff, wma…) → MP3, WAV, FLAC, M4A, OGG, OPUS, AIFF, WMA, or "
               "an MP4 video with a picture.\n\nVIDEO (mp4, mkv, mov, avi, webm, wmv, flv…) → MP4 (H.264 / H.265), "
               "MKV, WebM, MOV, AVI, WMV, animated GIF, or just the sound (MP3, WAV, M4A, FLAC).\n\nPICTURES (png, "
               "jpg, webp, bmp, gif, tiff, ico, psd) → PNG, JPG, WebP, BMP, GIF, TIFF, ICO, PDF.\n\nDOCUMENTS: PDF "
               "→ pictures, Word or text · Word → PDF, text, HTML, Markdown, ODT · PowerPoint → PDF or pictures · "
               "Excel → CSV · CSV → Excel · text/Markdown/HTML → PDF or Word.\n\nCOMPRESS makes any of these "
               "smaller. COMBINE joins pictures/PDFs into one PDF, or audio/videos into one. ZIP / UNZIP packs or "
               "unpacks .zip, .7z, .tar.gz and more.")))

    def closeEvent(self, e):
        if self.runner.running:
            if QMessageBox.question(self, APP_NAME, tr("Files are still being converted. Stop and quit?")) != QMessageBox.Yes:
                e.ignore()
                return
            self.runner.stop()
        e.accept()


SERVER_NAME = "EthicalConverter-" + os.environ.get("USERNAME", "user")


def send_to_running(paths):
    """If a converter window is already open, hand it our files and return True."""
    from PySide6.QtNetwork import QLocalSocket
    for _ in range(30):
        sock = QLocalSocket()
        sock.connectToServer(SERVER_NAME)
        if sock.waitForConnected(150):
            sock.write("\n".join(paths).encode("utf-8"))
            sock.flush()
            sock.waitForBytesWritten(1000)
            sock.disconnectFromServer()
            return True
        time.sleep(0.1)
    return False


def main():
    from PySide6.QtCore import QLockFile, QStandardPaths
    from PySide6.QtNetwork import QLocalServer
    app = make_app(APP_NAME, sys.argv)
    paths = [os.path.abspath(p) for p in sys.argv[1:]]
    # Explorer starts one copy per selected file: the first becomes the window, the rest pass their files to it
    lock = QLockFile(os.path.join(QStandardPaths.writableLocation(QStandardPaths.TempLocation), SERVER_NAME + ".lock"))
    if not lock.tryLock(0):
        if send_to_running(paths):
            return
    win = ConverterWindow(paths)
    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def incoming():
        sock = server.nextPendingConnection()

        def read():
            data = bytes(sock.readAll()).decode("utf-8", "replace")
            more = [p for p in data.split("\n") if p.strip()]
            if more:
                win.add_paths(more)
                win.raise_()
                win.activateWindow()
        sock.readyRead.connect(read)
    server.newConnection.connect(incoming)
    win.show()
    code = app.exec()
    lock.unlock()
    sys.exit(code)


if __name__ == "__main__":
    main()
