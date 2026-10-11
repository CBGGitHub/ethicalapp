"""Ethical Database - a simple Access-style database app (tables, forms, queries, relationships, reports)."""
import os
import shutil
import sqlite3
import sys

from PySide6.QtCore import QAbstractTableModel, QMarginsF, QModelIndex, QPointF, QRectF, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import (QAction, QColor, QFont, QKeySequence, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen,
                           QTextDocument)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSplitter, QStyledItemDelegate, QTableView, QTableWidget,
                               QTableWidgetItem, QTabWidget, QTextBrowser, QToolBar, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base_core as bc  # noqa: E402
from suite_common import SETTINGS_ORG, SUITE_NAME, make_app  # noqa: E402
from suite_common import add_guide_action  # noqa: E402

APP_NAME = "Ethical Database"
ACCENT = "#7B1F3A"
BATCH = 500
DB_FILTER = "Ethical Database / SQLite database (*.db *.sqlite *.sqlite3 *.edb);;All files (*)"


def error(parent, ex, what="That didn't work"):
    msg = str(ex)
    friendly = {
        "NOT NULL constraint failed": "This field is required - please fill it in.",
        "UNIQUE constraint failed": "That value is already used in another record, but this field must be unique.",
        "FOREIGN KEY constraint failed": "This would break a relationship: the related record doesn't exist, "
                                         "or other records still depend on this one.",
    }
    for k, v in friendly.items():
        if k in msg:
            msg = v + f"\n\n({ex})"
            break
    QMessageBox.warning(parent, APP_NAME, f"{what}:\n{msg}")


# ====================================================================== data model

class SqlModel(QAbstractTableModel):
    """A table or query shown as a grid, loaded in batches; tables are editable (+ a 'new record' row)."""

    def __init__(self, db, source):
        super().__init__()
        self.db, self.source = db, source
        self.view = db.is_view(source)
        self.cols = db.columns(source)
        self.kinds = db.kinds(source)
        self.editable = not self.view
        self.lookups = {}
        if not self.view:
            for c in self.cols:
                lk = db.lookup_for(source, c)
                if lk:
                    parent, key, disp = lk
                    rows = db.con.execute(f"SELECT {bc.q(key)}, {bc.q(disp)} FROM {bc.q(parent)} ORDER BY 2").fetchall()
                    self.lookups[c] = rows
        self.where, self.params, self.order = "", [], ""
        self.filters = []          # (column, value) from "filter by selection"
        self.search = ""
        self.reload()

    def _query(self):
        conds, params = [], []
        for c, v in self.filters:
            if v is None:
                conds.append(f"{bc.q(c)} IS NULL")
            else:
                conds.append(f"{bc.q(c)} = ?")
                params.append(v)
        if self.search:
            conds.append("(" + " OR ".join(f"CAST({bc.q(c)} AS TEXT) LIKE ?" for c in self.cols) + ")")
            params += [f"%{self.search}%"] * len(self.cols)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rid = "rowid AS __rid, " if not self.view else ""
        return f"SELECT {rid}* FROM {bc.q(self.source)} {where} {self.order}", params, where

    def reload(self):
        self.beginResetModel()
        sql, params, where = self._query()
        self.total = self.db.con.execute(f"SELECT COUNT(*) FROM {bc.q(self.source)} {where}", params).fetchone()[0]
        self.cur = self.db.con.execute(sql, params)
        self.rows = [list(r) for r in self.cur.fetchmany(BATCH)]
        self.endResetModel()

    def canFetchMore(self, parent=QModelIndex()):
        return len(self.rows) < self.total

    def fetchMore(self, parent=QModelIndex()):
        more = [list(r) for r in self.cur.fetchmany(BATCH)]
        if more:
            self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows) + len(more) - 1)
            self.rows += more
            self.endInsertRows()

    def fetch_all(self):
        while self.canFetchMore():
            self.fetchMore()

    # ---- Qt model API
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows) + (1 if self.editable else 0)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.cols)

    def is_new_row(self, r):
        return self.editable and r == len(self.rows)

    def value(self, r, c):
        if self.is_new_row(r):
            return None
        return self.rows[r][c + (0 if self.view else 1)]

    def rowid(self, r):
        return None if self.view or self.is_new_row(r) else self.rows[r][0]

    def headerData(self, s, o, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if o == Qt.Horizontal:
            return self.cols[s]
        return "✱" if self.is_new_row(s) else str(s + 1)

    def flags(self, idx):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if not self.editable:
            return f
        kind = self.kinds.get(self.cols[idx.column()])
        if kind == "AutoNumber":
            return f
        if kind == "Yes/No":
            return f | Qt.ItemIsUserCheckable
        return f | Qt.ItemIsEditable

    def data(self, idx, role=Qt.DisplayRole):
        r, c = idx.row(), idx.column()
        col = self.cols[c]
        kind = self.kinds.get(col)
        v = self.value(r, c)
        if role == Qt.DisplayRole:
            if self.is_new_row(r):
                return "(New)" if kind == "AutoNumber" else ""
            if kind == "Yes/No":
                return None
            if col in self.lookups and v is not None:
                return next((d for k, d in self.lookups[col] if k == v), str(v))
            return bc.display(v, kind)
        if role == Qt.EditRole:
            if kind in ("Date", "Date & Time") and v:
                return bc.display(v, kind) if kind == "Date" else str(v)
            return "" if v is None else str(v)
        if role == Qt.CheckStateRole and kind == "Yes/No" and not self.is_new_row(r):
            return Qt.Checked if v in (1, "1", True) else Qt.Unchecked
        if role == Qt.TextAlignmentRole:
            if kind in ("Whole Number", "Decimal Number", "Currency", "AutoNumber"):
                return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and self.is_new_row(r):
            return QColor("#999")
        if role == Qt.ToolTipRole and kind == "Long Text" and v:
            return str(v)[:1000]
        return None

    def setData(self, idx, value, role=Qt.EditRole):
        r, c = idx.row(), idx.column()
        col = self.cols[c]
        kind = self.kinds.get(col)
        if role == Qt.CheckStateRole:
            value = 1 if Qt.CheckState(value) == Qt.Checked else 0
        elif role != Qt.EditRole:
            return False
        try:
            v = bc.to_db(value, kind) if kind != "Yes/No" or role != Qt.CheckStateRole else value
        except ValueError as ex:
            QMessageBox.warning(None, APP_NAME, f"{col}: {ex}")
            return False
        try:
            if self.is_new_row(r):
                if v is None:
                    return False
                cur = self.db.con.execute(f"INSERT INTO {bc.q(self.source)} ({bc.q(col)}) VALUES (?)", (v,))
                self.db.con.commit()
                new = self.db.con.execute(f"SELECT rowid AS __rid, * FROM {bc.q(self.source)} WHERE rowid=?",
                                          (cur.lastrowid,)).fetchone()
                self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows))
                self.rows.append(list(new))
                self.total += 1
                self.endInsertRows()
                return True
            self.db.con.execute(f"UPDATE {bc.q(self.source)} SET {bc.q(col)} = ? WHERE rowid = ?", (v, self.rowid(r)))
            self.db.con.commit()
        except sqlite3.Error as ex:
            self.db.con.rollback()
            error(None, ex, "Couldn't save")
            return False
        self.rows[r] = list(self.db.con.execute(f"SELECT rowid AS __rid, * FROM {bc.q(self.source)} WHERE rowid=?",
                                                (self.rowid(r),)).fetchone())
        self.dataChanged.emit(self.index(r, 0), self.index(r, len(self.cols) - 1))
        return True

    def delete_rows(self, rows):
        ids = [self.rowid(r) for r in rows if self.rowid(r) is not None]
        if not ids:
            return 0
        try:
            self.db.con.executemany(f"DELETE FROM {bc.q(self.source)} WHERE rowid = ?", [(i,) for i in ids])
            self.db.con.commit()
        except sqlite3.Error as ex:
            self.db.con.rollback()
            error(None, ex, "Couldn't delete")
            return 0
        self.reload()
        return len(ids)

    def insert_record(self, values):
        """values: {column: python value}. Returns the new rowid."""
        cols = [c for c in values]
        sql = (f"INSERT INTO {bc.q(self.source)} ({', '.join(bc.q(c) for c in cols)}) VALUES "
               f"({', '.join('?' for _ in cols)})") if cols else f"INSERT INTO {bc.q(self.source)} DEFAULT VALUES"
        cur = self.db.con.execute(sql, [values[c] for c in cols])
        self.db.con.commit()
        return cur.lastrowid


class CellDelegate(QStyledItemDelegate):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def createEditor(self, parent, opt, idx):
        col = self.model.cols[idx.column()]
        if col in self.model.lookups:
            cb = QComboBox(parent)
            cb.addItem("", None)
            for k, d in self.model.lookups[col]:
                cb.addItem(f"{d}", k)
            return cb
        e = super().createEditor(parent, opt, idx)
        kind = self.model.kinds.get(col)
        if isinstance(e, QLineEdit) and kind in ("Date", "Date & Time"):
            e.setPlaceholderText("YYYY-MM-DD or 'today'")
        return e

    def setEditorData(self, editor, idx):
        if isinstance(editor, QComboBox):
            v = self.model.value(idx.row(), idx.column())
            i = editor.findData(v)
            editor.setCurrentIndex(max(i, 0))
            return
        super().setEditorData(editor, idx)

    def setModelData(self, editor, model, idx):
        if isinstance(editor, QComboBox):
            model.setData(idx, editor.currentData(), Qt.EditRole)
            return
        super().setModelData(editor, model, idx)


# ====================================================================== tabs

class DatasheetTab(QWidget):
    def __init__(self, win, source):
        super().__init__()
        self.win, self.source = win, source
        self.model = SqlModel(win.db, source)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(CellDelegate(self.model))
        self.view.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.view.setAlternatingRowColors(True)
        self.view.setSortingEnabled(False)
        self.view.horizontalHeader().setSectionsClickable(True)
        self.view.horizontalHeader().sectionClicked.connect(self.sort_by)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self.context_menu)
        self.view.verticalHeader().setDefaultSectionSize(24)
        self.sort_col, self.sort_desc = None, False
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search all fields…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self.search_timer.start())
        self.search_timer = QTimer(self, singleShot=True, interval=250)
        self.search_timer.timeout.connect(self.apply_search)
        bar.addWidget(self.search, 1)
        for text, slot, tip in (("＋ New Record", self.new_record, "Add a record (or type in the ✱ row)"),
                                ("✖ Delete", self.delete_records, "Delete the selected records"),
                                ("Filter by Selection", self.filter_selection, "Show only records with this value"),
                                ("Remove Filter", self.clear_filter, None), ("Form View", self.form_view, None),
                                ("↻", self.refresh, "Refresh")):
            b = QPushButton(text)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(slot)
            if text not in ("↻", "Form View", "Filter by Selection", "Remove Filter") and not self.model.editable:
                b.setEnabled(False)
            bar.addWidget(b)
        self.status = QLabel()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(bar)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.status)
        self.model.modelReset.connect(self.update_status)
        self.model.rowsInserted.connect(lambda *_: self.update_status())
        self.size_columns()
        self.update_status()

    def size_columns(self):
        self.view.resizeColumnsToContents()
        for c in range(self.model.columnCount()):
            self.view.setColumnWidth(c, min(max(self.view.columnWidth(c), 70), 320))

    def update_status(self):
        filt = " (filtered)" if self.model.filters or self.model.search else ""
        ro = "  ·  read-only query results" if self.model.view else ""
        self.status.setText(f"{self.model.total:,} record(s){filt}{ro}"
                            + ("" if not self.model.order else f"  ·  sorted by {self.sort_col}"))

    def refresh(self):
        self.model.reload()
        self.size_columns()

    def apply_search(self):
        self.model.search = self.search.text().strip()
        self.model.reload()

    def sort_by(self, c):
        col = self.model.cols[c]
        self.sort_desc = not self.sort_desc if self.sort_col == col else False
        self.sort_col = col
        self.model.order = f"ORDER BY {bc.q(col)}" + (" DESC" if self.sort_desc else "")
        self.view.horizontalHeader().setSortIndicatorShown(True)
        self.view.horizontalHeader().setSortIndicator(c, Qt.DescendingOrder if self.sort_desc else Qt.AscendingOrder)
        self.model.reload()

    def filter_selection(self):
        idx = self.view.currentIndex()
        if not idx.isValid() or self.model.is_new_row(idx.row()):
            return
        self.model.filters.append((self.model.cols[idx.column()], self.model.value(idx.row(), idx.column())))
        self.model.reload()

    def clear_filter(self):
        self.model.filters = []
        self.search.clear()
        self.model.search = ""
        self.model.reload()

    def new_record(self):
        if not self.model.editable:
            return
        self.model.fetch_all()
        r = len(self.model.rows)
        first = next((i for i, c in enumerate(self.model.cols) if self.model.kinds.get(c) != "AutoNumber"), 0)
        self.view.scrollToBottom()
        self.view.setCurrentIndex(self.model.index(r, first))
        self.view.edit(self.model.index(r, first))

    def delete_records(self):
        rows = sorted({i.row() for i in self.view.selectionModel().selectedIndexes()})
        rows = [r for r in rows if not self.model.is_new_row(r)]
        if not rows:
            return
        if QMessageBox.question(self, APP_NAME, f"Delete {len(rows)} record(s)? This can't be undone.") != QMessageBox.Yes:
            return
        n = self.model.delete_rows(rows)
        if n:
            self.win.statusBar().showMessage(f"Deleted {n} record(s)", 3000)

    def form_view(self):
        idx = self.view.currentIndex()
        self.win.open_form(self.source, idx.row() if idx.isValid() else 0)

    def context_menu(self, pos):
        m = QMenu(self)
        m.addAction("Filter by Selection", self.filter_selection)
        m.addAction("Remove Filter", self.clear_filter)
        m.addSeparator()
        m.addAction("Copy", self.copy_cells)
        if self.model.editable:
            m.addAction("New Record", self.new_record)
            m.addAction("Delete Record(s)", self.delete_records)
        m.addAction("Open in Form View", self.form_view)
        m.exec(self.view.viewport().mapToGlobal(pos))

    def copy_cells(self):
        idxs = sorted(self.view.selectionModel().selectedIndexes(), key=lambda i: (i.row(), i.column()))
        if not idxs:
            return
        rows = {}
        for i in idxs:
            rows.setdefault(i.row(), []).append(str(self.model.data(i) or ""))
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText("\n".join("\t".join(v) for v in rows.values()))

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Copy):
            self.copy_cells()
            return
        super().keyPressEvent(e)


class FormTab(QWidget):
    """One record at a time, with a field editor per column."""

    def __init__(self, win, source, row=0):
        super().__init__()
        self.win, self.source = win, source
        self.model = SqlModel(win.db, source)
        self.model.fetch_all()
        self.row = min(row, max(len(self.model.rows) - 1, 0))
        self.new_mode = not self.model.rows and self.model.editable
        self.editors = {}
        title = QLabel(source)
        title.setStyleSheet(f"font-size: 20px; font-weight: 600; color: {ACCENT}; padding: 4px;")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        for col in self.model.cols:
            kind = self.model.kinds.get(col)
            if col in self.model.lookups:
                e = QComboBox()
                e.addItem("", None)
                for k, d in self.model.lookups[col]:
                    e.addItem(str(d), k)
            elif kind == "Yes/No":
                e = QCheckBox()
            elif kind == "Long Text":
                e = QPlainTextEdit()
                e.setMaximumHeight(110)
            else:
                e = QLineEdit()
                if kind in ("Date", "Date & Time"):
                    e.setPlaceholderText("YYYY-MM-DD or 'today'")
                if kind == "AutoNumber":
                    e.setReadOnly(True)
                    e.setStyleSheet("background: #f2f2f2;")
            if not self.model.editable:
                e.setEnabled(False)
            self.editors[col] = e
            label = QLabel(f"{col}:")
            label.setToolTip(kind)
            form.addRow(label, e)
        inner = QWidget()
        inner.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        nav = QHBoxLayout()
        self.pos_label = QLabel()
        for text, slot in (("⏮", lambda: self.go(0)), ("◀", lambda: self.go(self.row - 1)),
                           ("▶", lambda: self.go(self.row + 1)), ("⏭", lambda: self.go(len(self.model.rows) - 1))):
            b = QPushButton(text)
            b.setFixedWidth(40)
            b.clicked.connect(slot)
            nav.addWidget(b)
        nav.addWidget(self.pos_label)
        nav.addStretch()
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find…")
        self.find.returnPressed.connect(self.find_next)
        nav.addWidget(self.find)
        for text, slot in (("＋ New", self.new_record), ("💾 Save", self.save), ("✖ Delete", self.delete),
                           ("Datasheet", lambda: self.win.open_datasheet(self.source))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            b.setEnabled(self.model.editable or text == "Datasheet")
            nav.addWidget(b)
        lay = QVBoxLayout(self)
        lay.addWidget(title)
        lay.addWidget(scroll, 1)
        lay.addLayout(nav)
        self.load()

    def load(self):
        for col, e in self.editors.items():
            v = None if self.new_mode or not self.model.rows else self.model.value(self.row, self.model.cols.index(col))
            kind = self.model.kinds.get(col)
            if isinstance(e, QComboBox):
                e.setCurrentIndex(max(e.findData(v), 0))
            elif isinstance(e, QCheckBox):
                e.setChecked(v in (1, "1", True))
            elif isinstance(e, QPlainTextEdit):
                e.setPlainText("" if v is None else str(v))
            else:
                e.setText("(New)" if self.new_mode and kind == "AutoNumber" else
                          "" if v is None else (bc.display(v, kind) if kind in ("Date", "Currency") else str(v)))
        n = len(self.model.rows)
        self.pos_label.setText("  New record" if self.new_mode else f"  Record {self.row + 1} of {n}" if n else "  No records")

    def values(self):
        out = {}
        for col, e in self.editors.items():
            kind = self.model.kinds.get(col)
            if kind == "AutoNumber":
                continue
            if isinstance(e, QComboBox):
                raw = e.currentData()
            elif isinstance(e, QCheckBox):
                raw = e.isChecked()
            elif isinstance(e, QPlainTextEdit):
                raw = e.toPlainText()
            else:
                raw = e.text()
            try:
                out[col] = bc.to_db(raw, kind) if not isinstance(raw, (int, bool)) or kind == "Yes/No" else raw
            except ValueError as ex:
                raise ValueError(f"{col}: {ex}")
        return out

    def dirty(self):
        if not self.model.editable or (not self.model.rows and not self.new_mode):
            return False
        try:
            vals = self.values()
        except ValueError:
            return True
        if self.new_mode:
            return any(v not in (None, 0, "") for v in vals.values())
        cur = {c: self.model.value(self.row, self.model.cols.index(c)) for c in vals}
        return any(str(vals[c]) != str(cur[c]) and not (vals[c] in (None, "") and cur[c] in (None, "")) for c in vals)

    def save(self):
        if not self.model.editable:
            return True
        try:
            vals = self.values()
            if self.new_mode:
                rid = self.model.insert_record({k: v for k, v in vals.items() if v is not None})
                self.model.reload()
                self.model.fetch_all()
                self.row = next((i for i, r in enumerate(self.model.rows) if r[0] == rid), len(self.model.rows) - 1)
                self.new_mode = False
            else:
                rid = self.model.rowid(self.row)
                sets = ", ".join(f"{bc.q(c)} = ?" for c in vals)
                self.win.db.con.execute(f"UPDATE {bc.q(self.source)} SET {sets} WHERE rowid = ?", [*vals.values(), rid])
                self.win.db.con.commit()
                self.model.reload()
                self.model.fetch_all()
        except ValueError as ex:
            QMessageBox.warning(self, APP_NAME, str(ex))
            return False
        except sqlite3.Error as ex:
            self.win.db.con.rollback()
            error(self, ex, "Couldn't save the record")
            return False
        self.load()
        self.win.statusBar().showMessage("Record saved", 2000)
        return True

    def go(self, row):
        if self.dirty() and not self.save():
            return
        n = len(self.model.rows)
        if n == 0:
            return
        self.new_mode = False
        self.row = max(0, min(row, n - 1))
        self.load()

    def new_record(self):
        if self.dirty() and not self.save():
            return
        self.new_mode = True
        self.load()
        first = next((e for c, e in self.editors.items() if self.model.kinds.get(c) != "AutoNumber"), None)
        if first:
            first.setFocus()

    def delete(self):
        if self.new_mode or not self.model.rows:
            self.new_mode = False
            self.load()
            return
        if QMessageBox.question(self, APP_NAME, "Delete this record? This can't be undone.") != QMessageBox.Yes:
            return
        if self.model.delete_rows([self.row]):
            self.model.fetch_all()
            self.row = min(self.row, max(len(self.model.rows) - 1, 0))
            self.load()

    def find_next(self):
        t = self.find.text().strip().lower()
        if not t:
            return
        n = len(self.model.rows)
        for k in range(1, n + 1):
            r = (self.row + k) % n
            if any(t in str(v).lower() for v in self.model.rows[r][1:] if v is not None):
                self.go(r)
                return
        self.win.statusBar().showMessage("Not found", 2000)


class DesignTab(QWidget):
    """Create or change a table's fields."""

    def __init__(self, win, table=None):
        super().__init__()
        self.win, self.table = win, table
        top = QHBoxLayout()
        top.addWidget(QLabel("Table name:"))
        self.name = QLineEdit(table or "")
        self.name.setPlaceholderText("e.g. Customers")
        top.addWidget(self.name, 1)
        self.grid = QTableWidget(0, 5)
        self.grid.setHorizontalHeaderLabels(["Field Name", "Data Type", "Required", "Unique", "Default Value"])
        self.grid.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.grid.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.grid.setColumnWidth(1, 150)
        btns = QHBoxLayout()
        for text, slot in (("＋ Add Field", lambda: self.add_row(bc.Field(""))), ("✖ Remove Field", self.remove_row),
                           ("▲", lambda: self.move(-1)), ("▼", lambda: self.move(1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch()
        save = QPushButton("💾 Save Table")
        save.setStyleSheet(f"background: {ACCENT}; color: white; font-weight: bold; padding: 6px 16px;")
        save.clicked.connect(self.save)
        btns.addWidget(save)
        help_ = QLabel("Tip: every table should have an AutoNumber ID. Defaults: type a value, or DATE() for "
                       "today's date. Relationships between tables: Database → Relationships.")
        help_.setWordWrap(True)
        help_.setStyleSheet("color: #666;")
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.grid, 1)
        lay.addLayout(btns)
        lay.addWidget(help_)
        fields = win.db.fields(table) if table else [bc.Field("ID", "AutoNumber", pk=True), bc.Field("Name")]
        for f in fields:
            self.add_row(f)

    def add_row(self, f):
        r = self.grid.rowCount()
        self.grid.insertRow(r)
        item = QTableWidgetItem(f.name)
        item.setData(Qt.UserRole, f.original)
        self.grid.setItem(r, 0, item)
        cb = QComboBox()
        cb.addItems(bc.FIELD_TYPES)
        cb.setCurrentText(f.kind)
        self.grid.setCellWidget(r, 1, cb)
        for c, val in ((2, f.required), (3, f.unique)):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if val else Qt.Unchecked)
            self.grid.setItem(r, c, chk)
        self.grid.setItem(r, 4, QTableWidgetItem(f.default))
        if not f.name:
            self.grid.setCurrentCell(r, 0)
            self.grid.editItem(self.grid.item(r, 0))

    def remove_row(self):
        r = self.grid.currentRow()
        if r >= 0:
            name = self.grid.item(r, 0).text()
            if self.table and self.grid.item(r, 0).data(Qt.UserRole) and QMessageBox.question(
                    self, APP_NAME, f"Remove the field “{name}” and all its data?") != QMessageBox.Yes:
                return
            self.grid.removeRow(r)

    def move(self, d):
        r = self.grid.currentRow()
        j = r + d
        if r < 0 or not 0 <= j < self.grid.rowCount():
            return
        fields = self.read_fields()
        fields[r], fields[j] = fields[j], fields[r]
        self.grid.setRowCount(0)
        for f in fields:
            self.add_row(f)
        self.grid.setCurrentCell(j, 0)

    def read_fields(self):
        out = []
        for r in range(self.grid.rowCount()):
            kind = self.grid.cellWidget(r, 1).currentText()
            out.append(bc.Field(self.grid.item(r, 0).text().strip(), kind,
                                self.grid.item(r, 2).checkState() == Qt.Checked,
                                self.grid.item(r, 3).checkState() == Qt.Checked,
                                (self.grid.item(r, 4).text() if self.grid.item(r, 4) else "").strip(),
                                kind == "AutoNumber", self.grid.item(r, 0).data(Qt.UserRole)))
        return out

    def save(self):
        name = self.name.text().strip()
        fields = self.read_fields()
        db = self.win.db
        try:
            if self.table is None:
                db.create_table(name, fields)
            else:
                if name != self.table and (name in db.tables() or name in db.views()):
                    raise ValueError(f"There's already something called {name}.")
                self.win.close_tabs_for(self.table, keep=self)
                db.redesign(self.table, fields, new_name=name)
        except (ValueError, sqlite3.Error) as ex:
            error(self, ex, "Couldn't save the table")
            return
        broken = db.broken_views()
        self.table = name
        self.win.refresh_nav()
        self.win.statusBar().showMessage(f"Saved table {name}", 3000)
        idx = self.win.tabs.indexOf(self)
        self.win.tabs.setTabText(idx, f"{name} (Design)")
        self.grid.setRowCount(0)
        for f in db.fields(name):
            self.add_row(f)
        if broken:
            QMessageBox.information(self, APP_NAME, "These saved queries no longer work because of the change and "
                                    "need updating: " + ", ".join(broken))


class QueryTab(QWidget):
    """Query designer (pick fields, criteria, sorting, totals) + SQL view + results."""

    def __init__(self, win, name=None):
        super().__init__()
        self.win, self.name = win, name
        db = win.db
        self.tabs = QTabWidget()
        # --- design page
        design = QWidget()
        dl = QVBoxLayout(design)
        row = QHBoxLayout()
        row.addWidget(QLabel("Main table:"))
        self.base = QComboBox()
        self.base.addItems(db.tables() + db.views())
        self.base.currentTextChanged.connect(self._base_changed)
        row.addWidget(self.base)
        row.addWidget(QLabel("  Also show fields from related tables:"))
        self.related = QListWidget()
        self.related.setMaximumHeight(70)
        self.related.itemChanged.connect(lambda _: self._fill_field_list())
        row.addWidget(self.related, 1)
        dl.addLayout(row)
        self.totals = QCheckBox("Totals (group and add up)")
        self.totals.toggled.connect(lambda on: self.grid.setColumnHidden(5, not on))
        self.distinct = QCheckBox("Hide duplicate rows")
        r2 = QHBoxLayout()
        r2.addWidget(self.totals)
        r2.addWidget(self.distinct)
        r2.addStretch()
        add = QPushButton("＋ Add Field")
        add.clicked.connect(lambda: self.add_row())
        rm = QPushButton("✖ Remove")
        rm.clicked.connect(lambda: self.grid.removeRow(self.grid.currentRow()))
        allf = QPushButton("Add All Fields")
        allf.clicked.connect(self.add_all)
        for b in (add, allf, rm):
            r2.addWidget(b)
        dl.addLayout(r2)
        self.grid = QTableWidget(0, 6)
        self.grid.setHorizontalHeaderLabels(["Field", "Show", "Sort", "Criteria", "", "Total"])
        self.grid.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.grid.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.grid.setColumnHidden(4, True)
        self.grid.setColumnHidden(5, True)
        dl.addWidget(self.grid, 1)
        tip = QLabel('Criteria examples:  >100   <=#2026-12-31#   Like "A*"   Between 1 And 50   Is Null   '
                     '"London" Or "Paris"   Yes')
        tip.setStyleSheet("color: #666;")
        dl.addWidget(tip)
        self.tabs.addTab(design, "Design")
        # --- SQL page
        self.sql = QPlainTextEdit()
        self.sql.setFont(QFont("Consolas", 11))
        self.sql.setPlaceholderText("SELECT * FROM \"Customers\" WHERE \"City\" = 'London'")
        self.tabs.addTab(self.sql, "SQL")
        self.tabs.currentChanged.connect(self._tab_changed)
        # --- results
        self.results = QTableView()
        self.results.setAlternatingRowColors(True)
        self.result_label = QLabel()
        btns = QHBoxLayout()
        for text, slot in (("▶ Run", self.run), ("💾 Save Query…", self.save)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addWidget(self.result_label, 1)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.tabs)
        rw = QWidget()
        rl = QVBoxLayout(rw)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addLayout(btns)
        rl.addWidget(self.results)
        split.addWidget(rw)
        split.setSizes([330, 330])
        lay = QVBoxLayout(self)
        lay.addWidget(split)
        if name:
            self.sql.setPlainText(db.view_sql(name))
            self.tabs.setCurrentIndex(1)
            self.run()
        elif self.base.count():
            self._base_changed(self.base.currentText())

    def _base_changed(self, base):
        self.related.blockSignals(True)
        self.related.clear()
        for r in self.win.db.relations():
            other = r.parent if r.child == base else r.child if r.parent == base else None
            if other:
                it = QListWidgetItem(other)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Unchecked)
                it.setData(Qt.UserRole, r)
                self.related.addItem(it)
        self.related.blockSignals(False)
        self.grid.setRowCount(0)
        self._fill_field_list()

    def _tables(self):
        out = [self.base.currentText()]
        for i in range(self.related.count()):
            it = self.related.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.text())
        return out

    def _field_options(self):
        opts = []
        for t in self._tables():
            for c in self.win.db.columns(t):
                opts.append(f"{t}.{c}")
        return opts

    def _fill_field_list(self):
        opts = self._field_options()
        for r in range(self.grid.rowCount()):
            cb = self.grid.cellWidget(r, 0)
            cur = cb.currentText()
            cb.clear()
            cb.addItems(opts)
            cb.setCurrentText(cur)

    def add_row(self, field=None):
        r = self.grid.rowCount()
        self.grid.insertRow(r)
        cb = QComboBox()
        cb.addItems(self._field_options())
        if field:
            cb.setCurrentText(field)
        self.grid.setCellWidget(r, 0, cb)
        show = QTableWidgetItem()
        show.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        show.setCheckState(Qt.Checked)
        self.grid.setItem(r, 1, show)
        sort = QComboBox()
        sort.addItems(["", "Ascending", "Descending"])
        self.grid.setCellWidget(r, 2, sort)
        self.grid.setItem(r, 3, QTableWidgetItem(""))
        tot = QComboBox()
        tot.addItems(["Group By", "Sum", "Average", "Count", "Min", "Max", "Where"])
        self.grid.setCellWidget(r, 5, tot)

    def add_all(self):
        for f in self._field_options():
            self.add_row(f)

    def design_sql(self):
        rows = []
        for r in range(self.grid.rowCount()):
            t, _, f = self.grid.cellWidget(r, 0).currentText().partition(".")
            if not f:
                continue
            rows.append(dict(table=t, field=f, show=self.grid.item(r, 1).checkState() == Qt.Checked,
                             sort=self.grid.cellWidget(r, 2).currentText(), criteria=self.grid.item(r, 3).text(),
                             total=self.grid.cellWidget(r, 5).currentText()))
        joins = [self.related.item(i).data(Qt.UserRole) for i in range(self.related.count())
                 if self.related.item(i).checkState() == Qt.Checked]
        return bc.build_query(self.win.db, self.base.currentText(), joins, rows, self.distinct.isChecked(),
                              self.totals.isChecked())

    def _tab_changed(self, i):
        if i == 1 and self.grid.rowCount():
            self.sql.setPlainText(self.design_sql())

    def current_sql(self):
        return self.design_sql() if self.tabs.currentIndex() == 0 else self.sql.toPlainText().strip()

    def run(self):
        sql = self.current_sql()
        if not sql:
            return
        con = self.win.db.con
        first = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        try:
            if first not in ("SELECT", "WITH", "PRAGMA", "VALUES"):
                if QMessageBox.question(self, APP_NAME, f"This is a {first} statement that changes data or the "
                                        "database design. Run it?") != QMessageBox.Yes:
                    return
                con.executescript(sql)
                con.commit()
                self.result_label.setText(f"Done ({con.total_changes} total changes this session).")
                self.win.refresh_nav()
                return
            cur = con.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(5000)
        except sqlite3.Error as ex:
            con.rollback()
            error(self, ex, "The query has a problem")
            return
        self.results.setModel(None)
        tw = _ResultModel(cols, rows)
        self.results.setModel(tw)
        self.results.resizeColumnsToContents()
        self.result_label.setText(f"{len(rows):,} row(s)" + (" (first 5,000 shown)" if len(rows) == 5000 else ""))

    def save(self):
        sql = self.current_sql()
        name, ok = QInputDialog.getText(self, "Save Query", "Query name:", QLineEdit.Normal, self.name or "")
        if not ok or not name.strip():
            return
        try:
            self.win.db.save_query(name.strip(), sql)
        except (ValueError, sqlite3.Error) as ex:
            error(self, ex, "Couldn't save the query")
            return
        self.name = name.strip()
        self.win.tabs.setTabText(self.win.tabs.indexOf(self), f"{self.name} (Query)")
        self.win.refresh_nav()
        self.win.statusBar().showMessage(f"Saved query {self.name}", 3000)


class _ResultModel(QAbstractTableModel):
    def __init__(self, cols, rows):
        super().__init__()
        self.cols, self.rows = cols, rows

    def rowCount(self, p=QModelIndex()):
        return len(self.rows)

    def columnCount(self, p=QModelIndex()):
        return len(self.cols)

    def headerData(self, s, o, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return self.cols[s] if o == Qt.Horizontal else str(s + 1)

    def data(self, idx, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            v = self.rows[idx.row()][idx.column()]
            return "" if v is None else (f"{v:,.10g}" if isinstance(v, float) else str(v))
        if role == Qt.TextAlignmentRole and isinstance(self.rows[idx.row()][idx.column()], (int, float)):
            return int(Qt.AlignRight | Qt.AlignVCenter)


class ReportTab(QWidget):
    def __init__(self, win, spec, name=None):
        super().__init__()
        self.win, self.spec, self.name = win, spec, name
        self.browser = QTextBrowser()
        bar = QHBoxLayout()
        for text, slot in (("🖨 Print…", self.print_), ("👁 Print Preview", self.preview), ("📄 Export PDF…", self.pdf),
                           ("✎ Edit Report…", self.edit), ("💾 Save Report…", self.save), ("↻ Refresh", self.render)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addStretch()
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(self.browser, 1)
        self.render()

    def render(self):
        try:
            self.html = bc.report_html(self.win.db, self.spec)
        except sqlite3.Error as ex:
            self.html = f"<p>Couldn't build the report: {ex}</p>"
        self.browser.setHtml(self.html)

    def _doc(self):
        d = QTextDocument()
        d.setHtml(self.html)
        return d

    def _layout(self):
        return QPageLayout(QPageSize(QPageSize.Letter), QPageLayout.Landscape if self.spec.get("landscape") else
                           QPageLayout.Portrait, QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)

    def print_(self):
        p = QPrinter(QPrinter.HighResolution)
        p.setPageLayout(self._layout())
        if QPrintDialog(p, self).exec():
            self._doc().print_(p)

    def preview(self):
        p = QPrinter(QPrinter.HighResolution)
        p.setPageLayout(self._layout())
        dlg = QPrintPreviewDialog(p, self)
        dlg.paintRequested.connect(lambda pr: self._doc().print_(pr))
        dlg.resize(1000, 800)
        dlg.exec()

    def pdf(self):
        f, _ = QFileDialog.getSaveFileName(self, "Export Report as PDF", (self.spec.get("title") or "Report") + ".pdf",
                                           "PDF files (*.pdf)")
        if f:
            w = QPdfWriter(f)
            w.setPageLayout(self._layout())
            w.setResolution(150)
            self._doc().print_(w)
            self.win.statusBar().showMessage(f"Exported {f}", 4000)

    def edit(self):
        dlg = ReportDialog(self.win, self.spec)
        if dlg.exec():
            self.spec = dlg.spec()
            self.render()

    def save(self):
        name, ok = QInputDialog.getText(self, "Save Report", "Report name:", QLineEdit.Normal,
                                        self.name or self.spec.get("title", ""))
        if ok and name.strip():
            self.win.db.save_report(name.strip(), self.spec)
            self.name = name.strip()
            self.win.tabs.setTabText(self.win.tabs.indexOf(self), f"{self.name} (Report)")
            self.win.refresh_nav()


class ReportDialog(QDialog):
    def __init__(self, win, spec=None):
        super().__init__(win)
        self.win = win
        spec = spec or {}
        self.setWindowTitle("Report")
        self.source = QComboBox()
        self.source.addItems(win.db.tables() + win.db.views())
        if spec.get("source"):
            self.source.setCurrentText(spec["source"])
        self.title = QLineEdit(spec.get("title", ""))
        self.fields = QListWidget()
        self.group = QComboBox()
        self.sort = QComboBox()
        self.desc = QCheckBox("Descending")
        self.desc.setChecked(spec.get("sort_desc", False))
        self.landscape = QCheckBox("Landscape (wide reports)")
        self.landscape.setChecked(spec.get("landscape", False))
        self.totals = QTableWidget(0, 2)
        self.totals.setHorizontalHeaderLabels(["Number field", "Total"])
        self.totals.horizontalHeader().setStretchLastSection(True)
        self.totals.setMaximumHeight(140)
        self.source.currentTextChanged.connect(lambda _: self._fill({}))
        form = QFormLayout(self)
        form.addRow("Show data from:", self.source)
        form.addRow("Title:", self.title)
        form.addRow("Fields (tick and drag to order):", self.fields)
        form.addRow("Group by:", self.group)
        row = QHBoxLayout()
        row.addWidget(self.sort, 1)
        row.addWidget(self.desc)
        form.addRow("Sort by:", row)
        form.addRow("Totals:", self.totals)
        form.addRow("", self.landscape)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.fields.setDragDropMode(QAbstractItemView.InternalMove)
        self.resize(560, 640)
        self._fill(spec)

    def _fill(self, spec):
        db = self.win.db
        src = self.source.currentText()
        if not src:
            return
        cols = db.columns(src)
        kinds = db.kinds(src)
        chosen = spec.get("fields") or [c for c in cols if kinds.get(c) != "AutoNumber"]
        self.fields.clear()
        for c in chosen + [c for c in cols if c not in chosen]:
            it = QListWidgetItem(c)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if c in chosen else Qt.Unchecked)
            self.fields.addItem(it)
        for cb in (self.group, self.sort):
            cb.clear()
            cb.addItem("")
            cb.addItems(cols)
        self.group.setCurrentText(spec.get("group_by", ""))
        self.sort.setCurrentText(spec.get("sort", ""))
        if not self.title.text():
            self.title.setText(src)
        self.totals.setRowCount(0)
        tot = spec.get("totals", {})
        for c in cols:
            k = kinds.get(c)
            if k in ("Whole Number", "Decimal Number", "Currency") or c in tot:
                r = self.totals.rowCount()
                self.totals.insertRow(r)
                self.totals.setItem(r, 0, QTableWidgetItem(c))
                cb = QComboBox()
                cb.addItems(["", "Sum", "Average", "Count"])
                cb.setCurrentText(tot.get(c, ""))
                self.totals.setCellWidget(r, 1, cb)

    def spec(self):
        fields = [self.fields.item(i).text() for i in range(self.fields.count())
                  if self.fields.item(i).checkState() == Qt.Checked]
        totals = {self.totals.item(r, 0).text(): self.totals.cellWidget(r, 1).currentText()
                  for r in range(self.totals.rowCount()) if self.totals.cellWidget(r, 1).currentText()}
        return dict(source=self.source.currentText(), title=self.title.text().strip(), fields=fields,
                    group_by=self.group.currentText(), sort=self.sort.currentText(), sort_desc=self.desc.isChecked(),
                    totals=totals, landscape=self.landscape.isChecked())


class RelationshipsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Relationships")
        self.resize(900, 620)
        self.diagram = Diagram(win.db)
        self.listw = QListWidget()
        self.listw.setMaximumHeight(130)
        add = QGroupBoxLike("Add a relationship (one parent record ↔ many child records)")
        g = QGridLayout(add)
        self.parent_t, self.parent_f, self.child_t, self.child_f = QComboBox(), QComboBox(), QComboBox(), QComboBox()
        tables = win.db.tables()
        self.parent_t.addItems(tables)
        self.child_t.addItems(tables)
        self.parent_t.currentTextChanged.connect(lambda t: self._fields(self.parent_f, t, pk=True))
        self.child_t.currentTextChanged.connect(lambda t: self._fields(self.child_f, t))
        self.cascade = QCheckBox("Deleting a parent also deletes its children (cascade delete)")
        g.addWidget(QLabel("Parent table (the “one”):"), 0, 0)
        g.addWidget(self.parent_t, 0, 1)
        g.addWidget(QLabel("key field:"), 0, 2)
        g.addWidget(self.parent_f, 0, 3)
        g.addWidget(QLabel("Child table (the “many”):"), 1, 0)
        g.addWidget(self.child_t, 1, 1)
        g.addWidget(QLabel("field that points to the parent:"), 1, 2)
        g.addWidget(self.child_f, 1, 3)
        g.addWidget(self.cascade, 2, 0, 1, 3)
        b = QPushButton("＋ Add Relationship")
        b.clicked.connect(self.add)
        g.addWidget(b, 2, 3)
        rm = QPushButton("✖ Remove Selected Relationship")
        rm.clicked.connect(self.remove)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.diagram, 1)
        lay.addWidget(self.listw)
        lay.addWidget(rm, alignment=Qt.AlignLeft)
        lay.addWidget(add)
        lay.addWidget(close)
        self._fields(self.parent_f, self.parent_t.currentText(), pk=True)
        self._fields(self.child_f, self.child_t.currentText())
        self.refresh()

    def _fields(self, cb, table, pk=False):
        cb.clear()
        if not table:
            return
        fields = self.win.db.fields(table)
        names = [f.name for f in fields if f.pk or f.unique] if pk else [f.name for f in fields if not f.pk]
        cb.addItems(names or [f.name for f in fields])

    def refresh(self):
        self.rels = self.win.db.relations()
        self.listw.clear()
        for r in self.rels:
            self.listw.addItem(f"{r.parent}.{r.parent_field}  1 ──── ∞  {r.child}.{r.child_field}"
                               + ("   (cascade delete)" if r.cascade_delete else ""))
        self.diagram.rels = self.rels
        self.diagram.update()

    def add(self):
        rel = bc.Relation(self.child_t.currentText(), self.child_f.currentText(), self.parent_t.currentText(),
                          self.parent_f.currentText(), self.cascade.isChecked())
        if not all([rel.child, rel.child_field, rel.parent, rel.parent_field]):
            return
        if rel.child == rel.parent:
            QMessageBox.information(self, APP_NAME, "Choose two different tables.")
            return
        try:
            self.win.close_tabs_for(rel.child)
            self.win.db.add_relation(rel)
        except (ValueError, sqlite3.Error) as ex:
            error(self, ex, "Couldn't add the relationship")
            return
        self.refresh()

    def remove(self):
        i = self.listw.currentRow()
        if i < 0:
            return
        try:
            self.win.close_tabs_for(self.rels[i].child)
            self.win.db.remove_relation(self.rels[i])
        except (ValueError, sqlite3.Error) as ex:
            error(self, ex, "Couldn't remove the relationship")
            return
        self.refresh()


def QGroupBoxLike(title):
    from PySide6.QtWidgets import QGroupBox
    return QGroupBox(title)


class Diagram(QWidget):
    """Tables as boxes with their fields; lines join related fields."""

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.rels = []
        self.setMinimumHeight(300)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#f7f4f5"))
        tables = self.db.tables()
        if not tables:
            p.drawText(self.rect(), Qt.AlignCenter, "No tables yet.")
            return
        cols = max(1, min(4, len(tables)))
        bw, gap = 190, 40
        pos, boxes = {}, {}
        f = QFont()
        f.setPointSize(9)
        p.setFont(f)
        y_off = {}
        for i, t in enumerate(tables):
            fields = self.db.fields(t)
            c, r = i % cols, i // cols
            x = 20 + c * (bw + gap)
            y = 20 + sum(y_off.get((rr, c), 0) for rr in range(r))
            h = 26 + 18 * len(fields)
            y_off[(r, c)] = h + gap
            boxes[t] = QRectF(x, y, bw, h)
            p.setPen(QPen(QColor(ACCENT), 1.5))
            p.setBrush(QColor("white"))
            p.drawRoundedRect(boxes[t], 6, 6)
            p.fillRect(QRectF(x + 1, y + 1, bw - 2, 22), QColor(ACCENT))
            p.setPen(QColor("white"))
            p.drawText(QRectF(x + 8, y, bw - 16, 24), Qt.AlignVCenter, t)
            for j, fld in enumerate(fields):
                fy = y + 26 + j * 18
                pos[(t, fld.name)] = (x, x + bw, fy + 9)
                p.setPen(QColor("#222"))
                fnt = QFont(f)
                fnt.setBold(fld.pk)
                p.setFont(fnt)
                p.drawText(QRectF(x + 10, fy, bw - 20, 18), Qt.AlignVCenter, ("🔑 " if fld.pk else "") + fld.name)
                p.setFont(f)
        p.setPen(QPen(QColor("#2b78e4"), 2))
        for r in self.rels:
            a, b = pos.get((r.parent, r.parent_field)), pos.get((r.child, r.child_field))
            if not a or not b:
                continue
            ax = a[1] if a[0] < b[0] else a[0]
            bx = b[0] if a[0] < b[0] else b[1]
            p.drawLine(QPointF(ax, a[2]), QPointF(bx, b[2]))
            p.drawText(QPointF(ax + (6 if ax == a[1] else -12), a[2] - 4), "1")
            p.drawText(QPointF(bx + (-12 if bx == b[0] else 6), b[2] - 4), "∞")


# ====================================================================== start page

class StartPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(60, 40, 60, 40)
        title = QLabel(f"<span style='font-size:30px; font-weight:600; color:{ACCENT}'>Ethical Database</span>"
                       "<br><span style='color:#666; font-size:14px'>Keep lists and records organised: contacts, "
                       "stock, orders, tasks — anything.</span>")
        lay.addWidget(title)
        lay.addSpacing(20)
        lay.addWidget(QLabel("<b>Create a new database</b>"))
        grid = QGridLayout()
        descs = {"Blank database": "Start from scratch", "Contacts": "People, phone numbers, emails, birthdays",
                 "Tasks": "To-do list with due dates and priorities", "Inventory": "Products, categories, stock levels",
                 "Customers & Orders": "Customers, products, orders with totals and a report"}
        for i, (name, d) in enumerate(descs.items()):
            b = QPushButton(name.replace("&", "&&") + "\n" + d)  # && shows a literal & on buttons
            b.setMinimumHeight(64)
            b.setStyleSheet("text-align: left; padding: 8px 14px; font-size: 13px;")
            b.clicked.connect(lambda _=False, n=name: self.win.new_database(n))
            grid.addWidget(b, i // 3, i % 3)
        lay.addLayout(grid)
        lay.addSpacing(20)
        row = QHBoxLayout()
        ob = QPushButton("📂 Open a database…")
        ob.clicked.connect(self.win.open_dialog)
        row.addWidget(ob)
        ib = QPushButton("Import from Excel / CSV / Access into a new database…")
        ib.clicked.connect(self.win.import_new)
        row.addWidget(ib)
        row.addStretch()
        lay.addLayout(row)
        lay.addSpacing(16)
        lay.addWidget(QLabel("<b>Recent</b>"))
        self.recent = QListWidget()
        self.recent.itemDoubleClicked.connect(lambda it: self.win.open_path(it.data(Qt.UserRole)))
        lay.addWidget(self.recent, 1)
        self.refresh()

    def refresh(self):
        self.recent.clear()
        for p in self.win.recent_files():
            it = QListWidgetItem(f"{os.path.basename(p)}    —    {os.path.dirname(p)}")
            it.setData(Qt.UserRole, p)
            self.recent.addItem(it)


# ====================================================================== main window

class BaseWindow(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        self.settings = QSettings(SETTINGS_ORG, APP_NAME)
        self.db = None
        self.resize(1300, 820)
        self.setAcceptDrops(True)
        self.nav = QTreeWidget()
        self.nav.setHeaderHidden(True)
        self.nav.setMinimumWidth(230)
        self.nav.itemDoubleClicked.connect(self._nav_open)
        self.nav.setContextMenuPolicy(Qt.CustomContextMenu)
        self.nav.customContextMenuRequested.connect(self._nav_menu)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.split = QSplitter()
        self.split.addWidget(self.nav)
        self.split.addWidget(self.tabs)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([240, 1060])
        self.start = StartPage(self)
        self._build_menus()
        self.show_start()
        if path:
            self.open_path(path)

    def act(self, text, slot, shortcut=None, menu=None):
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if menu is not None:
            menu.addAction(a)
        return a

    def _build_menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self.act("&New Database…", self.new_dialog, "Ctrl+N", f)
        self.act("&Open…", self.open_dialog, "Ctrl+O", f)
        self.act("Save a &Copy As…", self.save_copy, None, f)
        f.addSeparator()
        self.act("&Import (Excel, CSV, Access)…", self.import_dialog, None, f)
        self.act("&Export Table/Query…", self.export_dialog, None, f)
        f.addSeparator()
        self.act("&Close Database", self.close_database, None, f)
        self.act("E&xit", self.close, None, f)
        c = mb.addMenu("&Create")
        a_table = self.act("&Table…", lambda: self.open_design(None), "Ctrl+Shift+T", c)
        a_query = self.act("&Query…", lambda: self.open_query(None), "Ctrl+Shift+Q", c)
        a_report = self.act("&Report…", self.new_report, "Ctrl+Shift+R", c)
        a_form = self.act("&Form for Current Table", self.form_for_current, None, c)
        d = mb.addMenu("&Database")
        a_rel = self.act("&Relationships…", self.relationships, None, d)
        self.act("&SQL Console", lambda: self._sql_console(), None, d)
        self.act("&Compact && Repair", self.compact, None, d)
        h = mb.addMenu("&Help")
        add_guide_action(self, h, "base-basics")
        self.act("&About", lambda: QMessageBox.about(
            self, APP_NAME, f"<b>{APP_NAME}</b><br>Part of {SUITE_NAME}.<br><br>Databases are standard SQLite files."),
                 None, h)
        tb = QToolBar("Main")
        tb.setObjectName("main")
        self.addToolBar(tb)
        tb.addAction(self.act("New", self.new_dialog))
        tb.addAction(self.act("Open", self.open_dialog))
        tb.addSeparator()
        for a, t in ((a_table, "＋ Table"), (a_query, "＋ Query"), (a_form, "Form"), (a_report, "＋ Report"),
                     (a_rel, "Relationships")):
            a.setIconText(t)
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act("Import", self.import_dialog))
        tb.addAction(self.act("Export", self.export_dialog))
        self.db_actions = [a_table, a_query, a_report, a_form, a_rel]

    # ------------------------------------------------------------ database lifecycle
    def show_start(self):
        self.start.refresh()
        if self.centralWidget() is not self.start:
            old = self.takeCentralWidget()
            if old is not None and old is not self.start:
                old.setParent(None)
                self.split = old
            self.setCentralWidget(self.start)
        self.setWindowTitle(APP_NAME)
        for a in self.db_actions:
            a.setEnabled(False)

    def show_db(self):
        if self.centralWidget() is not self.split:
            self.takeCentralWidget()
            self.setCentralWidget(self.split)
        for a in self.db_actions:
            a.setEnabled(True)

    def recent_files(self):
        r = self.settings.value("recent") or []
        if isinstance(r, str):
            r = [r]
        return [p for p in r if os.path.exists(p)]

    def _add_recent(self, path):
        path = os.path.abspath(path)
        self.settings.setValue("recent", ([path] + [p for p in self.recent_files() if p != path])[:12])
        self.settings.setValue("last_dir", os.path.dirname(path))

    def close_database(self):
        if self.db:
            self.tabs.clear()
            self.db.close()
            self.db = None
        self.nav.clear()
        self.show_start()

    def open_path(self, path):
        if path.lower().endswith((".accdb", ".mdb")):
            self.import_new(path)
            return
        try:
            with open(path, "rb") as fh:
                head = fh.read(16)
            if head and not head.startswith(b"SQLite format 3"):
                raise ValueError("This isn't an Ethical Database / SQLite database file.")
            db = bc.Database(path)
            db.tables()
        except Exception as ex:
            QMessageBox.critical(self, APP_NAME, f"Could not open the database:\n{ex}")
            return
        self.close_database()
        self.db = db
        self._add_recent(path)
        self.setWindowTitle(f"{os.path.basename(path)} - {APP_NAME}")
        self.show_db()
        self.refresh_nav()
        tables = db.tables()
        if tables:
            self.open_datasheet(tables[0])
        self.statusBar().showMessage("Changes are saved automatically.", 5000)

    def _ask_new_path(self, suggestion):
        f, _ = QFileDialog.getSaveFileName(self, "Create Database", os.path.join(
            self.settings.value("last_dir", os.path.expanduser("~/Documents")), suggestion), DB_FILTER)
        if f and not os.path.splitext(f)[1]:
            f += ".db"
        return f

    def new_database(self, template="Blank database"):
        f = self._ask_new_path(("Database" if template == "Blank database" else template.replace(" & ", " and ")) + ".db")
        if not f:
            return
        try:
            self.close_database()
            bc.create_from_template(f, template).close()
        except Exception as ex:
            QMessageBox.critical(self, APP_NAME, f"Could not create the database:\n{ex}")
            return
        self.open_path(f)
        if template == "Blank database":
            self.open_design(None)

    def new_dialog(self):
        name, ok = QInputDialog.getItem(self, "New Database", "Start from:", list(bc.TEMPLATES), 0, False)
        if ok:
            self.new_database(name)

    def open_dialog(self):
        f, _ = QFileDialog.getOpenFileName(self, "Open Database", self.settings.value("last_dir", ""),
                                           DB_FILTER.replace("*.edb)", "*.edb *.accdb *.mdb)"))
        if f:
            self.open_path(f)

    def save_copy(self):
        if not self.db:
            return
        f = self._ask_new_path(os.path.splitext(os.path.basename(self.db.path))[0] + " (copy).db")
        if f:
            self.db.con.commit()
            dst = sqlite3.connect(f)
            self.db.con.backup(dst)
            dst.close()
            self.statusBar().showMessage(f"Saved a copy to {f}", 4000)

    def compact(self):
        if self.db:
            ok = self.db.compact()
            QMessageBox.information(self, APP_NAME, "Database checked and compacted." if ok == "ok" else
                                    f"Problems were found: {ok}")

    def closeEvent(self, e):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, FormTab) and w.dirty():
                r = QMessageBox.question(self, APP_NAME, f"Save the changed record in {w.source}?",
                                         QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
                if r == QMessageBox.Cancel or (r == QMessageBox.Save and not w.save()):
                    e.ignore()
                    return
        if self.db:
            self.db.con.commit()
            self.db.close()
        e.accept()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith((".db", ".sqlite", ".sqlite3", ".edb", ".accdb", ".mdb")):
                self.open_path(p)
            elif p.lower().endswith((".csv", ".xlsx")) and self.db:
                self.import_file(p)
            return

    # ------------------------------------------------------------ navigation pane
    def refresh_nav(self):
        self.nav.clear()
        if not self.db:
            return
        for title, items, kind in (("Tables", self.db.tables(), "table"), ("Queries", self.db.views(), "query"),
                                   ("Reports", self.db.reports(), "report")):
            top = QTreeWidgetItem([f"{title} ({len(items)})"])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            top.setForeground(0, QColor(ACCENT))
            for name in items:
                icon = {"table": "▦", "query": "⚲", "report": "📄"}[kind]
                it = QTreeWidgetItem([f"{icon}  {name}"])
                it.setData(0, Qt.UserRole, (kind, name))
                top.addChild(it)
            self.nav.addTopLevelItem(top)
            top.setExpanded(True)

    def _nav_open(self, item):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, name = data
        if kind in ("table", "query"):
            self.open_datasheet(name)
        else:
            self.open_report(name)

    def _nav_menu(self, pos):
        item = self.nav.itemAt(pos)
        m = QMenu(self)
        data = item.data(0, Qt.UserRole) if item else None
        if data:
            kind, name = data
            if kind in ("table", "query"):
                m.addAction("Open", lambda: self.open_datasheet(name))
                m.addAction("Form View", lambda: self.open_form(name))
                m.addAction("Design View" if kind == "table" else "Edit Query (SQL)",
                            lambda: self.open_design(name) if kind == "table" else self.open_query(name))
                m.addAction("New Report from This…", lambda: self.new_report(name))
                m.addAction("Export…", lambda: self.export_dialog(name))
                m.addSeparator()
                m.addAction("Rename…", lambda: self.rename(name))
                m.addAction("Delete", lambda: self.delete(kind, name))
            else:
                m.addAction("Open", lambda: self.open_report(name))
                m.addAction("Delete", lambda: self.delete(kind, name))
        if self.db:
            m.addSeparator()
            m.addAction("New Table…", lambda: self.open_design(None))
            m.addAction("New Query…", lambda: self.open_query(None))
            m.addAction("New Report…", lambda: self.new_report())
        m.exec(self.nav.viewport().mapToGlobal(pos))

    def rename(self, name):
        new, ok = QInputDialog.getText(self, "Rename", "New name:", QLineEdit.Normal, name)
        new = new.strip()
        if not ok or not new or new == name:
            return
        try:
            self.close_tabs_for(name)
            self.db.rename_object(name, new)
            if not self.db.is_view(new):
                self.db._fix_views(name, new, {})
        except sqlite3.Error as ex:
            error(self, ex, "Couldn't rename")
        self.refresh_nav()

    def delete(self, kind, name):
        what = {"table": "table and all its records", "query": "query", "report": "report"}[kind]
        if QMessageBox.question(self, APP_NAME, f"Delete the {what} “{name}”? This can't be undone.") != QMessageBox.Yes:
            return
        try:
            self.close_tabs_for(name)
            if kind == "report":
                self.db.delete_report(name)
            else:
                self.db.drop(name)
        except sqlite3.Error as ex:
            error(self, ex, "Couldn't delete")
        self.refresh_nav()

    # ------------------------------------------------------------ tabs
    def _tab(self, widget, title, key):
        for i in range(self.tabs.count()):
            if getattr(self.tabs.widget(i), "_key", None) == key:
                self.tabs.setCurrentIndex(i)
                return self.tabs.widget(i)
        widget._key = key
        self.tabs.addTab(widget, title)
        self.tabs.setCurrentWidget(widget)
        return widget

    def close_tab(self, i):
        w = self.tabs.widget(i)
        if isinstance(w, FormTab) and w.dirty():
            r = QMessageBox.question(self, APP_NAME, "Save the changed record?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel or (r == QMessageBox.Save and not w.save()):
                return
        self.tabs.removeTab(i)
        w.deleteLater()

    def close_tabs_for(self, name, keep=None):
        for i in reversed(range(self.tabs.count())):
            w = self.tabs.widget(i)
            if w is not keep and getattr(w, "source", getattr(w, "table", None)) == name:
                self.tabs.removeTab(i)
                w.deleteLater()

    def open_datasheet(self, name):
        try:
            self._tab(DatasheetTab(self, name), name, ("sheet", name))
        except sqlite3.Error as ex:
            error(self, ex, f"Couldn't open {name}")

    def open_form(self, name, row=0):
        for i in reversed(range(self.tabs.count())):
            if getattr(self.tabs.widget(i), "_key", None) == ("form", name):
                self.tabs.removeTab(i)
        self._tab(FormTab(self, name, row), f"{name} (Form)", ("form", name))

    def form_for_current(self):
        w = self.tabs.currentWidget()
        src = getattr(w, "source", None)
        if src:
            self.open_form(src)
        elif self.db and self.db.tables():
            name, ok = QInputDialog.getItem(self, "Form", "Form for:", self.db.tables() + self.db.views(), 0, False)
            if ok:
                self.open_form(name)

    def open_design(self, table):
        self._tab(DesignTab(self, table), f"{table} (Design)" if table else "New Table", ("design", table or object()))

    def open_query(self, name):
        if not self.db.tables():
            QMessageBox.information(self, APP_NAME, "Create a table first.")
            return
        self._tab(QueryTab(self, name), f"{name} (Query)" if name else "New Query", ("query", name or object()))

    def _sql_console(self):
        if not self.db:
            return
        t = self._tab(QueryTab(self, None), "SQL Console", ("query", object()))
        t.tabs.setCurrentIndex(1)

    def open_report(self, name):
        spec = self.db.report(name)
        if spec:
            self._tab(ReportTab(self, spec, name), f"{name} (Report)", ("report", name))

    def new_report(self, source=None):
        if not self.db or not (self.db.tables() or self.db.views()):
            return
        dlg = ReportDialog(self, {"source": source} if source else None)
        if dlg.exec():
            spec = dlg.spec()
            self._tab(ReportTab(self, spec), f"{spec['title'] or spec['source']} (Report)", ("report", object()))

    def relationships(self):
        if self.db:
            RelationshipsDialog(self).exec()
            self.refresh_nav()

    # ------------------------------------------------------------ import / export
    def import_dialog(self):
        if not self.db:
            self.import_new()
            return
        f, _ = QFileDialog.getOpenFileName(self, "Import", self.settings.value("last_dir", ""),
                                           "Data files (*.csv *.txt *.xlsx *.accdb *.mdb);;All files (*)")
        if f:
            self.import_file(f)

    def import_new(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Import into a new database", self.settings.value("last_dir", ""),
                                                  "Data files (*.csv *.txt *.xlsx *.accdb *.mdb)")
        if not path:
            return
        dst = self._ask_new_path(os.path.splitext(os.path.basename(path))[0] + ".db")
        if not dst:
            return
        self.close_database()
        if os.path.exists(dst):
            os.remove(dst)
        bc.Database(dst).close()
        self.open_path(dst)
        self.import_file(path)

    def import_file(self, path):
        low = path.lower()
        try:
            if low.endswith((".csv", ".txt")):
                sources = {os.path.splitext(os.path.basename(path))[0]: bc.read_csv(path)}
            elif low.endswith(".xlsx"):
                sources = bc.read_xlsx(path)
            elif low.endswith((".accdb", ".mdb")):
                sources = bc.read_access(path)
            else:
                raise ValueError("Unsupported file type.")
        except Exception as ex:
            QMessageBox.warning(self, APP_NAME, f"Couldn't read the file:\n{ex}")
            return
        if not sources:
            QMessageBox.information(self, APP_NAME, "No data found in that file.")
            return
        names = list(sources)
        if len(names) > 1:
            dlg = QDialog(self)
            dlg.setWindowTitle("Choose what to import")
            lw = QListWidget()
            for n in names:
                it = QListWidgetItem(f"{n}  ({len(sources[n][1])} rows)")
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked)
                it.setData(Qt.UserRole, n)
                lw.addItem(it)
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            lay = QVBoxLayout(dlg)
            lay.addWidget(QLabel("Each one becomes a table:"))
            lay.addWidget(lw)
            lay.addWidget(bb)
            if not dlg.exec():
                return
            names = [lw.item(i).data(Qt.UserRole) for i in range(lw.count()) if lw.item(i).checkState() == Qt.Checked]
        done = []
        for n in names:
            header, rows = sources[n]
            table = n
            k = 2
            while table in self.db.tables() or table in self.db.views():
                table = f"{n} {k}"
                k += 1
            try:
                cnt = bc.import_rows(self.db, table, header, rows)
                done.append(f"{table}: {cnt:,} records")
            except Exception as ex:
                error(self, ex, f"Couldn't import {n}")
        self.refresh_nav()
        if done:
            self.open_datasheet(done[0].split(":")[0])
            QMessageBox.information(self, APP_NAME, "Imported:\n" + "\n".join(done) +
                                    "\n\nTip: check the field types in Design View.")

    def export_dialog(self, name=None):
        if not self.db:
            return
        if not name:
            w = self.tabs.currentWidget()
            name = getattr(w, "source", None)
        objs = self.db.tables() + self.db.views()
        if not objs:
            return
        if not name:
            name, ok = QInputDialog.getItem(self, "Export", "What to export:", objs, 0, False)
            if not ok:
                return
        f, flt = QFileDialog.getSaveFileName(self, f"Export {name}", os.path.join(
            self.settings.value("last_dir", ""), name), "Excel workbook (*.xlsx);;Excel - all tables & queries (*.xlsx);;"
            "CSV (*.csv);;PDF report (*.pdf)")
        if not f:
            return
        try:
            if flt.startswith("CSV") or f.lower().endswith(".csv"):
                f = f if f.lower().endswith(".csv") else f + ".csv"
                n = bc.export_csv(self.db, name, f)
            elif flt.startswith("PDF") or f.lower().endswith(".pdf"):
                f = f if f.lower().endswith(".pdf") else f + ".pdf"
                doc = QTextDocument()
                doc.setHtml(bc.report_html(self.db, {"source": name, "title": name}))
                w = QPdfWriter(f)
                w.setPageLayout(QPageLayout(QPageSize(QPageSize.Letter), QPageLayout.Landscape,
                                            QMarginsF(12, 12, 12, 12), QPageLayout.Millimeter))
                doc.print_(w)
                n = self.db.count(name)
            else:
                f = f if f.lower().endswith(".xlsx") else f + ".xlsx"
                srcs = objs if "all tables" in flt else [name]
                bc.export_xlsx(self.db, srcs, f)
                n = sum(self.db.count(s) for s in srcs)
        except Exception as ex:
            error(self, ex, "Export failed")
            return
        self.statusBar().showMessage(f"Exported {n:,} record(s) to {f}", 5000)


def main():
    app = make_app(APP_NAME, sys.argv)
    win = BaseWindow(sys.argv[1] if len(sys.argv) > 1 else None)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
