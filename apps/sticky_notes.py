"""Ethical Sticky Notes - notes that stay on your desktop. Good for to-do lists.

Each note is its own small window: drag it by the top bar, resize it from any edge, pick a colour, keep it on
top of other windows, or fold it down to its title (double-click the top bar). Notes can hold to-do checkboxes,
bullets and bold/italic/underline/strikethrough text. Everything saves automatically to a file on this PC
(see stickies_core.py) - nothing is uploaded. A tray icon (bottom-right of the taskbar) brings all notes back.

Run: .venv\\Scripts\\pythonw apps\\sticky_notes.py   [--new] [--startup]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal  # noqa: E402
from PySide6.QtGui import (QAction, QActionGroup, QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap,  # noqa: E402
                           QShortcut, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument, QTextFormat,
                           QTextListFormat)
from PySide6.QtWidgets import (QApplication, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,  # noqa: E402
                               QListWidgetItem, QMenu, QMessageBox, QPushButton, QSystemTrayIcon, QTextEdit,
                               QToolButton, QVBoxLayout, QWidget, QWidgetAction)

import stickies_core as core  # noqa: E402
from suite_common import icon_path, launch_command, make_app, open_guide  # noqa: E402

APP_NAME = "Ethical Sticky Notes"
SERVER_NAME = "EthicalStickyNotes-" + os.environ.get("USERNAME", "user")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "EthicalSuite.StickyNotes"
EDGE = 6                     # px around a note that resize it
HEADER_H = 30
MarkerType = QTextBlockFormat.MarkerType


# ====================================================================== text helpers (checklists etc.)

def blocks_in(cursor):
    doc = cursor.document()
    b = doc.findBlock(cursor.selectionStart())
    end = cursor.selectionEnd()
    while b.isValid():
        yield b
        if b.position() + b.length() > end:
            break
        b = b.next()


def set_checked(block, checked):
    tc = QTextCursor(block)
    bf = block.blockFormat()
    bf.setMarker(MarkerType.Checked if checked else MarkerType.Unchecked)
    tc.setBlockFormat(bf)
    tc.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
    cf = QTextCharFormat()
    cf.setFontStrikeOut(checked)          # done items are crossed out
    tc.mergeCharFormat(cf)


def remove_from_list(block):
    lst = block.textList()
    if lst:
        lst.remove(block)
    bf = block.blockFormat()
    bf.setIndent(0)
    bf.setMarker(MarkerType.NoMarker)
    QTextCursor(block).setBlockFormat(bf)


def normalize_checks(doc):
    """Cross out checked items (e.g. ones the AI ticked) so they look the same as ones ticked by hand."""
    b = doc.begin()
    while b.isValid():
        if b.blockFormat().marker() == MarkerType.Checked:
            set_checked(b, True)
        b = b.next()


class NoteEdit(QTextEdit):
    """The writing area. Click a checkbox to tick it; '- ' or '[] ' at the start of a line starts a list."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QTextEdit.NoFrame)
        self.setAcceptRichText(False)
        self.setTabChangesFocus(False)
        self.document().setDocumentMargin(10)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def _box_rect(self, b):
        """Where the checkbox of to-do item `b` is drawn (viewport coordinates) - painting and clicking use this."""
        r = self.cursorRect(QTextCursor(b))
        s = max(12, round(r.height() * 0.72))
        return QRect(r.left() - s - 7, r.center().y() - s // 2, s, s)

    def _checkbox_hit(self, pos):
        b = self.cursorForPosition(pos).block()
        for cand in (b, b.previous(), b.next()):
            if cand.isValid() and cand.blockFormat().marker() != MarkerType.NoMarker:
                if self._box_rect(cand).adjusted(-7, -5, 7, 5).contains(pos):    # a little extra room around the box
                    return cand
        return None

    def mousePressEvent(self, e):
        b = self._checkbox_hit(e.position().toPoint()) if e.button() == Qt.LeftButton else None
        if b is not None:
            self._toggle(b)
            return                                 # clicking a box never moves the text cursor or selects text
        super().mousePressEvent(e)

    def _toggle(self, b):
        import time
        c = QTextCursor(b)
        c.beginEditBlock()
        set_checked(b, b.blockFormat().marker() != MarkerType.Checked)
        c.endEditBlock()
        self._last_toggle = (b.blockNumber(), time.monotonic())
        self.viewport().update()

    def mouseDoubleClickEvent(self, e):
        # a double-click on a box counts as ONE click (the first press already ticked it) - it doesn't untick again
        # or select the word next to it
        b = self._checkbox_hit(e.position().toPoint()) if e.button() == Qt.LeftButton else None
        if b is not None:
            import time
            num, when = getattr(self, "_last_toggle", (-1, 0.0))
            if num != b.blockNumber() or time.monotonic() - when > 0.6:
                self._toggle(b)                    # a double-click without a first click (some tablets/tools)
            return
        super().mouseDoubleClickEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._checkbox_hit(e.position().toPoint()) is not None:
            return
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        hit = self._checkbox_hit(e.position().toPoint())
        num = hit.blockNumber() if hit is not None else -1
        if num != getattr(self, "_hover", -1):
            self._hover = num
            self.viewport().update()
        self.viewport().setCursor(Qt.PointingHandCursor if hit is not None else Qt.IBeamCursor)
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        if getattr(self, "_hover", -1) != -1:
            self._hover = -1
            self.viewport().update()
        super().leaveEvent(e)

    def keyPressEvent(self, e):
        c = self.textCursor()
        b = c.block()
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers() & Qt.ShiftModifier:
            if c.currentList() and not b.text().strip():
                remove_from_list(b)               # Enter on an empty item ends the list
                return
            super().keyPressEvent(e)
            nb = self.textCursor().block()
            if nb.blockFormat().marker() == MarkerType.Checked:
                set_checked(nb, False)           # new item after a done item starts unticked
            cf = self.currentCharFormat()
            if cf.fontStrikeOut() and nb.blockFormat().marker() != MarkerType.NoMarker:
                cf.setFontStrikeOut(False)
                self.setCurrentCharFormat(cf)
            return
        if e.key() == Qt.Key_Space and not c.hasSelection() and not c.currentList():
            before = b.text()[:c.positionInBlock()]
            kind = {"-": "bullet", "*": "bullet", "[]": "check", "[ ]": "check"}.get(before)
            if kind:
                c.beginEditBlock()
                c.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
                c.removeSelectedText()
                make_list(c, kind == "check")
                c.endEditBlock()
                return
        if e.key() == Qt.Key_Backspace and c.currentList() and c.positionInBlock() == 0 and not c.hasSelection():
            remove_from_list(b)                   # Backspace at the start of an item turns it back into text
            return
        super().keyPressEvent(e)

    def paintEvent(self, e):
        """Qt draws plain ☐/☒ boxes for to-do items; paint friendlier rounded checkboxes with a tick on top."""
        super().paintEvent(e)
        body, text = getattr(self, "colors", ("#FFF6A5", "#2B2B2B"))
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        b = self.cursorForPosition(QPoint(0, 0)).block()
        bottom = self.viewport().height()
        while b.isValid():
            r = self.cursorRect(QTextCursor(b))
            if r.top() > bottom:
                break
            marker = b.blockFormat().marker()
            if marker != MarkerType.NoMarker and b.isVisible():
                box = self._box_rect(b)
                s = box.width()
                p.fillRect(box.adjusted(-4, -4, 4, 4), QColor(body))          # hide Qt's own box
                ink = QColor(text)
                if b.blockNumber() == getattr(self, "_hover", -1):           # the box under the mouse
                    glow = QColor(text)
                    glow.setAlpha(28)
                    p.setPen(Qt.NoPen)
                    p.setBrush(glow)
                    p.drawRoundedRect(QRectF(box).adjusted(-4, -4, 4, 4), 6, 6)
                if marker == MarkerType.Checked:
                    p.setPen(Qt.NoPen)
                    p.setBrush(ink)
                    p.drawRoundedRect(box, 3.5, 3.5)
                    pen = QPen(QColor(body), max(1.6, s / 7))
                    pen.setCapStyle(Qt.RoundCap)
                    pen.setJoinStyle(Qt.RoundJoin)
                    p.setPen(pen)
                    p.drawPolyline([QPointF(box.left() + s * .24, box.top() + s * .52),
                                    QPointF(box.left() + s * .43, box.top() + s * .71),
                                    QPointF(box.left() + s * .77, box.top() + s * .30)])
                else:
                    ink.setAlpha(170)
                    p.setPen(QPen(ink, max(1.4, s / 9)))
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(QRectF(box).adjusted(.75, .75, -.75, -.75), 3.5, 3.5)
            b = b.next()
        p.end()

    def insertFromMimeData(self, source):
        if source.hasText():                      # paste as plain text: keeps the note's own look
            self.textCursor().insertText(source.text())


def make_list(cursor, checklist):
    blocks = list(blocks_in(cursor))
    lst = blocks[0].textList()
    if lst is None:
        lst = QTextCursor(blocks[0]).createList(QTextListFormat.ListDisc)
    for b in blocks:
        if b.textList() is None:
            lst.add(b)
        if checklist:
            bf = b.blockFormat()
            if bf.marker() == MarkerType.NoMarker:
                bf.setMarker(MarkerType.Unchecked)
                QTextCursor(b).setBlockFormat(bf)
        elif b.blockFormat().marker() != MarkerType.NoMarker:
            set_checked(b, False)
            bf = b.blockFormat()
            bf.setMarker(MarkerType.NoMarker)
            QTextCursor(b).setBlockFormat(bf)


def toggle_list(edit, checklist):
    c = edit.textCursor()
    first = next(blocks_in(c))
    is_check = first.blockFormat().marker() != MarkerType.NoMarker
    c.beginEditBlock()
    if first.textList() is not None and is_check == checklist:
        for b in list(blocks_in(c)):
            if checklist:
                set_checked(b, False)
            remove_from_list(b)
    else:
        make_list(c, checklist)
    c.endEditBlock()
    edit.setFocus()


# ====================================================================== one note window

class Header(QWidget):
    """Top bar: drag to move, double-click to fold the note."""
    def __init__(self, note):
        super().__init__(note)
        self.note = note
        self.setFixedHeight(HEADER_H)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.window().windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        self.note.toggle_collapsed()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(core.COLORS[self.note.data["color"]][1]))


def tool_button(text, tip, slot, parent, checkable=False):
    b = QToolButton(parent)
    b.setText(text)
    b.setToolTip(tip)
    b.setAutoRaise(True)
    b.setCheckable(checkable)
    b.setCursor(Qt.PointingHandCursor)
    b.setFocusPolicy(Qt.NoFocus)
    b.clicked.connect(slot)
    return b


class NoteWindow(QWidget):
    changed = Signal(str)          # note id: content, colour or position changed -> save

    def __init__(self, manager, data):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint)
        self.manager = manager
        self.data = dict(data)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setMouseTracking(True)
        self.setMinimumSize(170, HEADER_H + 2 * EDGE)
        self.setWindowTitle(APP_NAME)

        root = QVBoxLayout(self)
        root.setContentsMargins(EDGE, EDGE, EDGE, EDGE)
        root.setSpacing(0)

        self.header = Header(self)
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(4, 0, 4, 0)
        hl.setSpacing(0)
        self.btn_new = tool_button("+", "New note (Ctrl+N)", lambda: manager.new_note(near=self), self.header)
        hl.addWidget(self.btn_new)
        self.title = QLabel()
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents)
        hl.addWidget(self.title, 1)
        self.btn_pin = tool_button("📌", "Keep on top of other windows", self.toggle_on_top, self.header, True)
        hl.addWidget(self.btn_pin)
        self.btn_menu = tool_button("⋯", "Colour and more", self.show_menu, self.header)
        hl.addWidget(self.btn_menu)
        self.btn_close = tool_button("✕", "Close note (it's kept - reopen it from the tray icon or All notes)",
                                     self.close_note, self.header)
        hl.addWidget(self.btn_close)
        root.addWidget(self.header)

        self.edit = NoteEdit(self)
        self.edit.setPlaceholderText("Take a note…\n\nTip: type [] and a space for a to-do checkbox")
        root.addWidget(self.edit, 1)

        self.footer = QWidget(self)
        fl = QHBoxLayout(self.footer)
        fl.setContentsMargins(4, 2, 4, 2)
        fl.setSpacing(0)
        self.fmt_buttons = []
        for text, tip, fn, style in (
                ("B", "Bold (Ctrl+B)", self.bold, "font-weight:bold"),
                ("I", "Italic (Ctrl+I)", self.italic, "font-style:italic"),
                ("U", "Underline (Ctrl+U)", self.underline, "text-decoration:underline"),
                ("S", "Strikethrough (Ctrl+T)", self.strike, "text-decoration:line-through"),
                ("•", "Bullet list (Ctrl+Shift+L)", lambda: toggle_list(self.edit, False), ""),
                ("☑", "To-do checkboxes (Ctrl+Shift+C)", lambda: toggle_list(self.edit, True), "")):
            b = tool_button(text, tip, fn, self.footer)
            b.setStyleSheet(f"QToolButton {{ {style}; font-size:14px; min-width:24px; }}")
            fl.addWidget(b)
            self.fmt_buttons.append(b)
        fl.addStretch(1)
        self.btn_delete = tool_button("🗑", "Delete note (Ctrl+D)", self.delete_note, self.footer)
        fl.addWidget(self.btn_delete)
        root.addWidget(self.footer)
        self.footer.hide()

        for keys, fn in (("Ctrl+N", lambda: manager.new_note(near=self)), ("Ctrl+D", self.delete_note),
                         ("Ctrl+W", self.close_note), ("Ctrl+B", self.bold), ("Ctrl+I", self.italic),
                         ("Ctrl+U", self.underline), ("Ctrl+T", self.strike),
                         ("Ctrl+Shift+L", lambda: toggle_list(self.edit, False)),
                         ("Ctrl+Shift+C", lambda: toggle_list(self.edit, True)),
                         ("F1", lambda: open_guide("stickies"))):
            QShortcut(QKeySequence(keys), self, fn, context=Qt.WidgetWithChildrenShortcut)

        self._expanded_h = self.data.get("h") or 300
        self._loading = False
        self.edit.document().contentsChanged.connect(self._content_changed)
        self.load_from(self.data, geometry=True)

    # ---------------------------------------------------------------- loading / saving
    def load_from(self, data, geometry=False):
        self._loading = True
        self.data = dict(data)
        self.on_disk = dict(data)            # what the notes file says - to notice changes made by others
        doc = self.edit.document()
        f = QFont("Segoe UI")
        f.setPixelSize(core.FONT_SIZES.get(self.data.get("font_size"), 14))
        doc.setDefaultFont(f)
        if self.data.get("html"):
            doc.setHtml(self.data["html"])
        elif self.data.get("text"):
            doc.setMarkdown(self.data["text"])
            normalize_checks(doc)
        else:
            doc.clear()
        # one font for the whole note (size from the note's "Text size"); bold/italic/... are kept
        c = QTextCursor(doc)
        c.select(QTextCursor.Document)
        cf = QTextCharFormat()
        cf.setFontFamilies(["Segoe UI"])
        cf.setProperty(QTextFormat.FontPixelSize, f.pixelSize())
        c.mergeCharFormat(cf)
        doc.clearUndoRedoStacks()
        self.apply_color()
        self.btn_pin.setChecked(bool(self.data.get("on_top")))
        self.set_on_top(bool(self.data.get("on_top")), save=False)
        if geometry:
            w, h = self.data.get("w") or 300, self.data.get("h") or 300
            self._expanded_h = h
            x, y = self.data.get("x"), self.data.get("y")
            self.resize(w, h)
            if x is not None and y is not None:
                self.move(x, y)
            self.manager.keep_on_screen(self)
        self.set_collapsed(bool(self.data.get("collapsed")), save=False)
        self._loading = False

    def snapshot(self):
        doc = self.edit.document()
        d = dict(self.data)
        d["html"] = doc.toHtml() if not doc.isEmpty() else ""
        d["text"] = doc.toMarkdown(QTextDocument.MarkdownDialectGitHub).strip()
        g = self.geometry()
        d.update(x=g.x(), y=g.y(), w=g.width(), h=self._expanded_h if self.data.get("collapsed") else g.height())
        return d

    def _content_changed(self):
        if self._loading:
            return
        self.data["modified"] = core.now()
        self.update_title()
        self.changed.emit(self.data["id"])

    def moveEvent(self, e):
        super().moveEvent(e)
        if not self._loading:
            self.changed.emit(self.data["id"])

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._loading and not self.data.get("collapsed"):
            self._expanded_h = self.height()
            self.changed.emit(self.data["id"])

    # ---------------------------------------------------------------- look
    def apply_color(self):
        body, head, text = core.COLORS.get(self.data.get("color"), core.COLORS[core.DEFAULT_COLOR])
        dark = self.data.get("color") == "charcoal"
        hover = "rgba(255,255,255,40)" if dark else "rgba(0,0,0,28)"
        self.setStyleSheet(f"""
            NoteWindow {{ background: {body}; }}
            QTextEdit {{ background: {body}; color: {text}; border: none;
                         selection-background-color: {'#5a6b8a' if dark else '#9ec5f5'}; selection-color: {text}; }}
            QLabel {{ color: {text}; font-weight: 600; padding-left: 4px; }}
            QToolButton {{ color: {text}; border: none; border-radius: 4px; padding: 2px 6px; font-size: 13px; }}
            QToolButton:hover {{ background: {hover}; }}
            QToolButton:checked {{ background: {hover}; }}
            QScrollBar:vertical {{ width: 8px; background: transparent; }}
            QScrollBar::handle:vertical {{ background: {'rgba(255,255,255,60)' if dark else 'rgba(0,0,0,45)'};
                                           border-radius: 4px; min-height: 20px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}""")
        self.edit.setPlaceholderText(self.edit.placeholderText())
        pal = self.edit.palette()
        pal.setColor(pal.ColorRole.PlaceholderText, QColor(text).lighter(160) if not dark else QColor("#9a9a9a"))
        self.edit.setPalette(pal)
        self.edit.colors = (body, text)
        self.edit.viewport().update()
        self.header.update()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        body, head, _ = core.COLORS.get(self.data.get("color"), core.COLORS[core.DEFAULT_COLOR])
        p.fillRect(self.rect(), QColor(body))
        p.fillRect(QRect(0, 0, self.width(), EDGE + HEADER_H), QColor(head))
        p.setPen(QColor(head).darker(125))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))   # thin outline so the note stands out from the desktop

    def update_title(self):
        t = core.title_of({"text": self.edit.toPlainText()}, 40) if self.data.get("collapsed") else ""
        self.title.setText(t if t != "(empty note)" else "")

    def set_color(self, name):
        self.data["color"] = name
        self.apply_color()
        self.data["modified"] = core.now()
        self.changed.emit(self.data["id"])

    def set_on_top(self, on, save=True):
        self.data["on_top"] = on
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        if was_visible:
            self.show()
        self.btn_pin.setChecked(on)
        if save:
            self.changed.emit(self.data["id"])

    def toggle_on_top(self):
        self.set_on_top(self.btn_pin.isChecked())

    def set_collapsed(self, on, save=True):
        if on and not self.data.get("collapsed"):
            self._expanded_h = self.height()
        self.data["collapsed"] = on
        self.edit.setVisible(not on)
        self.footer.setVisible(not on and self.isActiveWindow())
        if on:
            self.setFixedHeight(HEADER_H + 2 * EDGE)
        else:
            target = max(self._expanded_h, 120)
            was_loading, self._loading = self._loading, True   # the in-between sizes aren't the note's size
            self.setMinimumHeight(HEADER_H + 2 * EDGE + 60)
            self.setMaximumHeight(16777215)
            self.resize(self.width(), target)
            self._loading = was_loading
            self._expanded_h = target
        self.update_title()
        if save:
            self.changed.emit(self.data["id"])

    def toggle_collapsed(self):
        self.set_collapsed(not self.data.get("collapsed"))

    def set_font_size(self, name):
        self.load_from(self.snapshot() | {"font_size": name, "modified": core.now()})
        self.changed.emit(self.data["id"])

    def changeEvent(self, e):
        if e.type() == QEvent.ActivationChange:
            self.footer.setVisible(self.isActiveWindow() and not self.data.get("collapsed"))
        super().changeEvent(e)

    # ---------------------------------------------------------------- formatting
    def _merge(self, fn):
        c = self.edit.textCursor()
        cf = QTextCharFormat()
        fn(cf, self.edit.currentCharFormat())
        if not c.hasSelection():
            c.select(QTextCursor.WordUnderCursor)
        c.mergeCharFormat(cf)
        self.edit.mergeCurrentCharFormat(cf)
        self.edit.setFocus()

    def bold(self):
        self._merge(lambda cf, cur: cf.setFontWeight(QFont.Normal if cur.fontWeight() > QFont.Normal else QFont.Bold))

    def italic(self):
        self._merge(lambda cf, cur: cf.setFontItalic(not cur.fontItalic()))

    def underline(self):
        self._merge(lambda cf, cur: cf.setFontUnderline(not cur.fontUnderline()))

    def strike(self):
        self._merge(lambda cf, cur: cf.setFontStrikeOut(not cur.fontStrikeOut()))

    # ---------------------------------------------------------------- menu
    def show_menu(self):
        m = QMenu(self)
        swatches = QWidget(m)
        g = QGridLayout(swatches)
        g.setContentsMargins(10, 8, 10, 8)
        g.setSpacing(6)
        for i, (name, (body, head, _)) in enumerate(core.COLORS.items()):
            b = QToolButton(swatches)
            b.setFixedSize(30, 30)
            b.setToolTip(name.title())
            sel = "3px solid #2E7D32" if name == self.data.get("color") else f"1px solid {QColor(head).darker(130).name()}"
            b.setStyleSheet(f"QToolButton {{ background: {body}; border: {sel}; border-radius: 15px; }}")
            b.clicked.connect(lambda _=False, n=name: (self.set_color(n), m.close()))
            g.addWidget(b, i // 4, i % 4)
        wa = QWidgetAction(m)
        wa.setDefaultWidget(swatches)
        m.addAction(wa)
        m.addSeparator()
        a = m.addAction("Keep on top of other windows")
        a.setCheckable(True)
        a.setChecked(bool(self.data.get("on_top")))
        a.triggered.connect(lambda on: self.set_on_top(on))
        a = m.addAction("Fold to title" if not self.data.get("collapsed") else "Unfold")
        a.triggered.connect(self.toggle_collapsed)
        sizes = m.addMenu("Text size")
        grp = QActionGroup(sizes)
        for name in core.FONT_SIZES:
            sa = sizes.addAction(name.title())
            sa.setCheckable(True)
            sa.setChecked(self.data.get("font_size") == name)
            grp.addAction(sa)
            sa.triggered.connect(lambda _=False, n=name: self.set_font_size(n))
        m.addSeparator()
        m.addAction("New note\tCtrl+N", lambda: self.manager.new_note(near=self))
        m.addAction("All notes…", self.manager.show_list)
        m.addAction("Delete note\tCtrl+D", self.delete_note)
        m.addSeparator()
        m.addAction("Help\tF1", lambda: open_guide("stickies"))
        m.exec(self.btn_menu.mapToGlobal(QPoint(0, self.btn_menu.height())))

    # ---------------------------------------------------------------- close / delete
    def close_note(self):
        self.data["open"] = False
        self.hide()
        self.changed.emit(self.data["id"])

    def delete_note(self):
        if self.edit.toPlainText().strip():
            box = QMessageBox(QMessageBox.Question, APP_NAME, "Delete this note?",
                              QMessageBox.Yes | QMessageBox.No, self)
            box.setInformativeText("You can get it back with “Restore deleted note” in the tray icon menu.")
            box.setDefaultButton(QMessageBox.No)
            if box.exec() != QMessageBox.Yes:
                return
        self.manager.delete_note(self.data["id"])

    # ---------------------------------------------------------------- resize from the edges
    def _edges(self, pos):
        edges = Qt.Edges()
        if pos.x() < EDGE:
            edges |= Qt.LeftEdge
        if pos.x() >= self.width() - EDGE:
            edges |= Qt.RightEdge
        if not self.data.get("collapsed"):
            if pos.y() < EDGE:
                edges |= Qt.TopEdge
            if pos.y() >= self.height() - EDGE:
                edges |= Qt.BottomEdge
        return edges

    def mouseMoveEvent(self, e):
        edges = self._edges(e.position().toPoint())
        shapes = {Qt.LeftEdge | Qt.TopEdge: Qt.SizeFDiagCursor, Qt.RightEdge | Qt.BottomEdge: Qt.SizeFDiagCursor,
                  Qt.RightEdge | Qt.TopEdge: Qt.SizeBDiagCursor, Qt.LeftEdge | Qt.BottomEdge: Qt.SizeBDiagCursor}
        if edges in shapes:
            self.setCursor(shapes[edges])
        elif edges & (Qt.LeftEdge | Qt.RightEdge):
            self.setCursor(Qt.SizeHorCursor)
        elif edges & (Qt.TopEdge | Qt.BottomEdge):
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, e):
        edges = self._edges(e.position().toPoint())
        if e.button() == Qt.LeftButton and edges:
            self.windowHandle().startSystemResize(edges)
        elif e.button() == Qt.LeftButton and e.position().y() < EDGE + HEADER_H:
            self.windowHandle().startSystemMove()


# ====================================================================== "All notes" window

class NotesList(QWidget):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.setWindowTitle(f"{APP_NAME} – all notes")
        self.setWindowIcon(QIcon(icon_path("stickynotes")))
        self.resize(380, 520)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        new = QPushButton("+  New note")
        new.clicked.connect(lambda: manager.new_note())
        top.addWidget(new)
        top.addStretch(1)
        show = QPushButton("Show all notes")
        show.clicked.connect(manager.show_all)
        top.addWidget(show)
        lay.addLayout(top)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search notes…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        lay.addWidget(self.search)
        self.list = QListWidget()
        self.list.setIconSize(QSize(18, 40))
        self.list.setSpacing(2)
        self.list.itemDoubleClicked.connect(lambda it: manager.open_note(it.data(Qt.UserRole)))
        lay.addWidget(self.list, 1)
        bottom = QHBoxLayout()
        for text, fn in (("Open", self._open), ("Delete", self._delete), ("Restore deleted note", manager.restore_deleted)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bottom.addWidget(b)
        lay.addLayout(bottom)
        hint = QLabel("Notes are saved automatically on this PC. Double-click a note to open it.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        lay.addWidget(hint)
        QShortcut(QKeySequence("Ctrl+N"), self, lambda: manager.new_note())
        QShortcut(QKeySequence("F1"), self, lambda: open_guide("stickies"))
        QShortcut(QKeySequence.Find, self, self.search.setFocus)

    def refresh(self):
        q = self.search.text().strip().lower()
        self.list.clear()
        notes = sorted(self.manager.all_notes(), key=lambda n: n.get("modified", ""), reverse=True)
        for n in notes:
            text = n.get("text") or ""
            if q and q not in text.lower():
                continue
            preview = " ".join(l.strip() for l in text.replace("~~", "").splitlines()[1:3] if l.strip())[:70]
            when = (n.get("modified") or "")[:16].replace("T", " ")
            it = QListWidgetItem(f"{core.title_of(n)}\n{preview or ' '}   ·   {when}{'' if n.get('open') else '   (closed)'}")
            pm = QPixmap(18, 40)
            pm.fill(QColor(core.COLORS.get(n.get("color"), core.COLORS["yellow"])[1]))
            it.setIcon(QIcon(pm))
            it.setData(Qt.UserRole, n["id"])
            self.list.addItem(it)
        if not self.list.count():
            it = QListWidgetItem("No notes yet – click “+ New note”." if not q else "No notes match your search.")
            it.setFlags(Qt.NoItemFlags)
            self.list.addItem(it)

    def _selected(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _open(self):
        if self._selected():
            self.manager.open_note(self._selected())

    def _delete(self):
        nid = self._selected()
        if nid and QMessageBox.question(self, APP_NAME, "Delete this note?\n\nYou can get it back with “Restore deleted note”.") == QMessageBox.Yes:
            self.manager.delete_note(nid)


# ====================================================================== the manager (tray icon, saving)

class Manager:
    def __init__(self, app):
        self.app = app
        self.windows = {}
        self.dirty = set()
        self.list_window = None
        self.save_timer = QTimer(singleShot=True, interval=500, timeout=self.flush)
        self.reload_timer = QTimer(singleShot=True, interval=300, timeout=self.reload_if_changed)
        self.poll = QTimer(interval=1500, timeout=self.reload_if_changed)   # notices changes made by the AI tools
        self.last_mtime = 0.0
        data = core.load()
        self.trash_count = len(data["trash"])
        for n in data["notes"]:
            self._make_window(n)
        self.last_mtime = core.file_mtime()
        self.poll.start()
        self._make_tray()
        app.aboutToQuit.connect(self.flush)

    # ---------------------------------------------------------------- notes
    def _make_window(self, n):
        w = NoteWindow(self, n)
        w.changed.connect(self._mark_dirty)
        self.windows[n["id"]] = w
        if n.get("open", True):
            w.show()
        return w

    def all_notes(self):
        return [w.snapshot() for w in self.windows.values()]

    def _mark_dirty(self, nid):
        self.dirty.add(nid)
        self.save_timer.start()
        if self.list_window and self.list_window.isVisible():
            QTimer.singleShot(0, self.list_window.refresh)

    def flush(self):
        if not self.dirty:
            return
        changed = [self.windows[i].snapshot() for i in self.dirty if i in self.windows]
        for n in changed:
            self.windows[n["id"]].on_disk = n
        self.dirty.clear()
        try:
            core.apply(changed=changed)
        except OSError as ex:
            self.tray.showMessage(APP_NAME, f"Couldn't save notes: {ex}", QSystemTrayIcon.Warning)
            return
        self.last_mtime = core.file_mtime()

    def reload_if_changed(self):
        """Pick up notes added/changed/deleted by someone else (the AI tools) since our last save."""
        m = core.file_mtime()
        if not m or m == self.last_mtime or self.dirty:
            return
        self.last_mtime = m
        data = core.load()
        ids = set()
        for n in data["notes"]:
            ids.add(n["id"])
            w = self.windows.get(n["id"])
            if w is None:
                self._make_window(n).raise_()
            elif n != w.on_disk:
                if w.edit.hasFocus() and w.isActiveWindow():
                    self.last_mtime = 0.0       # you're typing in it: apply the outside change a moment later
                    continue
                w.load_from(n)
                if n.get("open") and not w.isVisible():
                    w.show()
        for nid in [i for i in self.windows if i not in ids]:
            self.windows.pop(nid).deleteLater()
        self.trash_count = len(data["trash"])
        if self.list_window and self.list_window.isVisible():
            self.list_window.refresh()

    def new_note(self, near=None, text=""):
        n = core.new_note(text=text)
        if near is not None:
            n["color"] = near.data.get("color", core.DEFAULT_COLOR)
            g = near.geometry()
            n["x"], n["y"] = g.x() + 34, g.y() + 34
        else:
            area = QApplication.primaryScreen().availableGeometry()
            k = sum(1 for w in self.windows.values() if w.isVisible()) % 8
            n["x"], n["y"] = area.right() - 340 - 30 * k, area.top() + 40 + 30 * k
        w = self._make_window(n)
        w.raise_()
        w.activateWindow()
        w.edit.setFocus()
        self._mark_dirty(n["id"])
        return w

    def open_note(self, nid):
        w = self.windows.get(nid)
        if not w:
            return
        if not w.data.get("open"):
            w.data["open"] = True
            self._mark_dirty(nid)
        w.show()
        w.raise_()
        w.activateWindow()

    def delete_note(self, nid):
        w = self.windows.pop(nid, None)
        self.dirty.discard(nid)
        self.flush()
        if w:
            w.hide()
            w.deleteLater()
        core.apply(deleted=[nid])
        self.last_mtime = core.file_mtime()
        self.trash_count += 1
        if self.list_window and self.list_window.isVisible():
            self.list_window.refresh()

    def restore_deleted(self):
        self.flush()
        n = core.restore_last()
        self.last_mtime = core.file_mtime()
        if not n:
            QMessageBox.information(None, APP_NAME, "There are no deleted notes to restore.")
            return
        self.trash_count -= 1
        w = self._make_window(n)
        self.keep_on_screen(w)
        w.raise_()
        w.activateWindow()
        if self.list_window and self.list_window.isVisible():
            self.list_window.refresh()

    def show_all(self):
        if not self.windows:
            self.new_note()
            return
        for nid, w in self.windows.items():
            if not w.data.get("open"):
                w.data["open"] = True
                self._mark_dirty(nid)
            w.show()
            w.raise_()

    def hide_all(self):
        for w in self.windows.values():
            w.hide()

    def show_list(self):
        if self.list_window is None:
            self.list_window = NotesList(self)
        self.flush()
        self.list_window.refresh()
        self.list_window.show()
        self.list_window.raise_()
        self.list_window.activateWindow()

    def keep_on_screen(self, w):
        g = w.frameGeometry()
        if QApplication.screenAt(g.center()) is None:
            area = QApplication.primaryScreen().availableGeometry()
            w.move(area.right() - g.width() - 40, area.top() + 40)

    # ---------------------------------------------------------------- tray icon
    def _make_tray(self):
        self.tray = QSystemTrayIcon(QIcon(icon_path("stickynotes")), self.app)
        self.tray.setToolTip(APP_NAME)
        m = QMenu()
        m.addAction("New note", lambda: self.new_note())
        m.addAction("Show all notes", self.show_all)
        m.addAction("Hide all notes", self.hide_all)
        m.addAction("All notes…", self.show_list)
        m.addAction("Restore deleted note", self.restore_deleted)
        m.addSeparator()
        self.autostart_action = m.addAction("Start when Windows starts")
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(autostart_enabled())
        self.autostart_action.triggered.connect(set_autostart)
        m.addAction("Help", lambda: open_guide("stickies"))
        m.addSeparator()
        m.addAction("Quit Sticky Notes", self.quit)
        self.tray_menu = m
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.show_all() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def quit(self):
        self.flush()
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
            cmd = " ".join(f'"{x}"' for x in launch_command("stickynotes", "--startup"))
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, cmd)
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
    message = "new" if "--new" in args else ("startup" if "--startup" in args else "show")
    app = make_app(APP_NAME, sys.argv)
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(os.path.join(QStandardPaths.writableLocation(QStandardPaths.TempLocation), SERVER_NAME + ".lock"))
    if not lock.tryLock(0):
        if send_to_running(message):
            return
    mgr = Manager(app)
    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def handle(msg):
        if msg == "new":
            mgr.new_note()
        elif msg != "startup":
            mgr.show_all()

    def incoming():
        sock = server.nextPendingConnection()
        sock.readyRead.connect(lambda: handle(bytes(sock.readAll()).decode("utf-8", "replace").strip()))
    server.newConnection.connect(incoming)

    if message == "new" or (not mgr.windows and message == "show"):
        mgr.new_note()                    # (at Windows start-up with no notes it just waits in the tray)
    elif message == "show" and not any(w.isVisible() for w in mgr.windows.values()):
        mgr.show_list()
    code = app.exec()
    lock.unlock()
    sys.exit(code)


if __name__ == "__main__":
    main()
