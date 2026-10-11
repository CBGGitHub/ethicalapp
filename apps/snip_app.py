"""Ethical Snip - take a screenshot of part of the screen, mark it up, copy or save it.

Snip a rectangle, a window, the whole screen or a free-form shape (optionally after a 3/5/10 s delay), from the
app, the tray icon or with a keyboard shortcut anywhere (Ctrl+PrtScn by default; changeable). Then draw on it (pen, highlighter, arrows, boxes, text),
pixelate private details, crop, undo/redo, and copy/save/open it in Ethical Photo Editor. Every snip is copied
to the clipboard and (unless turned off) saved to Pictures\\Ethical Snips. Nothing is uploaded.

Run: .venv\\Scripts\\pythonw apps\\snip_app.py  [--snip] [--startup] [picture file]
"""
import ctypes
import math
import os
import sys
import tempfile
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PySide6.QtCore import (QAbstractNativeEventFilter, QEvent, QPoint, QPointF, QRect, QRectF, QSettings, QSize, QSizeF, Qt,  # noqa: E402
                            QTimer, QUrl, Signal)
from PySide6.QtGui import (QAction, QActionGroup, QBrush, QColor, QCursor, QDesktopServices, QFont, QGuiApplication,  # noqa: E402
                           QIcon, QImage, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
                           QShortcut, QUndoCommand, QUndoStack)
from PySide6.QtWidgets import (QApplication, QColorDialog, QDialog, QFileDialog, QKeySequenceEdit, QGraphicsItem, QGraphicsPathItem,  # noqa: E402
                               QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsTextItem,
                               QGraphicsView, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QStackedWidget, QSystemTrayIcon, QToolBar, QToolButton, QVBoxLayout, QWidget)

import snip_core as core  # noqa: E402
from suite_common import icon_path, launch_command, make_app, open_guide, start_detached  # noqa: E402

APP_NAME = "Ethical Snip"
SERVER_NAME = "EthicalSnip-" + os.environ.get("USERNAME", "user")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "EthicalSuite.Snip"
HOTKEY_ID = 0xE51
MODES = [("rect", "Rectangle", "▭"), ("window", "Window", "🗔"), ("screen", "Full screen", "🖵"), ("free", "Free-form", "✎")]
COLORS = ["#E53935", "#FDD835", "#43A047", "#1E88E5", "#212121", "#FFFFFF"]
WIDTHS = {"Thin": 3, "Medium": 6, "Thick": 11}


def settings():
    return QSettings("Ethical Suite", "Ethical Snip")


def setting(key, default):
    v = settings().value(key, default)
    if isinstance(default, bool):
        return v in (True, "true", "1", 1)
    if isinstance(default, int):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default
    return v


# ====================================================================== capture overlay (one per monitor)

class Overlay(QWidget):
    """Frozen picture of one monitor, dimmed; you drag/click to choose what to keep."""
    def __init__(self, session, screen, pixmap):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.session, self.screen_, self.pm = session, screen, pixmap
        self.dpr = pixmap.devicePixelRatio() or 1.0
        self.origin = screen.geometry().topLeft()         # physical pixels on Windows (see snip_core)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.start = None
        self.sel = QRectF()
        self.path = QPainterPath()
        self.hover = None                                  # window rect (local) in window mode
        self.bar = None
        self.setGeometry(screen.geometry())

    def show_on_screen(self):
        self.create()
        self.windowHandle().setScreen(self.screen_)
        self.setGeometry(self.screen_.geometry())
        self.show()

    # ---- the mode bar (shown on the monitor with the mouse)
    def add_bar(self):
        self.bar = QWidget(self)
        self.bar.setObjectName("bar")
        self.bar.setStyleSheet("""#bar { background: rgba(32,32,32,235); border-radius: 10px; }
            QToolButton { color: white; background: transparent; border: none; padding: 6px 10px; font-size: 13px; border-radius: 6px; }
            QToolButton:hover { background: rgba(255,255,255,30); } QToolButton:checked { background: #C2185B; }""")
        lay = QHBoxLayout(self.bar)
        lay.setContentsMargins(6, 4, 6, 4)
        self.mode_buttons = {}
        for key, name, glyph in MODES:
            b = QToolButton(self.bar)
            b.setText(f"{glyph}  {name}")
            b.setCheckable(True)
            b.setChecked(key == self.session.mode)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.session.set_mode(k))
            lay.addWidget(b)
            self.mode_buttons[key] = b
        x = QToolButton(self.bar)
        x.setText("✕")
        x.setToolTip("Cancel (Esc)")
        x.clicked.connect(self.session.cancel)
        lay.addWidget(x)
        self.bar.adjustSize()
        self.bar.move((self.width() - self.bar.width()) // 2, 18)
        self.bar.show()

    def mode_changed(self):
        if self.bar:
            for k, b in self.mode_buttons.items():
                b.setChecked(k == self.session.mode)
        self.sel, self.path, self.start, self.hover = QRectF(), QPainterPath(), None, None
        self.update()
        if self.session.mode == "window":
            self._update_hover(self.mapFromGlobal(QCursor.pos()))

    # ---- painting
    def paintEvent(self, e):
        p = QPainter(self)
        p.drawPixmap(0, 0, self.pm)
        p.fillRect(self.rect(), QColor(0, 0, 0, 115))
        mode = self.session.mode
        keep = None
        if mode == "rect" and not self.sel.isEmpty():
            keep = QPainterPath()
            keep.addRect(self.sel)
        elif mode == "free" and not self.path.isEmpty():
            keep = QPainterPath(self.path)
            keep.closeSubpath()
        elif mode == "window" and self.hover is not None:
            keep = QPainterPath()
            keep.addRect(QRectF(self.hover))
        elif mode == "screen" and self.underMouse():
            keep = QPainterPath()
            keep.addRect(QRectF(self.rect()))
        if keep is not None:
            p.save()
            p.setClipPath(keep)
            p.drawPixmap(0, 0, self.pm)
            p.restore()
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor("#FFFFFF"), 1.5))
            p.drawPath(keep)
            p.setPen(QPen(QColor("#C2185B"), 1, Qt.DashLine))
            p.drawPath(keep)
            r = keep.boundingRect()
            label = f"{round(r.width() * self.dpr)} × {round(r.height() * self.dpr)}"
            f = QFont("Segoe UI")
            f.setPixelSize(12)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(label) + 14
            box = QRectF(r.left(), r.top() - 24 if r.top() > 30 else r.bottom() + 6, tw, 20)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(32, 32, 32, 220))
            p.drawRoundedRect(box, 5, 5)
            p.setPen(QColor("white"))
            p.drawText(box, Qt.AlignCenter, label)
        if mode in ("rect", "free") and self.start is None:
            p.setPen(QColor(255, 255, 255, 200))
            f = QFont("Segoe UI")
            f.setPixelSize(15)
            p.setFont(f)
            hint = "Drag to snip an area" if mode == "rect" else "Draw around what you want to snip"
            p.drawText(self.rect().adjusted(0, 70, 0, 0), Qt.AlignHCenter | Qt.AlignTop, hint + "   ·   Esc to cancel")

    # ---- mouse
    def _update_hover(self, pos):
        phys = QPoint(self.origin.x() + round(pos.x() * self.dpr), self.origin.y() + round(pos.y() * self.dpr))
        self.hover = None
        for hwnd, title, (l, t, r, b) in self.session.windows:
            if l <= phys.x() < r and t <= phys.y() < b:
                rect = QRect(round((l - self.origin.x()) / self.dpr), round((t - self.origin.y()) / self.dpr),
                             round((r - l) / self.dpr), round((b - t) / self.dpr))
                self.hover = rect.intersected(self.rect())
                break
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.session.cancel()
            return
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        mode = self.session.mode
        if mode == "screen":
            self.session.finish(self, QRectF(self.rect()), None)
        elif mode == "window":
            if self.hover is not None and not self.hover.isEmpty():
                self.session.finish(self, QRectF(self.hover), None)
        else:
            self.start = pos
            self.sel = QRectF(pos, pos)
            self.path = QPainterPath(pos)

    def mouseMoveEvent(self, e):
        pos = e.position()
        mode = self.session.mode
        if mode == "window":
            self._update_hover(pos.toPoint())
        elif self.start is not None:
            if mode == "rect":
                self.sel = QRectF(self.start, pos).normalized()
            else:
                self.path.lineTo(pos)
            self.update()
        elif mode == "screen":
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self.start is None:
            return
        mode = self.session.mode
        self.start = None
        if mode == "rect":
            if self.sel.width() >= 4 and self.sel.height() >= 4:
                self.session.finish(self, self.sel, None)
            else:
                self.sel = QRectF()
                self.update()
        elif mode == "free":
            path = QPainterPath(self.path)
            path.closeSubpath()
            r = path.boundingRect()
            if r.width() >= 6 and r.height() >= 6:
                self.session.finish(self, r, path)
            else:
                self.path = QPainterPath()
                self.update()

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.session.cancel()
        else:
            keys = {Qt.Key_R: "rect", Qt.Key_W: "window", Qt.Key_S: "screen", Qt.Key_F: "free"}
            if e.key() in keys:
                self.session.set_mode(keys[e.key()])


class SnipSession:
    """One snip: freeze all monitors, let the user choose, hand back a QImage."""
    def __init__(self, mode, on_done, on_cancel):
        self.mode = mode
        self.on_done, self.on_cancel = on_done, on_cancel
        self.overlays = []
        self.windows = []

    def begin(self):
        shots = core.grab_screens()
        self.windows = core.list_windows(skip_pid=os.getpid())
        cursor_screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        for screen, pm in shots:
            o = Overlay(self, screen, pm)
            self.overlays.append(o)
            o.show_on_screen()
            if screen is cursor_screen:
                o.add_bar()
                o.activateWindow()
                o.raise_()
                o.setFocus()
        for o in self.overlays:
            o.mode_changed()

    def set_mode(self, mode):
        self.mode = mode
        settings().setValue("mode", mode)
        for o in self.overlays:
            o.mode_changed()

    def _close(self):
        for o in self.overlays:
            o.close()
        self.overlays = []

    def cancel(self):
        self._close()
        self.on_cancel()

    def finish(self, overlay, rect, path):
        d = overlay.dpr
        phys = QRect(round(rect.x() * d), round(rect.y() * d), round(rect.width() * d), round(rect.height() * d))
        phys = phys.intersected(QRect(0, 0, overlay.pm.width(), overlay.pm.height()))
        img = overlay.pm.copy(phys).toImage()
        if path is not None:                     # free-form: keep only the inside of the shape
            out = QImage(img.size(), QImage.Format_ARGB32_Premultiplied)
            out.fill(Qt.transparent)
            p = QPainter(out)
            p.setRenderHint(QPainter.Antialiasing)
            clip = QPainterPath(path)
            clip.translate(-rect.x(), -rect.y())
            p.scale(d, d)
            p.setClipPath(clip)
            p.scale(1 / d, 1 / d)
            p.drawImage(0, 0, img)
            p.end()
            img = out
        img.setDevicePixelRatio(1.0)
        self._close()
        self.on_done(img, d)


# ====================================================================== editor items

class HighlightItem(QGraphicsPathItem):
    """Highlighter stroke: multiplies with the picture so text underneath stays readable."""
    def paint(self, painter, option, widget=None):
        painter.setCompositionMode(QPainter.CompositionMode_Multiply)
        super().paint(painter, option, widget)


def arrow_path(a, b, width):
    path = QPainterPath(a)
    head = max(12.0, width * 3.6)
    ang = math.atan2(b.y() - a.y(), b.x() - a.x())
    back = QPointF(b.x() - head * 0.8 * math.cos(ang), b.y() - head * 0.8 * math.sin(ang))
    path.lineTo(back)
    left = QPointF(b.x() - head * math.cos(ang - 0.45), b.y() - head * math.sin(ang - 0.45))
    right = QPointF(b.x() - head * math.cos(ang + 0.45), b.y() - head * math.sin(ang + 0.45))
    path.addPolygon(QPolygonF([b, left, right, b]))
    return path


class AddItems(QUndoCommand):
    def __init__(self, scene, items, text="Add", already=True):
        super().__init__(text)
        self.scene, self.items, self.first = scene, items, already

    def redo(self):
        if self.first:
            self.first = False
            return
        for it in self.items:
            self.scene.addItem(it)

    def undo(self):
        for it in self.items:
            self.scene.removeItem(it)


class RemoveItems(QUndoCommand):
    def __init__(self, scene, items):
        super().__init__("Delete")
        self.scene, self.items = scene, items

    def redo(self):
        for it in self.items:
            self.scene.removeItem(it)

    def undo(self):
        for it in self.items:
            self.scene.addItem(it)


class MoveItems(QUndoCommand):
    def __init__(self, moves):
        super().__init__("Move")
        self.moves = moves                       # [(item, old_pos, new_pos)]
        self.first = True

    def redo(self):
        if self.first:
            self.first = False
            return
        for it, _, new in self.moves:
            it.setPos(new)

    def undo(self):
        for it, old, _ in self.moves:
            it.setPos(old)


class CropCommand(QUndoCommand):
    def __init__(self, canvas, old, new):
        super().__init__("Crop")
        self.canvas, self.old, self.new = canvas, QRectF(old), QRectF(new)

    def redo(self):
        self.canvas.set_crop(self.new)

    def undo(self):
        self.canvas.set_crop(self.old)


class Canvas(QGraphicsView):
    """The picture plus everything drawn on it. Scene units = picture pixels."""
    changed = Signal()

    def __init__(self, undo):
        super().__init__()
        self.undo = undo
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setBackgroundBrush(QColor("#2b2d31"))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setAlignment(Qt.AlignCenter)
        self.base_item = None
        self.base = QImage()
        self.crop = QRectF()
        self.dpr = 1.0
        self.tool = "pen"
        self.color = QColor(COLORS[0])
        self.width_px = WIDTHS["Medium"]
        self.drawing = None
        self.drag_start = None
        self.temp_rect = None
        self.press_positions = {}

    # ---- picture
    def set_image(self, img, dpr=1.0):
        self.scene_.clear()
        self.undo.clear()
        self.base = img
        self.dpr = dpr or 1.0
        self.base_item = QGraphicsPixmapItem(QPixmap.fromImage(img))
        self.base_item.setTransformationMode(Qt.SmoothTransformation)
        self.base_item.setZValue(-10)
        self.scene_.addItem(self.base_item)
        self.set_crop(QRectF(0, 0, img.width(), img.height()))
        self.zoom_actual()

    def set_crop(self, r):
        self.crop = QRectF(r)
        self.scene_.setSceneRect(self.crop)
        self.viewport().update()
        self.changed.emit()

    def zoom_actual(self):
        """Show the snip at the size it had on screen (or smaller if it doesn't fit)."""
        self.resetTransform()
        s = 1 / self.dpr
        vw, vh = max(50, self.viewport().width() - 40), max(50, self.viewport().height() - 40)
        if self.crop.width() * s > vw or self.crop.height() * s > vh:
            s = min(vw / self.crop.width(), vh / self.crop.height())
        self.scale(s, s)
        self.centerOn(self.crop.center())

    def zoom_by(self, f):
        self.scale(f, f)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.zoom_by(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)
        else:
            super().wheelEvent(e)

    def drawForeground(self, p, rect):
        # cover everything outside the crop area, so the view shows exactly what will be saved
        outside = QPainterPath()
        outside.addRect(rect.adjusted(-10, -10, 10, 10))
        inner = QPainterPath()
        inner.addRect(self.crop)
        p.fillPath(outside.subtracted(inner), QColor("#2b2d31"))
        if self.temp_rect is not None:
            pen = QPen(QColor("#C2185B") if self.tool == "crop" else QColor(255, 255, 255, 200), 0, Qt.DashLine)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.temp_rect)

    # ---- tools
    def set_tool(self, tool):
        self.tool = tool
        sel = tool == "select"
        for it in self.scene_.items():
            if it is self.base_item:
                continue
            it.setFlag(QGraphicsItem.ItemIsSelectable, sel)
            it.setFlag(QGraphicsItem.ItemIsMovable, sel)
        if not sel:
            self.scene_.clearSelection()
        self.setDragMode(QGraphicsView.RubberBandDrag if sel else QGraphicsView.NoDrag)
        self.viewport().setCursor(Qt.ArrowCursor if sel else (Qt.IBeamCursor if tool == "text" else Qt.CrossCursor))

    def _pen(self, highlighter=False):
        w = self.width_px * self.dpr * (3.2 if highlighter else 1)
        c = QColor(self.color)
        if highlighter:
            c = QColor("#FFEB3B") if self.color.name().upper() in ("#212121", "#FFFFFF") else QColor(self.color)
        pen = QPen(c, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        return pen

    def _add(self, item, text):
        item.setZValue(len(self.scene_.items()))
        self.scene_.addItem(item)
        self.undo.push(AddItems(self.scene_, [item], text))
        self.changed.emit()

    def mousePressEvent(self, e):
        if self.base_item is None or e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        pt = self.mapToScene(e.position().toPoint())
        if self.tool == "select":
            super().mousePressEvent(e)
            self.press_positions = {it: it.pos() for it in self.scene_.selectedItems()}
            return
        if self.tool == "text":
            item = self.scene_.itemAt(pt, self.transform())
            if isinstance(item, QGraphicsTextItem):
                return super().mousePressEvent(e)
            self.new_text(pt)
            return
        self.drag_start = pt
        if self.tool in ("pen", "highlighter"):
            path = QPainterPath(pt)
            path.lineTo(pt + QPointF(0.01, 0.01))
            item = HighlightItem(path) if self.tool == "highlighter" else QGraphicsPathItem(path)
            item.setPen(self._pen(self.tool == "highlighter"))
            item.setZValue(len(self.scene_.items()))
            self.scene_.addItem(item)
            self.drawing = item
        elif self.tool == "arrow":
            item = QGraphicsPathItem(arrow_path(pt, pt + QPointF(1, 1), self.width_px * self.dpr))
            pen = self._pen()
            item.setPen(pen)
            item.setBrush(pen.color())
            item.setZValue(len(self.scene_.items()))
            self.scene_.addItem(item)
            self.drawing = item
        elif self.tool == "rect":
            item = QGraphicsRectItem(QRectF(pt, pt))
            item.setPen(self._pen())
            item.setZValue(len(self.scene_.items()))
            self.scene_.addItem(item)
            self.drawing = item
        elif self.tool in ("pixelate", "crop"):
            self.temp_rect = QRectF(pt, pt)

    def mouseMoveEvent(self, e):
        if self.drag_start is None:
            return super().mouseMoveEvent(e)
        pt = self.mapToScene(e.position().toPoint())
        if self.tool in ("pen", "highlighter") and self.drawing:
            path = self.drawing.path()
            path.lineTo(pt)
            self.drawing.setPath(path)
        elif self.tool == "arrow" and self.drawing:
            self.drawing.setPath(arrow_path(self.drag_start, pt, self.width_px * self.dpr))
        elif self.tool == "rect" and self.drawing:
            r = QRectF(self.drag_start, pt).normalized()
            if e.modifiers() & Qt.ShiftModifier:
                side = max(r.width(), r.height())
                r.setSize(QSizeF(side, side))
            self.drawing.setRect(r)
        elif self.temp_rect is not None:
            self.temp_rect = QRectF(self.drag_start, pt).normalized()
            self.viewport().update()

    def mouseReleaseEvent(self, e):
        if self.tool == "select":
            super().mouseReleaseEvent(e)
            moves = [(it, old, it.pos()) for it, old in self.press_positions.items() if it.pos() != old]
            if moves:
                self.undo.push(MoveItems(moves))
                self.changed.emit()
            self.press_positions = {}
            return
        if self.drag_start is None:
            return super().mouseReleaseEvent(e)
        self.drag_start = None
        if self.drawing is not None:
            item, self.drawing = self.drawing, None
            if isinstance(item, QGraphicsRectItem) and (item.rect().width() < 3 or item.rect().height() < 3):
                self.scene_.removeItem(item)
                return
            self.undo.push(AddItems(self.scene_, [item], "Draw"))
            self.changed.emit()
        elif self.temp_rect is not None:
            r, self.temp_rect = self.temp_rect.intersected(self.crop), None
            self.viewport().update()
            if r.width() < 4 or r.height() < 4:
                return
            if self.tool == "crop":
                self.undo.push(CropCommand(self, self.crop, r.toAlignedRect()))
                self.zoom_actual()
            else:
                self.pixelate(r)

    def pixelate(self, r):
        rr = r.toAlignedRect().intersected(self.base.rect())
        if rr.isEmpty():
            return
        block = max(6, round(9 * self.dpr))
        part = self.base.copy(rr)
        small = part.scaled(max(1, rr.width() // block), max(1, rr.height() // block),
                            Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        big = small.scaled(rr.size(), Qt.IgnoreAspectRatio, Qt.FastTransformation)
        item = QGraphicsPixmapItem(QPixmap.fromImage(big))
        item.setPos(rr.topLeft())
        self._add(item, "Pixelate")

    def new_text(self, pt):
        item = QGraphicsTextItem()
        f = QFont("Segoe UI")
        f.setPixelSize(round((12 + self.width_px * 2) * self.dpr))
        f.setBold(True)
        item.setFont(f)
        item.setDefaultTextColor(self.color)
        item.setTextInteractionFlags(Qt.TextEditorInteraction)
        item.setPos(pt - QPointF(2, f.pixelSize() * 0.7))
        self._add(item, "Text")
        item.setFocus()
        item.document().contentsChanged.connect(self.changed.emit)

    def delete_selected(self):
        items = [it for it in self.scene_.selectedItems() if it is not self.base_item]
        if items:
            self.undo.push(RemoveItems(self.scene_, items))
            self.changed.emit()

    def event(self, e):
        # while typing in a text box, plain letters (and Delete, Ctrl+C/V/A/Z…) belong to the text, not to the
        # one-key tool shortcuts (P = pen, T = text…) or the window's shortcuts
        if e.type() == QEvent.ShortcutOverride and self.editing_text():
            e.accept()
            return True
        return super().event(e)

    def viewportEvent(self, e):
        if e.type() == QEvent.ShortcutOverride and self.editing_text():
            e.accept()
            return True
        return super().viewportEvent(e)

    def editing_text(self):
        f = self.scene_.focusItem()
        return isinstance(f, QGraphicsTextItem) and bool(f.textInteractionFlags() & Qt.TextEditorInteraction)

    # ---- output
    def render_image(self):
        focus = self.scene_.focusItem()
        if focus:
            focus.clearFocus()
        self.scene_.clearSelection()
        # drop empty text boxes
        for it in list(self.scene_.items()):
            if isinstance(it, QGraphicsTextItem) and not it.toPlainText().strip():
                self.scene_.removeItem(it)
        size = self.crop.toAlignedRect().size()
        fmt = QImage.Format_ARGB32_Premultiplied if self.base.hasAlphaChannel() else QImage.Format_RGB32
        img = QImage(size, fmt)
        img.fill(Qt.transparent if self.base.hasAlphaChannel() else Qt.white)
        p = QPainter(img)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.scene_.render(p, QRectF(img.rect()), self.crop)
        p.end()
        return img


# ====================================================================== main window

class SnipWindow(QMainWindow):
    def __init__(self, app_ctl):
        super().__init__()
        self.ctl = app_ctl
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(icon_path("snip")))
        self.resize(1100, 720)
        self.path = None                 # file this snip is saved in
        self.saved = True
        self.saved_once = False
        self.undo = QUndoStack(self)
        self.undo.cleanChanged.connect(lambda _clean: self._changed())

        self.canvas = Canvas(self.undo)
        self.canvas.changed.connect(self._changed)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._empty_page())
        self.stack.addWidget(self.canvas)
        self.setCentralWidget(self.stack)
        self.setAcceptDrops(True)
        # the current shortcut, always visible in the bottom bar - click it to change it
        self.key_status = QPushButton("")
        self.key_status.setFlat(True)
        self.key_status.setCursor(Qt.PointingHandCursor)
        self.key_status.setToolTip("Click to change the keyboard shortcut that takes a snip from anywhere")
        self.key_status.clicked.connect(lambda: self.ctl.change_hotkey())
        self.statusBar().addPermanentWidget(self.key_status)
        self.update_hotkey_texts("")
        self._toolbars()
        self.statusBar().showMessage("Ready")
        self._update_enabled()

    # ---- layout
    def _empty_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        logo = QLabel()
        logo.setPixmap(QIcon(icon_path("snip")).pixmap(88, 88))
        logo.setAlignment(Qt.AlignCenter)
        lay.addWidget(logo)
        t = QLabel()
        self.empty_title = t
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        krow = QHBoxLayout()
        krow.addStretch(1)
        self.key_btn = QPushButton("⌨  Change shortcut…")
        self.key_btn.setToolTip("Pick the keys that take a snip from anywhere – e.g. Ctrl+Alt+S if your keyboard has no PrtScn key")
        self.key_btn.clicked.connect(lambda: self.ctl.change_hotkey())
        krow.addWidget(self.key_btn)
        krow.addStretch(1)
        lay.addLayout(krow)
        row = QHBoxLayout()
        row.addStretch(1)
        for key, name, glyph in MODES:
            b = QPushButton(f"{glyph}\n{name}")
            b.setFixedSize(120, 80)
            b.setStyleSheet("QPushButton { font-size: 14px; }")
            b.clicked.connect(lambda _=False, k=key: self.ctl.start_snip(k))
            row.addWidget(b)
        row.addStretch(1)
        lay.addSpacing(10)
        lay.addLayout(row)
        hint = QLabel("You can also open a picture (Ctrl+O), paste one (Ctrl+V) or drop one here to mark it up.")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color: palette(placeholder-text);")
        lay.addSpacing(8)
        lay.addWidget(hint)
        lay.addStretch(2)
        return w

    def _toolbars(self):
        tb = QToolBar("Snip")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(tb)
        self.new_btn = QToolButton()
        self.new_btn.setText("✂  New snip")
        self.new_btn.setToolTip("New snip (Ctrl+N) – the arrow chooses the kind and a delay")
        self.new_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self.new_btn.clicked.connect(lambda: self.ctl.start_snip())
        m = QMenu(self)
        self.mode_group = QActionGroup(self)
        for key, name, glyph in MODES:
            a = m.addAction(f"{glyph}  {name}")
            a.setCheckable(True)
            a.setChecked(key == setting("mode", "rect"))
            a.triggered.connect(lambda _=False, k=key: settings().setValue("mode", k))
            self.mode_group.addAction(a)
        m.addSeparator()
        dm = m.addMenu("Delay")
        dg = QActionGroup(self)
        for secs in (0, 3, 5, 10):
            a = dm.addAction("No delay" if not secs else f"{secs} seconds")
            a.setCheckable(True)
            a.setChecked(secs == setting("delay", 0))
            a.triggered.connect(lambda _=False, s=secs: settings().setValue("delay", s))
            dg.addAction(a)
        self.new_btn.setMenu(m)
        tb.addWidget(self.new_btn)
        tb.addSeparator()

        self.tool_group = QActionGroup(self)
        self.tool_actions = {}
        for key, label, tip, sc in (("select", "↖ Select", "Select, move or delete marks (V)", "V"),
                                    ("pen", "✎ Pen", "Draw freehand (P)", "P"),
                                    ("highlighter", "▍Highlight", "Highlighter (H)", "H"),
                                    ("arrow", "➜ Arrow", "Arrow (A)", "A"),
                                    ("rect", "▢ Box", "Rectangle – hold Shift for a square (R)", "R"),
                                    ("text", "T Text", "Click to type text (T)", "T"),
                                    ("pixelate", "▦ Pixelate", "Hide private details: drag over them (X)", "X"),
                                    ("crop", "⌗ Crop", "Drag to keep only that part (C)", "C")):
            a = QAction(label, self)
            a.setToolTip(tip)
            a.setCheckable(True)
            a.setShortcut(QKeySequence(sc))
            a.setShortcutContext(Qt.WindowShortcut)
            a.triggered.connect(lambda _=False, k=key: self.set_tool(k))
            self.tool_group.addAction(a)
            tb.addAction(a)
            self.tool_actions[key] = a
        self.tool_actions["pen"].setChecked(True)
        tb.addSeparator()

        self.color_buttons = []
        for c in COLORS:
            b = QToolButton()
            b.setFixedSize(22, 22)
            b.setToolTip("Colour")
            b.clicked.connect(lambda _=False, col=c: self.set_color(QColor(col)))
            tb.addWidget(b)
            self.color_buttons.append((b, c))
        more = QToolButton()
        more.setText("…")
        more.setToolTip("More colours")
        more.clicked.connect(self.pick_color)
        tb.addWidget(more)
        self.width_btn = QToolButton()
        self.width_btn.setPopupMode(QToolButton.InstantPopup)
        wm = QMenu(self)
        wg = QActionGroup(self)
        for name, px in WIDTHS.items():
            a = wm.addAction(name)
            a.setCheckable(True)
            a.setChecked(name == "Medium")
            a.triggered.connect(lambda _=False, n=name, p=px: self.set_width(n, p))
            wg.addAction(a)
        self.width_btn.setMenu(wm)
        self.width_btn.setText("Medium ▾")
        self.width_btn.setToolTip("Line and text size")
        tb.addWidget(self.width_btn)
        tb.addSeparator()

        self.undo_action = self.undo.createUndoAction(self, "↶ Undo")
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.redo_action = self.undo.createRedoAction(self, "↷ Redo")
        self.redo_action.setShortcuts([QKeySequence.Redo, QKeySequence("Ctrl+Shift+Z")])
        tb.addAction(self.undo_action)
        tb.addAction(self.redo_action)
        tb.addSeparator()

        right = QToolBar("File")
        right.setMovable(False)
        right.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(right)
        self.copy_action = right.addAction("⧉ Copy", self.copy)
        self.copy_action.setToolTip("Copy to the clipboard (Ctrl+C)")
        self.save_action = right.addAction("💾 Save", self.save)
        self.save_action.setToolTip("Save (Ctrl+S)")
        self.saveas_action = right.addAction("Save as…", self.save_as)
        self.photo_action = right.addAction("Open in Photo Editor", self.open_in_photo)
        menu_btn = QToolButton()
        menu_btn.setText("⋯")
        menu_btn.setPopupMode(QToolButton.InstantPopup)
        mm = QMenu(self)
        mm.addAction("Open a picture…\tCtrl+O", self.open_file)
        mm.addAction("Paste a picture\tCtrl+V", self.paste)
        mm.addAction("Open the snips folder", self.ctl.open_folder)
        mm.addSeparator()
        for key, label, default in (("auto_copy", "Copy every snip to the clipboard", True),
                                    ("auto_save", "Save every snip automatically (Pictures\\Ethical Snips)", True),
                                    ("keep_tray", "Keep running in the tray (so the shortcut works)", True)):
            a = mm.addAction(label)
            a.setCheckable(True)
            a.setChecked(setting(key, default))
            a.triggered.connect(lambda on, k=key: settings().setValue(k, on))
        self.autostart_action = mm.addAction("Start when Windows starts")
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(autostart_enabled())
        self.autostart_action.triggered.connect(set_autostart)
        mm.addAction("Change the shortcut…", self.ctl.change_hotkey)
        mm.addAction("Choose the snips folder…", self.ctl.choose_folder)
        mm.addSeparator()
        mm.addAction("Help\tF1", lambda: open_guide("snip"))
        mm.addAction("Quit Ethical Snip", self.ctl.quit)
        menu_btn.setMenu(mm)
        right.addWidget(menu_btn)

        for keys, fn in (("Ctrl+N", lambda: self.ctl.start_snip()), ("Ctrl+O", self.open_file),
                         ("Ctrl+S", self.save), ("Ctrl+Shift+S", self.save_as), ("F1", lambda: open_guide("snip")),
                         ("Ctrl+0", self.canvas.zoom_actual), ("Ctrl+=", lambda: self.canvas.zoom_by(1.25)),
                         ("Ctrl+-", lambda: self.canvas.zoom_by(0.8))):
            QShortcut(QKeySequence(keys), self, fn)
        self.copy_sc = QShortcut(QKeySequence.Copy, self, self._copy_shortcut)
        self.paste_sc = QShortcut(QKeySequence.Paste, self, self._paste_shortcut)
        self.del_sc = QShortcut(QKeySequence.Delete, self, self._delete_shortcut)
        QShortcut(QKeySequence(Qt.Key_Escape), self, lambda: self.set_tool("select"))
        self.set_color(QColor(COLORS[0]))

    def update_hotkey_texts(self, label):
        how = (f"Or press <b>{label}</b> anywhere, any time." if label
               else "No keyboard shortcut yet – click “Change shortcut…” to pick one.")
        self.empty_title.setText("<div style='font-size:22px;font-weight:600'>Take a snip</div>"
                                 f"<div style='color:palette(placeholder-text)'>Choose what to capture. {how}</div>")
        self.key_status.setText(f"⌨ Shortcut: {label}" if label else "⌨ Set a shortcut…")

    # ---- state
    def _set_saved(self, saved):
        self.saved = saved
        name = os.path.basename(self.path) if self.path else ("Untitled snip" if self.has_image() else "")
        self.setWindowTitle(f"{'*' if not saved else ''}{name} – {APP_NAME}" if name else APP_NAME)

    def _changed(self):
        self._set_saved(self.undo.isClean() and self.saved_once)

    def has_image(self):
        return self.canvas.base_item is not None

    def _update_enabled(self):
        on = self.has_image()
        for a in list(self.tool_actions.values()) + [self.copy_action, self.save_action, self.saveas_action,
                                                     self.photo_action]:
            a.setEnabled(on)

    def set_tool(self, key):
        self.tool_actions[key].setChecked(True)
        self.canvas.set_tool(key)

    def set_color(self, c):
        self.canvas.color = QColor(c)
        for b, col in self.color_buttons:
            border = "3px solid #C2185B" if QColor(col) == c else "1px solid #888"
            b.setStyleSheet(f"QToolButton {{ background: {col}; border: {border}; border-radius: 11px; }}")
        f = self.canvas.scene_.focusItem()
        if isinstance(f, QGraphicsTextItem):
            f.setDefaultTextColor(c)

    def pick_color(self):
        c = QColorDialog.getColor(self.canvas.color, self, "Colour")
        if c.isValid():
            self.set_color(c)

    def set_width(self, name, px):
        self.canvas.width_px = px
        self.width_btn.setText(f"{name} ▾")

    # ---- loading pictures
    def load_image(self, img, dpr=1.0, path=None):
        if not self.maybe_keep_changes():
            return False
        self.canvas.set_image(img, dpr)
        self.stack.setCurrentIndex(1)
        self.path = path
        self.saved_once = path is not None
        self.undo.setClean()
        self._set_saved(path is not None)
        self._update_enabled()
        self.set_tool("pen" if self.canvas.tool == "select" else self.canvas.tool)
        QTimer.singleShot(0, self.canvas.zoom_actual)
        return True

    def open_file(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open a picture", self.ctl.folder(),
                                                  "Pictures (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff);;All files (*)")
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, APP_NAME, "That file couldn't be opened as a picture.")
            return
        if self.load_image(img, 1.0, None):
            self.statusBar().showMessage(f"Opened {os.path.basename(path)} – mark it up, then Save as…", 6000)
        self.show_window()

    def paste(self):
        img = QApplication.clipboard().image()
        if img.isNull():
            self.statusBar().showMessage("There's no picture on the clipboard.", 4000)
            return
        self.load_image(img, 1.0, None)

    def _copy_shortcut(self):
        if self.canvas.editing_text():
            self.canvas.scene_.focusItem().textCursor()   # let the text box handle it
            return
        self.copy()

    def _paste_shortcut(self):
        if self.canvas.editing_text():
            f = self.canvas.scene_.focusItem()
            f.textCursor().insertText(QApplication.clipboard().text())
            return
        self.paste()

    def _delete_shortcut(self):
        if not self.canvas.editing_text():
            self.canvas.delete_selected()

    # ---- output
    def copy(self):
        if not self.has_image():
            return
        QApplication.clipboard().setImage(self.canvas.render_image())
        self.statusBar().showMessage("Copied – paste it anywhere with Ctrl+V.", 5000)

    def _write(self, path):
        img = self.canvas.render_image()
        ext = os.path.splitext(path)[1].lower()
        if ext in (".jpg", ".jpeg", ".bmp") and img.hasAlphaChannel():
            flat = QImage(img.size(), QImage.Format_RGB32)
            flat.fill(Qt.white)
            p = QPainter(flat)
            p.drawImage(0, 0, img)
            p.end()
            img = flat
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not img.save(path, quality=92):
            QMessageBox.warning(self, APP_NAME, f"Couldn't save {path}.")
            return False
        self.path = path
        self.saved_once = True
        self.undo.setClean()
        self._set_saved(True)
        self.statusBar().showMessage(f"Saved {path}", 6000)
        return True

    def save(self):
        if not self.has_image():
            return False
        if self.path:
            return self._write(self.path)
        return self.save_as()

    def save_as(self):
        if not self.has_image():
            return False
        start = self.path or core.new_file_name(self.ctl.folder())
        path, _ = QFileDialog.getSaveFileName(self, "Save snip", start,
                                              "PNG picture (*.png);;JPG picture (*.jpg);;WebP picture (*.webp);;BMP picture (*.bmp)")
        return self._write(path) if path else False

    def open_in_photo(self):
        if not self.has_image():
            return
        if self.path and self.saved:
            path = self.path
        else:
            path = os.path.join(tempfile.gettempdir(), "Ethical Snip", os.path.basename(core.new_file_name(".")))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.canvas.render_image().save(path)
        start_detached(launch_command("photo", path))
        self.statusBar().showMessage("Opening in Ethical Photo Editor…", 4000)

    def maybe_keep_changes(self):
        """Ask before throwing away marks that haven't been saved. Returns False to cancel."""
        if not self.has_image() or self.undo.isClean() or self.undo.count() == 0:
            return True
        r = QMessageBox.question(self, APP_NAME, "Save the changes to this snip first?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.Save:
            return bool(self.save())
        return True

    # ---- window
    def show_window(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):
        if not self.maybe_keep_changes():
            e.ignore()
            return
        self.undo.setClean()
        if setting("keep_tray", True) and self.ctl.tray is not None:
            e.ignore()
            self.hide()
            self.ctl.tray_tip()
        else:
            e.accept()
            self.ctl.quit()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasUrls() and md.urls()[0].isLocalFile():
            self.open_file(md.urls()[0].toLocalFile())
        elif md.hasImage():
            self.load_image(QImage(md.imageData()), 1.0)


# ====================================================================== global shortcut (Ctrl+PrtScn by default, changeable)

class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam == HOTKEY_ID:      # WM_HOTKEY
                QTimer.singleShot(0, self.callback)
                return True, 0
        return False, 0


DEFAULT_HOTKEY = "Ctrl+Print"
_VK_NAMED = {Qt.Key_Print: 0x2C, Qt.Key_Space: 0x20, Qt.Key_Insert: 0x2D, Qt.Key_Delete: 0x2E, Qt.Key_Home: 0x24,
             Qt.Key_End: 0x23, Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22, Qt.Key_Left: 0x25, Qt.Key_Up: 0x26,
             Qt.Key_Right: 0x27, Qt.Key_Down: 0x28, Qt.Key_Pause: 0x13, Qt.Key_ScrollLock: 0x91,
             Qt.Key_Backspace: 0x08, Qt.Key_Tab: 0x09, Qt.Key_Return: 0x0D, Qt.Key_Enter: 0x0D,
             Qt.Key_Minus: 0xBD, Qt.Key_Equal: 0xBB, Qt.Key_Comma: 0xBC, Qt.Key_Period: 0xBE, Qt.Key_Slash: 0xBF,
             Qt.Key_Semicolon: 0xBA, Qt.Key_Apostrophe: 0xDE, Qt.Key_BracketLeft: 0xDB, Qt.Key_BracketRight: 0xDD,
             Qt.Key_Backslash: 0xDC, Qt.Key_QuoteLeft: 0xC0}


def hotkey_to_win(text):
    """'Ctrl+Shift+S' -> (Win32 modifier flags, virtual-key code), or None if it can't be a global shortcut."""
    seq = QKeySequence(text)
    if seq.isEmpty():
        return None
    combo = seq[0]
    key, mods = combo.key(), combo.keyboardModifiers()
    flags = 0
    if mods & Qt.ControlModifier:
        flags |= 0x0002
    if mods & Qt.AltModifier:
        flags |= 0x0001
    if mods & Qt.ShiftModifier:
        flags |= 0x0004
    if mods & Qt.MetaModifier:
        flags |= 0x0008                          # Windows key
    if Qt.Key_A <= key <= Qt.Key_Z or Qt.Key_0 <= key <= Qt.Key_9:
        vk = int(key)                            # same codes as Windows for letters and digits
    elif Qt.Key_F1 <= key <= Qt.Key_F24:
        vk = 0x70 + int(key) - int(Qt.Key_F1)
    elif key in _VK_NAMED:
        vk = _VK_NAMED[key]
    else:
        return None
    # a plain letter/digit without Ctrl/Alt/Win would fire while typing anywhere - don't allow that
    if not flags & 0x000B and not (Qt.Key_F1 <= key <= Qt.Key_F24 or key in (Qt.Key_Print, Qt.Key_Pause, Qt.Key_ScrollLock)):
        return None
    return flags, vk


def hotkey_label(text):
    return QKeySequence(text).toString(QKeySequence.NativeText).replace("Print", "PrtScn") if text else ""


def register_hotkey(hwnd, text):
    user32 = ctypes.windll.user32
    user32.UnregisterHotKey(wintypes.HWND(hwnd), HOTKEY_ID)
    parsed = hotkey_to_win(text)
    if not parsed:
        return False
    flags, vk = parsed
    return bool(user32.RegisterHotKey(wintypes.HWND(hwnd), HOTKEY_ID, flags | 0x4000, vk))     # 0x4000 = no repeat


class HotkeyDialog(QDialog):
    """Pick the keyboard shortcut that starts a snip from anywhere."""
    def __init__(self, parent, current):
        super().__init__(parent)
        self.setWindowTitle("Snip shortcut")
        self.result_text = current
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Click the box and press the keys you want to use to start a snip from anywhere\n"
                             "(for example Ctrl+Alt+S – handy if your keyboard has no PrtScn key):"))
        self.edit = QKeySequenceEdit(QKeySequence(current) if current else QKeySequence())
        self.edit.setMaximumSequenceLength(1)
        lay.addWidget(self.edit)
        self.msg = QLabel("")
        self.msg.setStyleSheet("color: #C62828;")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        row = QHBoxLayout()
        for label, fn in (("Use Ctrl+PrtScn", lambda: self.edit.setKeySequence(QKeySequence(DEFAULT_HOTKEY))),
                          ("No shortcut", self._none)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self._ok)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)

    def _none(self):
        self.result_text = ""
        self.accept()

    def _ok(self):
        text = self.edit.keySequence().toString(QKeySequence.PortableText)
        if not text:
            self._none()
            return
        if hotkey_to_win(text) is None:
            self.msg.setText("That key can't be used on its own. Add Ctrl, Alt or the Windows key "
                             "(F-keys and PrtScn also work alone).")
            return
        self.result_text = text
        self.accept()


# ====================================================================== the app controller

class SnipApp:
    def __init__(self, app):
        self.app = app
        self.tray = None
        self.session = None
        self.hotkey_ok = False
        self.window = None
        self.window = SnipWindow(self)
        self.filter = HotkeyFilter(lambda: self.start_snip(from_hotkey=True))
        app.installNativeEventFilter(self.filter)
        self._make_tray()
        self.apply_hotkey(setting("hotkey", DEFAULT_HOTKEY), quiet=True)

    def hotkey_text(self):
        return hotkey_label(setting("hotkey", DEFAULT_HOTKEY)) if self.hotkey_ok else ""

    def apply_hotkey(self, text, quiet=False):
        """Register `text` as the global snip shortcut and update every place that mentions it."""
        self.hotkey_ok = register_hotkey(int(self.window.winId()), text) if text else False
        label = hotkey_label(text)
        if text and not self.hotkey_ok:
            msg = f"{label} is used by another program – choose another shortcut in ⋯ → Change the shortcut."
            if not quiet:
                QMessageBox.warning(self.window, APP_NAME, msg)
        elif self.hotkey_ok:
            msg = f"Press {label} anywhere to snip."
        else:
            msg = "No shortcut set – use New snip or the tray icon (⋯ → Change the shortcut to add one)."
        self.window.statusBar().showMessage(msg)
        self.window.update_hotkey_texts(self.hotkey_text())
        if self.tray:
            self.tray.setToolTip(f"{APP_NAME} – {label} to snip" if self.hotkey_ok else APP_NAME)
            self.tray_new.setText("New snip" + (f"\t{label}" if self.hotkey_ok else ""))
        return self.hotkey_ok

    def change_hotkey(self):
        old = setting("hotkey", DEFAULT_HOTKEY)
        d = HotkeyDialog(self.window, old)
        if d.exec() != QDialog.Accepted:
            return
        if self.apply_hotkey(d.result_text) or not d.result_text:
            settings().setValue("hotkey", d.result_text)
        else:
            self.apply_hotkey(old, quiet=True)          # keep the old one working

    def folder(self):
        return setting("folder", "") or core.default_folder()

    def choose_folder(self):
        f = QFileDialog.getExistingDirectory(self.window, "Save snips in", self.folder())
        if f:
            settings().setValue("folder", f)

    def open_folder(self):
        os.makedirs(self.folder(), exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder()))

    # ---- snipping
    def start_snip(self, mode=None, from_hotkey=False):
        if self.session is not None:
            return
        if mode:
            settings().setValue("mode", mode)
        mode = setting("mode", "rect")
        delay = 0 if from_hotkey else setting("delay", 0)
        self._was_visible = self.window.isVisible() and not self.window.isMinimized()
        self.window.hide()
        self.session = SnipSession(mode, self._snipped, self._cancelled)
        # give the window time to disappear (and the user time to set things up, if delayed)
        if delay and self.tray:
            self.tray.showMessage(APP_NAME, f"Snipping in {delay} seconds…", QSystemTrayIcon.Information, 1500)
        QTimer.singleShot(max(220, delay * 1000), self.session.begin)

    def _cancelled(self):
        self.session = None
        if self._was_visible:
            self.window.show_window()

    def _snipped(self, img, dpr):
        self.session = None
        notes = []
        saved_path = None
        if setting("auto_copy", True):
            QApplication.clipboard().setImage(img)
            notes.append("copied")
        if setting("auto_save", True):
            path = core.new_file_name(self.folder())
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if img.save(path):
                saved_path = path
                notes.append(f"saved to {path}")
        self.window.load_image(img, dpr, saved_path)
        self.window.show_window()
        if notes:
            self.window.statusBar().showMessage("Snip " + " and ".join(notes) + ".", 8000)

    # ---- tray
    def _make_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(QIcon(icon_path("snip")), self.app)
        self.tray.setToolTip(APP_NAME)
        m = QMenu()
        self.tray_new = m.addAction("New snip", lambda: self.start_snip())
        for key, name, glyph in MODES:
            m.addAction(f"    {glyph}  {name}", lambda k=key: self.start_snip(k))
        m.addSeparator()
        m.addAction("Open Ethical Snip", self.window.show_window)
        m.addAction("Open the snips folder", self.open_folder)
        m.addAction("Help", lambda: open_guide("snip"))
        m.addSeparator()
        m.addAction("Quit Ethical Snip", self.quit)
        self.tray_menu = m
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.window.show_window() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def tray_tip(self):
        if not setting("tray_tip_shown", False) and self.tray:
            settings().setValue("tray_tip_shown", True)
            how = f"Press {self.hotkey_text()} any time to take a snip." if self.hotkey_ok else "Click here to take a snip."
            self.tray.showMessage(APP_NAME, "Snip is still running here. " + how, QSystemTrayIcon.Information, 5000)

    def quit(self):
        ctypes.windll.user32.UnregisterHotKey(wintypes.HWND(int(self.window.winId())), HOTKEY_ID)
        if self.tray:
            self.tray.hide()
        self.app.quit()


# ====================================================================== start with Windows

def autostart_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_VALUE)
            return True
    except OSError:
        return False


def set_autostart(on):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ,
                              " ".join(f'"{x}"' for x in launch_command("snip", "--startup")))
        else:
            try:
                winreg.DeleteValue(k, RUN_VALUE)
            except OSError:
                pass


# ====================================================================== start-up (one copy only)

def send_to_running(message):
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(300):
        sock.write(message.encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def main():
    from PySide6.QtCore import QLockFile, QStandardPaths
    from PySide6.QtNetwork import QLocalServer
    args = sys.argv[1:]
    files = [a for a in args if not a.startswith("--") and os.path.isfile(a)]
    message = ("open\n" + files[0]) if files else ("snip" if "--snip" in args else
                                                    ("startup" if "--startup" in args else "show"))
    app = make_app(APP_NAME, sys.argv)
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(os.path.join(QStandardPaths.writableLocation(QStandardPaths.TempLocation), SERVER_NAME + ".lock"))
    if not lock.tryLock(0):
        if send_to_running(message):
            return
    ctl = SnipApp(app)
    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def handle(msg):
        if msg.startswith("open\n"):
            ctl.window.open_file(msg.split("\n", 1)[1])
        elif msg == "snip":
            ctl.start_snip()
        elif msg != "startup":
            ctl.window.show_window()

    def incoming():
        sock = server.nextPendingConnection()
        sock.readyRead.connect(lambda: handle(bytes(sock.readAll()).decode("utf-8", "replace").strip()))
    server.newConnection.connect(incoming)
    if message != "startup":
        handle(message)
    code = app.exec()
    lock.unlock()
    sys.exit(code)


if __name__ == "__main__":
    main()
