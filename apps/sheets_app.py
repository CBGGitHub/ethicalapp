"""Ethical Spreadsheet Editor - spreadsheets with Excel-compatible formulas; opens and saves real .xlsx files."""
import copy
import os
import re
import sys

from PySide6.QtCharts import (QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView,
                              QHorizontalBarSeries, QLineSeries, QPieSeries, QValueAxis)
from PySide6.QtCore import (QAbstractTableModel, QItemSelection, QItemSelectionModel, QMarginsF,
                            QModelIndex, QPoint, QPointF, QRect, QSettings, QSize, QSizeF, Qt, QTimer)
from PySide6.QtGui import (QAction, QBrush, QColor, QFont, QFontMetrics, QGuiApplication,
                           QKeySequence, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen,
                           QPolygon, QTextDocument)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView, QApplication, QCheckBox,
                               QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFontComboBox,
                               QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QSpinBox, QStyle, QStyledItemDelegate, QTabBar,
                               QTableView, QToolBar, QToolButton, QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sheet_engine import (FUNCTIONS, Cell, ExcelError, Sheet, Workbook,  # noqa: E402
                          adjust_for_structure, cell_name, col_name, format_value, general,
                          is_date_format, parse_input, parse_range, shift_formula)
from suite_common import SETTINGS_ORG, SUITE_NAME, ColorButton, make_app  # noqa: E402
from suite_common import add_guide_action  # noqa: E402
from xlsx_io import (DEFAULT_COL_PX, DEFAULT_FONT, DEFAULT_ROW_PX, DEFAULT_SIZE,  # noqa: E402
                     load_csv, load_xlsx, save_csv, save_xlsx)

APP_NAME = "Ethical Spreadsheet Editor"
OPEN_FILTER = ("Spreadsheets (*.xlsx *.xlsm *.csv *.tsv);;Excel workbook (*.xlsx *.xlsm);;"
               "CSV (*.csv *.tsv);;All files (*)")
SAVE_FILTER = "Excel workbook (*.xlsx);;CSV - current sheet only (*.csv)"
ACCENT = QColor("#217346")
NUMBER_FORMATS = [("General", "General"), ("Number", "#,##0.00"), ("Currency", "$#,##0.00"),
                  ("Accounting", '_($* #,##0.00_);_($* (#,##0.00);_($* "-"??_);_(@_)'),
                  ("Percent", "0%"), ("Percent 0.00", "0.00%"), ("Short date", "m/d/yyyy"),
                  ("Long date", "dddd, mmmm d, yyyy"), ("ISO date", "yyyy-mm-dd"), ("Time", "h:mm AM/PM"),
                  ("Scientific", "0.00E+00"), ("Text", "@"), ("Whole number", "0")]
CLIP_MARK = "⁣"  # invisible marker so we recognise our own clipboard text


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def change_decimals(fmt, delta):
    if not fmt or fmt == "General":
        return "0.0" if delta > 0 else "0"
    m = re.search(r"0(\.0*)?", fmt)
    if not m:
        return fmt
    cur = len(m.group(1)) - 1 if m.group(1) else 0
    new = max(0, cur + delta)
    rep = "0" + ("." + "0" * new if new else "")
    return fmt.replace(m.group(), rep, 1) if ";" not in fmt else re.sub(r"0(\.0*)?", rep, fmt)


# ====================================================================== model

class SheetModel(QAbstractTableModel):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.sheet = None
        self.rows, self.cols = 1000, 52
        self.display = {}
        self.fonts = {}

    @property
    def wb(self):
        return self.win.wb

    def set_sheet(self, sheet):
        self.beginResetModel()
        self.sheet = sheet
        self.rows = max(1000, sheet.max_row() + 100)
        self.cols = max(52, sheet.max_col() + 10)
        self.display.clear()
        self.endResetModel()

    def refresh(self):
        self.display.clear()
        need_r, need_c = self.sheet.max_row() + 100, self.sheet.max_col() + 10
        if need_r > self.rows:
            self.beginInsertRows(QModelIndex(), self.rows, need_r - 1)
            self.rows = need_r
            self.endInsertRows()
        if need_c > self.cols:
            self.beginInsertColumns(QModelIndex(), self.cols, need_c - 1)
            self.cols = min(need_c, 16384)
            self.endInsertColumns()
        self.dataChanged.emit(self.index(0, 0), self.index(self.rows - 1, self.cols - 1))

    def grow(self, rows=0, cols=0):
        if rows:
            self.beginInsertRows(QModelIndex(), self.rows, self.rows + rows - 1)
            self.rows += rows
            self.endInsertRows()
        if cols and self.cols < 16384:
            n = min(cols, 16384 - self.cols)
            self.beginInsertColumns(QModelIndex(), self.cols, self.cols + n - 1)
            self.cols += n
            self.endInsertColumns()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.rows

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.cols

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return col_name(section) if orientation == Qt.Horizontal else str(section + 1)
        if role == Qt.TextAlignmentRole:
            return Qt.AlignCenter
        return None

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def value(self, r, c):
        return self.wb.value(self.sheet, r, c)

    def text(self, r, c):
        key = (r, c)
        t = self.display.get(key)
        if t is None:
            cell = self.sheet.cells.get(key)
            if cell is None:
                t = ""
            else:
                t = format_value(self.value(r, c), cell.style.get("numfmt", "General"))
            self.display[key] = t
        return t

    def edit_text(self, r, c):
        cell = self.sheet.cells.get((r, c))
        if cell is None or cell.value is None:
            return ""
        v = cell.value
        fmt = cell.style.get("numfmt", "General")
        if isinstance(v, str):
            if v.startswith("="):
                return v
            parsed = parse_input(v)[0]
            return v if parsed == v else "'" + v
        if isinstance(v, ExcelError):
            return v.code
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if is_date_format(fmt):
            has_time = bool(re.search(r"h", fmt, re.I))
            has_date = bool(re.search(r"[yd]", fmt, re.I))
            if has_date and has_time:
                return format_value(v, "yyyy-mm-dd h:mm")
            if has_time:
                return format_value(v, "h:mm:ss")
            return format_value(v, "yyyy-mm-dd")
        if "%" in fmt:
            return general(v * 100) + "%"
        return general(v)

    def font_for(self, style):
        z = self.win.zoom
        key = (style.get("font"), style.get("size"), style.get("bold"), style.get("italic"),
               style.get("underline"), style.get("strike"), z)
        f = self.fonts.get(key)
        if f is None:
            f = QFont(style.get("font", DEFAULT_FONT))
            f.setPointSizeF(style.get("size", DEFAULT_SIZE) * z)
            f.setBold(bool(style.get("bold")))
            f.setItalic(bool(style.get("italic")))
            f.setUnderline(bool(style.get("underline")))
            f.setStrikeOut(bool(style.get("strike")))
            self.fonts[key] = f
        return f

    def data(self, index, role=Qt.DisplayRole):
        r, c = index.row(), index.column()
        if role == Qt.DisplayRole:
            return self.text(r, c)
        if role == Qt.EditRole:
            return self.edit_text(r, c)
        cell = self.sheet.cells.get((r, c))
        if role == Qt.ToolTipRole and cell is not None and cell.comment:
            return cell.comment
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole:
            return False
        self.win.set_cell_input(index.row(), index.column(), value)
        return True

    def overflow_right(self, r, c, need, start_w):
        """Width available for text spilling into empty cells to the right."""
        w, col = start_w, c + 1
        view = self.win.view
        while w < need and col < self.cols and col - c < 30:
            nb = self.sheet.cells.get((r, col))
            if nb is not None and nb.value not in (None, ""):
                break
            w += view.columnWidth(col)
            col += 1
        return w


# ====================================================================== delegate / view

class CellDelegate(QStyledItemDelegate):
    def __init__(self, win):
        super().__init__()
        self.win = win

    def paint(self, p, opt, index):
        model = self.win.model
        r, c = index.row(), index.column()
        cell = model.sheet.cells.get((r, c))
        rect = opt.rect
        style = cell.style if cell is not None else {}
        if style.get("fill"):
            p.fillRect(rect, QColor(style["fill"]))
        selected = opt.state & QStyle.State_Selected and index != self.win.view.currentIndex()
        if cell is not None:
            text = model.text(r, c)
            if text:
                v = model.value(r, c)
                p.save()
                font = model.font_for(style)
                p.setFont(font)
                color = QColor(style.get("color", "#000000"))
                fmt = style.get("numfmt", "")
                if _is_number(v) and v < 0 and "[Red]" in fmt:
                    color = QColor("#FF0000")
                p.setPen(color)
                h = style.get("halign")
                if not h:
                    h = "right" if _is_number(v) else "center" if isinstance(v, (bool, ExcelError)) else "left"
                va = {"top": Qt.AlignTop, "center": Qt.AlignVCenter}.get(style.get("valign"), Qt.AlignBottom)
                ha = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}.get(h, Qt.AlignLeft)
                pad = max(2, int(3 * self.win.zoom))
                tr = rect.adjusted(pad, 1, -pad, -1)
                fm = QFontMetrics(font)
                wrap = style.get("wrap")
                if wrap:
                    p.setClipRect(rect)
                    p.drawText(tr, ha | va | Qt.TextWordWrap, text)
                else:
                    need = fm.horizontalAdvance(text) + 2 * pad
                    if need > rect.width():
                        if _is_number(v):
                            text = "#" * max(1, (rect.width() - 2 * pad) // max(fm.horizontalAdvance("#"), 1))
                        elif ha == Qt.AlignLeft:
                            span = self.win.view.columnSpan(r, c)
                            if span == 1:
                                w = model.overflow_right(r, c, need, rect.width())
                                tr = QRect(tr.left(), tr.top(), w - 2 * pad, tr.height())
                            p.setClipRect(QRect(rect.left(), rect.top(), tr.width() + 2 * pad, rect.height()))
                        else:
                            p.setClipRect(rect)
                    p.drawText(tr, ha | va | Qt.TextSingleLine, text)
                p.restore()
            if style.get("border"):
                p.save()
                for side, kind in style["border"].items():
                    width = {"medium": 2, "thick": 3, "double": 3}.get(kind, 1)
                    pen = QPen(QColor("#000"), width)
                    if kind in ("dashed", "dotted", "hair"):
                        pen.setStyle(Qt.DashLine if kind == "dashed" else Qt.DotLine)
                    p.setPen(pen)
                    if side == "left":
                        p.drawLine(rect.topLeft(), rect.bottomLeft())
                    elif side == "right":
                        p.drawLine(rect.topRight(), rect.bottomRight())
                    elif side == "top":
                        p.drawLine(rect.topLeft(), rect.topRight())
                    elif side == "bottom":
                        p.drawLine(rect.bottomLeft(), rect.bottomRight())
                p.restore()
            if cell.comment:
                p.save()
                p.setBrush(QColor("#d00"))
                p.setPen(Qt.NoPen)
                tr_ = rect.topRight()
                p.drawPolygon(QPolygon([tr_, tr_ - QPoint(6, 0), tr_ + QPoint(0, 6)]))
                p.restore()
        if selected:
            p.fillRect(rect, QColor(33, 115, 70, 45))

    def createEditor(self, parent, opt, index):
        e = QLineEdit(parent)
        e.setFrame(False)
        cell = self.win.model.sheet.cells.get((index.row(), index.column()))
        e.setFont(self.win.model.font_for(cell.style if cell else {}))
        e.textEdited.connect(self.win.formula_edit.setText)
        return e

    def setEditorData(self, editor, index):
        editor.setText(index.data(Qt.EditRole) or "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text(), Qt.EditRole)


class SheetView(QTableView):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed |
                             QAbstractItemView.AnyKeyPressed)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setGridStyle(Qt.SolidLine)
        self.setStyleSheet("QTableView { gridline-color: #d4d4d4; background: white; selection-background-color: transparent;"
                           " selection-color: black; }"
                           "QHeaderView::section { background: #f3f3f3; border: 0; border-right: 1px solid #d4d4d4;"
                           " border-bottom: 1px solid #d4d4d4; padding: 0 4px; }"
                           "QHeaderView::section:checked { background: #d3f0e0; color: #0b5a34; font-weight: bold; }")
        self.setCornerButtonEnabled(True)
        self.horizontalHeader().setHighlightSections(True)
        self.verticalHeader().setHighlightSections(True)
        self.horizontalHeader().setMinimumSectionSize(0)
        self.verticalHeader().setMinimumSectionSize(0)
        self.verticalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setWordWrap(False)

    def closeEditor(self, editor, hint):
        move = None
        if hint == QAbstractItemDelegate.SubmitModelCache:
            move, hint = (1, 0), QAbstractItemDelegate.NoHint
        elif hint == QAbstractItemDelegate.EditNextItem:
            move, hint = (0, 1), QAbstractItemDelegate.NoHint
        elif hint == QAbstractItemDelegate.EditPreviousItem:
            move, hint = (0, -1), QAbstractItemDelegate.NoHint
        super().closeEditor(editor, hint)
        if move:
            self.win.move_cursor(*move)

    def keyPressEvent(self, e):
        key, mods = e.key(), e.modifiers()
        if self.state() != QAbstractItemView.EditingState:
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self.win.move_cursor(-1 if mods & Qt.ShiftModifier else 1, 0)
                return
            if key == Qt.Key_Tab:
                self.win.move_cursor(0, 1)
                return
            if key == Qt.Key_Backtab:
                self.win.move_cursor(0, -1)
                return
            if key in (Qt.Key_Delete, Qt.Key_Backspace) and not mods:
                self.win.clear_contents()
                if key == Qt.Key_Backspace:
                    self.edit(self.currentIndex())
                return
            if mods & Qt.ControlModifier and key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right):
                self.win.jump_edge(key, bool(mods & Qt.ShiftModifier))
                return
        super().keyPressEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        idx = self.currentIndex()
        if not idx.isValid():
            return
        p = QPainter(self.viewport())
        sel = self.selectionModel().selection()
        if len(sel) == 1 and (sel[0].height() > 1 or sel[0].width() > 1):
            rng = sel[0]
            r = self.visualRect(self.model().index(rng.top(), rng.left())).united(
                self.visualRect(self.model().index(rng.bottom(), rng.right())))
            p.setPen(QPen(ACCENT, 1))
            p.drawRect(r.adjusted(0, 0, -1, -1))
        p.setPen(QPen(ACCENT, 2))
        p.drawRect(self.visualRect(idx).adjusted(0, 0, -1, -1))

    def contextMenuEvent(self, e):
        self.win.cell_context_menu(e.globalPos())


# ====================================================================== charts

class ChartBox(QChartView):
    def __init__(self, win, spec):
        super().__init__()
        self.win, self.spec = win, spec
        self.setRenderHint(QPainter.Antialiasing)
        self.setFrameShape(QChartView.Box)
        self.setStyleSheet("background: white; border: 1px solid #bbb;")
        self._drag = None
        self.resize(spec.get("w", 480), spec.get("h", 288))
        self.rebuild()

    def rebuild(self):
        wb, sheet = self.win.wb, self.win.sheet
        r1, c1, r2, c2 = self.spec["ref"]
        chart = QChart()
        chart.setTitle(self.spec.get("title", ""))
        chart.setAnimationOptions(QChart.NoAnimation)
        cats = [format_value(wb.value(sheet, r, c1)) for r in range(r1 + 1, r2 + 1)]
        series_data = []
        for c in range(c1 + 1, c2 + 1):
            name = format_value(wb.value(sheet, r1, c)) or col_name(c)
            vals = []
            for r in range(r1 + 1, r2 + 1):
                v = wb.value(sheet, r, c)
                vals.append(float(v) if _is_number(v) else 0.0)
            series_data.append((name, vals))
        kind = self.spec.get("type", "column")
        if kind == "pie" and series_data:
            s = QPieSeries()
            for cat, v in zip(cats, series_data[0][1]):
                sl = s.append(cat, max(v, 0))
                sl.setLabelVisible(True)
            chart.addSeries(s)
        elif kind == "line":
            ax = QBarCategoryAxis()
            ax.append(cats)
            ay = QValueAxis()
            chart.addAxis(ax, Qt.AlignBottom)
            chart.addAxis(ay, Qt.AlignLeft)
            lo, hi = 0, 1
            for name, vals in series_data:
                s = QLineSeries()
                s.setName(name)
                for i, v in enumerate(vals):
                    s.append(i, v)
                chart.addSeries(s)
                s.attachAxis(ay)
                lo, hi = min([lo] + vals), max([hi] + vals)
            ay.setRange(lo, hi * 1.1 if hi > 0 else hi)
            hidden = QValueAxis()
            hidden.setRange(-0.5, max(len(cats) - 0.5, 0.5))
            hidden.setVisible(False)
            chart.addAxis(hidden, Qt.AlignTop)
            for s in chart.series():
                s.attachAxis(hidden)
        else:
            s = QHorizontalBarSeries() if kind == "bar" else QBarSeries()
            for name, vals in series_data:
                bs = QBarSet(name)
                bs.append(vals)
                s.append(bs)
            chart.addSeries(s)
            ac = QBarCategoryAxis()
            ac.append(cats)
            av = QValueAxis()
            chart.addAxis(ac, Qt.AlignLeft if kind == "bar" else Qt.AlignBottom)
            chart.addAxis(av, Qt.AlignBottom if kind == "bar" else Qt.AlignLeft)
            s.attachAxis(ac)
            s.attachAxis(av)
        chart.legend().setVisible(kind == "pie" or len(series_data) > 1)
        chart.legend().setAlignment(Qt.AlignBottom)
        self.setChart(chart)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.pos()
            self.raise_()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.win.chart_moved(self)
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.addAction("Edit Chart...", lambda: self.win.edit_chart(self))
        m.addAction("Delete Chart", lambda: self.win.delete_chart(self))
        m.exec(e.globalPos())


class ImageBox(QLabel):
    """A picture floating over the sheet; drag to move, right-click to resize/delete."""

    def __init__(self, win, spec):
        super().__init__()
        self.win, self.spec = win, spec
        from PySide6.QtGui import QPixmap
        self.pix = QPixmap()
        self.pix.loadFromData(spec["data"])
        self.setScaledContents(True)
        self.setPixmap(self.pix)
        self.setCursor(Qt.SizeAllCursor)
        self._drag = None

    def rebuild(self):
        pass

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.pos()
            self.raise_()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.win.chart_moved(self)

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.addAction("Resize Picture...", lambda: self.win.resize_picture(self))
        m.addAction("Delete Picture", lambda: self.win.delete_chart(self))
        m.exec(e.globalPos())


class ChartDialog(QDialog):
    def __init__(self, parent, spec):
        super().__init__(parent)
        self.setWindowTitle("Chart")
        self.kind = QComboBox()
        self.kind.addItems(["Column", "Bar", "Line", "Pie"])
        self.kind.setCurrentText(spec.get("type", "column").title())
        self.title = QLineEdit(spec.get("title", ""))
        self.ref = QLineEdit(":".join([cell_name(spec["ref"][0], spec["ref"][1]),
                                       cell_name(spec["ref"][2], spec["ref"][3])]))
        self.w, self.h = QSpinBox(), QSpinBox()
        for s, v in ((self.w, spec.get("w", 480)), (self.h, spec.get("h", 288))):
            s.setRange(150, 2000)
            s.setValue(v)
            s.setSuffix(" px")
        form = QFormLayout(self)
        form.addRow("Type:", self.kind)
        form.addRow("Title:", self.title)
        form.addRow("Data range:", self.ref)
        form.addRow(QLabel("First row = series names, first column = categories."))
        form.addRow("Width:", self.w)
        form.addRow("Height:", self.h)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def apply(self, spec):
        rng = parse_range(self.ref.text())
        if rng:
            spec["ref"] = rng
        spec.update(type=self.kind.currentText().lower(), title=self.title.text(),
                    w=self.w.value(), h=self.h.value())


# ====================================================================== find / sort dialogs

class FindDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Find and Replace")
        self.find, self.repl = QLineEdit(), QLineEdit()
        self.case = QCheckBox("Match case")
        self.whole = QCheckBox("Match entire cell")
        self.all_sheets = QCheckBox("Search all sheets")
        form = QFormLayout()
        form.addRow("Find:", self.find)
        form.addRow("Replace:", self.repl)
        for cb in (self.case, self.whole, self.all_sheets):
            form.addRow("", cb)
        self.info = QLabel()
        row = QHBoxLayout()
        for t, s in (("Find Next", self.find_next), ("Replace", self.replace), ("Replace All", self.replace_all),
                     ("Close", self.close)):
            b = QPushButton(t)
            b.clicked.connect(s)
            row.addWidget(b)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.info)
        lay.addLayout(row)
        self.find.returnPressed.connect(self.find_next)

    def _matches(self, sheet, r, c):
        q = self.find.text()
        text = self.win.model.edit_text(r, c) if sheet is self.win.sheet else ""
        if sheet is not self.win.sheet:
            cell = sheet.cells.get((r, c))
            text = str(cell.value) if cell and cell.value is not None else ""
        display = format_value(self.win.wb.value(sheet, r, c),
                               sheet.cells[(r, c)].style.get("numfmt", "General")) if (r, c) in sheet.cells else ""
        for t in (text, display):
            a, b = (t, q) if self.case.isChecked() else (t.lower(), q.lower())
            if (a == b) if self.whole.isChecked() else (b in a):
                return True
        return False

    def find_next(self):
        if not self.find.text():
            return
        sheets = self.win.wb.sheets if self.all_sheets.isChecked() else [self.win.sheet]
        start_sheet = sheets.index(self.win.sheet) if self.win.sheet in sheets else 0
        cur = (self.win.view.currentIndex().row(), self.win.view.currentIndex().column())
        order = sheets[start_sheet:] + sheets[:start_sheet] + [sheets[start_sheet]]
        for n, sh in enumerate(order):
            keys = sorted(sh.cells)
            if n == 0:
                keys = [k for k in keys if k > cur]
            for k in keys:
                if self._matches(sh, *k):
                    if sh is not self.win.sheet:
                        self.win.switch_sheet(self.win.wb.sheets.index(sh))
                    self.win.select_cell(*k)
                    self.info.setText("")
                    return True
        self.info.setText("Not found.")
        return False

    def replace(self):
        idx = self.win.view.currentIndex()
        if self._matches(self.win.sheet, idx.row(), idx.column()):
            self._replace_cell(idx.row(), idx.column())
        self.find_next()

    def _replace_cell(self, r, c):
        cell = self.win.sheet.cells.get((r, c))
        if cell is None or cell.value is None:
            return
        src = self.win.model.edit_text(r, c)
        flags = 0 if self.case.isChecked() else re.I
        new = re.sub(re.escape(self.find.text()), self.repl.text().replace("\\", "\\\\"), src, flags=flags)
        self.win.set_cell_input(r, c, new, record=False)

    def replace_all(self):
        self.win.push_undo()
        n = 0
        for k in list(self.win.sheet.cells):
            if self._matches(self.win.sheet, *k):
                self._replace_cell(*k)
                n += 1
        self.win.changed()
        self.info.setText(f"Replaced {n} cell(s).")


# ====================================================================== main window

class SheetsWindow(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        self.settings = QSettings(SETTINGS_ORG, APP_NAME)
        self.path = None
        self.wb = Workbook()
        self.sheet = self.wb.sheets[0]
        self.zoom = 1.0
        self.modified = False
        self.lossy = []
        self.undo_stack, self.redo_stack = [], []
        self.clip = None
        self.charts = []
        self.find_dialog = None
        self._syncing = False
        self.resize(1300, 850)
        self.setAcceptDrops(True)

        self.model = SheetModel(self)
        self.view = SheetView(self)
        self.view.setModel(self.model)
        self.view.setItemDelegate(CellDelegate(self))
        self.view.selectionModel().currentChanged.connect(lambda *_: self._sync_current())
        self.view.selectionModel().selectionChanged.connect(lambda *_: self._sync_selection())
        self.view.horizontalHeader().sectionResized.connect(self._col_resized)
        self.view.verticalHeader().sectionResized.connect(self._row_resized)
        self.view.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.view.horizontalScrollBar().valueChanged.connect(self._scrolled)

        # formula bar
        self.name_box = QLineEdit()
        self.name_box.setFixedWidth(100)
        self.name_box.returnPressed.connect(self._goto_name_box)
        self.formula_edit = QLineEdit()
        self.formula_edit.setPlaceholderText("Type a value or a formula like =SUM(A1:A10)")
        self.formula_edit.returnPressed.connect(self._commit_formula_bar)
        fx = QPushButton("fx")
        fx.setFixedWidth(34)
        fx.setToolTip("Insert function")
        fx.clicked.connect(self.insert_function)
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(4, 2, 4, 2)
        bl.addWidget(self.name_box)
        bl.addWidget(fx)
        bl.addWidget(self.formula_edit)

        # sheet tabs
        self.tabs = QTabBar()
        self.tabs.setShape(QTabBar.RoundedSouth)
        self.tabs.setMovable(True)
        self.tabs.setExpanding(False)
        self.tabs.currentChanged.connect(self.switch_sheet)
        self.tabs.tabMoved.connect(self._tab_moved)
        self.tabs.tabBarDoubleClicked.connect(self.rename_sheet)
        self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._tab_menu)
        add = QToolButton()
        add.setText("+")
        add.setToolTip("New sheet")
        add.clicked.connect(self.add_sheet)
        tabrow = QWidget()
        tl = QHBoxLayout(tabrow)
        tl.setContentsMargins(4, 0, 4, 0)
        tl.addWidget(self.tabs)
        tl.addWidget(add)
        tl.addStretch()

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(bar)
        cl.addWidget(self.view, 1)
        cl.addWidget(tabrow)
        self.setCentralWidget(central)
        self.stats_label = QLabel()
        self.statusBar().addPermanentWidget(self.stats_label)

        self._build_actions()
        self.load_workbook(Workbook(), None)
        if path:
            self.open_path(path)

    # ------------------------------------------------------------ actions
    def act(self, text, slot, shortcut=None, menu=None, tip=None, checkable=False):
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
        a_print = self.act("&Print...", self.print_sheet, "Ctrl+P", f)
        f.addSeparator()
        self.act("E&xit", self.close, None, f)

        e = mb.addMenu("&Edit")
        a_undo = self.act("&Undo", self.undo, "Ctrl+Z", e)
        a_redo = self.act("&Redo", self.redo, "Ctrl+Y", e)
        e.addSeparator()
        self.act("Cu&t", self.cut, "Ctrl+X", e)
        self.act("&Copy", self.copy, "Ctrl+C", e)
        self.act("&Paste", self.paste, "Ctrl+V", e)
        self.act("Paste &Values Only", lambda: self.paste(values_only=True), "Ctrl+Shift+V", e)
        e.addSeparator()
        self.act("Clear &Contents", self.clear_contents, None, e)
        self.act("Clear &Formats", self.clear_formats, None, e)
        self.act("Clear &All", lambda: self.clear_contents(everything=True), None, e)
        e.addSeparator()
        self.act("Fill &Down", lambda: self.fill("down"), "Ctrl+D", e)
        self.act("Fill &Right", lambda: self.fill("right"), "Ctrl+R", e)
        self.act("Fill &Series", self.fill_series, None, e)
        e.addSeparator()
        self.act("&Find and Replace...", self.show_find, "Ctrl+F", e)
        self.act("Rep&lace...", self.show_find, "Ctrl+H", e)
        self.act("&Go To...", lambda: (self.name_box.setFocus(), self.name_box.selectAll()), "Ctrl+G", e)

        ins = mb.addMenu("&Insert")
        self.insert_menu = ins
        self.act("Rows &Above", lambda: self.insert_rows(above=True), "Ctrl+Shift+=", ins)
        self.act("Rows &Below", lambda: self.insert_rows(above=False), None, ins)
        self.act("Columns &Left", lambda: self.insert_cols(left=True), None, ins)
        self.act("Columns &Right", lambda: self.insert_cols(left=False), None, ins)
        ins.addSeparator()
        self.act("&Sheet", self.add_sheet, "Shift+F11", ins)
        a_chart = self.act("&Chart...", self.insert_chart, None, ins)
        self.act("&Picture...", self.insert_picture, None, ins)
        a_fn = self.act("&Function...", self.insert_function, "Shift+F3", ins)
        self.act("C&omment...", self.edit_comment, "Shift+F2", ins)

        dm = mb.addMenu("&Delete")
        self.delete_menu = dm
        self.act("&Rows", self.delete_rows, "Ctrl+-", dm)
        self.act("&Columns", self.delete_cols, None, dm)
        self.act("&Sheet", self.delete_sheet, None, dm)

        fm = mb.addMenu("F&ormat")
        self.a_bold = self.act("&Bold", lambda: self.toggle_style("bold"), "Ctrl+B", fm, checkable=True)
        self.a_italic = self.act("&Italic", lambda: self.toggle_style("italic"), "Ctrl+I", fm, checkable=True)
        self.a_under = self.act("&Underline", lambda: self.toggle_style("underline"), "Ctrl+U", fm, checkable=True)
        self.a_strike = self.act("&Strikethrough", lambda: self.toggle_style("strike"), "Ctrl+5", fm, checkable=True)
        fm.addSeparator()
        nf = fm.addMenu("&Number Format")
        for label, code in NUMBER_FORMATS:
            self.act(label, lambda _=False, code=code: self.set_style("numfmt", None if code == "General" else code),
                     None, nf)
        nf.addSeparator()
        self.act("Custom...", self.custom_format, None, nf)
        self.act("Increase &Decimals", lambda: self.decimals(1), None, fm)
        self.act("Decrease D&ecimals", lambda: self.decimals(-1), None, fm)
        fm.addSeparator()
        al = fm.addMenu("&Alignment")
        for t, v in (("Left", "left"), ("Centre", "center"), ("Right", "right")):
            self.act(t, lambda _=False, v=v: self.set_style("halign", v), None, al)
        al.addSeparator()
        for t, v in (("Top", "top"), ("Middle", "center"), ("Bottom", None)):
            self.act(t, lambda _=False, v=v: self.set_style("valign", v), None, al)
        self.a_wrap = self.act("&Wrap Text", lambda: self.toggle_style("wrap"), None, fm, checkable=True)
        self.act("&Merge && Centre", self.merge_cells, None, fm)
        self.act("U&nmerge", self.unmerge_cells, None, fm)
        bm = fm.addMenu("&Borders")
        for t, kind in (("All Borders", "all"), ("Outside Borders", "outside"), ("Thick Outside", "thick"),
                        ("Bottom Border", "bottom"), ("Top and Bottom", "topbottom"), ("No Border", "none")):
            self.act(t, lambda _=False, k=kind: self.set_borders(k), None, bm)
        fm.addSeparator()
        self.act("Column &Width...", self.set_col_width, None, fm)
        self.act("&Row Height...", self.set_row_height, None, fm)
        self.act("AutoFit Column &Width", self.autofit_cols, None, fm)
        self.act("&Hide Columns", lambda: self.hide("col"), None, fm)
        self.act("Hide R&ows", lambda: self.hide("row"), None, fm)
        self.act("Unhide &All", self.unhide_all, None, fm)

        da = mb.addMenu("&Data")
        a_az = self.act("Sort A → Z", lambda: self.quick_sort(False), None, da)
        a_za = self.act("Sort Z → A", lambda: self.quick_sort(True), None, da)
        self.act("&Sort...", self.sort_dialog, None, da)
        self.act("Remove &Duplicates", self.remove_duplicates, None, da)
        da.addSeparator()
        self.act("&Define Name...", self.define_name, None, da)

        vm = mb.addMenu("&View")
        self.a_grid = self.act("&Gridlines", lambda on: self.view.setShowGrid(on), None, vm, checkable=True)
        self.a_grid.setChecked(True)
        zm = vm.addMenu("&Zoom")
        for z in (50, 75, 90, 100, 125, 150, 200):
            self.act(f"{z}%", lambda _=False, z=z: self.set_zoom(z / 100), None, zm)
        self.act("Zoom &In", lambda: self.set_zoom(self.zoom * 1.1), "Ctrl+=", vm)
        self.act("Zoom &Out", lambda: self.set_zoom(self.zoom / 1.1), "Ctrl+Shift+-", vm)

        h = mb.addMenu("&Help")

        add_guide_action(self, h, "sheets-basics")
        self.act("&Functions List", self.show_functions, None, h)
        self.act("&About", lambda: QMessageBox.about(
            self, APP_NAME, f"<b>{APP_NAME}</b><br>Part of {SUITE_NAME}."), None, h)

        tb = QToolBar("Main")
        tb.setObjectName("main")
        self.addToolBar(tb)
        for a in (a_new, a_open, a_save, a_print, a_pdf):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(a_undo)
        tb.addAction(a_redo)
        tb.addSeparator()
        tb.addAction(self.act("AutoSum", self.autosum, "Alt+=", tip="Sum the numbers above or to the left"))
        tb.addAction(a_fn)
        tb.addAction(a_az)
        tb.addAction(a_za)
        tb.addAction(a_chart)

        self.addToolBarBreak()
        ft = QToolBar("Formatting")
        ft.setObjectName("format")
        self.addToolBar(ft)
        self.font_box = QFontComboBox()
        self.font_box.setMaxVisibleItems(20)
        self.font_box.currentFontChanged.connect(
            lambda f: None if self._syncing else self.set_style("font", None if f.family() == DEFAULT_FONT else f.family()))
        ft.addWidget(self.font_box)
        self.size_box = QComboBox()
        self.size_box.setEditable(True)
        self.size_box.addItems([str(s) for s in (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36, 48, 72)])
        self.size_box.setFixedWidth(60)
        self.size_box.activated.connect(lambda _: self._size_from_box())
        self.size_box.lineEdit().returnPressed.connect(self._size_from_box)
        ft.addWidget(self.size_box)
        for a, t in ((self.a_bold, "B"), (self.a_italic, "I"), (self.a_under, "U"), (self.a_strike, "S")):
            a.setIconText(t)
            fnt = QFont()
            fnt.setBold(t == "B")
            fnt.setItalic(t == "I")
            fnt.setUnderline(t == "U")
            fnt.setStrikeOut(t == "S")
            a.setFont(fnt)
            ft.addAction(a)
        ft.addSeparator()
        self.text_color = ColorButton(QColor("#C00000"), "Font colour")
        self.text_color.colorChanged.connect(lambda c: self.set_style("color", c.name().upper()))
        ft.addAction(self.act("A", lambda: self.set_style("color", self.text_color.color().name().upper()),
                              tip="Apply font colour"))
        ft.addWidget(self.text_color)
        self.fill_color = ColorButton(QColor("#FFFF00"), "Fill colour")
        self.fill_color.colorChanged.connect(lambda c: self.set_style("fill", c.name().upper()))
        ft.addAction(self.act("Fill", lambda: self.set_style("fill", self.fill_color.color().name().upper()),
                              tip="Apply fill colour"))
        ft.addWidget(self.fill_color)
        ft.addAction(self.act("No Fill", lambda: self.set_style("fill", None)))
        ft.addSeparator()
        for t, v in (("Left", "left"), ("Centre", "center"), ("Right", "right")):
            ft.addAction(self.act(t, lambda _=False, v=v: self.set_style("halign", v)))
        ft.addAction(self.a_wrap)
        self.a_wrap.setIconText("Wrap")
        ft.addAction(self.act("Merge", self.merge_cells, tip="Merge & Centre"))
        ft.addSeparator()
        ft.addAction(self.act("$", lambda: self.set_style("numfmt", "$#,##0.00"), tip="Currency"))
        ft.addAction(self.act("%", lambda: self.set_style("numfmt", "0%"), tip="Percent"))
        ft.addAction(self.act(",", lambda: self.set_style("numfmt", "#,##0.00"), tip="Thousands separator"))
        ft.addAction(self.act(".0+", lambda: self.decimals(1), tip="Increase decimals"))
        ft.addAction(self.act(".0-", lambda: self.decimals(-1), tip="Decrease decimals"))
        self.fmt_box = QComboBox()
        self.fmt_box.addItems([l for l, _ in NUMBER_FORMATS])
        self.fmt_box.activated.connect(lambda i: self.set_style(
            "numfmt", None if NUMBER_FORMATS[i][1] == "General" else NUMBER_FORMATS[i][1]))
        ft.addWidget(self.fmt_box)
        ft.addSeparator()
        borders = QToolButton()
        borders.setText("Borders")
        borders.setPopupMode(QToolButton.InstantPopup)
        borders.setMenu(bm)
        ft.addWidget(borders)
        for w in (self.font_box, self.size_box, self.fmt_box):
            w.setFocusPolicy(Qt.ClickFocus)

    # ------------------------------------------------------------ workbook lifecycle
    def load_workbook(self, wb, path):
        self.wb = wb
        self.path = path
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.modified = False
        self._rebuild_tabs(0)
        self.update_title()

    def _rebuild_tabs(self, index):
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for s in self.wb.sheets:
            self.tabs.addTab(s.name)
        self.tabs.setCurrentIndex(index)
        self.tabs.blockSignals(False)
        self.switch_sheet(index)

    def switch_sheet(self, index):
        if not 0 <= index < len(self.wb.sheets):
            return
        if self.tabs.currentIndex() != index:
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(index)
            self.tabs.blockSignals(False)
        self.sheet = self.wb.sheets[index]
        self.model.set_sheet(self.sheet)
        self.apply_geometry()
        self.select_cell(0, 0)
        self._rebuild_charts()

    def apply_geometry(self):
        v, s, z = self.view, self.sheet, self.zoom
        self._syncing = True
        hh, vh = v.horizontalHeader(), v.verticalHeader()
        hh.setDefaultSectionSize(int(DEFAULT_COL_PX * z))
        vh.setDefaultSectionSize(int(DEFAULT_ROW_PX * z))
        f = QFont()
        f.setPointSizeF(9 * z)
        hh.setFont(f)
        vh.setFont(f)
        for c in range(self.model.cols):
            w = s.col_widths.get(c)
            v.setColumnHidden(c, w == 0)
            v.setColumnWidth(c, int((w if w else DEFAULT_COL_PX) * z))
        for r, h in s.row_heights.items():
            if r < self.model.rows:
                v.setRowHidden(r, h == 0)
                if h:
                    v.setRowHeight(r, int(h * z))
        v.clearSpans()
        for r1, c1, r2, c2 in s.merges:
            v.setSpan(r1, c1, r2 - r1 + 1, c2 - c1 + 1)
        self._syncing = False

    def update_title(self):
        name = os.path.basename(self.path) if self.path else "Book1"
        self.setWindowTitle(f"{'*' if self.modified else ''}{name} - {APP_NAME}")

    def maybe_save(self):
        if not self.modified:
            return True
        r = QMessageBox.question(self, APP_NAME, "Save changes to this workbook?",
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
            self.lossy = []
            self.load_workbook(Workbook(), None)

    def open_dialog(self):
        f, _ = QFileDialog.getOpenFileName(self, "Open", self.settings.value("last_dir", ""), OPEN_FILTER)
        if f:
            self.open_path(f)

    def open_path(self, path):
        if not self.maybe_save():
            return
        ext = os.path.splitext(path)[1].lower()
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if ext in (".xlsx", ".xlsm"):
                wb, warnings = load_xlsx(path)
            elif ext in (".csv", ".tsv", ".txt"):
                wb, warnings = load_csv(path), []
            elif ext == ".xls":
                raise ValueError("The old .xls format isn't supported yet. Please save it as .xlsx first.")
            else:
                raise ValueError(f"Unsupported file type: {ext}")
        except Exception as ex:
            QGuiApplication.restoreOverrideCursor()
            QMessageBox.critical(self, APP_NAME, f"Could not open the file:\n{ex}")
            return
        QGuiApplication.restoreOverrideCursor()
        self.lossy = warnings + (["macros"] if ext == ".xlsm" and "macros" not in warnings else [])
        self.load_workbook(wb, path if ext != ".xlsm" else None)
        self._add_recent(path)
        if self.lossy:
            QMessageBox.information(
                self, APP_NAME,
                "This workbook contains " + ", ".join(self.lossy) + ".\n\n"
                f"{APP_NAME} can't keep these yet - they will be missing if you save over the "
                "original file. Use File > Save As to save a separate copy.")

    def save(self):
        if not self.path:
            return self.save_as()
        if self.lossy and self.path.lower().endswith(".xlsx"):
            r = QMessageBox.question(
                self, APP_NAME, "Saving over the original will remove: " + ", ".join(self.lossy) +
                ".\nSave anyway? (Choose No to use Save As instead.)",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if r == QMessageBox.No:
                return self.save_as()
            if r != QMessageBox.Yes:
                return False
        return self.write(self.path)

    def save_as(self):
        start = os.path.splitext(self.path)[0] + ".xlsx" if self.path else os.path.join(
            self.settings.value("last_dir", ""), "Book1.xlsx")
        f, flt = QFileDialog.getSaveFileName(self, "Save As", start, SAVE_FILTER)
        if not f:
            return False
        if not os.path.splitext(f)[1]:
            f += ".csv" if flt.startswith("CSV") else ".xlsx"
        ok = self.write(f)
        if ok and f.lower().endswith(".xlsx"):
            self.lossy = []
        return ok

    def write(self, path):
        try:
            if path.lower().endswith(".csv"):
                save_csv(self.wb, self.sheet, path)
            else:
                save_xlsx(self.wb, path)
        except PermissionError:
            QMessageBox.critical(self, APP_NAME, "Could not save - the file may be open in another program.")
            return False
        except Exception as ex:
            QMessageBox.critical(self, APP_NAME, f"Could not save:\n{ex}")
            return False
        if path.lower().endswith(".xlsx"):
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
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith((".xlsx", ".xlsm", ".csv", ".tsv")):
                self.open_path(p)
                return

    # ------------------------------------------------------------ undo / change tracking
    def push_undo(self):
        self.undo_stack.append(self._snapshot())
        del self.undo_stack[:-60]
        self.redo_stack.clear()

    def _snapshot(self):
        idx = self.view.currentIndex()
        return (copy.deepcopy(self.wb.sheets), dict(self.wb.names), self.tabs.currentIndex(),
                (idx.row(), idx.column()))

    def _restore(self, snap):
        sheets, names, tab, (r, c) = snap
        self.wb.sheets, self.wb.names = sheets, names
        self.wb.recalc_all()
        self._rebuild_tabs(min(tab, len(sheets) - 1))
        self.select_cell(max(r, 0), max(c, 0))
        self.modified = True
        self.update_title()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self._snapshot())
            self._restore(self.undo_stack.pop())

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self._snapshot())
            self._restore(self.redo_stack.pop())

    def changed(self, geometry=False):
        self.wb.recalc_all()
        self.model.refresh()
        if geometry:
            self.apply_geometry()
        for ch in self.charts:
            ch.rebuild()
        self.view.viewport().update()
        self.modified = True
        self.update_title()
        self._sync_current()
        self._sync_selection()
        if self.wb.has_circular:
            self.statusBar().showMessage("Warning: circular reference - a formula refers to itself.", 5000)

    # ------------------------------------------------------------ cell editing
    def set_cell_input(self, r, c, text, record=True):
        if record:
            self.push_undo()
        v, fmt = parse_input(text)
        cell = self.sheet.cells.get((r, c))
        if v is None:
            if cell is not None:
                cell.value = None
                if not cell.style and not cell.comment:
                    del self.sheet.cells[(r, c)]
        else:
            if cell is None:
                cell = self.sheet.cells[(r, c)] = Cell()
            if isinstance(v, str) and v.startswith("="):
                v = self._normalise_formula(v)
            cell.value = v
            cell.cached = None
            if fmt and fmt != "@" and "numfmt" not in cell.style:
                cell.style = dict(cell.style, numfmt=fmt)
        if record:
            self.changed()

    @staticmethod
    def _normalise_formula(f):
        # upper-case function names and cell references, like Excel does
        out, i, q = [], 0, False
        for part in re.split(r'("(?:[^"]|"")*")', f):
            if part.startswith('"'):
                out.append(part)
            else:
                out.append(re.sub(r"\b([A-Za-z_][A-Za-z0-9_.]*)(?=\s*\()|(?<![A-Za-z_'])(\$?[A-Za-z]{1,3}\$?\d+)\b",
                                  lambda m: m.group().upper(), part))
        return "".join(out)

    def move_cursor(self, dr, dc):
        idx = self.view.currentIndex()
        r = max(0, idx.row() + dr * (self.view.rowSpan(idx.row(), idx.column()) if dr > 0 else 1))
        c = max(0, idx.column() + dc * (self.view.columnSpan(idx.row(), idx.column()) if dc > 0 else 1))
        self.select_cell(r, c)

    def select_cell(self, r, c, r2=None, c2=None):
        if r >= self.model.rows - 5:
            self.model.grow(rows=500)
        if c >= self.model.cols - 2:
            self.model.grow(cols=26)
            self.apply_geometry()
        idx = self.model.index(r, c)
        sm = self.view.selectionModel()
        if r2 is None:
            sm.setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect)
        else:
            sel = QItemSelection(idx, self.model.index(r2, c2))
            sm.select(sel, QItemSelectionModel.ClearAndSelect)
            sm.setCurrentIndex(idx, QItemSelectionModel.NoUpdate)
        self.view.scrollTo(idx)
        self.view.viewport().update()

    def jump_edge(self, key, extend):
        idx = self.view.currentIndex()
        r, c = idx.row(), idx.column()
        dr, dc = {Qt.Key_Up: (-1, 0), Qt.Key_Down: (1, 0), Qt.Key_Left: (0, -1), Qt.Key_Right: (0, 1)}[key]

        def filled(rr, cc):
            cell = self.sheet.cells.get((rr, cc))
            return cell is not None and cell.value not in (None, "")
        limit_r, limit_c = max(self.sheet.max_row(), 0) + 1, max(self.sheet.max_col(), 0) + 1
        nr, nc = r + dr, c + dc
        if filled(r, c) and 0 <= nr and 0 <= nc and filled(nr, nc):
            while 0 <= nr + dr <= limit_r and 0 <= nc + dc <= limit_c and filled(nr + dr, nc + dc):
                nr, nc = nr + dr, nc + dc
        else:
            while 0 <= nr <= limit_r and 0 <= nc <= limit_c and not filled(nr, nc):
                nr, nc = nr + dr, nc + dc
            if not (0 <= nr <= limit_r and 0 <= nc <= limit_c):
                nr = 0 if dr < 0 else (limit_r if dr > 0 else r)
                nc = 0 if dc < 0 else (limit_c if dc > 0 else c)
        nr, nc = max(nr, 0), max(nc, 0)
        if extend:
            sm = self.view.selectionModel()
            anchor = self.view.selectionModel().selection()
            top = anchor[0] if len(anchor) else None
            ar, ac = (top.top(), top.left()) if top else (r, c)
            sm.select(QItemSelection(self.model.index(min(ar, nr), min(ac, nc)),
                                     self.model.index(max(ar, nr), max(ac, nc))), QItemSelectionModel.ClearAndSelect)
            sm.setCurrentIndex(self.model.index(nr, nc), QItemSelectionModel.NoUpdate)
            self.view.scrollTo(self.model.index(nr, nc))
        else:
            self.select_cell(nr, nc)

    def _sync_current(self):
        idx = self.view.currentIndex()
        if not idx.isValid():
            return
        r, c = idx.row(), idx.column()
        self.formula_edit.setText(self.model.edit_text(r, c))
        self._sync_selection()
        cell = self.sheet.cells.get((r, c))
        st = cell.style if cell else {}
        self._syncing = True
        self.font_box.setCurrentFont(QFont(st.get("font", DEFAULT_FONT)))
        self.size_box.setEditText(f"{st.get('size', DEFAULT_SIZE):g}")
        self.a_bold.setChecked(bool(st.get("bold")))
        self.a_italic.setChecked(bool(st.get("italic")))
        self.a_under.setChecked(bool(st.get("underline")))
        self.a_strike.setChecked(bool(st.get("strike")))
        self.a_wrap.setChecked(bool(st.get("wrap")))
        fmt = st.get("numfmt", "General")
        label = next((l for l, code in NUMBER_FORMATS if code == fmt), None)
        self.fmt_box.setCurrentText(label or "General")
        self._syncing = False

    def _sync_selection(self):
        rects = self.selected_rects()
        if not rects:
            return
        r1, c1, r2, c2 = rects[0]
        idx = self.view.currentIndex()
        if len(rects) == 1 and (r1, c1) == (r2, c2) or (r1 == r2 and c1 == c2):
            self.name_box.setText(cell_name(idx.row(), idx.column()))
        else:
            self.name_box.setText(f"{cell_name(r1, c1)}:{cell_name(r2, c2)}")
        nums, count = [], 0
        for (r1, c1, r2, c2) in rects:
            r2 = min(r2, self.sheet.max_row())
            c2 = min(c2, self.sheet.max_col())
            if (r2 - r1 + 1) * (c2 - c1 + 1) > 200000:
                continue
            for (r, c) in self.sheet.cells:
                if r1 <= r <= r2 and c1 <= c <= c2:
                    v = self.wb.value(self.sheet, r, c)
                    if v not in (None, ""):
                        count += 1
                    if _is_number(v):
                        nums.append(v)
        if count > 1:
            parts = [f"Count: {count}"]
            if nums:
                parts = [f"Average: {general(sum(nums) / len(nums))}", parts[0], f"Sum: {general(sum(nums))}"]
            self.stats_label.setText("   ".join(parts) + "   ")
        else:
            self.stats_label.setText("")

    def _commit_formula_bar(self):
        idx = self.view.currentIndex()
        self.set_cell_input(idx.row(), idx.column(), self.formula_edit.text())
        self.move_cursor(1, 0)
        self.view.setFocus()

    def _goto_name_box(self):
        text = self.name_box.text().strip()
        sheet_name = None
        if "!" in text:
            sheet_name, text = text.rsplit("!", 1)
            sheet_name = sheet_name.strip("'")
        rng = parse_range(text)
        if rng is None and text.upper() in self.wb.names:
            target = self.wb.names[text.upper()].lstrip("=")
            if "!" in target:
                sheet_name, target = target.rsplit("!", 1)
                sheet_name = sheet_name.strip("'")
            rng = parse_range(target.replace("$", ""))
        if rng is None:
            QMessageBox.information(self, APP_NAME, f"'{self.name_box.text()}' isn't a valid cell reference.")
            return
        if sheet_name:
            s = self.wb.sheet(sheet_name)
            if s:
                self.switch_sheet(self.wb.sheets.index(s))
        r1, c1, r2, c2 = rng
        self.select_cell(r1, c1, r2, c2) if (r1, c1) != (r2, c2) else self.select_cell(r1, c1)
        self.view.setFocus()

    def selected_rects(self):
        out = []
        for rng in self.view.selectionModel().selection():
            out.append((rng.top(), rng.left(), rng.bottom(), rng.right()))
        if not out:
            idx = self.view.currentIndex()
            if idx.isValid():
                out.append((idx.row(), idx.column(), idx.row(), idx.column()))
        return out

    def selected_cells(self, used_only=False):
        seen = set()
        for r1, c1, r2, c2 in self.selected_rects():
            if used_only:
                for (r, c) in list(self.sheet.cells):
                    if r1 <= r <= r2 and c1 <= c <= c2:
                        seen.add((r, c))
            else:
                r2 = min(r2, max(self.sheet.max_row(), r1) + 0) if r2 - r1 > 5000 else r2
                c2 = min(c2, max(self.sheet.max_col(), c1)) if c2 - c1 > 200 else c2
                for r in range(r1, r2 + 1):
                    for c in range(c1, c2 + 1):
                        seen.add((r, c))
        return sorted(seen)

    # ------------------------------------------------------------ formatting
    def set_style(self, key, value):
        if self._syncing:
            return
        self.push_undo()
        for rc in self.selected_cells():
            cell = self.sheet.cells.get(rc)
            if cell is None:
                if value is None:
                    continue
                cell = self.sheet.cells[rc] = Cell()
            st = dict(cell.style)
            if value is None or value is False:
                st.pop(key, None)
            else:
                st[key] = value
            cell.style = st
            if cell.value is None and not st and not cell.comment:
                del self.sheet.cells[rc]
        self.model.fonts.clear()
        self.changed()
        self.view.setFocus()

    def toggle_style(self, key):
        idx = self.view.currentIndex()
        cell = self.sheet.cells.get((idx.row(), idx.column()))
        on = not (cell and cell.style.get(key))
        self.set_style(key, True if on else None)

    def _size_from_box(self):
        try:
            v = float(self.size_box.currentText())
        except ValueError:
            return
        self.set_style("size", None if v == DEFAULT_SIZE else v)

    def decimals(self, delta):
        idx = self.view.currentIndex()
        cell = self.sheet.cells.get((idx.row(), idx.column()))
        fmt = cell.style.get("numfmt", "General") if cell else "General"
        if fmt == "General" and cell is not None and _is_number(self.model.value(idx.row(), idx.column())):
            v = self.model.value(idx.row(), idx.column())
            s = general(v)
            places = len(s.split(".")[1]) if "." in s else 0
            fmt = "0" + ("." + "0" * places if places else "")
        self.set_style("numfmt", change_decimals(fmt, delta))

    def custom_format(self):
        idx = self.view.currentIndex()
        cell = self.sheet.cells.get((idx.row(), idx.column()))
        cur = cell.style.get("numfmt", "General") if cell else "General"
        text, ok = QInputDialog.getText(self, "Custom Number Format",
                                        "Format code (e.g. #,##0.00, 0.0%, yyyy-mm-dd, \"$\"0.00):",
                                        QLineEdit.Normal, cur)
        if ok and text.strip():
            self.set_style("numfmt", None if text.strip() == "General" else text.strip())

    def set_borders(self, kind):
        self.push_undo()
        for r1, c1, r2, c2 in self.selected_rects():
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    cell = self.sheet.cells.get((r, c))
                    if cell is None:
                        if kind == "none":
                            continue
                        cell = self.sheet.cells[(r, c)] = Cell()
                    b = dict(cell.style.get("border", {}))
                    if kind == "none":
                        b = {}
                    elif kind == "all":
                        b = {s: "thin" for s in ("left", "right", "top", "bottom")}
                    else:
                        weight = "medium" if kind == "thick" else "thin"
                        if kind in ("outside", "thick"):
                            if r == r1:
                                b["top"] = weight
                            if r == r2:
                                b["bottom"] = weight
                            if c == c1:
                                b["left"] = weight
                            if c == c2:
                                b["right"] = weight
                        if kind in ("bottom", "topbottom") and r == r2:
                            b["bottom"] = "thin"
                        if kind == "topbottom" and r == r1:
                            b["top"] = "thin"
                    st = dict(cell.style)
                    if b:
                        st["border"] = b
                    else:
                        st.pop("border", None)
                    cell.style = st
        self.changed()

    def clear_formats(self):
        self.push_undo()
        for rc in self.selected_cells(used_only=True):
            cell = self.sheet.cells[rc]
            cell.style = {}
            if cell.value is None and not cell.comment:
                del self.sheet.cells[rc]
        self.changed()

    def clear_contents(self, everything=False):
        self.push_undo()
        for rc in self.selected_cells(used_only=True):
            cell = self.sheet.cells[rc]
            if everything or (not cell.style and not cell.comment):
                del self.sheet.cells[rc]
            else:
                cell.value = None
                cell.cached = None
        self.changed()

    def merge_cells(self):
        r1, c1, r2, c2 = self.selected_rects()[0]
        if (r1, c1) == (r2, c2):
            return
        others = [rc for rc in self.selected_cells(used_only=True)
                  if rc != (r1, c1) and self.sheet.cells[rc].value is not None]
        if others and QMessageBox.question(
                self, APP_NAME, "Merging keeps only the top-left value. Continue?") != QMessageBox.Yes:
            return
        self.push_undo()
        for rc in others:
            self.sheet.cells[rc].value = None
        self.sheet.merges = [m for m in self.sheet.merges
                             if m[2] < r1 or m[0] > r2 or m[3] < c1 or m[1] > c2]
        self.sheet.merges.append((r1, c1, r2, c2))
        cell = self.sheet.cells.setdefault((r1, c1), Cell())
        cell.style = dict(cell.style, halign="center", valign="center")
        self.changed(geometry=True)
        self.select_cell(r1, c1)

    def unmerge_cells(self):
        idx = self.view.currentIndex()
        r, c = idx.row(), idx.column()
        keep = [m for m in self.sheet.merges if not (m[0] <= r <= m[2] and m[1] <= c <= m[3])]
        if len(keep) != len(self.sheet.merges):
            self.push_undo()
            self.sheet.merges = keep
            self.changed(geometry=True)

    # ------------------------------------------------------------ sizes / zoom
    def _col_resized(self, col, old, new):
        if not self._syncing:
            self.sheet.col_widths[col] = int(round(new / self.zoom))
            self.modified = True
            self._place_charts()

    def _row_resized(self, row, old, new):
        if not self._syncing:
            self.sheet.row_heights[row] = int(round(new / self.zoom))
            self.modified = True
            self._place_charts()

    def set_col_width(self):
        idx = self.view.currentIndex()
        cur = self.sheet.col_widths.get(idx.column(), DEFAULT_COL_PX)
        w, ok = QInputDialog.getInt(self, "Column Width", "Width (pixels):", cur, 0, 2000)
        if ok:
            self.push_undo()
            cols = {c for r1, c1, r2, c2 in self.selected_rects() for c in range(c1, c2 + 1)}
            for c in cols:
                self.sheet.col_widths[c] = w
            self.changed(geometry=True)

    def set_row_height(self):
        idx = self.view.currentIndex()
        cur = self.sheet.row_heights.get(idx.row(), DEFAULT_ROW_PX)
        h, ok = QInputDialog.getInt(self, "Row Height", "Height (pixels):", cur, 0, 800)
        if ok:
            self.push_undo()
            rows = {r for r1, c1, r2, c2 in self.selected_rects() for r in range(r1, r2 + 1)}
            for r in rows:
                self.sheet.row_heights[r] = h
            self.changed(geometry=True)

    def autofit_cols(self):
        self.push_undo()
        cols = {c for r1, c1, r2, c2 in self.selected_rects() for c in range(c1, c2 + 1)}
        for c in cols:
            best = 20
            for (r, cc), cell in self.sheet.cells.items():
                if cc == c:
                    fm = QFontMetrics(self.model.font_for(dict(cell.style)))
                    best = max(best, int(fm.horizontalAdvance(self.model.text(r, c)) / self.zoom) + 10)
            self.sheet.col_widths[c] = min(best, 800)
        self.changed(geometry=True)

    def hide(self, axis):
        self.push_undo()
        for r1, c1, r2, c2 in self.selected_rects():
            if axis == "col":
                for c in range(c1, c2 + 1):
                    self.sheet.col_widths[c] = 0
            else:
                for r in range(r1, r2 + 1):
                    self.sheet.row_heights[r] = 0
        self.changed(geometry=True)

    def unhide_all(self):
        self.push_undo()
        self.sheet.col_widths = {c: w for c, w in self.sheet.col_widths.items() if w}
        self.sheet.row_heights = {r: h for r, h in self.sheet.row_heights.items() if h}
        for c in range(self.model.cols):
            self.view.setColumnHidden(c, False)
        for r in range(self.model.rows):
            if self.view.isRowHidden(r):
                self.view.setRowHidden(r, False)
        self.changed(geometry=True)

    def set_zoom(self, z):
        self.zoom = max(0.3, min(4.0, z))
        self.model.fonts.clear()
        self.apply_geometry()
        self.model.refresh()
        self._place_charts()
        self.statusBar().showMessage(f"Zoom {round(self.zoom * 100)}%", 2000)

    def _scrolled(self):
        sb = self.view.verticalScrollBar()
        if sb.value() >= sb.maximum() - 20 and self.model.rows < 1048576:
            self.model.grow(rows=500)
        hb = self.view.horizontalScrollBar()
        if hb.value() >= hb.maximum() - 20 and self.model.cols < 16384:
            self.model.grow(cols=26)
            self.apply_geometry()
        self._place_charts()

    # ------------------------------------------------------------ rows / columns
    def _shift(self, axis, at, n):
        """Insert (n>0) or delete (n<0) rows/cols on the current sheet, fixing formulas everywhere."""
        s = self.sheet
        idx = 0 if axis == "row" else 1
        new_cells = {}
        for key, cell in s.cells.items():
            k = key[idx]
            if n < 0 and at <= k < at - n:
                continue
            if k >= at:
                key = (key[0] + n, key[1]) if axis == "row" else (key[0], key[1] + n)
            new_cells[key] = cell
        s.cells = new_cells
        sizes = s.row_heights if axis == "row" else s.col_widths
        moved = {}
        for k, v in sizes.items():
            if n < 0 and at <= k < at - n:
                continue
            moved[k + n if k >= at else k] = v
        sizes.clear()
        sizes.update(moved)
        merges = []
        for m in s.merges:
            a, b = (m[0], m[2]) if axis == "row" else (m[1], m[3])
            if n < 0 and at <= a and b < at - n:
                continue
            a2 = a + n if a >= at else a
            b2 = b + n if b >= at else (b if n > 0 or b < at else max(at - 1, a2))
            merges.append((a2, m[1], b2, m[3]) if axis == "row" else (m[0], a2, m[2], b2))
        s.merges = [m for m in merges if m[0] <= m[2] and m[1] <= m[3] and (m[0], m[1]) != (m[2], m[3])]
        for ch in s.charts:
            r1, c1, r2, c2 = ch["ref"]
            if axis == "row":
                ch["ref"] = (r1 + n if r1 >= at else r1, c1, r2 + n if r2 >= at else r2, c2)
                if ch.get("row", 0) >= at:
                    ch["row"] = max(0, ch["row"] + n)
            else:
                ch["ref"] = (r1, c1 + n if c1 >= at else c1, r2, c2 + n if c2 >= at else c2)
                if ch.get("col", 0) >= at:
                    ch["col"] = max(0, ch["col"] + n)
        for sh in self.wb.sheets:
            for cell in sh.cells.values():
                if cell.is_formula():
                    cell.value = adjust_for_structure(cell.value, sh.name, s.name, axis, at, n)
        for name, ref in list(self.wb.names.items()):
            self.wb.names[name] = adjust_for_structure("=" + ref.lstrip("="), s.name, s.name, axis, at, n)[1:]

    def insert_rows(self, above=True):
        r1, _, r2, _ = self.selected_rects()[0]
        n = r2 - r1 + 1 if r2 - r1 < 1000 else 1
        self.push_undo()
        self._shift("row", r1 if above else r2 + 1, n)
        self.changed(geometry=True)
        self._reset_hidden()

    def insert_cols(self, left=True):
        _, c1, _, c2 = self.selected_rects()[0]
        n = c2 - c1 + 1 if c2 - c1 < 200 else 1
        self.push_undo()
        self._shift("col", c1 if left else c2 + 1, n)
        self.changed(geometry=True)
        self._reset_hidden()

    def delete_rows(self):
        r1, _, r2, _ = self.selected_rects()[0]
        self.push_undo()
        self._shift("row", r1, -(r2 - r1 + 1))
        self.changed(geometry=True)
        self._reset_hidden()

    def delete_cols(self):
        _, c1, _, c2 = self.selected_rects()[0]
        self.push_undo()
        self._shift("col", c1, -(c2 - c1 + 1))
        self.changed(geometry=True)
        self._reset_hidden()

    def _reset_hidden(self):
        for r in range(self.model.rows):
            if self.view.isRowHidden(r) and self.sheet.row_heights.get(r) != 0:
                self.view.setRowHidden(r, False)
            h = self.sheet.row_heights.get(r)
            self.view.setRowHeight(r, int((h if h else DEFAULT_ROW_PX) * self.zoom)) if not h == 0 else None
        self._rebuild_charts()

    # ------------------------------------------------------------ clipboard
    def _block(self):
        r1, c1, r2, c2 = self.selected_rects()[0]
        r2 = min(r2, max(self.sheet.max_row(), r1))
        c2 = min(c2, max(self.sheet.max_col(), c1))
        return r1, c1, r2, c2

    def copy(self, cut=False):
        if self.view.state() == QAbstractItemView.EditingState:
            return
        r1, c1, r2, c2 = self._block()
        cells = {(r - r1, c - c1): copy.deepcopy(cell) for (r, c), cell in self.sheet.cells.items()
                 if r1 <= r <= r2 and c1 <= c <= c2}
        lines = ["\t".join(self.model.text(r, c) for c in range(c1, c2 + 1)) for r in range(r1, r2 + 1)]
        text = "\n".join(lines)
        self.clip = {"origin": (r1, c1), "size": (r2 - r1 + 1, c2 - c1 + 1), "cells": cells, "cut": cut,
                     "sheet": self.sheet, "text": text + CLIP_MARK}
        QGuiApplication.clipboard().setText(text + CLIP_MARK)
        self.statusBar().showMessage("Cut - select where to paste" if cut else "Copied", 3000)

    def cut(self):
        self.copy(cut=True)

    def paste(self, values_only=False):
        if self.view.state() == QAbstractItemView.EditingState:
            return
        idx = self.view.currentIndex()
        tr, tc = idx.row(), idx.column()
        text = QGuiApplication.clipboard().text()
        self.push_undo()
        if self.clip and text == self.clip["text"]:
            clip = self.clip
            rows, cols = clip["size"]
            sel = self.selected_rects()[0]
            # paste a single copied cell into a whole selected block
            targets = [(tr, tc)]
            if (rows, cols) == (1, 1) and (sel[2] > sel[0] or sel[3] > sel[1]):
                targets = [(r, c) for r in range(sel[0], sel[2] + 1) for c in range(sel[1], sel[3] + 1)]
            if clip["cut"]:
                sr, sc = clip["origin"]
                for dr in range(rows):
                    for dc in range(cols):
                        clip["sheet"].cells.pop((sr + dr, sc + dc), None)
            for (br, bc) in targets:
                for dr in range(rows):
                    for dc in range(cols):
                        self.sheet.cells.pop((br + dr, bc + dc), None)
                for (dr, dc), cell in clip["cells"].items():
                    new = copy.deepcopy(cell)
                    if values_only:
                        v = self.wb.value(clip["sheet"], clip["origin"][0] + dr, clip["origin"][1] + dc)
                        new.value = None if isinstance(v, ExcelError) and not cell.is_formula() else v
                    elif new.is_formula() and not clip["cut"]:
                        new.value = shift_formula(new.value, br - clip["origin"][0], bc - clip["origin"][1])
                    self.sheet.cells[(br + dr, bc + dc)] = new
            if clip["cut"]:
                self.clip = None
            self.changed()
            self.select_cell(tr, tc, tr + rows - 1, tc + cols - 1) if (rows, cols) != (1, 1) else None
            return
        rows = [line.split("\t") for line in text.rstrip("\n").replace("\r\n", "\n").split("\n")]
        for dr, row in enumerate(rows):
            for dc, val in enumerate(row):
                self.set_cell_input(tr + dr, tc + dc, val, record=False)
        self.changed()

    # ------------------------------------------------------------ fill / sort
    def fill(self, direction):
        r1, c1, r2, c2 = self.selected_rects()[0]
        self.push_undo()
        if direction == "down":
            if r1 == r2 and r1 > 0:
                r1 -= 1
            for c in range(c1, c2 + 1):
                src = self.sheet.cells.get((r1, c))
                for r in range(r1 + 1, r2 + 1):
                    self._copy_cell(src, r1, c, r, c)
        else:
            if c1 == c2 and c1 > 0:
                c1 -= 1
            for r in range(r1, r2 + 1):
                src = self.sheet.cells.get((r, c1))
                for c in range(c1 + 1, c2 + 1):
                    self._copy_cell(src, r, c1, r, c)
        self.changed()

    def _copy_cell(self, src, sr, sc, r, c):
        if src is None:
            self.sheet.cells.pop((r, c), None)
            return
        new = copy.deepcopy(src)
        if new.is_formula():
            new.value = shift_formula(new.value, r - sr, c - sc)
        self.sheet.cells[(r, c)] = new

    def fill_series(self):
        r1, c1, r2, c2 = self.selected_rects()[0]
        vertical = r2 > r1
        self.push_undo()
        lines = range(c1, c2 + 1) if vertical else range(r1, r2 + 1)
        for line in lines:
            cells = [(r, line) for r in range(r1, r2 + 1)] if vertical else [(line, c) for c in range(c1, c2 + 1)]
            vals = [self.sheet.cells[k].value if k in self.sheet.cells else None for k in cells]
            if not _is_number(vals[0]):
                continue
            step = vals[1] - vals[0] if len(vals) > 1 and _is_number(vals[1]) else 1
            known = 2 if len(vals) > 1 and _is_number(vals[1]) else 1
            for i in range(known, len(cells)):
                cell = self.sheet.cells.get(cells[i]) or Cell(style=dict(self.sheet.cells[cells[0]].style))
                cell.value = vals[0] + step * i
                self.sheet.cells[cells[i]] = cell
        self.changed()

    def _data_region(self):
        r1, c1, r2, c2 = self.selected_rects()[0]
        if (r1, c1) == (r2, c2):  # single cell: use the used area around it
            r1, c1 = 0, 0
            r2, c2 = self.sheet.max_row(), self.sheet.max_col()
        r2 = min(r2, self.sheet.max_row())
        c2 = min(c2, self.sheet.max_col())
        return r1, c1, r2, c2

    def _guess_header(self, r1, c1, c2):
        first = [self.wb.value(self.sheet, r1, c) for c in range(c1, c2 + 1)]
        second = [self.wb.value(self.sheet, r1 + 1, c) for c in range(c1, c2 + 1)]
        return all(isinstance(v, str) or v is None for v in first) and any(
            not isinstance(v, str) and v is not None for v in second)

    def quick_sort(self, descending):
        r1, c1, r2, c2 = self._data_region()
        key_col = self.view.currentIndex().column()
        if not c1 <= key_col <= c2:
            key_col = c1
        self.sort_range(r1, c1, r2, c2, [(key_col, descending)], self._guess_header(r1, c1, c2))

    def sort_dialog(self):
        r1, c1, r2, c2 = self._data_region()
        dlg = QDialog(self)
        dlg.setWindowTitle("Sort")
        header = QCheckBox("My data has headers")
        header.setChecked(self._guess_header(r1, c1, c2))
        rows = []
        form = QFormLayout(dlg)
        form.addRow(QLabel(f"Range: {cell_name(r1, c1)}:{cell_name(r2, c2)}"))
        form.addRow(header)
        for i in range(3):
            col = QComboBox()
            col.addItem("(none)" if i else col_name(c1), None if i else c1)
            if i == 0:
                col.clear()
            for c in range(c1, c2 + 1):
                title = format_value(self.wb.value(self.sheet, r1, c))
                col.addItem(f"Column {col_name(c)}" + (f" ({title})" if title else ""), c)
            if i:
                col.insertItem(0, "(none)", None)
                col.setCurrentIndex(0)
            order = QComboBox()
            order.addItems(["A → Z / smallest first", "Z → A / largest first"])
            row = QHBoxLayout()
            row.addWidget(col, 1)
            row.addWidget(order)
            form.addRow("Sort by:" if i == 0 else "Then by:", row)
            rows.append((col, order))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec():
            keys = [(col.currentData(), order.currentIndex() == 1) for col, order in rows if col.currentData() is not None]
            self.sort_range(r1, c1, r2, c2, keys, header.isChecked())

    def sort_range(self, r1, c1, r2, c2, keys, has_header):
        if has_header:
            r1 += 1
        if r2 <= r1:
            return
        self.push_undo()
        s = self.sheet
        rows = list(range(r1, r2 + 1))

        def sort_key(r, col):
            v = self.wb.value(s, r, col)
            if v is None or v == "":
                return (3, 0)
            if isinstance(v, ExcelError):
                return (2, 0)
            if isinstance(v, bool):
                return (1.5, int(v))
            if _is_number(v):
                return (0, v)
            return (1, str(v).lower())
        for col, desc in reversed(keys):
            blanks = [r for r in rows if sort_key(r, col)[0] == 3]
            filled = [r for r in rows if sort_key(r, col)[0] != 3]
            filled.sort(key=lambda r: sort_key(r, col), reverse=desc)
            rows = filled + blanks  # blanks always last, like Excel
        old = {(r, c): s.cells.get((r, c)) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)}
        for i, src_r in enumerate(rows):
            dst_r = r1 + i
            for c in range(c1, c2 + 1):
                cell = old[(src_r, c)]
                if cell is None:
                    s.cells.pop((dst_r, c), None)
                else:
                    cell = copy.deepcopy(cell)
                    if cell.is_formula():
                        cell.value = shift_formula(cell.value, dst_r - src_r, 0)
                    s.cells[(dst_r, c)] = cell
        self.changed()

    def remove_duplicates(self):
        r1, c1, r2, c2 = self._data_region()
        if self._guess_header(r1, c1, c2):
            r1 += 1
        seen, keep = set(), []
        for r in range(r1, r2 + 1):
            key = tuple(format_value(self.wb.value(self.sheet, r, c)) for c in range(c1, c2 + 1))
            if key not in seen:
                seen.add(key)
                keep.append(r)
        removed = (r2 - r1 + 1) - len(keep)
        if not removed:
            QMessageBox.information(self, APP_NAME, "No duplicate rows found.")
            return
        self.push_undo()
        old = {(r, c): self.sheet.cells.get((r, c)) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)}
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                self.sheet.cells.pop((r, c), None)
        for i, src in enumerate(keep):
            for c in range(c1, c2 + 1):
                if old[(src, c)] is not None:
                    self.sheet.cells[(r1 + i, c)] = old[(src, c)]
        self.changed()
        QMessageBox.information(self, APP_NAME, f"Removed {removed} duplicate row(s).")

    # ------------------------------------------------------------ formulas helpers
    def autosum(self):
        idx = self.view.currentIndex()
        r, c = idx.row(), idx.column()

        def num(rr, cc):
            return _is_number(self.wb.value(self.sheet, rr, cc))
        if r > 0 and num(r - 1, c):
            top = r - 1
            while top > 0 and num(top - 1, c):
                top -= 1
            f = f"=SUM({cell_name(top, c)}:{cell_name(r - 1, c)})"
        elif c > 0 and num(r, c - 1):
            left = c - 1
            while left > 0 and num(r, left - 1):
                left -= 1
            f = f"=SUM({cell_name(r, left)}:{cell_name(r, c - 1)})"
        else:
            f = "=SUM()"
        self.formula_edit.setText(f)
        self.formula_edit.setFocus()
        self.formula_edit.setCursorPosition(len(f) - 1)

    def insert_function(self):
        names = sorted(n for n in FUNCTIONS if "." not in n or n.count(".") == 1)
        name, ok = QInputDialog.getItem(self, "Insert Function", "Function:", names, names.index("SUM"), False)
        if ok:
            cur = self.formula_edit.text()
            self.formula_edit.setText((cur if cur.startswith("=") else "=") + name + "()")
            self.formula_edit.setFocus()
            self.formula_edit.setCursorPosition(len(self.formula_edit.text()) - 1)

    def show_functions(self):
        names = sorted(FUNCTIONS)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{len(names)} supported functions")
        lw = QListWidget()
        lw.addItems(names)
        QVBoxLayout(dlg).addWidget(lw)
        dlg.resize(300, 500)
        dlg.exec()

    def define_name(self):
        r1, c1, r2, c2 = self.selected_rects()[0]
        ref = f"{cell_name(r1, c1)}" + (f":{cell_name(r2, c2)}" if (r1, c1) != (r2, c2) else "")
        ref = re.sub(r"([A-Z]+)(\d+)", r"$\1$\2", ref)
        from sheet_engine import quote_sheet
        name, ok = QInputDialog.getText(self, "Define Name", f"Name for {ref}:")
        if ok and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", name.strip()):
            self.push_undo()
            self.wb.names[name.strip().upper()] = f"{quote_sheet(self.sheet.name)}!{ref}"
            self.changed()

    def edit_comment(self):
        idx = self.view.currentIndex()
        cell = self.sheet.cells.get((idx.row(), idx.column()))
        text, ok = QInputDialog.getMultiLineText(self, "Comment", "Comment (leave empty to delete):",
                                                 cell.comment if cell else "")
        if ok:
            self.push_undo()
            if cell is None:
                if not text.strip():
                    return
                cell = self.sheet.cells[(idx.row(), idx.column())] = Cell()
            cell.comment = text.strip()
            self.changed()

    # ------------------------------------------------------------ sheets
    def _tab_menu(self, pos):
        i = self.tabs.tabAt(pos)
        if i >= 0:
            self.switch_sheet(i)
        m = QMenu(self)
        m.addAction("Insert Sheet", self.add_sheet)
        m.addAction("Rename...", lambda: self.rename_sheet(self.tabs.currentIndex()))
        m.addAction("Duplicate", self.duplicate_sheet)
        m.addAction("Delete", self.delete_sheet)
        m.exec(self.tabs.mapToGlobal(pos))

    def _unique_name(self, base):
        n = 1
        name = base
        while self.wb.sheet(name):
            n += 1
            name = f"{base} ({n})" if not base.startswith("Sheet") else f"Sheet{n}"
        return name

    def add_sheet(self):
        self.push_undo()
        s = Sheet(self._unique_name("Sheet1"))
        i = self.tabs.currentIndex() + 1
        self.wb.sheets.insert(i, s)
        self.modified = True
        self._rebuild_tabs(i)
        self.update_title()

    def duplicate_sheet(self):
        self.push_undo()
        s = copy.deepcopy(self.sheet)
        s.name = self._unique_name(self.sheet.name)
        i = self.tabs.currentIndex() + 1
        self.wb.sheets.insert(i, s)
        self.changed()
        self._rebuild_tabs(i)

    def rename_sheet(self, i):
        if i < 0:
            return
        old = self.wb.sheets[i].name
        name, ok = QInputDialog.getText(self, "Rename Sheet", "Sheet name:", QLineEdit.Normal, old)
        name = name.strip()
        if not ok or not name or name == old:
            return
        if any(ch in name for ch in "[]:*?/\\") or len(name) > 31:
            QMessageBox.warning(self, APP_NAME, "Sheet names can't contain [ ] : * ? / \\ and max 31 characters.")
            return
        if self.wb.sheet(name):
            QMessageBox.warning(self, APP_NAME, "There's already a sheet with that name.")
            return
        self.push_undo()
        from sheet_engine import join_ref, rewrite_refs
        for sh in self.wb.sheets:
            for cell in sh.cells.values():
                if cell.is_formula():
                    cell.value = rewrite_refs(cell.value, lambda s, parts: join_ref(name, parts)
                                              if s and s.lower() == old.lower() else None)
        self.wb.sheets[i].name = name
        self.tabs.setTabText(i, name)
        self.changed()

    def delete_sheet(self):
        if len(self.wb.sheets) == 1:
            QMessageBox.information(self, APP_NAME, "A workbook needs at least one sheet.")
            return
        if QMessageBox.question(self, APP_NAME, f"Delete sheet '{self.sheet.name}'?") != QMessageBox.Yes:
            return
        self.push_undo()
        i = self.tabs.currentIndex()
        del self.wb.sheets[i]
        self.changed()
        self._rebuild_tabs(min(i, len(self.wb.sheets) - 1))

    def _tab_moved(self, frm, to):
        self.wb.sheets.insert(to, self.wb.sheets.pop(frm))
        self.modified = True
        self.update_title()

    # ------------------------------------------------------------ charts
    def _rebuild_charts(self):
        for ch in self.charts:
            ch.deleteLater()
        self.charts = []
        for spec in self.sheet.images:
            box = ImageBox(self, spec)
            box.setParent(self.view.viewport())
            box.show()
            self.charts.append(box)
        for spec in self.sheet.charts:
            box = ChartBox(self, spec)
            box.setParent(self.view.viewport())
            box.show()
            self.charts.append(box)
        self._place_charts()

    def _place_charts(self):
        for box in self.charts:
            spec = box.spec
            rect = self.view.visualRect(self.model.index(spec.get("row", 0), spec.get("col", 0)))
            if not rect.isValid():  # anchor scrolled out of view
                x = self.view.columnViewportPosition(spec.get("col", 0))
                y = self.view.rowViewportPosition(spec.get("row", 0))
                rect = QRect(x, y, 1, 1)
            box.move(rect.topLeft())
            box.resize(int(spec.get("w", 480) * self.zoom), int(spec.get("h", 288) * self.zoom))

    def insert_chart(self):
        r1, c1, r2, c2 = self._block()
        if r2 - r1 < 1 or c2 - c1 < 1:
            QMessageBox.information(self, APP_NAME, "Select the data first, including a header row and a "
                                    "label column (e.g. A1:C6), then choose Insert > Chart.")
            return
        spec = {"type": "column", "ref": (r1, c1, r2, c2), "title": "", "row": r1, "col": c2 + 2,
                "w": 480, "h": 288}
        dlg = ChartDialog(self, spec)
        if dlg.exec():
            dlg.apply(spec)
            self.push_undo()
            self.sheet.charts.append(spec)
            self.changed()
            self._rebuild_charts()

    def edit_chart(self, box):
        dlg = ChartDialog(self, box.spec)
        if dlg.exec():
            self.push_undo()
            dlg.apply(box.spec)
            self.changed()
            self._rebuild_charts()

    def delete_chart(self, box):
        self.push_undo()
        (self.sheet.images if isinstance(box, ImageBox) else self.sheet.charts).remove(box.spec)
        self.changed()
        self._rebuild_charts()

    def insert_picture(self):
        f, _ = QFileDialog.getOpenFileName(self, "Insert Picture", self.settings.value("last_dir", ""),
                                           "Images (*.png *.jpg *.jpeg *.gif *.bmp)")
        if not f:
            return
        from PySide6.QtGui import QImage
        img = QImage(f)
        if img.isNull():
            QMessageBox.warning(self, APP_NAME, "Couldn't read that image.")
            return
        with open(f, "rb") as fh:
            data = fh.read()
        if not f.lower().endswith((".png", ".jpg", ".jpeg")):  # store as PNG for Excel compatibility
            from sheet_engine import Cell as _C  # noqa: F401
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")
            data = bytes(ba)
        w = min(img.width(), 400)
        idx = self.view.currentIndex()
        self.push_undo()
        self.sheet.images.append({"data": data, "row": idx.row(), "col": idx.column(),
                                  "w": w, "h": int(img.height() * w / img.width())})
        self.changed()
        self._rebuild_charts()

    def resize_picture(self, box):
        pct, ok = QInputDialog.getInt(self, "Resize Picture", "Size (% of current):", 100, 5, 1000)
        if ok and pct != 100:
            self.push_undo()
            box.spec["w"] = max(5, int(box.spec["w"] * pct / 100))
            box.spec["h"] = max(5, int(box.spec["h"] * pct / 100))
            self.changed()
            self._rebuild_charts()

    def chart_moved(self, box):
        idx = self.view.indexAt(box.pos() + QPoint(2, 2))
        if idx.isValid():
            box.spec["row"], box.spec["col"] = idx.row(), idx.column()
            self.modified = True
            self.update_title()
        self._place_charts()

    # ------------------------------------------------------------ print / PDF
    def render_pages(self, device):
        """Draw the used area of the sheet onto pages, scaled to fit the page width."""
        s = self.sheet
        r2, c2 = s.max_row(), s.max_col()
        for m in s.merges:
            r2, c2 = max(r2, m[2]), max(c2, m[3])
        if r2 < 0:
            r2 = c2 = 0
        widths = [s.col_widths.get(c, DEFAULT_COL_PX) for c in range(c2 + 1)]
        heights = [s.row_heights.get(r, DEFAULT_ROW_PX) for r in range(r2 + 1)]
        xs = [0]
        for w in widths:
            xs.append(xs[-1] + w)
        dpi_scale = device.resolution() / 96
        page_w = device.width() / dpi_scale
        page_h = device.height() / dpi_scale
        fit = min(1.0, page_w / max(xs[-1], 1))
        # split rows into pages
        pages, cur, used = [], [], 0
        for r in range(r2 + 1):
            h = heights[r] * fit
            if cur and used + h > page_h:
                pages.append(cur)
                cur, used = [], 0
            cur.append(r)
            used += h
        pages.append(cur)
        anchors, covered = {}, set()
        for m in s.merges:
            anchors[(m[0], m[1])] = m
            covered |= {(r, c) for r in range(m[0], m[2] + 1) for c in range(m[1], m[3] + 1)} - {(m[0], m[1])}
        grid = self.view.showGrid()
        p = QPainter(device)
        try:
            for n, rows in enumerate(pages):
                if n:
                    device.newPage()
                p.save()
                p.scale(dpi_scale * fit, dpi_scale * fit)
                ys, y = {}, 0
                for r in rows:
                    ys[r] = y
                    y += heights[r]
                if grid:
                    p.setPen(QPen(QColor("#d0d0d0"), 0))
                    for r in rows:
                        if heights[r]:
                            p.drawLine(QPointF(0, ys[r] + heights[r]), QPointF(xs[-1], ys[r] + heights[r]))
                    for x in xs:
                        p.drawLine(QPointF(x, 0), QPointF(x, y))
                for r in rows:
                    if not heights[r]:
                        continue
                    for c in range(c2 + 1):
                        if (r, c) in covered or not widths[c]:
                            continue
                        rect = QRect(xs[c], ys[r], widths[c], heights[r])
                        if (r, c) in anchors:
                            m = anchors[(r, c)]
                            rect.setRight(xs[m[3] + 1] - 1)
                            rect.setBottom(ys[r] + sum(heights[rr] for rr in range(r, m[2] + 1)) - 1)
                        self._print_cell(p, r, c, rect, xs, c2, covered)
                p.restore()
        finally:
            p.end()

    def _print_cell(self, p, r, c, rect, xs, c2, covered):
        cell = self.sheet.cells.get((r, c))
        if cell is None:
            return
        st = cell.style
        if st.get("fill"):
            p.fillRect(rect, QColor(st["fill"]))
        text = self.model.text(r, c)
        if text:
            v = self.model.value(r, c)
            f = QFont(st.get("font", DEFAULT_FONT))
            f.setPixelSize(max(1, round(st.get("size", DEFAULT_SIZE) * 96 / 72)))
            f.setBold(bool(st.get("bold")))
            f.setItalic(bool(st.get("italic")))
            f.setUnderline(bool(st.get("underline")))
            f.setStrikeOut(bool(st.get("strike")))
            p.setFont(f)
            p.setPen(QColor(st.get("color", "#000000")))
            h = st.get("halign") or ("right" if _is_number(v) else "center" if isinstance(v, (bool, ExcelError)) else "left")
            ha = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}[h]
            va = {"top": Qt.AlignTop, "center": Qt.AlignVCenter}.get(st.get("valign"), Qt.AlignBottom)
            tr = rect.adjusted(3, 1, -3, -1)
            fm = QFontMetrics(f)
            if st.get("wrap"):
                p.drawText(tr, ha | va | Qt.TextWordWrap, text)
            else:
                need = fm.horizontalAdvance(text) + 6
                if need > rect.width() and _is_number(v):
                    text = "#" * max(1, (rect.width() - 6) // max(fm.horizontalAdvance("#"), 1))
                elif need > rect.width() and ha == Qt.AlignLeft:
                    cc, right = c + 1, rect.right()
                    while right - rect.left() < need and cc <= c2 + 30:
                        nb = self.sheet.cells.get((r, cc))
                        if (nb is not None and nb.value not in (None, "")) or (r, cc) in covered:
                            break
                        right += (xs[cc + 1] - xs[cc]) if cc + 1 < len(xs) else DEFAULT_COL_PX
                        cc += 1
                    tr.setRight(right - 3)
                p.save()
                p.setClipRect(QRect(rect.left(), rect.top(), tr.right() - rect.left() + 3, rect.height()))
                p.drawText(tr, ha | va | Qt.TextSingleLine, text)
                p.restore()
        for side, kind in st.get("border", {}).items():
            p.setPen(QPen(QColor("#000"), {"medium": 2, "thick": 3, "double": 3}.get(kind, 1)))
            pts = {"left": (rect.topLeft(), rect.bottomLeft()), "right": (rect.topRight(), rect.bottomRight()),
                   "top": (rect.topLeft(), rect.topRight()), "bottom": (rect.bottomLeft(), rect.bottomRight())}
            if side in pts:
                p.drawLine(*pts[side])

    def _page_layout(self):
        s = self.sheet
        wide = sum(s.col_widths.get(c, DEFAULT_COL_PX) for c in range(s.max_col() + 1)) > 720
        return QPageLayout(QPageSize(QPageSize.Letter), QPageLayout.Landscape if wide else QPageLayout.Portrait,
                           QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)

    def export_pdf(self):
        start = os.path.splitext(self.path)[0] + ".pdf" if self.path else "Book1.pdf"
        f, _ = QFileDialog.getSaveFileName(self, "Export Sheet as PDF", start, "PDF files (*.pdf)")
        if not f:
            return
        if not f.lower().endswith(".pdf"):
            f += ".pdf"
        w = QPdfWriter(f)
        w.setResolution(300)
        w.setPageLayout(self._page_layout())
        w.setCreator(f"{SUITE_NAME} {APP_NAME}")
        self.render_pages(w)
        self.statusBar().showMessage(f"Exported {f}", 5000)

    def print_sheet(self):
        p = QPrinter(QPrinter.HighResolution)
        p.setPageLayout(self._page_layout())
        if QPrintDialog(p, self).exec():
            self.render_pages(p)

    # ------------------------------------------------------------ misc
    def show_find(self):
        if self.find_dialog is None:
            self.find_dialog = FindDialog(self)
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.find.setFocus()

    def cell_context_menu(self, pos):
        m = QMenu(self)
        m.addAction("Cut", self.cut)
        m.addAction("Copy", self.copy)
        m.addAction("Paste", self.paste)
        m.addAction("Paste Values Only", lambda: self.paste(values_only=True))
        m.addSeparator()
        m.addMenu(self.insert_menu)
        m.addMenu(self.delete_menu)
        m.addAction("Clear Contents", self.clear_contents)
        m.addSeparator()
        m.addAction("Sort A → Z", lambda: self.quick_sort(False))
        m.addAction("Sort Z → A", lambda: self.quick_sort(True))
        m.addSeparator()
        m.addAction("Insert/Edit Comment...", self.edit_comment)
        m.addAction("Format: Custom Number Format...", self.custom_format)
        m.exec(pos)


def main():
    app = make_app(APP_NAME, sys.argv)
    win = SheetsWindow(sys.argv[1] if len(sys.argv) > 1 else None)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
