"""Ethical Photo Editor - layer-based photo editor (opens/saves PSD with layers, plus all common image formats)."""
import math
import os
import sys

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSettings, QSize, QTimer, Qt
from PySide6.QtGui import (QAction, QActionGroup, QBrush, QColor, QCursor, QFont, QGuiApplication, QIcon,
                           QImage, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QDockWidget, QDoubleSpinBox, QFileDialog, QFontComboBox, QFormLayout,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QSlider, QSpinBox, QToolBar, QToolButton, QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photo_core as pc  # noqa: E402
from suite_common import SETTINGS_ORG, SUITE_NAME, ColorButton, make_app  # noqa: E402
from suite_common import add_guide_action  # noqa: E402

APP_NAME = "Ethical Photo Editor"
MAX_UNDO = 30
TOOLS = [  # key, icon text, name, shortcut
    ("move", "✥", "Move", "V"), ("rect", "⬚", "Rectangle Select", "M"), ("ellipse", "◯", "Ellipse Select", None),
    ("lasso", "➰", "Lasso", "L"), ("wand", "✨", "Magic Wand", "W"), ("crop", "⌗", "Crop", "C"),
    ("brush", "🖌", "Brush", "B"), ("eraser", "⌫", "Eraser", "E"), ("fill", "◧", "Paint Bucket", "G"),
    ("gradient", "▤", "Gradient", None), ("clone", "⎘", "Clone Stamp", "S"), ("eyedropper", "💧", "Eyedropper", "I"),
    ("text", "T", "Text", "T"), ("shape", "▭", "Shape", "U"), ("hand", "✋", "Hand (pan)", "H"),
    ("zoom", "🔍", "Zoom (Alt = out)", "Z"),
]
SELECT_TOOLS = ("rect", "ellipse", "lasso", "wand")


def checker(size=8):
    pm = QPixmap(size * 2, size * 2)
    pm.fill(QColor("#ffffff"))
    p = QPainter(pm)
    p.fillRect(0, 0, size, size, QColor("#cccccc"))
    p.fillRect(size, size, size, size, QColor("#cccccc"))
    p.end()
    return pm


# ====================================================================== canvas

class Canvas(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.zoom = 1.0
        self.offset = QPointF(20, 20)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.checker = QBrush(checker())
        self.ants = 0
        self.timer = QTimer(self, interval=150)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.mouse = None
        self.panning = None
        self.space = False

    def _tick(self):
        if self.win.sel_path is not None:
            self.ants = (self.ants + 1) % 8
            self.update()

    def to_img(self, pos):
        return QPointF((pos.x() - self.offset.x()) / self.zoom, (pos.y() - self.offset.y()) / self.zoom)

    def to_view(self, pt):
        return QPointF(pt.x() * self.zoom + self.offset.x(), pt.y() * self.zoom + self.offset.y())

    def fit(self):
        d = self.win.doc
        if not d or self.width() < 10:
            return
        z = min((self.width() - 40) / d.width, (self.height() - 40) / d.height, 1.0)
        self.set_zoom(z, center=True)

    def set_zoom(self, z, anchor=None, center=False):
        z = max(0.02, min(z, 32))
        d = self.win.doc
        if center:
            self.zoom = z
            self.offset = QPointF((self.width() - d.width * z) / 2, (self.height() - d.height * z) / 2)
        else:
            anchor = anchor or QPointF(self.width() / 2, self.height() / 2)
            ip = self.to_img(anchor)
            self.zoom = z
            self.offset = QPointF(anchor.x() - ip.x() * z, anchor.y() - ip.y() * z)
        self.win.update_status()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#3a3d42"))
        d = self.win.doc
        if d is None:
            return
        r = QRectF(self.offset.x(), self.offset.y(), d.width * self.zoom, d.height * self.zoom)
        p.fillRect(r.adjusted(3, 3, 3, 3), QColor(0, 0, 0, 90))
        p.fillRect(r, self.checker)
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.zoom < 1)
        p.drawImage(r, self.win.comp)
        if self.zoom >= 8:  # pixel grid when zoomed far in
            p.setPen(QPen(QColor(0, 0, 0, 40), 1))
            vis = r.intersected(QRectF(self.rect()))
            x0 = int((vis.left() - self.offset.x()) / self.zoom)
            x1 = int((vis.right() - self.offset.x()) / self.zoom) + 1
            y0 = int((vis.top() - self.offset.y()) / self.zoom)
            y1 = int((vis.bottom() - self.offset.y()) / self.zoom) + 1
            for x in range(x0, x1 + 1):
                X = self.offset.x() + x * self.zoom
                p.drawLine(QPointF(X, vis.top()), QPointF(X, vis.bottom()))
            for y in range(y0, y1 + 1):
                Y = self.offset.y() + y * self.zoom
                p.drawLine(QPointF(vis.left(), Y), QPointF(vis.right(), Y))
        tf = QTransform(self.zoom, 0, 0, self.zoom, self.offset.x(), self.offset.y())
        p.setRenderHint(QPainter.Antialiasing)
        # selection marching ants
        if self.win.sel_path is not None:
            path = tf.map(self.win.sel_path)
            p.setPen(QPen(Qt.white, 1))
            p.drawPath(path)
            pen = QPen(Qt.black, 1, Qt.CustomDashLine)
            pen.setDashPattern([4, 4])
            pen.setDashOffset(self.ants)
            p.setPen(pen)
            p.drawPath(path)
        self.win.paint_tool_overlay(p, tf)
        # brush cursor
        if self.mouse is not None and self.win.tool in ("brush", "eraser", "clone") and not self.space:
            rad = self.win.opt["size"] / 2 * self.zoom
            p.setPen(QPen(QColor(255, 255, 255, 200), 1))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(self.mouse, rad, rad)
            p.setPen(QPen(QColor(0, 0, 0, 160), 1))
            p.drawEllipse(self.mouse, rad + 1, rad + 1)

    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and (self.space or self.win.tool == "hand")):
            self.panning = (e.position(), QPointF(self.offset))
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() == Qt.LeftButton:
            self.win.tool_press(self.to_img(e.position()), e.modifiers())

    def mouseMoveEvent(self, e):
        self.mouse = e.position()
        if self.panning:
            start, off = self.panning
            self.offset = off + (e.position() - start)
            self.update()
            return
        ip = self.to_img(e.position())
        self.win.update_status(ip)
        if e.buttons() & Qt.LeftButton:
            self.win.tool_move(ip, e.modifiers())
        self.update()

    def mouseReleaseEvent(self, e):
        if self.panning:
            self.panning = None
            self.win.update_cursor()
            return
        if e.button() == Qt.LeftButton:
            self.win.tool_release(self.to_img(e.position()), e.modifiers())

    def mouseDoubleClickEvent(self, e):
        if self.win.tool == "crop":
            self.win.apply_crop()

    def leaveEvent(self, e):
        self.mouse = None
        self.update()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier or e.modifiers() & Qt.AltModifier:
            f = 1.2 if e.angleDelta().y() > 0 else 1 / 1.2
            self.set_zoom(self.zoom * f, anchor=e.position())
        else:
            dx, dy = e.angleDelta().x(), e.angleDelta().y()
            if e.modifiers() & Qt.ShiftModifier:
                dx, dy = dy, dx
            self.offset += QPointF(dx / 2, dy / 2)
            self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self.space = True
            self.setCursor(Qt.OpenHandCursor)
            return
        self.win.canvas_key(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self.space = False
            self.win.update_cursor()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.win.doc is not None and not getattr(self, "_fitted", False):
            self._fitted = True
            self.fit()


# ====================================================================== dialogs

class ParamDialog(QDialog):
    """Sliders for an adjustment/filter with live preview on the canvas."""

    def __init__(self, win, title, params, on_change):
        super().__init__(win)
        self.setWindowTitle(title)
        self.values = {}
        self.on_change = on_change
        form = QFormLayout(self)
        self.timer = QTimer(self, singleShot=True, interval=120)
        self.timer.timeout.connect(lambda: self.on_change(dict(self.values)))
        for key, label, lo, hi, default in params:
            is_float = isinstance(default, float) or (hi - lo) <= 10
            row = QHBoxLayout()
            slider = QSlider(Qt.Horizontal)
            spin = QDoubleSpinBox() if is_float else QSpinBox()
            scale = 100 if is_float else 1
            slider.setRange(int(lo * scale), int(hi * scale))
            spin.setRange(lo, hi)
            if is_float:
                spin.setDecimals(2)
                spin.setSingleStep(0.05 if hi - lo <= 5 else 0.5)
            spin.setValue(default)
            slider.setValue(int(default * scale))
            self.values[key] = default

            def from_slider(v, key=key, spin=spin, scale=scale):
                spin.blockSignals(True)
                spin.setValue(v / scale)
                spin.blockSignals(False)
                self.values[key] = v / scale if scale != 1 else v
                self.timer.start()

            def from_spin(v, key=key, slider=slider, scale=scale):
                slider.blockSignals(True)
                slider.setValue(int(v * scale))
                slider.blockSignals(False)
                self.values[key] = v
                self.timer.start()
            slider.valueChanged.connect(from_slider)
            spin.valueChanged.connect(from_spin)
            slider.setMinimumWidth(260)
            row.addWidget(slider)
            row.addWidget(spin)
            form.addRow(label + ":", row)
        self.preview = QCheckBox("Preview")
        self.preview.setChecked(True)
        self.preview.toggled.connect(lambda _: self.on_change(dict(self.values)))
        form.addRow("", self.preview)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


class NewImageDialog(QDialog):
    PRESETS = {"Custom": None, "HD 1920×1080": (1920, 1080), "4K 3840×2160": (3840, 2160),
               "Instagram post 1080×1080": (1080, 1080), "Instagram story 1080×1920": (1080, 1920),
               "YouTube thumbnail 1280×720": (1280, 720), "A4 @ 300 dpi": (2480, 3508),
               "Letter @ 300 dpi": (2550, 3300), "Icon 512×512": (512, 512)}

    def __init__(self, parent, w=1920, h=1080):
        super().__init__(parent)
        self.setWindowTitle("New Image")
        self.preset = QComboBox()
        self.preset.addItems(self.PRESETS)
        self.preset.setCurrentText("HD 1920×1080")
        self.w, self.h = QSpinBox(), QSpinBox()
        for s, v in ((self.w, w), (self.h, h)):
            s.setRange(1, 30000)
            s.setValue(v)
            s.setSuffix(" px")
        self.bg = QComboBox()
        self.bg.addItems(["White", "Transparent", "Black", "Foreground colour"])
        self.preset.currentTextChanged.connect(self._preset)
        form = QFormLayout(self)
        form.addRow("Preset:", self.preset)
        form.addRow("Width:", self.w)
        form.addRow("Height:", self.h)
        form.addRow("Background:", self.bg)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _preset(self, name):
        if self.PRESETS.get(name):
            self.w.setValue(self.PRESETS[name][0])
            self.h.setValue(self.PRESETS[name][1])


class TextDialog(QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle("Text")
        self.edit = QPlainTextEdit(settings.get("text", ""))
        self.edit.setMinimumSize(380, 110)
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont(settings.get("font", "Arial")))
        self.size = QSpinBox()
        self.size.setRange(4, 2000)
        self.size.setValue(settings.get("size", 48))
        self.bold, self.italic = QCheckBox("Bold"), QCheckBox("Italic")
        self.bold.setChecked(settings.get("bold", False))
        self.italic.setChecked(settings.get("italic", False))
        self.color = ColorButton(QColor(settings.get("color", "#000000")), "Text colour")
        self.align = QComboBox()
        self.align.addItems(["Left", "Centre", "Right"])
        self.align.setCurrentText(settings.get("align", "Left"))
        self.outline = QSpinBox()
        self.outline.setRange(0, 100)
        self.outline.setValue(settings.get("outline", 0))
        self.outline_color = ColorButton(QColor(settings.get("outline_color", "#FFFFFF")), "Outline colour")
        self.shadow = QCheckBox("Drop shadow")
        self.shadow.setChecked(settings.get("shadow", False))
        form = QFormLayout(self)
        form.addRow(self.edit)
        form.addRow("Font:", self.font)
        form.addRow("Size (px):", self.size)
        row = QHBoxLayout()
        row.addWidget(self.bold)
        row.addWidget(self.italic)
        row.addWidget(QLabel("Colour"))
        row.addWidget(self.color)
        row.addStretch()
        form.addRow("Style:", row)
        form.addRow("Align:", self.align)
        row2 = QHBoxLayout()
        row2.addWidget(self.outline)
        row2.addWidget(self.outline_color)
        row2.addStretch()
        form.addRow("Outline (px):", row2)
        form.addRow("", self.shadow)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def settings(self):
        return dict(text=self.edit.toPlainText(), font=self.font.currentFont().family(), size=self.size.value(),
                    bold=self.bold.isChecked(), italic=self.italic.isChecked(), color=self.color.color().name(),
                    align=self.align.currentText(), outline=self.outline.value(),
                    outline_color=self.outline_color.color().name(), shadow=self.shadow.isChecked())


def render_text(t):
    """Text settings -> (QImage, offset QPoint relative to the click point)."""
    f = QFont(t["font"])
    f.setPixelSize(max(1, t["size"]))
    f.setBold(t["bold"])
    f.setItalic(t["italic"])
    lines = t["text"].split("\n")
    path = QPainterPath()
    from PySide6.QtGui import QFontMetricsF
    fm = QFontMetricsF(f)
    widths = [fm.horizontalAdvance(line) for line in lines]
    maxw = max(widths + [1])
    for i, line in enumerate(lines):
        x = {"Left": 0, "Centre": (maxw - widths[i]) / 2, "Right": maxw - widths[i]}[t["align"]]
        path.addText(QPointF(x, fm.ascent() + i * fm.lineSpacing()), f, line)
    pad = t["outline"] + (t["size"] // 8 if t["shadow"] else 0) + 4
    br = path.boundingRect().adjusted(-pad, -pad, pad, pad)
    img = pc.blank(int(math.ceil(br.width())), int(math.ceil(br.height())))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(-br.left(), -br.top())
    if t["shadow"]:
        off = max(2, t["size"] // 16)
        p.save()
        p.translate(off, off)
        p.fillPath(path, QColor(0, 0, 0, 120))
        p.restore()
    if t["outline"]:
        pen = QPen(QColor(t["outline_color"]), t["outline"] * 2)
        pen.setJoinStyle(Qt.RoundJoin)
        p.strokePath(path, pen)
    p.fillPath(path, QColor(t["color"]))
    p.end()
    return img, QPoint(int(br.left()), int(br.top()))


# ====================================================================== main window

class PhotoWindow(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        self.settings = QSettings(SETTINGS_ORG, APP_NAME)
        self.doc = None
        self.path = None
        self.modified = False
        self.comp = QImage()
        self.sel_path = None
        self.tool = "brush"
        self.drag = None
        self.history = []          # list of (label, snapshot)
        self.hist_pos = -1          # index of the current state in history
        self.clone_src = None
        self.crop_rect = None
        self.opt = dict(size=30, hardness=80, opacity=100, tolerance=32, contiguous=True, sample_all=False,
                        feather=0, shape="Rectangle", shape_fill=True, stroke=4, grad_type="Linear",
                        grad_mode="Foreground → Background", sel_mode="replace")
        self.resize(1450, 920)
        self.setAcceptDrops(True)
        self.canvas = Canvas(self)
        self.setCentralWidget(self.canvas)
        self.fg = ColorButton(QColor("#000000"), "Foreground colour")
        self.bg = ColorButton(QColor("#FFFFFF"), "Background colour")
        self._build_toolbox()
        self._build_layers_dock()
        self._build_history_dock()
        self._build_menus()
        self.opts_bar = QToolBar("Tool Options")
        self.opts_bar.setObjectName("options")
        self.addToolBar(Qt.TopToolBarArea, self.opts_bar)
        self.pos_label, self.zoom_label, self.size_label = QLabel(), QLabel(), QLabel()
        for w in (self.size_label, self.zoom_label, self.pos_label):
            self.statusBar().addPermanentWidget(w)
        self.thumb_timer = QTimer(self, singleShot=True, interval=300)
        self.thumb_timer.timeout.connect(self.refresh_layers)
        self.set_document(pc.new_document(1920, 1080), None)
        self.set_tool("brush")
        if path:
            self.open_path(path)

    # ------------------------------------------------------------ UI building
    def act(self, text, slot, shortcut=None, menu=None, tip=None):
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setStatusTip(tip)
        if menu is not None:
            menu.addAction(a)
        return a

    def _build_toolbox(self):
        tb = QToolBar("Tools")
        tb.setObjectName("tools")
        tb.setOrientation(Qt.Vertical)
        tb.setMovable(False)
        tb.setStyleSheet("QToolButton { font-size: 16px; min-width: 34px; min-height: 30px; }")
        self.addToolBar(Qt.LeftToolBarArea, tb)
        group = QActionGroup(self)
        self.tool_actions = {}
        for key, icon, name, sc in TOOLS:
            a = QAction(icon, self, checkable=True)
            a.setToolTip(f"{name}" + (f" ({sc})" if sc else ""))
            a.setStatusTip(name)
            a.triggered.connect(lambda _=False, k=key: self.set_tool(k))
            group.addAction(a)
            tb.addAction(a)
            self.tool_actions[key] = a
        tb.addSeparator()
        box = QWidget()
        g = QGridLayout(box)
        g.setContentsMargins(4, 4, 4, 4)
        g.addWidget(self.fg, 0, 0)
        g.addWidget(self.bg, 1, 1)
        swap = QToolButton()
        swap.setText("⇄")
        swap.setToolTip("Swap colours (X)")
        swap.clicked.connect(self.swap_colors)
        g.addWidget(swap, 0, 1)
        reset = QToolButton()
        reset.setText("◩")
        reset.setToolTip("Default black/white (D)")
        reset.clicked.connect(self.reset_colors)
        g.addWidget(reset, 1, 0)
        tb.addWidget(box)

    def _build_layers_dock(self):
        dock = QDockWidget("Layers", self)
        dock.setObjectName("layers")
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        self.blend_box = QComboBox()
        self.blend_box.addItems(pc.BLEND_MODES)
        self.blend_box.activated.connect(lambda _: self.set_layer_prop("blend", self.blend_box.currentText()))
        row.addWidget(self.blend_box, 1)
        row.addWidget(QLabel("Opacity"))
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setSuffix("%")
        self.opacity_spin.editingFinished.connect(
            lambda: self.set_layer_prop("opacity", self.opacity_spin.value() / 100))
        row.addWidget(self.opacity_spin)
        v.addLayout(row)
        self.layer_list = QListWidget()
        self.layer_list.setIconSize(QSize(56, 42))
        self.layer_list.currentRowChanged.connect(self._layer_selected)
        self.layer_list.itemChanged.connect(self._layer_item_changed)
        self.layer_list.itemDoubleClicked.connect(lambda _: self.rename_layer())
        self.layer_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.layer_list.customContextMenuRequested.connect(
            lambda pos: self.layer_menu.exec(self.layer_list.mapToGlobal(pos)))
        v.addWidget(self.layer_list, 1)
        btns = QHBoxLayout()
        for text, tip, slot in (("＋", "New layer", self.new_layer), ("⧉", "Duplicate layer", self.duplicate_layer),
                                ("▲", "Move up", lambda: self.move_layer(1)), ("▼", "Move down", lambda: self.move_layer(-1)),
                                ("⤓", "Merge down", self.merge_down), ("🗑", "Delete layer", self.delete_layer)):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            btns.addWidget(b)
        v.addLayout(btns)
        dock.setWidget(w)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.layers_dock = dock

    def _build_history_dock(self):
        dock = QDockWidget("History", self)
        dock.setObjectName("history")
        self.hist_list = QListWidget()
        self.hist_list.itemClicked.connect(lambda it: self.jump_history(self.hist_list.row(it)))
        dock.setWidget(self.hist_list)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.hist_dock = dock

    def _build_menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self.act("&New...", self.new_file, "Ctrl+N", f)
        self.act("&Open...", self.open_dialog, "Ctrl+O", f)
        self.recent_menu = f.addMenu("Open &Recent")
        self._refresh_recent()
        self.act("&Place Image as Layer...", self.place_image, None, f)
        f.addSeparator()
        self.act("&Save", self.save, "Ctrl+S", f)
        self.act("Save &As...", self.save_as, "Ctrl+Shift+S", f)
        self.act("&Export As (PNG, JPG, WebP...)...", self.export_as, "Ctrl+Alt+Shift+W", f)
        f.addSeparator()
        self.act("E&xit", self.close, None, f)

        e = mb.addMenu("&Edit")
        self.act("&Undo", self.undo, "Ctrl+Z", e)
        self.act("&Redo", self.redo, "Ctrl+Shift+Z", e)
        self.addAction(self.act("Redo", self.redo, "Ctrl+Y"))
        e.addSeparator()
        self.act("Cu&t", self.cut, "Ctrl+X", e)
        self.act("&Copy", self.copy, "Ctrl+C", e)
        self.act("Copy &Merged", lambda: self.copy(merged=True), "Ctrl+Shift+C", e)
        self.act("&Paste as New Layer", self.paste, "Ctrl+V", e)
        self.act("C&lear Selection Pixels", self.clear_pixels, "Delete", e)
        e.addSeparator()
        self.act("&Fill with Foreground", lambda: self.fill_selection(self.fg.color()), "Alt+Backspace", e)
        self.act("Fill with &Background", lambda: self.fill_selection(self.bg.color()), "Ctrl+Backspace", e)
        self.act("&Stroke Selection...", self.stroke_selection, None, e)
        e.addSeparator()
        self.act("Free &Transform (scale/rotate)...", self.transform_dialog, "Ctrl+T", e)

        im = mb.addMenu("&Image")
        adj = im.addMenu("&Adjustments")
        for name in pc.ADJUSTMENTS:
            self.act(name + "...", lambda _=False, n=name: self.run_adjustment(n), None, adj)
        adj.addSeparator()
        for name in pc.INSTANT:
            self.act(name, lambda _=False, n=name: self.run_instant(n), None, adj)
        self.act("&Image Size...", self.image_size, "Ctrl+Alt+I", im)
        self.act("&Canvas Size...", self.canvas_size, "Ctrl+Alt+C", im)
        rot = im.addMenu("&Rotate Canvas")
        self.act("90° Clockwise", lambda: self.rotate_canvas(90), None, rot)
        self.act("90° Counter-clockwise", lambda: self.rotate_canvas(-90), None, rot)
        self.act("180°", lambda: self.rotate_canvas(180), None, rot)
        self.act("Arbitrary...", self.rotate_arbitrary, None, rot)
        self.act("Flip Canvas &Horizontal", lambda: self.flip_canvas(True), None, im)
        self.act("Flip Canvas &Vertical", lambda: self.flip_canvas(False), None, im)
        self.act("Cr&op to Selection", self.crop_to_selection, None, im)
        self.act("&Trim Transparent Edges", self.trim, None, im)
        self.act("&Flatten Image", self.flatten, None, im)

        lm = mb.addMenu("&Layer")
        self.layer_menu = lm
        self.act("&New Layer", self.new_layer, "Ctrl+Shift+N", lm)
        self.act("&Duplicate / Copy Selection to New Layer", self.duplicate_layer, "Ctrl+J", lm)
        self.act("Cut Selection to New Layer", lambda: self.duplicate_layer(cut=True), "Ctrl+Shift+J", lm)
        self.act("De&lete Layer", self.delete_layer, None, lm)
        self.act("&Rename Layer...", self.rename_layer, None, lm)
        self.act("Edit &Text Layer...", self.edit_text_layer, None, lm)
        lm.addSeparator()
        self.act("Move Layer &Up", lambda: self.move_layer(1), "Ctrl+]", lm)
        self.act("Move Layer D&own", lambda: self.move_layer(-1), "Ctrl+[", lm)
        self.act("&Merge Down", self.merge_down, "Ctrl+E", lm)
        self.act("Merge &Visible", self.merge_visible, "Ctrl+Shift+E", lm)
        lm.addSeparator()
        self.act("Flip Layer Horizontal", lambda: self.flip_layer(True), None, lm)
        self.act("Flip Layer Vertical", lambda: self.flip_layer(False), None, lm)
        self.act("Rotate Layer 90°", lambda: self.rotate_layer(90), None, lm)

        sm = mb.addMenu("&Select")
        self.act("&All", self.select_all, "Ctrl+A", sm)
        self.act("&Deselect", self.deselect, "Ctrl+D", sm)
        self.act("&Inverse", self.invert_selection, "Ctrl+Shift+I", sm)
        self.act("&Layer Pixels", self.select_layer_pixels, None, sm)
        self.act("&Colour Range (all similar colours)...", self.color_range, None, sm)
        sm.addSeparator()
        self.act("&Grow...", lambda: self.modify_selection("grow"), None, sm)
        self.act("&Shrink...", lambda: self.modify_selection("shrink"), None, sm)
        self.act("&Feather...", lambda: self.modify_selection("feather"), "Shift+F6", sm)

        fl = mb.addMenu("Fil&ter")
        for name in pc.FILTERS:
            self.act(name + ("..." if pc.FILTERS[name][1] else ""), lambda _=False, n=name: self.run_filter(n), None, fl)

        vm = mb.addMenu("&View")
        self.act("Zoom &In", lambda: self.canvas.set_zoom(self.canvas.zoom * 1.25), "Ctrl+=", vm)
        self.act("Zoom &Out", lambda: self.canvas.set_zoom(self.canvas.zoom / 1.25), "Ctrl+-", vm)
        self.act("&Fit on Screen", self.canvas.fit, "Ctrl+0", vm)
        self.act("&Actual Pixels (100%)", lambda: self.canvas.set_zoom(1.0), "Ctrl+1", vm)
        vm.addSeparator()
        vm.addAction(self.layers_dock.toggleViewAction())
        vm.addAction(self.hist_dock.toggleViewAction())

        h = mb.addMenu("&Help")

        add_guide_action(self, h, "photo-basics")
        self.act("&Keyboard Shortcuts", self.show_shortcuts, None, h)
        self.act("&About", lambda: QMessageBox.about(self, APP_NAME, f"<b>{APP_NAME}</b><br>Part of {SUITE_NAME}."),
                 None, h)
        for key, _, _, sc in TOOLS:
            if sc:
                self.addAction(self.act(key, lambda _=False, k=key: self.set_tool(k), sc))
        self.addAction(self.act("swap", self.swap_colors, "X"))
        self.addAction(self.act("reset", self.reset_colors, "D"))
        self.addAction(self.act("smaller", lambda: self.change_size(-1), "["))
        self.addAction(self.act("bigger", lambda: self.change_size(1), "]"))

    # ------------------------------------------------------------ tool options bar
    def set_tool(self, key):
        if self.tool == "crop" and key != "crop":
            self.crop_rect = None
        self.tool = key
        self.tool_actions[key].setChecked(True)
        self._build_options()
        self.update_cursor()
        self.canvas.update()

    def update_cursor(self):
        cur = {"move": Qt.SizeAllCursor, "hand": Qt.OpenHandCursor, "text": Qt.IBeamCursor,
               "eyedropper": Qt.CrossCursor, "zoom": Qt.PointingHandCursor}.get(self.tool, Qt.CrossCursor)
        self.canvas.setCursor(cur)

    def _spin(self, key, label, lo, hi, suffix=""):
        self.opts_bar.addWidget(QLabel(f" {label} "))
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(int(self.opt[key]))
        s.setSuffix(suffix)
        s.valueChanged.connect(lambda v: self.opt.__setitem__(key, v))
        s.setFocusPolicy(Qt.ClickFocus)
        self.opts_bar.addWidget(s)
        return s

    def _check(self, key, label):
        c = QCheckBox(label)
        c.setChecked(bool(self.opt[key]))
        c.toggled.connect(lambda v: self.opt.__setitem__(key, v))
        c.setFocusPolicy(Qt.NoFocus)
        self.opts_bar.addWidget(c)

    def _combo(self, key, label, items):
        self.opts_bar.addWidget(QLabel(f" {label} "))
        c = QComboBox()
        c.addItems(items)
        c.setCurrentText(self.opt[key])
        c.currentTextChanged.connect(lambda v: self.opt.__setitem__(key, v))
        c.setFocusPolicy(Qt.ClickFocus)
        self.opts_bar.addWidget(c)

    def _build_options(self):
        bar = self.opts_bar
        bar.clear()
        name = next(n for k, _, n, _ in TOOLS if k == self.tool)
        lbl = QLabel(f"  {name}  ")
        lbl.setStyleSheet("font-weight: bold;")
        bar.addWidget(lbl)
        t = self.tool
        if t in ("brush", "eraser", "clone"):
            self.size_spin = self._spin("size", "Size", 1, 2000, " px")
            self._spin("hardness", "Hardness", 0, 100, "%")
            self._spin("opacity", "Opacity", 1, 100, "%")
            if t == "clone":
                bar.addWidget(QLabel("   Alt+click to pick the source point"))
        elif t in SELECT_TOOLS:
            self._combo("sel_mode", "Mode", ["replace", "add", "subtract", "intersect"])
            if t == "wand":
                self._spin("tolerance", "Tolerance", 0, 255)
                self._check("contiguous", "Contiguous")
                self._check("sample_all", "Sample all layers")
            else:
                self._spin("feather", "Feather", 0, 250, " px")
            bar.addWidget(QLabel("   Shift = add, Alt = subtract"))
        elif t == "fill":
            self._spin("tolerance", "Tolerance", 0, 255)
            self._check("contiguous", "Contiguous")
            self._check("sample_all", "Sample all layers")
            self._spin("opacity", "Opacity", 1, 100, "%")
        elif t == "gradient":
            self._combo("grad_type", "Type", ["Linear", "Radial"])
            self._combo("grad_mode", "Colours", ["Foreground → Background", "Foreground → Transparent"])
            self._spin("opacity", "Opacity", 1, 100, "%")
        elif t == "shape":
            self._combo("shape", "Shape", ["Rectangle", "Rounded Rectangle", "Ellipse", "Line", "Arrow"])
            self._check("shape_fill", "Fill (foreground)")
            self._spin("stroke", "Outline (background)", 0, 200, " px")
            bar.addWidget(QLabel("   Drawn on a new layer"))
        elif t == "crop":
            b = QPushButton("Apply Crop (Enter)")
            b.clicked.connect(self.apply_crop)
            bar.addWidget(b)
            b2 = QPushButton("Cancel (Esc)")
            b2.clicked.connect(lambda: (setattr(self, "crop_rect", None), self.canvas.update()))
            bar.addWidget(b2)
        elif t == "text":
            bar.addWidget(QLabel("   Click to add text (click an existing text layer to edit it)"))
        elif t == "move":
            bar.addWidget(QLabel("   Drag to move the layer (or the selected pixels). Arrow keys nudge."))
        elif t == "eyedropper":
            bar.addWidget(QLabel("   Click: foreground colour   Alt+click: background colour"))

    def change_size(self, d):
        s = self.opt["size"]
        step = 1 if s < 10 else 5 if s < 50 else 10 if s < 200 else 50
        self.opt["size"] = max(1, s + d * step)
        if self.tool in ("brush", "eraser", "clone"):
            self.size_spin.setValue(self.opt["size"])
        self.canvas.update()

    def swap_colors(self):
        a, b = self.fg.color(), self.bg.color()
        self.fg.setColor(b)
        self.bg.setColor(a)

    def reset_colors(self):
        self.fg.setColor(QColor("black"))
        self.bg.setColor(QColor("white"))

    # ------------------------------------------------------------ document
    def set_document(self, doc, path):
        self.doc = doc
        self.path = path
        self.modified = False
        self.history = [("Open" if path else "New", doc.snapshot())]
        self.hist_pos = 0
        self.crop_rect = None
        self.update_selection()
        self.recomposite()
        self.refresh_layers()
        self.refresh_history()
        self.canvas.fit()
        self.update_title()
        self.update_status()

    def recomposite(self):
        self.comp = pc.composite(self.doc)
        self.canvas.update()

    def changed(self, label, layers_changed=True):
        """Call after modifying the document; records an undo step."""
        del self.history[self.hist_pos + 1:]
        self.history.append((label, self.doc.snapshot()))
        if len(self.history) > MAX_UNDO:
            del self.history[0]
        self.hist_pos = len(self.history) - 1
        self.modified = True
        self.recomposite()
        if layers_changed:
            self.refresh_layers()
        else:
            self.thumb_timer.start()
        self.refresh_history()
        self.update_title()
        self.update_status()

    def jump_history(self, i):
        if not 0 <= i < len(self.history):
            return
        self.hist_pos = i
        self.doc.restore(self.history[i][1])
        self.modified = True
        self.update_selection()
        self.recomposite()
        self.refresh_layers()
        self.refresh_history()
        self.update_title()
        self.update_status()

    def undo(self):
        self.jump_history(self.hist_pos - 1)

    def redo(self):
        self.jump_history(self.hist_pos + 1)

    def refresh_history(self):
        self.hist_list.clear()
        for i, (label, _) in enumerate(self.history):
            it = QListWidgetItem(label)
            if i > self.hist_pos:
                it.setForeground(QColor("#999"))
            self.hist_list.addItem(it)
        self.hist_list.setCurrentRow(self.hist_pos)

    def refresh_layers(self):
        lw = self.layer_list
        lw.blockSignals(True)
        lw.clear()
        for i in reversed(range(len(self.doc.layers))):
            l = self.doc.layers[i]
            thumb = pc.blank(self.doc.width, self.doc.height)
            p = QPainter(thumb)
            p.drawImage(l.x, l.y, l.image)
            p.end()
            pm = QPixmap(56, 42)
            pm.fill(QColor("#ddd"))
            pp = QPainter(pm)
            pp.fillRect(pm.rect(), QBrush(checker(4)))
            sc = thumb.scaled(56, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pp.drawImage((56 - sc.width()) // 2, (42 - sc.height()) // 2, sc)
            pp.end()
            it = QListWidgetItem(QIcon(pm), ("T  " if l.text else "") + l.name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if l.visible else Qt.Unchecked)
            lw.addItem(it)
        lw.setCurrentRow(len(self.doc.layers) - 1 - self.doc.active)
        lw.blockSignals(False)
        l = self.doc.layer
        self.blend_box.setCurrentText(l.blend)
        self.opacity_spin.setValue(int(round(l.opacity * 100)))

    def _layer_selected(self, row):
        if row >= 0:
            self.doc.active = len(self.doc.layers) - 1 - row
            l = self.doc.layer
            self.blend_box.setCurrentText(l.blend)
            self.opacity_spin.setValue(int(round(l.opacity * 100)))

    def _layer_item_changed(self, item):
        i = len(self.doc.layers) - 1 - self.layer_list.row(item)
        vis = item.checkState() == Qt.Checked
        if self.doc.layers[i].visible != vis:
            self.doc.layers[i].visible = vis
            self.changed("Show layer" if vis else "Hide layer", layers_changed=False)

    def set_layer_prop(self, prop, value):
        l = self.doc.layer
        if getattr(l, prop) != value:
            setattr(l, prop, value)
            self.changed({"blend": "Blend mode", "opacity": "Layer opacity"}[prop], layers_changed=False)

    def update_title(self):
        name = os.path.basename(self.path) if self.path else "Untitled"
        self.setWindowTitle(f"{'*' if self.modified else ''}{name} - {APP_NAME}")

    def update_status(self, ip=None):
        d = self.doc
        if d is None:
            return
        self.size_label.setText(f"  {d.width} × {d.height} px  ")
        self.zoom_label.setText(f"  {round(self.canvas.zoom * 100)}%  ")
        if ip is not None:
            x, y = int(ip.x()), int(ip.y())
            if 0 <= x < d.width and 0 <= y < d.height:
                c = QColor(self.comp.pixel(x, y))
                self.pos_label.setText(f"  X {x}  Y {y}   {c.name().upper()}  ")
            else:
                self.pos_label.setText(f"  X {x}  Y {y}  ")

    # ------------------------------------------------------------ selection
    def update_selection(self):
        m = self.doc.selection
        self.sel_path = pc.mask_outline(m) if m is not None else None
        self.canvas.update()

    def set_selection(self, mask, mode, label="Select"):
        if mask is not None and self.opt["feather"] and self.tool in ("rect", "ellipse", "lasso"):
            mask = pc.feather_mask(mask, self.opt["feather"])
        self.doc.selection = pc.combine_masks(self.doc.selection, mask, mode) if mask is not None else None
        if self.doc.selection is not None and pc.mask_bounds(self.doc.selection) is None:
            self.doc.selection = None
        self.update_selection()
        self.changed(label, layers_changed=False)

    def select_all(self):
        m = QImage(self.doc.width, self.doc.height, QImage.Format_Grayscale8)
        m.fill(255)
        self.doc.selection = m
        self.update_selection()
        self.changed("Select all", False)

    def deselect(self):
        if self.doc.selection is not None:
            self.doc.selection = None
            self.update_selection()
            self.changed("Deselect", False)

    def invert_selection(self):
        if self.doc.selection is None:
            return
        m = QImage(self.doc.selection)
        m.invertPixels()
        self.doc.selection = m if pc.mask_bounds(m) else None
        self.update_selection()
        self.changed("Inverse selection", False)

    def select_layer_pixels(self):
        l = self.doc.layer
        a = pc.to_array(l.image)[..., 3].astype(np.float32) / 255
        full = np.zeros((self.doc.height, self.doc.width), np.float32)
        r = l.rect().intersected(QRect(0, 0, self.doc.width, self.doc.height))
        if r.isEmpty():
            return
        full[r.y():r.bottom() + 1, r.x():r.right() + 1] = a[r.y() - l.y:r.bottom() + 1 - l.y, r.x() - l.x:r.right() + 1 - l.x]
        self.doc.selection = pc.mask_from_array(full)
        self.update_selection()
        self.changed("Select layer pixels", False)

    def color_range(self):
        tol, ok = QInputDialog.getInt(self, "Colour Range", "Select every pixel similar to the foreground colour.\n"
                                      "Tolerance:", 40, 0, 255)
        if not ok:
            return
        arr = pc.to_array(self.comp).astype(np.int16)
        c = self.fg.color()
        diff = np.abs(arr[..., :3] - np.array([c.red(), c.green(), c.blue()])).max(-1)
        self.doc.selection = pc.mask_from_array((diff <= tol).astype(np.float32))
        self.update_selection()
        self.changed("Colour range", False)

    def modify_selection(self, how):
        if self.doc.selection is None:
            return
        v, ok = QInputDialog.getInt(self, how.title(), "Pixels:", 5, 1, 500)
        if not ok:
            return
        m = self.doc.selection
        self.doc.selection = pc.feather_mask(m, v) if how == "feather" else pc.grow_mask(m, v if how == "grow" else -v)
        self.update_selection()
        self.changed(f"{how.title()} selection", False)

    def sel_alpha(self, rect):
        """Selection mask as an ARGB alpha image covering canvas rect (or None)."""
        if self.doc.selection is None:
            return None
        m = self.doc.selection.copy(rect)
        img = QImage(m.width(), m.height(), pc.FMT)
        img.fill(Qt.white)
        img.setAlphaChannel(m)
        return img

    # ------------------------------------------------------------ layer helpers
    def ensure_cover(self, layer):
        """Grow a layer so it covers the whole canvas (so you can paint anywhere)."""
        canvas = QRect(0, 0, self.doc.width, self.doc.height)
        r = layer.rect()
        if r.contains(canvas):
            return
        u = r.united(canvas)
        img = pc.blank(u.width(), u.height())
        p = QPainter(img)
        p.drawImage(r.x() - u.x(), r.y() - u.y(), layer.image)
        p.end()
        layer.image, layer.x, layer.y = img, u.x(), u.y()

    def layer_canvas_image(self, layer):
        """The layer's pixels in canvas coordinates (canvas sized)."""
        img = pc.blank(self.doc.width, self.doc.height)
        p = QPainter(img)
        p.drawImage(layer.x, layer.y, layer.image)
        p.end()
        return img

    def check_editable(self):
        l = self.doc.layer
        if l is None:
            return False
        if not l.visible:
            QMessageBox.information(self, APP_NAME, "The selected layer is hidden - show it first.")
            return False
        return True

    # ------------------------------------------------------------ tool handling
    def tool_press(self, ip, mods):
        t = self.tool
        d = self.doc
        mode = self.opt["sel_mode"]
        if mods & Qt.ShiftModifier:
            mode = "add"
        elif mods & Qt.AltModifier:
            mode = "subtract"
        self.drag = {"start": ip, "cur": ip, "pts": [ip], "mode": mode, "mods": mods}
        if t in ("brush", "eraser", "clone"):
            if t == "clone" and mods & Qt.AltModifier:
                self.clone_src = ip
                self.drag = None
                self.statusBar().showMessage("Clone source set - now paint where you want to copy to", 4000)
                return
            if t == "clone" and self.clone_src is None:
                self.drag = None
                QMessageBox.information(self, APP_NAME, "Alt+click on the picture first to choose what to copy from.")
                return
            if not self.check_editable():
                self.drag = None
                return
            self.begin_stroke(ip)
        elif t == "move":
            if not self.check_editable():
                self.drag = None
                return
            self.begin_move()
        elif t == "eyedropper":
            self.pick_color(ip, mods)
        elif t == "wand":
            m = pc.region_mask(d, int(ip.x()), int(ip.y()), self.opt["tolerance"], self.opt["contiguous"],
                               self.opt["sample_all"])
            if m is not None:
                self.set_selection(m, mode, "Magic wand")
            self.drag = None
        elif t == "fill":
            if self.check_editable():
                self.bucket_fill(ip)
            self.drag = None
        elif t == "text":
            self.text_click(ip)
            self.drag = None
        elif t == "zoom":
            f = 1 / 1.5 if mods & Qt.AltModifier else 1.5
            self.canvas.set_zoom(self.canvas.zoom * f, anchor=self.canvas.to_view(ip))
            self.drag = None

    def tool_move(self, ip, mods):
        if not self.drag:
            return
        self.drag["cur"] = ip
        t = self.tool
        if t in ("brush", "eraser", "clone"):
            self.continue_stroke(ip)
        elif t == "lasso":
            self.drag["pts"].append(ip)
        elif t == "move":
            self.continue_move(ip)
        elif t == "eyedropper":
            self.pick_color(ip, mods)
        self.canvas.update()

    def tool_release(self, ip, mods):
        d = self.drag
        if not d:
            return
        self.drag = None
        t = self.tool
        a, b = d["start"], ip
        rect = QRectF(a, b).normalized()
        if t in ("brush", "eraser", "clone"):
            self.end_stroke()
        elif t == "move":
            self.end_move()
        elif t in ("rect", "ellipse"):
            if rect.width() < 2 and rect.height() < 2:
                if d["mode"] == "replace":
                    self.deselect()
                return
            path = QPainterPath()
            if t == "rect":
                path.addRect(rect)
            else:
                path.addEllipse(rect)
            self.set_selection(pc.path_mask(self.doc, path, antialias=t == "ellipse"), d["mode"],
                               "Rectangle select" if t == "rect" else "Ellipse select")
        elif t == "lasso":
            if len(d["pts"]) > 2:
                path = QPainterPath()
                path.addPolygon(QPolygonF(d["pts"]))
                path.closeSubpath()
                self.set_selection(pc.path_mask(self.doc, path), d["mode"], "Lasso")
        elif t == "crop":
            r = rect.toRect().intersected(QRect(0, 0, self.doc.width, self.doc.height))
            self.crop_rect = r if r.width() > 2 and r.height() > 2 else None
            if self.crop_rect is not None:
                self.statusBar().showMessage("Press Enter or double-click to crop, Esc to cancel", 5000)
        elif t == "gradient":
            if (b - a).manhattanLength() > 2 and self.check_editable():
                self.draw_gradient(a, b)
        elif t == "shape":
            if rect.width() > 2 or rect.height() > 2:
                self.draw_shape(a, b, d["mods"])
        self.canvas.update()

    def paint_tool_overlay(self, p, tf):
        d = self.drag
        t = self.tool
        pen = QPen(QColor("#ffffff"), 1, Qt.DashLine)
        if t == "crop" and (self.crop_rect is not None or (d and t == "crop")):
            r = self.crop_rect if not d else QRectF(d["start"], d["cur"]).normalized()
            vr = tf.mapRect(QRectF(r))
            full = tf.mapRect(QRectF(0, 0, self.doc.width, self.doc.height))
            path = QPainterPath()
            path.addRect(full)
            inner = QPainterPath()
            inner.addRect(vr)
            p.fillPath(path.subtracted(inner), QColor(0, 0, 0, 130))
            p.setPen(QPen(Qt.white, 1))
            p.drawRect(vr)
            for i in (1, 2):  # rule of thirds
                p.setPen(QPen(QColor(255, 255, 255, 90), 1))
                p.drawLine(QPointF(vr.left() + vr.width() * i / 3, vr.top()), QPointF(vr.left() + vr.width() * i / 3, vr.bottom()))
                p.drawLine(QPointF(vr.left(), vr.top() + vr.height() * i / 3), QPointF(vr.right(), vr.top() + vr.height() * i / 3))
            return
        if t == "clone" and self.clone_src is not None and self.canvas.mouse is not None:
            src = self.clone_src
            if d and d.get("clone_off") is not None:
                src = self.canvas.to_img(self.canvas.mouse) + d["clone_off"]
            c = tf.map(src)
            p.setPen(QPen(Qt.white, 1))
            p.drawLine(c - QPointF(8, 0), c + QPointF(8, 0))
            p.drawLine(c - QPointF(0, 8), c + QPointF(0, 8))
        if not d:
            return
        a, b = tf.map(d["start"]), tf.map(d["cur"])
        r = QRectF(a, b).normalized()
        p.setBrush(Qt.NoBrush)
        if t in ("rect", "ellipse"):
            for color, style in ((Qt.white, Qt.SolidLine), (Qt.black, Qt.DashLine)):
                p.setPen(QPen(color, 1, style))
                p.drawRect(r) if t == "rect" else p.drawEllipse(r)
        elif t == "lasso" and len(d["pts"]) > 1:
            p.setPen(QPen(Qt.black, 1, Qt.DashLine))
            p.drawPolyline(QPolygonF([tf.map(q) for q in d["pts"]]))
        elif t == "gradient":
            p.setPen(QPen(Qt.white, 2))
            p.drawLine(a, b)
            p.setPen(QPen(Qt.black, 1))
            p.drawLine(a, b)
        elif t == "shape":
            p.setPen(QPen(self.bg.color(), max(1, self.opt["stroke"] * self.canvas.zoom)))
            p.setBrush(self.fg.color() if self.opt["shape_fill"] else Qt.NoBrush)
            s = self.opt["shape"]
            if s in ("Line", "Arrow"):
                p.setPen(QPen(self.fg.color(), max(1, self.opt["stroke"] * self.canvas.zoom)))
                p.drawLine(a, b)
            elif s == "Ellipse":
                p.drawEllipse(r)
            elif s == "Rounded Rectangle":
                p.drawRoundedRect(r, min(r.width(), r.height()) * 0.15, min(r.width(), r.height()) * 0.15)
            else:
                p.drawRect(r)

    # ---- brush / eraser / clone
    def begin_stroke(self, ip):
        l = self.doc.layer
        self.ensure_cover(l)
        self.stroke_orig = QImage(l.image)
        self.stroke_buf = pc.blank(self.doc.width, self.doc.height)
        self.stroke_dirty = QRect()
        self.stroke_last = ip
        self.stroke_left = 0.0
        self.sel_img = self.sel_alpha(QRect(0, 0, self.doc.width, self.doc.height))
        if self.tool == "clone":
            self.drag["clone_off"] = self.clone_src - ip
            self.clone_source = self.layer_canvas_image(l)
        self.dab(ip)
        self.flush_stroke()

    def continue_stroke(self, ip):
        spacing = max(1.0, self.opt["size"] * 0.12)
        a = self.stroke_last
        dist = math.hypot(ip.x() - a.x(), ip.y() - a.y())
        t = spacing - self.stroke_left
        while t <= dist:
            self.dab(QPointF(a.x() + (ip.x() - a.x()) * t / dist, a.y() + (ip.y() - a.y()) * t / dist))
            t += spacing
        self.stroke_left = dist - (t - spacing) if dist else self.stroke_left
        self.stroke_last = ip
        self.flush_stroke()

    def dab(self, pt):
        r = self.opt["size"] / 2
        hard = self.opt["hardness"] / 100
        rect = QRect(int(pt.x() - r - 1), int(pt.y() - r - 1), int(2 * r + 3), int(2 * r + 3))
        p = QPainter(self.stroke_buf)
        p.setRenderHint(QPainter.Antialiasing)
        grad = QRadialGradient(pt, max(r, 0.5))
        if self.tool == "clone":
            off = self.drag["clone_off"]
            src_rect = QRect(rect.translated(int(round(off.x())), int(round(off.y()))))
            patch = self.clone_source.copy(src_rect)
            mp = QPainter(patch)
            g = QRadialGradient(QPointF(pt.x() - rect.x(), pt.y() - rect.y()), max(r, 0.5))
            g.setColorAt(0, QColor(0, 0, 0, 255))
            g.setColorAt(min(hard, 0.99), QColor(0, 0, 0, 255))
            g.setColorAt(1, QColor(0, 0, 0, 0))
            mp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            mp.fillRect(patch.rect(), QBrush(g))
            mp.end()
            p.drawImage(rect.topLeft(), patch)
        else:
            c = self.fg.color() if self.tool == "brush" else QColor(0, 0, 0)
            c0 = QColor(c)
            c1 = QColor(c)
            c1.setAlpha(0)
            grad.setColorAt(0, c0)
            grad.setColorAt(min(hard, 0.99), c0)
            grad.setColorAt(1, c1)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(grad))
            p.drawEllipse(pt, r, r)
        p.end()
        self.stroke_dirty = self.stroke_dirty.united(rect)

    def flush_stroke(self):
        l = self.doc.layer
        dirty = self.stroke_dirty.intersected(QRect(0, 0, self.doc.width, self.doc.height))
        if dirty.isEmpty():
            return
        lr = dirty.translated(-l.x, -l.y)
        piece = self.stroke_buf.copy(dirty)
        if self.sel_img is not None:
            sp = QPainter(piece)
            sp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            sp.drawImage(0, 0, self.sel_img.copy(dirty))
            sp.end()
        p = QPainter(l.image)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(lr.topLeft(), self.stroke_orig.copy(lr))
        p.setOpacity(self.opt["opacity"] / 100)
        p.setCompositionMode(QPainter.CompositionMode_DestinationOut if self.tool == "eraser"
                             else QPainter.CompositionMode_SourceOver)
        p.drawImage(lr.topLeft(), piece)
        p.end()
        # update the composite only in the dirty area
        cp = QPainter(self.comp)
        cp.setCompositionMode(QPainter.CompositionMode_Source)
        cp.fillRect(dirty, Qt.transparent)
        cp.setCompositionMode(QPainter.CompositionMode_SourceOver)
        cp.setClipRect(dirty)
        for layer in self.doc.layers:
            if layer.visible and layer.opacity > 0:
                cp.setOpacity(layer.opacity)
                cp.setCompositionMode(pc.BLEND_MODES[layer.blend][0])
                cp.drawImage(layer.x, layer.y, layer.image)
        cp.end()
        self.stroke_dirty = QRect()
        self.canvas.update()

    def end_stroke(self):
        self.stroke_buf = self.stroke_orig = self.sel_img = None
        self.changed({"brush": "Brush", "eraser": "Eraser", "clone": "Clone stamp"}[self.tool], layers_changed=False)

    # ---- move
    def begin_move(self):
        l = self.doc.layer
        self.move_float = None
        self.move_orig = (l.x, l.y)
        if self.doc.selection is not None:
            self.ensure_cover(l)
            sel = self.sel_alpha(QRect(l.x, l.y, l.image.width(), l.image.height()))
            fl = QImage(l.image)
            p = QPainter(fl)
            p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            p.drawImage(0, 0, sel)
            p.end()
            p = QPainter(l.image)
            p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
            p.drawImage(0, 0, sel)
            p.end()
            self.move_float = pc.Layer("float", fl, l.x, l.y)
            self.move_sel = QImage(self.doc.selection)
            self.doc.layers.insert(self.doc.active + 1, self.move_float)

    def continue_move(self, ip):
        d = self.drag
        dx, dy = int(round(ip.x() - d["start"].x())), int(round(ip.y() - d["start"].y()))
        if self.move_float is not None:
            self.move_float.x, self.move_float.y = self.move_orig[0] + dx, self.move_orig[1] + dy
            m = QImage(self.doc.width, self.doc.height, QImage.Format_Grayscale8)
            m.fill(0)
            p = QPainter(m)
            p.drawImage(dx, dy, self.move_sel)
            p.end()
            self.doc.selection = m
            self.sel_path = pc.mask_outline(m)
        else:
            l = self.doc.layer
            l.x, l.y = self.move_orig[0] + dx, self.move_orig[1] + dy
        self.recomposite()

    def end_move(self):
        if self.move_float is not None:
            f = self.move_float
            self.doc.layers.remove(f)
            l = self.doc.layer
            p = QPainter(l.image)
            p.drawImage(f.x - l.x, f.y - l.y, f.image)
            p.end()
            self.move_float = None
            self.update_selection()
        self.changed("Move", layers_changed=False)

    def nudge(self, dx, dy):
        self.drag = {"start": QPointF(0, 0)}
        self.begin_move()
        self.continue_move(QPointF(dx, dy))
        self.drag = None
        self.end_move()

    # ---- other tools
    def pick_color(self, ip, mods):
        x, y = int(ip.x()), int(ip.y())
        if 0 <= x < self.doc.width and 0 <= y < self.doc.height:
            c = QColor(self.comp.pixel(x, y))
            (self.bg if mods & Qt.AltModifier else self.fg).setColor(c)

    def bucket_fill(self, ip):
        x, y = int(ip.x()), int(ip.y())
        m = pc.region_mask(self.doc, x, y, self.opt["tolerance"], self.opt["contiguous"], self.opt["sample_all"])
        if m is None:
            return
        if self.doc.selection is not None:
            m = pc.combine_masks(self.doc.selection, m, "intersect")
        self._fill_mask(m, self.fg.color(), self.opt["opacity"] / 100)
        self.changed("Paint bucket", layers_changed=False)

    def _fill_mask(self, mask, color, opacity=1.0):
        """Paint `color` onto the current layer wherever the canvas-sized mask is set."""
        l = self.doc.layer
        self.ensure_cover(l)
        a = QImage(self.doc.width, self.doc.height, pc.FMT)
        a.fill(Qt.white)
        a.setAlphaChannel(mask)
        tmp = pc.blank(l.image.width(), l.image.height())
        p = QPainter(tmp)
        p.drawImage(-l.x, -l.y, a)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(tmp.rect(), color)
        p.end()
        p = QPainter(l.image)
        p.setOpacity(opacity)
        p.drawImage(0, 0, tmp)
        p.end()

    def fill_selection(self, color):
        if not self.check_editable():
            return
        m = self.doc.selection
        if m is None:
            m = QImage(self.doc.width, self.doc.height, QImage.Format_Grayscale8)
            m.fill(255)
        self._fill_mask(m, color)
        self.changed("Fill", layers_changed=False)

    def stroke_selection(self):
        if self.doc.selection is None or not self.check_editable():
            return
        w, ok = QInputDialog.getInt(self, "Stroke", "Width (px):", 4, 1, 500)
        if not ok:
            return
        l = self.doc.layer
        self.ensure_cover(l)
        p = QPainter(l.image)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(-l.x, -l.y)
        p.setPen(QPen(self.fg.color(), w))
        p.drawPath(self.sel_path)
        p.end()
        self.changed("Stroke", layers_changed=False)

    def draw_gradient(self, a, b):
        l = self.doc.layer
        self.ensure_cover(l)
        c1 = self.fg.color()
        c2 = QColor(self.bg.color()) if self.opt["grad_mode"].endswith("Background") else QColor(c1.red(), c1.green(), c1.blue(), 0)
        if self.opt["grad_type"] == "Radial":
            g = QRadialGradient(a, math.hypot(b.x() - a.x(), b.y() - a.y()))
        else:
            g = QLinearGradient(a, b)
        g.setColorAt(0, c1)
        g.setColorAt(1, c2)
        layer_img = pc.blank(self.doc.width, self.doc.height)
        p = QPainter(layer_img)
        p.fillRect(layer_img.rect(), QBrush(g))
        p.end()
        sel = self.sel_alpha(QRect(0, 0, self.doc.width, self.doc.height))
        if sel is not None:
            p = QPainter(layer_img)
            p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            p.drawImage(0, 0, sel)
            p.end()
        p = QPainter(l.image)
        p.setOpacity(self.opt["opacity"] / 100)
        p.drawImage(-l.x, -l.y, layer_img)
        p.end()
        self.changed("Gradient", layers_changed=False)

    def draw_shape(self, a, b, mods):
        s = self.opt["shape"]
        if mods & Qt.ShiftModifier and s not in ("Line", "Arrow"):
            side = max(abs(b.x() - a.x()), abs(b.y() - a.y()))
            b = QPointF(a.x() + math.copysign(side, b.x() - a.x()), a.y() + math.copysign(side, b.y() - a.y()))
        stroke = self.opt["stroke"]
        pad = stroke + 20
        r = QRectF(a, b).normalized()
        box = r.adjusted(-pad, -pad, pad, pad).toAlignedRect()
        img = pc.blank(box.width(), box.height())
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(-box.x(), -box.y())
        if s in ("Line", "Arrow"):
            pen = QPen(self.fg.color(), max(1, stroke), Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(a, b)
            if s == "Arrow":
                ang = math.atan2(b.y() - a.y(), b.x() - a.x())
                size = max(12, stroke * 4)
                pts = [b, QPointF(b.x() - size * math.cos(ang - 0.45), b.y() - size * math.sin(ang - 0.45)),
                       QPointF(b.x() - size * math.cos(ang + 0.45), b.y() - size * math.sin(ang + 0.45))]
                p.setBrush(self.fg.color())
                p.drawPolygon(QPolygonF(pts))
        else:
            p.setBrush(self.fg.color() if self.opt["shape_fill"] else Qt.NoBrush)
            p.setPen(QPen(self.bg.color(), stroke) if stroke else Qt.NoPen)
            if s == "Ellipse":
                p.drawEllipse(r)
            elif s == "Rounded Rectangle":
                rad = min(r.width(), r.height()) * 0.15
                p.drawRoundedRect(r, rad, rad)
            else:
                p.drawRect(r)
        p.end()
        self.doc.layers.insert(self.doc.active + 1, pc.Layer(s, img, box.x(), box.y()))
        self.doc.active += 1
        self.changed(f"{s} shape")

    def text_click(self, ip):
        # clicking an existing text layer re-edits it
        for i in reversed(range(len(self.doc.layers))):
            l = self.doc.layers[i]
            if l.text and l.visible and l.rect().contains(ip.toPoint()):
                self.doc.active = i
                self.edit_text_layer()
                return
        settings = dict(self.settings.value("last_text") or {}) if isinstance(self.settings.value("last_text"), dict) else {}
        settings.update(text="", color=self.fg.color().name())
        dlg = TextDialog(self, settings)
        if not dlg.exec():
            return
        t = dlg.settings()
        if not t["text"].strip():
            return
        self.settings.setValue("last_text", {k: v for k, v in t.items() if k != "text"})
        img, off = render_text(t)
        t["anchor"] = (int(ip.x()), int(ip.y()))
        layer = pc.Layer(t["text"].split("\n")[0][:30], img, int(ip.x()) + off.x(), int(ip.y()) + off.y(), text=t)
        self.doc.layers.insert(self.doc.active + 1, layer)
        self.doc.active += 1
        self.changed("Text")

    def edit_text_layer(self):
        l = self.doc.layer
        if not l.text:
            QMessageBox.information(self, APP_NAME, "The selected layer isn't a text layer.")
            return
        dlg = TextDialog(self, l.text)
        if not dlg.exec():
            return
        t = dlg.settings()
        t["anchor"] = l.text.get("anchor", (l.x, l.y))
        img, off = render_text(t)
        l.image, l.text = img, t
        l.x, l.y = t["anchor"][0] + off.x(), t["anchor"][1] + off.y()
        l.name = t["text"].split("\n")[0][:30] or l.name
        self.changed("Edit text")

    def apply_crop(self):
        r = self.crop_rect
        if r is None:
            return
        for l in self.doc.layers:
            l.x -= r.x()
            l.y -= r.y()
        self.doc.width, self.doc.height = r.width(), r.height()
        self.doc.selection = None
        self.crop_rect = None
        self.update_selection()
        self.changed("Crop")
        self.canvas.fit()

    def canvas_key(self, e):
        k = e.key()
        if k in (Qt.Key_Return, Qt.Key_Enter) and self.tool == "crop":
            self.apply_crop()
        elif k == Qt.Key_Escape:
            if self.crop_rect is not None:
                self.crop_rect = None
                self.canvas.update()
            else:
                self.deselect()
        elif self.tool == "move" and k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 10 if e.modifiers() & Qt.ShiftModifier else 1
            self.nudge({Qt.Key_Left: -step, Qt.Key_Right: step}.get(k, 0), {Qt.Key_Up: -step, Qt.Key_Down: step}.get(k, 0))

    # ------------------------------------------------------------ adjustments & filters
    def _run_param(self, title, fn, params, label):
        if not self.check_editable():
            return
        l = self.doc.layer
        orig = QImage(l.image)
        arr = pc.to_array(orig)

        def preview(values):
            if dlg.preview.isChecked():
                QGuiApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    l.image = QImage(orig)
                    pc.apply_with_mask(l, pc.from_array(fn(arr, **values)), self.doc)
                finally:
                    QGuiApplication.restoreOverrideCursor()
            else:
                l.image = QImage(orig)
            self.recomposite()
        dlg = ParamDialog(self, title, params, preview)
        if params:
            preview(dict(dlg.values))
            ok = dlg.exec()
        else:
            ok = True
        if ok:
            l.image = QImage(orig)
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                pc.apply_with_mask(l, pc.from_array(fn(arr, **dlg.values)), self.doc)
            finally:
                QGuiApplication.restoreOverrideCursor()
            self.changed(label, layers_changed=False)
        else:
            l.image = orig
            self.recomposite()

    def run_adjustment(self, name):
        fn, params = pc.ADJUSTMENTS[name]
        self._run_param(name, fn, params, name)

    def run_filter(self, name):
        fn, params = pc.FILTERS[name]
        self._run_param(name, fn, params, name)

    def run_instant(self, name):
        if not self.check_editable():
            return
        l = self.doc.layer
        pc.apply_with_mask(l, pc.from_array(pc.INSTANT[name](pc.to_array(l.image))), self.doc)
        self.changed(name, layers_changed=False)

    # ------------------------------------------------------------ image operations
    def image_size(self):
        d = self.doc
        dlg = QDialog(self)
        dlg.setWindowTitle("Image Size")
        w, h = QSpinBox(), QSpinBox()
        for s, v in ((w, d.width), (h, d.height)):
            s.setRange(1, 30000)
            s.setValue(v)
            s.setSuffix(" px")
        pct = QDoubleSpinBox()
        pct.setRange(1, 1000)
        pct.setValue(100)
        pct.setSuffix(" %")
        keep = QCheckBox("Keep proportions")
        keep.setChecked(True)
        lock = [False]

        def sync(src):
            if lock[0]:
                return
            lock[0] = True
            if src == "pct":
                w.setValue(round(d.width * pct.value() / 100))
                h.setValue(round(d.height * pct.value() / 100))
            elif keep.isChecked() and src == "w":
                h.setValue(max(1, round(w.value() * d.height / d.width)))
                pct.setValue(w.value() * 100 / d.width)
            elif keep.isChecked() and src == "h":
                w.setValue(max(1, round(h.value() * d.width / d.height)))
                pct.setValue(h.value() * 100 / d.height)
            lock[0] = False
        w.valueChanged.connect(lambda _: sync("w"))
        h.valueChanged.connect(lambda _: sync("h"))
        pct.valueChanged.connect(lambda _: sync("pct"))
        dpi = QSpinBox()
        dpi.setRange(1, 2400)
        dpi.setValue(d.dpi)
        form = QFormLayout(dlg)
        form.addRow("Scale:", pct)
        form.addRow("Width:", w)
        form.addRow("Height:", h)
        form.addRow("", keep)
        form.addRow("Resolution (dpi):", dpi)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if not dlg.exec():
            return
        sx, sy = w.value() / d.width, h.value() / d.height
        for l in d.layers:
            nw, nh = max(1, round(l.image.width() * sx)), max(1, round(l.image.height() * sy))
            l.image = l.image.scaled(nw, nh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            l.x, l.y = round(l.x * sx), round(l.y * sy)
            if l.text:
                l.text = None  # scaled text is now a picture
        d.width, d.height, d.dpi = w.value(), h.value(), dpi.value()
        d.selection = None
        self.update_selection()
        self.changed("Image size")
        self.canvas.fit()

    def canvas_size(self):
        d = self.doc
        dlg = QDialog(self)
        dlg.setWindowTitle("Canvas Size")
        w, h = QSpinBox(), QSpinBox()
        for s, v in ((w, d.width), (h, d.height)):
            s.setRange(1, 30000)
            s.setValue(v)
            s.setSuffix(" px")
        anchor = QComboBox()
        anchor.addItems(["Centre", "Top-left", "Top", "Top-right", "Left", "Right", "Bottom-left", "Bottom", "Bottom-right"])
        form = QFormLayout(dlg)
        form.addRow("Width:", w)
        form.addRow("Height:", h)
        form.addRow("Anchor:", anchor)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if not dlg.exec():
            return
        a = anchor.currentText().lower()
        dw, dh = w.value() - d.width, h.value() - d.height
        ox = 0 if "left" in a else dw if "right" in a else dw // 2
        oy = 0 if "top" in a else dh if "bottom" in a else dh // 2
        for l in d.layers:
            l.x += ox
            l.y += oy
        d.width, d.height = w.value(), h.value()
        d.selection = None
        bgl = d.layers[0]
        if bgl.name == "Background":  # extend the background with the background colour
            img = pc.blank(d.width, d.height, self.bg.color())
            p = QPainter(img)
            p.drawImage(bgl.x, bgl.y, bgl.image)
            p.end()
            bgl.image, bgl.x, bgl.y = img, 0, 0
        self.update_selection()
        self.changed("Canvas size")
        self.canvas.fit()

    def _transform_all(self, tf_fn, new_w, new_h, label):
        d = self.doc
        for l in d.layers:
            full = self.layer_canvas_image(l) if l.rect() != QRect(0, 0, d.width, d.height) else l.image
            l.image, l.x, l.y = tf_fn(full), 0, 0
            l.text = None
        d.width, d.height = new_w, new_h
        d.selection = None
        self.update_selection()
        self.changed(label)
        self.canvas.fit()

    def rotate_canvas(self, deg):
        d = self.doc
        t = QTransform().rotate(deg)
        nw, nh = (d.height, d.width) if deg in (90, -90) else (d.width, d.height)
        self._transform_all(lambda img: img.transformed(t, Qt.SmoothTransformation), nw, nh, f"Rotate {deg}°")

    def rotate_arbitrary(self):
        deg, ok = QInputDialog.getDouble(self, "Rotate Canvas", "Degrees (clockwise):", 15, -360, 360, 1)
        if not ok:
            return
        d = self.doc
        t = QTransform().rotate(deg)
        r = t.mapRect(QRectF(0, 0, d.width, d.height))
        self._transform_all(lambda img: img.transformed(t, Qt.SmoothTransformation), int(round(r.width())),
                            int(round(r.height())), f"Rotate {deg:g}°")

    def flip_canvas(self, horizontal):
        d = self.doc
        self._transform_all(lambda img: img.mirrored(horizontal, not horizontal), d.width, d.height,
                            "Flip horizontal" if horizontal else "Flip vertical")

    def crop_to_selection(self):
        if self.doc.selection is None:
            return
        self.crop_rect = pc.mask_bounds(self.doc.selection)
        self.apply_crop()

    def trim(self):
        b = pc.mask_bounds(pc.mask_from_array(pc.to_array(self.comp)[..., 3].astype(np.float32) / 255))
        if b and b != QRect(0, 0, self.doc.width, self.doc.height):
            self.crop_rect = b
            self.apply_crop()

    def flatten(self):
        d = self.doc
        img = pc.composite(d, background=QColor("white"))
        d.layers = [pc.Layer("Background", img)]
        d.active = 0
        self.changed("Flatten")

    # ------------------------------------------------------------ layer operations
    def new_layer(self):
        d = self.doc
        n = len(d.layers) + 1
        d.layers.insert(d.active + 1, pc.Layer(f"Layer {n}", pc.blank(d.width, d.height)))
        d.active += 1
        self.changed("New layer")

    def duplicate_layer(self, cut=False):
        d = self.doc
        l = d.layer
        if d.selection is not None:
            self.ensure_cover(l)
            sel = self.sel_alpha(QRect(l.x, l.y, l.image.width(), l.image.height()))
            img = QImage(l.image)
            p = QPainter(img)
            p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            p.drawImage(0, 0, sel)
            p.end()
            if cut:
                p = QPainter(l.image)
                p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
                p.drawImage(0, 0, sel)
                p.end()
            new = pc.Layer("Layer via " + ("cut" if cut else "copy"), img, l.x, l.y)
        else:
            new = l.copy()
            new.name = l.name + " copy"
        d.layers.insert(d.active + 1, new)
        d.active += 1
        self.changed("Cut to layer" if cut else "Duplicate layer")

    def delete_layer(self):
        d = self.doc
        if len(d.layers) == 1:
            QMessageBox.information(self, APP_NAME, "An image needs at least one layer.")
            return
        del d.layers[d.active]
        d.active = max(0, d.active - 1)
        self.changed("Delete layer")

    def rename_layer(self):
        l = self.doc.layer
        name, ok = QInputDialog.getText(self, "Rename Layer", "Name:", QLineEdit.Normal, l.name)
        if ok and name.strip():
            l.name = name.strip()
            self.changed("Rename layer")

    def move_layer(self, d_):
        d = self.doc
        j = d.active + d_
        if 0 <= j < len(d.layers):
            d.layers[d.active], d.layers[j] = d.layers[j], d.layers[d.active]
            d.active = j
            self.changed("Move layer")

    def merge_down(self):
        d = self.doc
        if d.active == 0:
            return
        top, below = d.layers[d.active], d.layers[d.active - 1]
        u = top.rect().united(below.rect())
        img = pc.blank(u.width(), u.height())
        p = QPainter(img)
        p.setOpacity(below.opacity)
        p.drawImage(below.x - u.x(), below.y - u.y(), below.image)
        p.setOpacity(top.opacity)
        p.setCompositionMode(pc.BLEND_MODES[top.blend][0])
        p.drawImage(top.x - u.x(), top.y - u.y(), top.image)
        p.end()
        below.image, below.x, below.y, below.opacity, below.text = img, u.x(), u.y(), 1.0, None
        del d.layers[d.active]
        d.active -= 1
        self.changed("Merge down")

    def merge_visible(self):
        d = self.doc
        img = pc.composite(d)
        hidden = [l for l in d.layers if not l.visible]
        d.layers = [pc.Layer("Merged", img)] + hidden
        d.active = 0
        self.changed("Merge visible")

    def flip_layer(self, horizontal):
        l = self.doc.layer
        l.image = l.image.mirrored(horizontal, not horizontal)
        l.text = None
        self.changed("Flip layer")

    def rotate_layer(self, deg):
        l = self.doc.layer
        c = l.rect().center()
        l.image = l.image.transformed(QTransform().rotate(deg), Qt.SmoothTransformation)
        l.x, l.y = c.x() - l.image.width() // 2, c.y() - l.image.height() // 2
        l.text = None
        self.changed("Rotate layer")

    def transform_dialog(self):
        if not self.check_editable():
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Free Transform")
        sx, sy, rot = QDoubleSpinBox(), QDoubleSpinBox(), QDoubleSpinBox()
        for s in (sx, sy):
            s.setRange(1, 2000)
            s.setValue(100)
            s.setSuffix(" %")
        rot.setRange(-360, 360)
        rot.setSuffix(" °")
        keep = QCheckBox("Keep proportions")
        keep.setChecked(True)
        sx.valueChanged.connect(lambda v: sy.setValue(v) if keep.isChecked() else None)
        form = QFormLayout(dlg)
        form.addRow("Width:", sx)
        form.addRow("Height:", sy)
        form.addRow("", keep)
        form.addRow("Rotate:", rot)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if not dlg.exec():
            return
        if self.doc.selection is not None:
            self.duplicate_layer(cut=True)
        l = self.doc.layer
        c = l.rect().center()
        t = QTransform().rotate(rot.value()).scale(sx.value() / 100, sy.value() / 100)
        l.image = l.image.transformed(t, Qt.SmoothTransformation)
        l.x, l.y = c.x() - l.image.width() // 2, c.y() - l.image.height() // 2
        l.text = None
        self.doc.selection = None
        self.update_selection()
        self.changed("Transform")

    # ------------------------------------------------------------ clipboard
    def _selected_pixels(self, merged=False):
        d = self.doc
        src = self.comp if merged else self.layer_canvas_image(d.layer)
        if d.selection is None:
            return QImage(src), QPoint(0, 0)
        b = pc.mask_bounds(d.selection)
        img = src.copy(b)
        p = QPainter(img)
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawImage(0, 0, self.sel_alpha(b))
        p.end()
        return img, b.topLeft()

    def copy(self, merged=False):
        img, _ = self._selected_pixels(merged)
        QGuiApplication.clipboard().setImage(img)
        self.statusBar().showMessage("Copied", 2000)

    def cut(self):
        self.copy()
        self.clear_pixels()

    def paste(self):
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            QMessageBox.information(self, APP_NAME, "There's no picture on the clipboard.")
            return
        self._add_image_layer(img.convertToFormat(pc.FMT), "Pasted")

    def _add_image_layer(self, img, name):
        d = self.doc
        x, y = (d.width - img.width()) // 2, (d.height - img.height()) // 2
        d.layers.insert(d.active + 1, pc.Layer(name, img, x, y))
        d.active += 1
        self.changed(f"Add {name.lower()}")

    def clear_pixels(self):
        if self.doc.selection is None or not self.check_editable():
            return
        l = self.doc.layer
        sel = self.sel_alpha(QRect(l.x, l.y, l.image.width(), l.image.height()))
        p = QPainter(l.image)
        p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
        p.drawImage(0, 0, sel)
        p.end()
        self.changed("Clear", layers_changed=False)

    # ------------------------------------------------------------ files
    def maybe_save(self):
        if not self.modified:
            return True
        r = QMessageBox.question(self, APP_NAME, "Save changes to this image?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def closeEvent(self, e):
        if self.maybe_save():
            e.accept()
        else:
            e.ignore()

    def new_file(self):
        if not self.maybe_save():
            return
        dlg = NewImageDialog(self)
        if dlg.exec():
            bg = dlg.bg.currentText()
            color = {"White": "white", "Transparent": "transparent", "Black": "black"}.get(bg, self.fg.color().name())
            self.set_document(pc.new_document(dlg.w.value(), dlg.h.value(), color), None)

    def open_dialog(self):
        f, _ = QFileDialog.getOpenFileName(self, "Open", self.settings.value("last_dir", ""), pc.READ_FORMATS)
        if f:
            self.open_path(f)

    def open_path(self, path):
        if not self.maybe_save():
            return
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            doc, warnings = pc.load_image_file(path)
        except Exception as ex:
            QGuiApplication.restoreOverrideCursor()
            QMessageBox.critical(self, APP_NAME, f"Could not open the image:\n{ex}")
            return
        QGuiApplication.restoreOverrideCursor()
        self.set_document(doc, path)
        self._add_recent(path)
        if warnings:
            QMessageBox.information(self, APP_NAME, "Note: this file uses " + ", ".join(warnings) +
                                    ". These can't be edited here yet; the layers' pixels were loaded.")

    def place_image(self):
        f, _ = QFileDialog.getOpenFileName(self, "Place Image", self.settings.value("last_dir", ""), pc.READ_FORMATS)
        if f:
            try:
                doc, _ = pc.load_image_file(f)
            except Exception as ex:
                QMessageBox.critical(self, APP_NAME, f"Could not open the image:\n{ex}")
                return
            self._add_image_layer(pc.composite(doc), os.path.splitext(os.path.basename(f))[0])

    def save(self):
        if not self.path:
            return self.save_as()
        return self.write(self.path)

    def save_as(self):
        start = os.path.splitext(self.path)[0] + ".psd" if self.path else os.path.join(
            self.settings.value("last_dir", ""), "Untitled.psd")
        f, flt = QFileDialog.getSaveFileName(
            self, "Save As", start,
            "Photoshop PSD - keeps layers (*.psd);;OpenRaster - keeps layers (*.ora);;PNG (*.png);;JPEG (*.jpg);;"
            "WebP (*.webp);;TIFF (*.tif);;BMP (*.bmp);;GIF (*.gif);;Icon (*.ico);;PDF (*.pdf)")
        if not f:
            return False
        if not os.path.splitext(f)[1]:
            f += "." + flt.split("*.")[1].split(")")[0]
        return self.write(f)

    def export_as(self):
        start = os.path.splitext(self.path or "Untitled")[0] + ".png"
        f, _ = QFileDialog.getSaveFileName(self, "Export As", start,
                                           "PNG (*.png);;JPEG (*.jpg);;WebP (*.webp);;TIFF (*.tif);;BMP (*.bmp);;"
                                           "GIF (*.gif);;Icon (*.ico);;PDF (*.pdf)")
        if f:
            self.write(f, export=True)

    def write(self, path, export=False):
        low = path.lower()
        try:
            if low.endswith(".psd"):
                pc.save_psd(self.doc, path)
            elif low.endswith(".ora"):
                pc.save_ora(self.doc, path)
            else:
                if len(self.doc.layers) > 1 and not export:
                    r = QMessageBox.question(self, APP_NAME, f"{os.path.splitext(path)[1].upper()} files can't keep "
                                             "layers - the picture will be flattened in the saved file (your layers "
                                             "stay here). Continue?")
                    if r != QMessageBox.Yes:
                        return False
                quality = 90
                if low.endswith((".jpg", ".jpeg", ".webp")):
                    quality, ok = QInputDialog.getInt(self, "Quality", "Quality (1-100):", 90, 1, 100)
                    if not ok:
                        return False
                pc.save_flat(self.doc, path, quality)
        except PermissionError:
            QMessageBox.critical(self, APP_NAME, "Could not save - the file may be open in another program.")
            return False
        except Exception as ex:
            QMessageBox.critical(self, APP_NAME, f"Could not save:\n{ex}")
            return False
        if not export:
            self.path = path
            self.modified = False
            self.update_title()
        self._add_recent(path)
        self.statusBar().showMessage(f"Saved {path}", 4000)
        return True

    def _add_recent(self, path):
        path = os.path.abspath(path)
        self.settings.setValue("last_dir", os.path.dirname(path))
        recent = self.settings.value("recent") or []
        if isinstance(recent, str):
            recent = [recent]
        self.settings.setValue("recent", ([path] + [p for p in recent if p != path])[:10])
        self._refresh_recent()

    def _refresh_recent(self):
        self.recent_menu.clear()
        recent = self.settings.value("recent") or []
        if isinstance(recent, str):
            recent = [recent]
        for p in recent:
            if os.path.exists(p):
                self.recent_menu.addAction(os.path.basename(p), lambda p=p: self.open_path(p))
        self.recent_menu.setEnabled(bool(self.recent_menu.actions()))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()]
        if not files:
            return
        if self.modified or len(self.doc.layers) > 1:
            for f in files:
                try:
                    doc, _ = pc.load_image_file(f)
                    self._add_image_layer(pc.composite(doc), os.path.splitext(os.path.basename(f))[0])
                except Exception:
                    pass
        else:
            self.open_path(files[0])

    def show_shortcuts(self):
        lines = [f"{sc}  —  {name}" for _, _, name, sc in TOOLS if sc]
        lines += ["", "Space + drag — pan    Ctrl + wheel — zoom", "[ / ] — brush size    X — swap colours",
                  "Ctrl+Z / Ctrl+Shift+Z — undo / redo    Ctrl+D — deselect", "Ctrl+J — duplicate layer / copy selection to layer",
                  "Ctrl+E — merge down    Ctrl+T — transform    Delete — clear selected pixels"]
        QMessageBox.information(self, "Keyboard Shortcuts", "\n".join(lines))


def main():
    app = make_app(APP_NAME, sys.argv)
    win = PhotoWindow(sys.argv[1] if len(sys.argv) > 1 else None)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
