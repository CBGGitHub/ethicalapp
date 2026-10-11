"""Word Processor - write and edit documents; opens and saves real Word (.docx) files."""
import datetime
import os
import sys
import uuid

from PySide6.QtCore import QMarginsF, QRectF, QSettings, QSizeF, Qt, QTimer, QUrl
from PySide6.QtGui import (QAbstractTextDocumentLayout, QAction, QActionGroup, QBrush, QColor,
                           QDesktopServices, QFont, QFontDatabase, QImage, QKeySequence,
                           QPageLayout, QPageSize, QPainter, QPalette, QPdfWriter,
                           QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument,
                           QTextDocumentWriter, QTextFormat, QTextImageFormat, QTextLength,
                           QTextListFormat, QTextTableFormat)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFontComboBox, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSpinBox, QTextEdit, QToolBar, QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from docx_io import (HEADING_LOOK, PX_PER_PT, TITLE_PROP, PageSetup, load_docx,  # noqa: E402
                     save_docx)
from suite_common import SETTINGS_ORG, SUITE_NAME, ColorButton, make_app  # noqa: E402
from suite_common import add_guide_action  # noqa: E402

APP_NAME = "Ethical Document Editor"
OPEN_FILTER = ("All supported (*.docx *.html *.htm *.md *.txt);;Word documents (*.docx);;"
               "Web pages (*.html *.htm);;Markdown (*.md);;Plain text (*.txt);;All files (*)")
SAVE_FILTER = ("Word document (*.docx);;OpenDocument text (*.odt);;Web page (*.html);;"
               "Markdown (*.md);;Plain text (*.txt)")
STYLES = ["Normal", "Title", "Heading 1", "Heading 2", "Heading 3", "Heading 4"]
PAGE_SIZES = {"Letter (8.5 x 11 in)": (8.5, 11), "Legal (8.5 x 14 in)": (8.5, 14),
              "A4 (210 x 297 mm)": (8.27, 11.69), "A5 (148 x 210 mm)": (5.83, 8.27)}
BULLET_CYCLE = [QTextListFormat.ListDisc, QTextListFormat.ListCircle, QTextListFormat.ListSquare]
NUMBER_CYCLE = [QTextListFormat.ListDecimal, QTextListFormat.ListLowerAlpha,
                QTextListFormat.ListLowerRoman]
GAP_COLOR = QColor("#6b6f76")


def default_family():
    fams = set(QFontDatabase.families())
    return next((f for f in ("Calibri", "Aptos", "Arial") if f in fams), QFont().family())


def normal_spacing(bf):
    bf.setTopMargin(0)
    bf.setBottomMargin(8 * PX_PER_PT)
    bf.setLineHeight(108, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)


def new_document():
    doc = QTextDocument()
    doc.setDefaultFont(QFont(default_family(), 11))
    c = QTextCursor(doc)
    bf = QTextBlockFormat()
    normal_spacing(bf)
    c.setBlockFormat(bf)
    doc.setModified(False)
    return doc


def draw_header_footer(p, setup, page, pages):
    """Draw header/footer/page number for one page; painter origin = page top-left (96 dpi)."""
    if not (setup.header or setup.footer or setup.page_numbers):
        return
    w, h = setup.size_px
    left, right = setup.margin_left * 96, w - setup.margin_right * 96
    p.save()
    f = QFont(default_family())
    f.setPixelSize(12)  # 9pt at 96 dpi; pixel size so it scales with the painter when printing
    p.setFont(f)
    p.setPen(QColor("#555"))
    if setup.header:
        p.drawText(QRectF(left, 0, right - left, setup.margin_top * 96 * 0.75),
                   Qt.AlignHCenter | Qt.AlignBottom, setup.header)
    fy = h - setup.margin_bottom * 96 * 0.75
    if setup.footer:
        p.drawText(QRectF(left, fy, right - left, 40), Qt.AlignLeft | Qt.AlignTop, setup.footer)
    if setup.page_numbers:
        p.drawText(QRectF(left, fy, right - left, 40), Qt.AlignRight | Qt.AlignTop, str(page + 1))
    p.restore()


# ---------------------------------------------------------------- page-shaped editor

class PageEditor(QTextEdit):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setup = PageSetup()
        self.setFrameStyle(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.FixedPixelWidth)
        self.setAutoFormatting(QTextEdit.AutoNone)
        self.setTabStopDistance(48)
        pal = self.viewport().palette()
        pal.setColor(QPalette.Base, Qt.white)
        pal.setColor(QPalette.Text, Qt.black)
        self.viewport().setPalette(pal)

    # ---- page geometry
    def attach(self, doc, setup):
        self.setDocument(doc)
        doc.documentLayout().documentSizeChanged.connect(lambda *_: self.update_height())
        self.apply_setup(setup)

    def apply_setup(self, setup):
        self.setup = setup
        w, _ = setup.size_px
        doc = self.document()
        ff = doc.rootFrame().frameFormat()
        ff.setLeftMargin(setup.margin_left * 96)
        ff.setRightMargin(setup.margin_right * 96)
        ff.setTopMargin(setup.margin_top * 96)
        ff.setBottomMargin(setup.margin_bottom * 96)
        doc.rootFrame().setFrameFormat(ff)
        self.setLineWrapColumnOrWidth(int(w))
        self.setFixedWidth(int(w))
        self.fix_page_size()
        self.viewport().update()

    def fix_page_size(self):
        ps = QSizeF(*self.setup.size_px)
        if self.document().pageSize() != ps:
            self.document().setPageSize(ps)
        self.update_height()

    def page_count(self):
        return max(1, self.document().pageCount())

    def update_height(self):
        if self.document().pageSize().height() <= 0:
            QTimer.singleShot(0, self.fix_page_size)
            return
        h = int(self.page_count() * self.setup.size_px[1])
        if self.height() != h:
            self.setFixedHeight(h)
        self.verticalScrollBar().setValue(0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fix_page_size()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self.viewport())
        w, h = self.setup.size_px
        pages = self.page_count()
        for i in range(1, pages):
            p.fillRect(QRectF(0, i * h - 7, w, 14), GAP_COLOR)
        for i in range(pages):
            p.save()
            p.translate(0, i * h)
            draw_header_footer(p, self.setup, i, pages)
            p.restore()

    def wheelEvent(self, e):
        e.ignore()  # let the surrounding page view scroll

    # ---- keyboard behaviour like Word
    def keyPressEvent(self, e):
        c = self.textCursor()
        block = c.block()
        lst = block.textList()
        key = e.key()
        if key in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers() & Qt.ShiftModifier:
            if lst and not block.text():
                self.win.remove_from_list(c)
                return
            bf = block.blockFormat()
            special = bf.headingLevel() or bf.property(TITLE_PROP)
            super().keyPressEvent(e)
            c = self.textCursor()
            nbf = c.blockFormat()
            if nbf.pageBreakPolicy() != QTextFormat.PageBreak_Auto:
                nbf.setPageBreakPolicy(QTextFormat.PageBreak_Auto)
                c.setBlockFormat(nbf)
            if special and not c.block().text():
                self.win.set_block_style(c.block(), "Normal")
            return
        if key == Qt.Key_Backspace and lst and c.atBlockStart() and not c.hasSelection():
            self.win.remove_from_list(c)
            return
        if key in (Qt.Key_Tab, Qt.Key_Backtab) and lst and c.atBlockStart():
            self.win.change_list_level(1 if key == Qt.Key_Tab else -1)
            return
        super().keyPressEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.modifiers() & Qt.ControlModifier:
            href = self.anchorAt(e.position().toPoint())
            if href:
                QDesktopServices.openUrl(QUrl(href))

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        href = self.anchorAt(e.position().toPoint())
        self.viewport().setCursor(Qt.PointingHandCursor if href and e.modifiers() & Qt.ControlModifier
                                  else Qt.IBeamCursor)
        self.setToolTip(f"{href}\nCtrl+Click to open" if href else "")

    # ---- paste / drop images
    def canInsertFromMimeData(self, src):
        return src.hasImage() or super().canInsertFromMimeData(src)

    def insertFromMimeData(self, src):
        if src.hasImage():
            self.win.insert_qimage(QImage(src.imageData()))
            return
        if src.hasUrls():
            imgs = [u.toLocalFile() for u in src.urls()
                    if u.toLocalFile().lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp"))]
            if imgs:
                for f in imgs:
                    self.win.insert_qimage(QImage(f))
                return
        super().insertFromMimeData(src)

    def contextMenuEvent(self, e):
        menu = self.createStandardContextMenu(e.pos())
        c = self.cursorForPosition(e.pos())
        if not self.textCursor().hasSelection():
            self.setTextCursor(c)
        menu.addSeparator()
        if self.win.image_at_cursor() is not None:
            menu.addAction("Resize Image...", self.win.resize_image)
        if self.textCursor().currentTable():
            menu.addMenu(self.win.table_menu)
        href = self.anchorAt(e.pos())
        if href:
            menu.addAction("Open Link", lambda: QDesktopServices.openUrl(QUrl(href)))
            menu.addAction("Remove Link", self.win.remove_link)
        menu.addMenu(self.win.paragraph_menu)
        menu.exec(e.globalPos())


# ---------------------------------------------------------------- dialogs

class PageSetupDialog(QDialog):
    def __init__(self, parent, setup):
        super().__init__(parent)
        self.setWindowTitle("Page Setup")
        self.size = QComboBox()
        self.size.addItems(list(PAGE_SIZES) + ["Custom"])
        self.w = QDoubleSpinBox()
        self.h = QDoubleSpinBox()
        for s in (self.w, self.h):
            s.setRange(2, 40)
            s.setSuffix(" in")
            s.setSingleStep(0.1)
        self.landscape = QCheckBox("Landscape")
        portrait = (min(setup.width_in, setup.height_in), max(setup.width_in, setup.height_in))
        self.landscape.setChecked(setup.width_in > setup.height_in)
        self.w.setValue(portrait[0])
        self.h.setValue(portrait[1])
        match = next((k for k, v in PAGE_SIZES.items()
                      if abs(v[0] - portrait[0]) < 0.05 and abs(v[1] - portrait[1]) < 0.05), "Custom")
        self.size.setCurrentText(match)
        self.size.currentTextChanged.connect(self._size_changed)
        self.margins = []
        mg = QGridLayout()
        for i, (label, val) in enumerate((("Top", setup.margin_top), ("Bottom", setup.margin_bottom),
                                          ("Left", setup.margin_left), ("Right", setup.margin_right))):
            s = QDoubleSpinBox()
            s.setRange(0, 5)
            s.setSingleStep(0.1)
            s.setSuffix(" in")
            s.setValue(val)
            self.margins.append(s)
            mg.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            mg.addWidget(s, i // 2, (i % 2) * 2 + 1)
        self.header = QLineEdit(setup.header)
        self.footer = QLineEdit(setup.footer)
        self.pagenum = QCheckBox("Show page numbers (bottom right)")
        self.pagenum.setChecked(setup.page_numbers)
        form = QFormLayout()
        form.addRow("Paper size:", self.size)
        row = QHBoxLayout()
        row.addWidget(self.w)
        row.addWidget(QLabel("x"))
        row.addWidget(self.h)
        form.addRow("Size:", row)
        form.addRow("", self.landscape)
        form.addRow("Margins:", mg)
        form.addRow("Header:", self.header)
        form.addRow("Footer:", self.footer)
        form.addRow("", self.pagenum)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(bb)

    def _size_changed(self, name):
        if name in PAGE_SIZES:
            self.w.setValue(PAGE_SIZES[name][0])
            self.h.setValue(PAGE_SIZES[name][1])

    def result_setup(self):
        w, h = self.w.value(), self.h.value()
        if self.landscape.isChecked():
            w, h = max(w, h), min(w, h)
        else:
            w, h = min(w, h), max(w, h)
        t, b, l, r = (s.value() for s in self.margins)
        return PageSetup(w, h, l, t, r, b, self.header.text(), self.footer.text(),
                         self.pagenum.isChecked())


class FindReplaceDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Find and Replace")
        self.find = QLineEdit()
        self.repl = QLineEdit()
        self.case = QCheckBox("Match case")
        self.whole = QCheckBox("Whole words only")
        form = QFormLayout()
        form.addRow("Find:", self.find)
        form.addRow("Replace with:", self.repl)
        form.addRow("", self.case)
        form.addRow("", self.whole)
        self.info = QLabel("")
        btns = QHBoxLayout()
        for text, slot in (("Find Next", self.find_next), ("Replace", self.replace),
                           ("Replace All", self.replace_all), ("Close", self.close)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.info)
        lay.addLayout(btns)
        self.find.returnPressed.connect(self.find_next)

    def flags(self):
        f = QTextDocument.FindFlag(0)
        if self.case.isChecked():
            f |= QTextDocument.FindCaseSensitively
        if self.whole.isChecked():
            f |= QTextDocument.FindWholeWords
        return f

    def find_next(self):
        ed = self.win.editor
        text = self.find.text()
        if not text:
            return False
        c = ed.document().find(text, ed.textCursor(), self.flags())
        if c.isNull():
            c = ed.document().find(text, QTextCursor(ed.document()), self.flags())
        if c.isNull():
            self.info.setText("Not found.")
            return False
        self.info.setText("")
        ed.setTextCursor(c)
        return True

    def replace(self):
        ed = self.win.editor
        c = ed.textCursor()
        same = (c.selectedText() == self.find.text() if self.case.isChecked()
                else c.selectedText().lower() == self.find.text().lower())
        if c.hasSelection() and same:
            c.insertText(self.repl.text())
        self.find_next()

    def replace_all(self):
        ed = self.win.editor
        text = self.find.text()
        if not text:
            return
        doc = ed.document()
        c = QTextCursor(doc)
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        n = 0
        while True:
            c = doc.find(text, c, self.flags())
            if c.isNull():
                break
            c.insertText(self.repl.text())
            n += 1
        edit.endEditBlock()
        self.info.setText(f"Replaced {n} occurrence(s).")


# ---------------------------------------------------------------- main window

class WordProcessor(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        self.path = None
        self.settings = QSettings(SETTINGS_ORG, APP_NAME)
        self.find_dialog = None
        self._updating = False
        self.resize(1250, 900)
        self.setAcceptDrops(True)

        self.editor = PageEditor(self)
        container = QWidget()
        container.setObjectName("pageArea")
        container.setStyleSheet("#pageArea { background: #6b6f76; }")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(30, 24, 30, 40)
        lay.addWidget(self.editor, alignment=Qt.AlignHCenter | Qt.AlignTop)
        self.container = container
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(container)
        self.setCentralWidget(self.scroll)

        self.editor.cursorPositionChanged.connect(self._cursor_moved)
        self.editor.currentCharFormatChanged.connect(self._char_format_changed)
        self.words_label = QLabel()
        self.page_label = QLabel()
        self.statusBar().addPermanentWidget(self.page_label)
        self.statusBar().addPermanentWidget(self.words_label)
        self.count_timer = QTimer(self, singleShot=True, interval=400)
        self.count_timer.timeout.connect(self._update_counts)

        self._build_actions()
        self.set_document(new_document(), PageSetup(), None)
        if path:
            self.open_path(path)

    # ------------------------------------------------------------ actions / toolbars
    def act(self, text, slot, shortcut=None, menu=None, checkable=False, tip=None):
        a = QAction(text, self)
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        if menu is not None:
            menu.addAction(a)
        return a

    def _build_actions(self):
        ed = self.editor
        mb = self.menuBar()
        f = mb.addMenu("&File")
        a_new = self.act("&New", self.new_file, "Ctrl+N", f)
        a_open = self.act("&Open...", self.open_dialog, "Ctrl+O", f)
        self.recent_menu = f.addMenu("Open &Recent")
        self._refresh_recent()
        f.addSeparator()
        a_save = self.act("&Save", self.save, "Ctrl+S", f)
        self.act("Save &As...", self.save_as, "Ctrl+Shift+S", f)
        a_pdf = self.act("Export as &PDF...", self.export_pdf, None, f)
        f.addSeparator()
        self.act("Page Set&up...", self.page_setup, None, f)
        self.act("Print Pre&view...", self.print_preview, None, f)
        a_print = self.act("&Print...", self.print_doc, "Ctrl+P", f)
        f.addSeparator()
        self.act("E&xit", self.close, None, f)

        e = mb.addMenu("&Edit")
        a_undo = self.act("&Undo", ed.undo, "Ctrl+Z", e)
        a_redo = self.act("&Redo", ed.redo, "Ctrl+Y", e)
        e.addSeparator()
        self.act("Cu&t", ed.cut, "Ctrl+X", e)
        self.act("&Copy", ed.copy, "Ctrl+C", e)
        self.act("&Paste", ed.paste, "Ctrl+V", e)
        self.act("Paste as Plain &Text", self.paste_plain, "Ctrl+Shift+V", e)
        self.act("Select &All", ed.selectAll, "Ctrl+A", e)
        e.addSeparator()
        self.act("&Find and Replace...", self.show_find, "Ctrl+F", e)
        self.act("Find &Next", lambda: self.find_dialog and self.find_dialog.find_next(), "F3", e)
        self.act("Rep&lace...", self.show_find, "Ctrl+H", e)

        ins = mb.addMenu("&Insert")
        self.act("&Picture...", self.insert_image_dialog, None, ins)
        a_table = self.act("&Table...", self.insert_table, None, ins)
        self.act("&Link...", self.insert_link, "Ctrl+K", ins)
        self.act("Page &Break", self.insert_page_break, "Ctrl+Return", ins)
        self.act("&Date and Time", self.insert_date, None, ins)
        self.act("Horizontal &Line", self.insert_hline, None, ins)

        fm = mb.addMenu("F&ormat")
        self.a_bold = self.act("&Bold", lambda on: self.merge(weight=QFont.Bold if on else QFont.Normal),
                               "Ctrl+B", fm, True)
        self.a_italic = self.act("&Italic", lambda on: self.merge(italic=on), "Ctrl+I", fm, True)
        self.a_under = self.act("&Underline", lambda on: self.merge(underline=on), "Ctrl+U", fm, True)
        self.a_strike = self.act("&Strikethrough", lambda on: self.merge(strike=on), None, fm, True)
        self.a_sup = self.act("Su&perscript", lambda on: self.merge(valign="sup" if on else None),
                              "Ctrl+Shift+=", fm, True)
        self.a_sub = self.act("Subs&cript", lambda on: self.merge(valign="sub" if on else None),
                              "Ctrl+=", fm, True)
        fm.addSeparator()
        self.act("Text &Colour...", self.pick_text_color, None, fm)
        self.act("&Highlight Colour...", self.pick_highlight, None, fm)
        self.act("&Remove Highlight", self.remove_highlight, None, fm)
        self.act("C&lear Formatting", self.clear_formatting, "Ctrl+Space", fm)
        self.act("Change Ca&se: UPPER", lambda: self.change_case(str.upper), None, fm)
        self.act("Change Case: lower", lambda: self.change_case(str.lower), None, fm)
        self.act("Change Case: Title", lambda: self.change_case(str.title), None, fm)

        pm = mb.addMenu("&Paragraph")
        self.paragraph_menu = pm
        align_group = QActionGroup(self)
        self.align_actions = {}
        for text, al, sc in (("Align &Left", Qt.AlignLeft, "Ctrl+L"), ("&Centre", Qt.AlignHCenter, "Ctrl+E"),
                             ("Align &Right", Qt.AlignRight, "Ctrl+R"), ("&Justify", Qt.AlignJustify, "Ctrl+J")):
            a = self.act(text, lambda _=False, al=al: self.set_alignment(al), sc, pm, True)
            align_group.addAction(a)
            self.align_actions[al] = a
        pm.addSeparator()
        self.a_bullets = self.act("&Bullets", lambda: self.toggle_list(QTextListFormat.ListDisc),
                                  "Ctrl+Shift+L", pm, True)
        self.a_numbers = self.act("&Numbering", lambda: self.toggle_list(QTextListFormat.ListDecimal),
                                  None, pm, True)
        lists = pm.addMenu("List St&yle")
        for text, st in (("• Disc", QTextListFormat.ListDisc), ("○ Circle", QTextListFormat.ListCircle),
                         ("▪ Square", QTextListFormat.ListSquare), ("1. 2. 3.", QTextListFormat.ListDecimal),
                         ("a. b. c.", QTextListFormat.ListLowerAlpha), ("A. B. C.", QTextListFormat.ListUpperAlpha),
                         ("i. ii. iii.", QTextListFormat.ListLowerRoman),
                         ("I. II. III.", QTextListFormat.ListUpperRoman)):
            self.act(text, lambda _=False, st=st: self.set_list_style(st), None, lists)
        pm.addSeparator()
        a_indent = self.act("&Increase Indent", lambda: self.indent(1), "Ctrl+M", pm)
        a_outdent = self.act("&Decrease Indent", lambda: self.indent(-1), "Ctrl+Shift+M", pm)
        pm.addSeparator()
        sp = pm.addMenu("Line &Spacing")
        for v in (1.0, 1.08, 1.15, 1.5, 2.0, 2.5, 3.0):
            self.act(f"{v:g}", lambda _=False, v=v: self.set_line_spacing(v), None, sp)
        self.act("Add Space &Before Paragraph", lambda: self.para_space(top=12), None, pm)
        self.act("Add Space &After Paragraph", lambda: self.para_space(bottom=8), None, pm)
        self.act("Remove Paragraph Spacing", lambda: self.para_space(top=0, bottom=0), None, pm)

        tm = mb.addMenu("T&able")
        self.table_menu = tm
        tm.addAction(a_table)
        tm.addSeparator()
        self.act("Insert Row &Above", lambda: self.table_op("row_above"), None, tm)
        self.act("Insert Row &Below", lambda: self.table_op("row_below"), None, tm)
        self.act("Insert Column &Left", lambda: self.table_op("col_left"), None, tm)
        self.act("Insert Column &Right", lambda: self.table_op("col_right"), None, tm)
        tm.addSeparator()
        self.act("Delete Ro&w", lambda: self.table_op("del_row"), None, tm)
        self.act("Delete Colu&mn", lambda: self.table_op("del_col"), None, tm)
        self.act("Delete &Table", lambda: self.table_op("del_table"), None, tm)
        tm.addSeparator()
        self.act("&Merge Cells", lambda: self.table_op("merge"), None, tm)
        self.act("&Split Cell", lambda: self.table_op("split"), None, tm)
        self.act("Cell &Shading...", lambda: self.table_op("shade"), None, tm)

        vm = mb.addMenu("&View")
        self.act("Word &Count...", self.show_word_count, "Ctrl+Shift+G", vm)
        h = mb.addMenu("&Help")
        add_guide_action(self, h, "write-basics")
        self.act("&About", lambda: QMessageBox.about(
            self, APP_NAME, f"<b>{APP_NAME}</b><br>Part of {SUITE_NAME}."), None, h)

        # toolbar 1: file + edit
        tb = QToolBar("File")
        tb.setObjectName("file")
        self.addToolBar(tb)
        for a in (a_new, a_open, a_save, a_print, a_pdf):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(a_undo)
        tb.addAction(a_redo)
        tb.addSeparator()
        tb.addAction(a_table)
        tb.addAction(self.act("Picture", self.insert_image_dialog))
        tb.addAction(self.act("Link", self.insert_link))

        # toolbar 2: formatting
        self.addToolBarBreak()
        ft = QToolBar("Formatting")
        ft.setObjectName("format")
        self.addToolBar(ft)
        self.style_box = QComboBox()
        self.style_box.addItems(STYLES)
        self.style_box.setMinimumWidth(110)
        self.style_box.activated.connect(lambda i: self.apply_style(STYLES[i]))
        ft.addWidget(self.style_box)
        self.font_box = QFontComboBox()
        self.font_box.setMaxVisibleItems(20)
        self.font_box.currentFontChanged.connect(
            lambda font: None if self._updating else self.merge(family=font.family()))
        ft.addWidget(self.font_box)
        self.size_box = QComboBox()
        self.size_box.setEditable(True)
        self.size_box.addItems([str(s) for s in (8, 9, 10, 10.5, 11, 12, 14, 16, 18, 20, 24, 28, 32,
                                                 36, 48, 60, 72)])
        self.size_box.setFixedWidth(62)
        self.size_box.activated.connect(lambda _: self._size_from_box())
        self.size_box.lineEdit().returnPressed.connect(self._size_from_box)
        ft.addWidget(self.size_box)
        ft.addAction(self.act("A+", lambda: self.grow_font(1), "Ctrl+]", tip="Bigger text"))
        ft.addAction(self.act("A-", lambda: self.grow_font(-1), "Ctrl+[", tip="Smaller text"))
        ft.addSeparator()
        for a, style in ((self.a_bold, "bold"), (self.a_italic, "italic"), (self.a_under, "underline"),
                         (self.a_strike, "strike")):
            a.setText({"bold": "B", "italic": "I", "underline": "U", "strike": "S"}[style])
            fnt = QFont()
            fnt.setBold(style == "bold")
            fnt.setItalic(style == "italic")
            fnt.setUnderline(style == "underline")
            fnt.setStrikeOut(style == "strike")
            a.setFont(fnt)
            ft.addAction(a)
        self.a_sup.setText("x²")
        self.a_sub.setText("x₂")
        ft.addAction(self.a_sup)
        ft.addAction(self.a_sub)
        self.text_color = ColorButton(QColor("#C00000"), "Text colour (click the A to apply)")
        self.text_color.colorChanged.connect(lambda c: self.merge(color=c))
        apply_color = self.act("A", lambda: self.merge(color=self.text_color.color()),
                               tip="Apply text colour")
        ft.addAction(apply_color)
        ft.addWidget(self.text_color)
        self.hl_color = ColorButton(QColor("#FFFF00"), "Highlight colour (click the pen to apply)")
        self.hl_color.colorChanged.connect(lambda c: self.merge(background=c))
        ft.addAction(self.act("Highlight", lambda: self.merge(background=self.hl_color.color()),
                              tip="Apply highlight"))
        ft.addWidget(self.hl_color)
        ft.addSeparator()
        for al, label in ((Qt.AlignLeft, "Left"), (Qt.AlignHCenter, "Centre"),
                          (Qt.AlignRight, "Right"), (Qt.AlignJustify, "Justify")):
            self.align_actions[al].setIconText(label)
            ft.addAction(self.align_actions[al])
        ft.addSeparator()
        self.a_bullets.setIconText("• List")
        self.a_numbers.setIconText("1. List")
        ft.addAction(self.a_bullets)
        ft.addAction(self.a_numbers)
        a_outdent.setIconText("◄ Indent")
        a_indent.setIconText("Indent ►")
        ft.addAction(a_outdent)
        ft.addAction(a_indent)
        for w in (self.size_box, self.font_box, self.style_box):
            w.setFocusPolicy(Qt.ClickFocus)

    # ------------------------------------------------------------ document handling
    def set_document(self, doc, setup, path):
        self.doc = doc
        self.path = path
        was_modified = doc.isModified()
        self.editor.attach(doc, setup)
        doc.setModified(was_modified)  # applying page margins isn't a user change
        doc.modificationChanged.connect(lambda _: self.update_title())
        doc.contentsChanged.connect(self.count_timer.start)
        self.editor.setFocus()
        self.editor.moveCursor(QTextCursor.Start)
        self.scroll.verticalScrollBar().setValue(0)
        self.update_title()
        self._update_counts()
        self._cursor_moved()
        self._char_format_changed(self.editor.currentCharFormat())

    def update_title(self):
        name = os.path.basename(self.path) if self.path else "Untitled"
        self.setWindowTitle(f"{'*' if self.doc.isModified() else ''}{name} - {APP_NAME}")

    def maybe_save(self):
        if not self.doc.isModified():
            return True
        r = QMessageBox.question(self, APP_NAME, "Save changes to this document?",
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
        if self.maybe_save():
            self.set_document(new_document(), PageSetup(), None)

    def open_dialog(self):
        f, _ = QFileDialog.getOpenFileName(self, "Open", self.settings.value("last_dir", ""), OPEN_FILTER)
        if f:
            self.open_path(f)

    def open_path(self, path):
        if not self.maybe_save():
            return
        ext = os.path.splitext(path)[1].lower()
        setup = PageSetup()
        try:
            if ext == ".docx":
                doc, setup = load_docx(path)
            elif ext in (".doc", ".rtf", ".odt", ".pages", ".wps"):
                QMessageBox.information(
                    self, APP_NAME, f"The {ext} format isn't supported yet.\n"
                    "Supported: .docx, .html, .md, .txt")
                return
            else:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                doc = new_document()
                doc.setBaseUrl(QUrl.fromLocalFile(os.path.dirname(path) + "/"))
                if ext in (".html", ".htm"):
                    doc.setHtml(text)
                elif ext == ".md":
                    doc.setMarkdown(text)
                else:
                    doc.setPlainText(text)
                doc.setModified(False)
        except Exception as ex:
            QMessageBox.critical(self, APP_NAME, f"Could not open the file:\n{ex}")
            return
        self.set_document(doc, setup, path)
        self._add_recent(path)

    def save(self):
        if not self.path or not self.path.lower().endswith((".docx", ".odt", ".html", ".htm", ".md", ".txt")):
            return self.save_as()
        return self.write(self.path)

    def save_as(self):
        start = os.path.splitext(self.path)[0] + ".docx" if self.path else os.path.join(
            self.settings.value("last_dir", ""), "Document.docx")
        f, flt = QFileDialog.getSaveFileName(self, "Save As", start, SAVE_FILTER)
        if not f:
            return False
        if not os.path.splitext(f)[1]:
            f += {"Word": ".docx", "OpenD": ".odt", "Web p": ".html", "Markd": ".md",
                  "Plain": ".txt"}.get(flt[:5], ".docx")
        return self.write(f)

    def write(self, path):
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".docx":
                save_docx(self.doc, self.editor.setup, path)
            elif ext == ".odt":
                if not QTextDocumentWriter(path, b"odf").write(self.doc):
                    raise OSError("write failed")
            else:
                text = (self.doc.toHtml() if ext in (".html", ".htm") else
                        self.doc.toMarkdown() if ext == ".md" else self.doc.toPlainText())
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
        except Exception as ex:
            QMessageBox.critical(self, APP_NAME, f"Could not save:\n{ex}")
            return False
        self.path = path
        self.doc.setModified(False)
        self.update_title()
        self._add_recent(path)
        self.statusBar().showMessage(f"Saved {path}", 4000)
        return True

    def _add_recent(self, path):
        path = os.path.abspath(path)
        self.settings.setValue("last_dir", os.path.dirname(path))
        recent = [p for p in (self.settings.value("recent") or []) if p != path]
        self.settings.setValue("recent", ([path] + recent)[:10])
        self._refresh_recent()

    def _refresh_recent(self):
        self.recent_menu.clear()
        recent = self.settings.value("recent") or []
        if isinstance(recent, str):
            recent = [recent]
        for p in recent:
            if os.path.exists(p):
                self.recent_menu.addAction(os.path.basename(p), lambda p=p: self.open_path(p)).setToolTip(p)
        self.recent_menu.setEnabled(bool(self.recent_menu.actions()))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith((".docx", ".txt", ".md", ".html", ".htm")):
                self.open_path(p)
                return

    # ------------------------------------------------------------ printing / PDF
    def _page_layout(self):
        s = self.editor.setup
        w, h = s.width_in, s.height_in
        orient = QPageLayout.Landscape if w > h else QPageLayout.Portrait
        size = QPageSize(QSizeF(min(w, h), max(w, h)), QPageSize.Inch, "", QPageSize.ExactMatch)
        return QPageLayout(size, orient, QMarginsF(0, 0, 0, 0))

    def render_pages(self, device):
        doc = self.doc
        self.editor.fix_page_size()
        w, h = self.editor.setup.size_px
        pages = self.editor.page_count()
        scale = device.resolution() / 96
        painter = QPainter(device)
        layout = doc.documentLayout()
        try:
            for i in range(pages):
                if i:
                    device.newPage()
                painter.save()
                painter.scale(scale, scale)
                painter.save()
                painter.translate(0, -i * h)
                clip = QRectF(0, i * h, w, h)
                painter.setClipRect(clip)
                ctx = QAbstractTextDocumentLayout.PaintContext()
                ctx.clip = clip
                pal = ctx.palette
                pal.setColor(QPalette.Text, Qt.black)
                ctx.palette = pal
                layout.draw(painter, ctx)
                painter.restore()
                draw_header_footer(painter, self.editor.setup, i, pages)
                painter.restore()
        finally:
            painter.end()

    def export_pdf(self):
        start = os.path.splitext(self.path)[0] + ".pdf" if self.path else "Document.pdf"
        f, _ = QFileDialog.getSaveFileName(self, "Export as PDF", start, "PDF files (*.pdf)")
        if not f:
            return
        if not f.lower().endswith(".pdf"):
            f += ".pdf"
        writer = QPdfWriter(f)
        writer.setResolution(300)
        writer.setPageLayout(self._page_layout())
        writer.setTitle(os.path.splitext(os.path.basename(self.path or "Document"))[0])
        writer.setCreator(f"{SUITE_NAME} {APP_NAME}")
        self.render_pages(writer)
        self.statusBar().showMessage(f"Exported {f}", 5000)

    def _make_printer(self):
        printer = QPrinter(QPrinter.HighResolution)
        printer.setFullPage(True)
        printer.setPageLayout(self._page_layout())
        return printer

    def print_doc(self):
        printer = self._make_printer()
        if QPrintDialog(printer, self).exec():
            self.render_pages(printer)

    def print_preview(self):
        dlg = QPrintPreviewDialog(self._make_printer(), self)
        dlg.paintRequested.connect(self.render_pages)
        dlg.resize(1000, 800)
        dlg.exec()

    def page_setup(self):
        dlg = PageSetupDialog(self, self.editor.setup)
        if dlg.exec():
            self.editor.apply_setup(dlg.result_setup())
            self.doc.setModified(True)

    # ------------------------------------------------------------ status / state sync
    def _cursor_moved(self):
        r = self.editor.cursorRect()
        pt = self.editor.viewport().mapTo(self.container, r.center())
        self.scroll.ensureVisible(pt.x(), pt.y(), 20, 80)
        c = self.editor.textCursor()
        b = c.block()
        bf = b.blockFormat()
        self._updating = True
        style = ("Title" if bf.property(TITLE_PROP) else
                 f"Heading {bf.headingLevel()}" if bf.headingLevel() else "Normal")
        self.style_box.setCurrentText(style if style in STYLES else "Normal")
        al = bf.alignment() & Qt.AlignHorizontal_Mask
        for k, a in self.align_actions.items():
            a.setChecked(bool(al & k) if k != Qt.AlignLeft else not al & (Qt.AlignHCenter | Qt.AlignRight | Qt.AlignJustify))
        lst = b.textList()
        is_bullet = bool(lst and lst.format().style() in BULLET_CYCLE)
        self.a_bullets.setChecked(is_bullet)
        self.a_numbers.setChecked(bool(lst) and not is_bullet)
        self._updating = False
        page = int(r.center().y() // self.editor.setup.size_px[1]) + 1
        self.page_label.setText(f"  Page {page} of {self.editor.page_count()}  ")

    def _char_format_changed(self, cf):
        self._updating = True
        fams = cf.fontFamilies()
        fam = fams[0] if fams else self.doc.defaultFont().family()
        self.font_box.setCurrentFont(QFont(fam))
        size = cf.fontPointSize() or self.doc.defaultFont().pointSizeF()
        self.size_box.setEditText(f"{size:g}")
        self.a_bold.setChecked(cf.fontWeight() >= QFont.DemiBold)
        self.a_italic.setChecked(cf.fontItalic())
        self.a_under.setChecked(cf.fontUnderline())
        self.a_strike.setChecked(cf.fontStrikeOut())
        self.a_sup.setChecked(cf.verticalAlignment() == QTextCharFormat.AlignSuperScript)
        self.a_sub.setChecked(cf.verticalAlignment() == QTextCharFormat.AlignSubScript)
        self._updating = False

    def _update_counts(self):
        text = self.doc.toPlainText()
        words = len(text.split())
        self.words_label.setText(f"  {words:,} words  ")
        self._cursor_moved_light()

    def _cursor_moved_light(self):
        r = self.editor.cursorRect()
        page = int(r.center().y() // self.editor.setup.size_px[1]) + 1
        self.page_label.setText(f"  Page {page} of {self.editor.page_count()}  ")

    def show_word_count(self):
        c = self.editor.textCursor()
        text = c.selectedText().replace(" ", "\n") if c.hasSelection() else self.doc.toPlainText()
        where = "Selection" if c.hasSelection() else "Document"
        QMessageBox.information(
            self, "Word Count",
            f"{where}\n\nPages: {self.editor.page_count()}\nWords: {len(text.split()):,}\n"
            f"Characters (with spaces): {len(text):,}\n"
            f"Characters (no spaces): {len(''.join(text.split())):,}\n"
            f"Paragraphs: {len([p for p in text.splitlines() if p.strip()]):,}")

    # ------------------------------------------------------------ character formatting
    def merge(self, family=None, size=None, weight=None, italic=None, underline=None, strike=None,
              color=None, background=None, valign=False, **_):
        if self._updating:
            return
        cf = QTextCharFormat()
        if family is not None:
            cf.setFontFamilies([family])
        if size is not None:
            cf.setFontPointSize(size)
        if weight is not None:
            cf.setFontWeight(weight)
        if italic is not None:
            cf.setFontItalic(italic)
        if underline is not None:
            cf.setFontUnderline(underline)
        if strike is not None:
            cf.setFontStrikeOut(strike)
        if color is not None:
            cf.setForeground(QColor(color))
        if background is not None:
            cf.setBackground(QColor(background))
        if valign is not False:
            cf.setVerticalAlignment({"sup": QTextCharFormat.AlignSuperScript,
                                     "sub": QTextCharFormat.AlignSubScript}.get(valign,
                                                                                QTextCharFormat.AlignNormal))
        self.editor.mergeCurrentCharFormat(cf)
        self.editor.setFocus()

    def _size_from_box(self):
        try:
            v = float(self.size_box.currentText())
        except ValueError:
            return
        if 1 <= v <= 1638:
            self.merge(size=v)

    def grow_font(self, step):
        sizes = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 60, 72, 96]
        cur = self.editor.currentCharFormat().fontPointSize() or self.doc.defaultFont().pointSizeF()
        if step > 0:
            new = next((s for s in sizes if s > cur), cur + 12)
        else:
            new = next((s for s in reversed(sizes) if s < cur), max(1, cur - 1))
        self.merge(size=new)

    def pick_text_color(self):
        c = QColorDialog.getColor(self.text_color.color(), self, "Text colour")
        if c.isValid():
            self.text_color.setColor(c)
            self.merge(color=c)

    def pick_highlight(self):
        c = QColorDialog.getColor(self.hl_color.color(), self, "Highlight colour")
        if c.isValid():
            self.hl_color.setColor(c)
            self.merge(background=c)

    def remove_highlight(self):
        cf = QTextCharFormat()
        cf.setBackground(QBrush(Qt.NoBrush))
        self.editor.mergeCurrentCharFormat(cf)

    def clear_formatting(self):
        c = self.editor.textCursor()
        cf = QTextCharFormat()
        cf.setFontFamilies([self.doc.defaultFont().family()])
        cf.setFontPointSize(self.doc.defaultFont().pointSizeF())
        cf.setForeground(QColor("black"))
        if c.hasSelection():
            c.setCharFormat(cf)
        else:
            self.editor.setCurrentCharFormat(cf)

    def change_case(self, fn):
        c = self.editor.textCursor()
        if not c.hasSelection():
            c.select(QTextCursor.WordUnderCursor)
        text = c.selectedText()
        if text:
            c.beginEditBlock()
            start = c.selectionStart()
            fmt = c.charFormat()
            c.insertText(fn(text), fmt)
            c.setPosition(start)
            c.setPosition(start + len(text), QTextCursor.KeepAnchor)
            c.endEditBlock()
            self.editor.setTextCursor(c)

    # ------------------------------------------------------------ paragraph formatting
    def selected_blocks(self):
        c = self.editor.textCursor()
        doc = self.doc
        b = doc.findBlock(c.selectionStart())
        end = doc.findBlock(c.selectionEnd())
        out = [b]
        while b != end and b.isValid():
            b = b.next()
            out.append(b)
        return out

    def _each_block_format(self, fn):
        c = self.editor.textCursor()
        c.beginEditBlock()
        for b in self.selected_blocks():
            bc = QTextCursor(b)
            bf = b.blockFormat()
            fn(bf)
            bc.setBlockFormat(bf)
        c.endEditBlock()

    def set_alignment(self, al):
        self.editor.setAlignment(al | Qt.AlignAbsolute)

    def set_line_spacing(self, v):
        self._each_block_format(
            lambda bf: bf.setLineHeight(v * 100, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value))

    def para_space(self, top=None, bottom=None):
        def fn(bf):
            if top is not None:
                bf.setTopMargin(top * PX_PER_PT)
            if bottom is not None:
                bf.setBottomMargin(bottom * PX_PER_PT)
        self._each_block_format(fn)

    def indent(self, step):
        if self.editor.textCursor().block().textList():
            self.change_list_level(step)
            return
        self._each_block_format(lambda bf: bf.setIndent(max(0, bf.indent() + step)))

    def set_block_style(self, block, name):
        c = QTextCursor(block)
        c.beginEditBlock()
        bf = block.blockFormat()
        level = int(name.split()[-1]) if name.startswith("Heading") else 0
        bf.setHeadingLevel(level)
        if name == "Title":
            bf.setProperty(TITLE_PROP, True)
        else:
            bf.clearProperty(TITLE_PROP)
        cf = QTextCharFormat()
        if name == "Normal":
            normal_spacing(bf)
            cf.setFontPointSize(self.doc.defaultFont().pointSizeF())
            cf.setFontWeight(QFont.Normal)
            cf.setForeground(QColor("black"))
        else:
            size, color = HEADING_LOOK[0 if name == "Title" else level]
            bf.setTopMargin((0 if name == "Title" else 12 if level == 1 else 2) * PX_PER_PT)
            bf.setBottomMargin((4 if name == "Title" else 0) * PX_PER_PT)
            bf.setLineHeight(100, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            cf.setFontPointSize(size)
            cf.setFontWeight(QFont.Normal if name == "Title" or level > 2 else QFont.Bold)
            cf.setForeground(QColor(color))
        c.setBlockFormat(bf)
        c.movePosition(QTextCursor.StartOfBlock)
        c.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        c.mergeCharFormat(cf)
        c.mergeBlockCharFormat(cf)
        c.endEditBlock()
        if block == self.editor.textCursor().block():
            self.editor.mergeCurrentCharFormat(cf)

    def apply_style(self, name):
        c = self.editor.textCursor()
        c.beginEditBlock()
        for b in self.selected_blocks():
            self.set_block_style(b, name)
        c.endEditBlock()
        self.editor.setFocus()

    # ------------------------------------------------------------ lists
    def toggle_list(self, style):
        c = self.editor.textCursor()
        lst = c.block().textList()
        want_bullet = style in BULLET_CYCLE
        if lst and (lst.format().style() in BULLET_CYCLE) == want_bullet:
            c.beginEditBlock()
            for b in self.selected_blocks():
                self.remove_from_list(QTextCursor(b))
            c.endEditBlock()
        else:
            self.set_list_style(style)
        self._cursor_moved()

    def set_list_style(self, style):
        c = self.editor.textCursor()
        c.beginEditBlock()
        blocks = self.selected_blocks()
        lst = blocks[0].textList()
        if lst:  # restyle the existing list
            fmt = lst.format()
            fmt.setStyle(style)
            lst.setFormat(fmt)
            for b in blocks[1:]:
                if b.textList() != lst:
                    lst.add(b)
        else:
            fmt = QTextListFormat()
            fmt.setStyle(style)
            fmt.setIndent(1)
            first = QTextCursor(blocks[0])
            lst = first.createList(fmt)
            for b in blocks[1:]:
                lst.add(b)
        c.endEditBlock()
        self._cursor_moved()

    def remove_from_list(self, c):
        b = c.block()
        lst = b.textList()
        if lst:
            lst.remove(b)
            bf = b.blockFormat()
            bf.setIndent(0)
            bf.setObjectIndex(-1)
            c.setBlockFormat(bf)
        self._cursor_moved()

    def change_list_level(self, delta):
        c = self.editor.textCursor()
        b = c.block()
        lst = b.textList()
        if not lst:
            return
        fmt = QTextListFormat(lst.format())
        new = max(1, min(9, fmt.indent() + delta))
        if new == fmt.indent():
            return
        cycle = BULLET_CYCLE if fmt.style() in BULLET_CYCLE else NUMBER_CYCLE
        c.beginEditBlock()
        prev = b.previous()  # join an existing list at that level if there is one just above
        while prev.isValid() and prev.textList() and prev.textList().format().indent() >= new:
            pl = prev.textList()
            if pl.format().indent() == new and (pl.format().style() in BULLET_CYCLE) == (cycle is BULLET_CYCLE):
                lst.remove(b)  # note: Qt's remove() adds the list indent to the block; undo that
                bf = b.blockFormat()
                bf.setIndent(0)
                c.setBlockFormat(bf)
                pl.add(b)
                c.endEditBlock()
                return
            prev = prev.previous()
        fmt.setIndent(new)
        fmt.setStyle(cycle[(new - 1) % len(cycle)])
        c.createList(fmt)
        c.endEditBlock()

    # ------------------------------------------------------------ insert
    def insert_qimage(self, img):
        if img.isNull():
            return
        name = f"img-{uuid.uuid4().hex[:12]}.png"
        self.doc.addResource(QTextDocument.ImageResource, QUrl(name), img)
        s = self.editor.setup
        max_w = (s.width_in - s.margin_left - s.margin_right) * 96
        w = min(img.width(), max_w)
        f = QTextImageFormat()
        f.setName(name)
        f.setWidth(w)
        f.setHeight(img.height() * w / img.width())
        self.editor.textCursor().insertImage(f)

    def insert_image_dialog(self):
        f, _ = QFileDialog.getOpenFileName(self, "Insert Picture", self.settings.value("last_dir", ""),
                                           "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.tif *.tiff)")
        if f:
            img = QImage(f)
            if img.isNull():
                QMessageBox.warning(self, APP_NAME, "Couldn't read that image.")
            else:
                self.insert_qimage(img)

    def image_at_cursor(self):
        c = self.editor.textCursor()
        for pos in (c.position(), c.position() + 1):
            cc = QTextCursor(self.doc)
            cc.setPosition(min(pos, self.doc.characterCount() - 1))
            fmt = cc.charFormat()
            if fmt.isImageFormat():
                return cc
        return None

    def resize_image(self):
        cc = self.image_at_cursor()
        if cc is None:
            return
        fmt = cc.charFormat().toImageFormat()
        img = self.doc.resource(QTextDocument.ImageResource, QUrl(fmt.name()))
        natural = img.width() if isinstance(img, QImage) else fmt.width() or 100
        cur = int(round((fmt.width() or natural) * 100 / max(natural, 1)))
        pct, ok = QInputDialog.getInt(self, "Resize Image", "Size (% of original):", cur, 1, 1000)
        if not ok:
            return
        ratio = (fmt.height() / fmt.width()) if fmt.width() and fmt.height() else (
            img.height() / img.width() if isinstance(img, QImage) else 1)
        fmt.setWidth(natural * pct / 100)
        fmt.setHeight(natural * pct / 100 * ratio)
        cc.setPosition(cc.position() - 1)
        cc.setPosition(cc.position() + 1, QTextCursor.KeepAnchor)
        cc.setCharFormat(fmt)

    def insert_table(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Insert Table")
        rows, cols = QSpinBox(), QSpinBox()
        rows.setRange(1, 200)
        cols.setRange(1, 30)
        rows.setValue(3)
        cols.setValue(3)
        header = QCheckBox("Shade first row as header")
        form = QFormLayout(dlg)
        form.addRow("Rows:", rows)
        form.addRow("Columns:", cols)
        form.addRow("", header)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if not dlg.exec():
            return
        tf = QTextTableFormat()
        tf.setBorder(1)
        tf.setBorderBrush(QBrush(QColor("#808080")))
        tf.setBorderCollapse(True)
        tf.setCellPadding(4)
        tf.setCellSpacing(0)
        tf.setWidth(QTextLength(QTextLength.PercentageLength, 100))
        t = self.editor.textCursor().insertTable(rows.value(), cols.value(), tf)
        if header.isChecked():
            for col in range(cols.value()):
                cell = t.cellAt(0, col)
                cfm = cell.format().toTableCellFormat()
                cfm.setBackground(QColor("#D9E2F3"))
                cell.setFormat(cfm)

    def table_op(self, op):
        c = self.editor.textCursor()
        t = c.currentTable()
        if not t:
            QMessageBox.information(self, APP_NAME, "Put the cursor inside a table first.")
            return
        cell = t.cellAt(c)
        r, col = cell.row(), cell.column()
        if op == "row_above":
            t.insertRows(r, 1)
        elif op == "row_below":
            t.insertRows(r + cell.rowSpan(), 1)
        elif op == "col_left":
            t.insertColumns(col, 1)
        elif op == "col_right":
            t.insertColumns(col + cell.columnSpan(), 1)
        elif op == "del_row":
            if t.rows() == 1:
                self.table_op("del_table")
            else:
                t.removeRows(r, 1)
        elif op == "del_col":
            if t.columns() == 1:
                self.table_op("del_table")
            else:
                t.removeColumns(col, 1)
        elif op == "del_table":
            dc = QTextCursor(self.doc)
            dc.setPosition(t.firstPosition() - 1)
            dc.setPosition(t.lastPosition() + 1, QTextCursor.KeepAnchor)
            dc.removeSelectedText()
        elif op == "merge":
            if c.hasSelection():
                t.mergeCells(c)
        elif op == "split":
            t.splitCell(r, col, 1, 1)
        elif op == "shade":
            color = QColorDialog.getColor(QColor("#D9E2F3"), self, "Cell shading")
            if color.isValid():
                if c.hasSelection():
                    fr, nr, fc, nc = c.selectedTableCells()
                    cells = [t.cellAt(fr + i, fc + j) for i in range(max(nr, 1)) for j in range(max(nc, 1))]
                else:
                    cells = [cell]
                for ce in cells:
                    f = ce.format().toTableCellFormat()
                    f.setBackground(color)
                    ce.setFormat(f)

    def insert_link(self):
        c = self.editor.textCursor()
        dlg = QDialog(self)
        dlg.setWindowTitle("Insert Link")
        text = QLineEdit(c.selectedText())
        url = QLineEdit(c.charFormat().anchorHref() or "https://")
        form = QFormLayout(dlg)
        form.addRow("Text to show:", text)
        form.addRow("Address:", url)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if not dlg.exec() or not url.text().strip():
            return
        cf = QTextCharFormat(c.charFormat())
        cf.setAnchor(True)
        cf.setAnchorHref(url.text().strip())
        cf.setForeground(QColor("#0563C1"))
        cf.setFontUnderline(True)
        c.beginEditBlock()
        c.insertText(text.text() or url.text(), cf)
        plain = QTextCharFormat(cf)
        plain.setAnchor(False)
        plain.setAnchorHref("")
        plain.setForeground(QColor("black"))
        plain.setFontUnderline(False)
        c.endEditBlock()
        self.editor.setCurrentCharFormat(plain)

    def remove_link(self):
        c = self.editor.textCursor()
        if not c.hasSelection():
            c.select(QTextCursor.WordUnderCursor)
        cf = QTextCharFormat()
        cf.setAnchor(False)
        cf.setAnchorHref("")
        cf.setFontUnderline(False)
        cf.setForeground(QColor("black"))
        c.mergeCharFormat(cf)

    def insert_page_break(self):
        c = self.editor.textCursor()
        c.beginEditBlock()
        c.insertBlock()
        bf = c.blockFormat()
        bf.setPageBreakPolicy(QTextFormat.PageBreak_AlwaysBefore)
        c.setBlockFormat(bf)
        c.endEditBlock()

    def insert_date(self):
        self.editor.textCursor().insertText(datetime.datetime.now().strftime("%B %d, %Y"))

    def insert_hline(self):
        c = self.editor.textCursor()
        c.insertBlock()
        c.insertHtml("<hr/>")
        c.insertBlock()

    def paste_plain(self):
        from PySide6.QtWidgets import QApplication
        self.editor.insertPlainText(QApplication.clipboard().text())

    def show_find(self):
        if self.find_dialog is None:
            self.find_dialog = FindReplaceDialog(self)
        sel = self.editor.textCursor().selectedText()
        if sel:
            self.find_dialog.find.setText(sel)
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.find.setFocus()
        self.find_dialog.find.selectAll()


def main():
    app = make_app(APP_NAME, sys.argv)
    win = WordProcessor(sys.argv[1] if len(sys.argv) > 1 else None)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
