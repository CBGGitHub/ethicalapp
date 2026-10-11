"""Ethical Planner - reminders and a calendar that pop up on time.

Repeating reminders ("take supplements every day at 8:00"), events with a heads-up before they start, a month
calendar and an agenda list. When something is due, a card pops up in the bottom-right corner with Done and
Snooze (it works even with Windows' Focus Assist on). Planner keeps running in the tray so reminders always
arrive; it can start with Windows. Anything missed while the PC was off pops up (marked "missed") next start.
Everything is stored on this PC (planner_core.py) - nothing is uploaded.

Run: .venv\\Scripts\\pythonw apps\\planner_app.py  [--new] [--startup]
"""
import os
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PySide6.QtCore import QDate, QPoint, QSettings, QSize, Qt, QTime, QTimer  # noqa: E402
from PySide6.QtGui import QAction, QActionGroup, QBrush, QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap, QShortcut, QTextCharFormat  # noqa: E402
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCalendarWidget, QCheckBox, QComboBox, QDateEdit,  # noqa: E402
                               QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QSpinBox, QSplitter, QSystemTrayIcon,
                               QTimeEdit, QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import planner_core as core  # noqa: E402
from suite_common import icon_path, launch_command, make_app, open_guide  # noqa: E402

APP_NAME = "Ethical Planner"
SERVER_NAME = "EthicalPlanner-" + os.environ.get("USERNAME", "user")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "EthicalSuite.Planner"
ALERTS = [(None, "No alert"), (0, "At the time"), (5, "5 minutes before"), (10, "10 minutes before"),
          (15, "15 minutes before"), (30, "30 minutes before"), (60, "1 hour before"), (120, "2 hours before"),
          (1440, "1 day before"), (2880, "2 days before"), (10080, "1 week before")]
DURATIONS = [(15, "15 minutes"), (30, "30 minutes"), (45, "45 minutes"), (60, "1 hour"), (90, "1½ hours"),
             (120, "2 hours"), (180, "3 hours"), (240, "4 hours"), (480, "8 hours")]
SNOOZES = [(5, "5 minutes"), (10, "10 minutes"), (30, "30 minutes"), (60, "1 hour"), (180, "3 hours"), (-1, "Tomorrow morning")]
PRESETS = [  # label, fields
    ("💊 Daily supplements", dict(kind="reminder", title="Take supplements", time="08:00", repeat="daily", color="green")),
    ("💧 Drink water", dict(kind="reminder", title="Drink a glass of water", time="11:00", repeat="daily", color="teal")),
    ("🗑 Bins out", dict(kind="reminder", title="Put the bins out", time="19:00", repeat="weekly", color="gray")),
    ("🎂 Birthday", dict(kind="event", title="'s birthday", all_day=True, repeat="yearly", color="purple", alerts=[1440, 0])),
]


def settings():
    return QSettings("Ethical Suite", "Ethical Planner")


def qdate(d):
    return QDate(d.year, d.month, d.day)


def use_12h():
    """12-hour clock (8:00 PM) or 24-hour (20:00): the user's choice in ⋯ → Clock, else what Windows uses."""
    v = settings().value("clock", "")
    if v in ("12", "24"):
        return v == "12"
    from PySide6.QtCore import QLocale
    return "ap" in QLocale.system().timeFormat(QLocale.ShortFormat).lower()


def time_text(dt):
    if use_12h():
        return dt.strftime("%I:%M %p").lstrip("0")
    return dt.strftime("%H:%M")


SOUND = os.path.join(os.path.dirname(HERE), "branding", "sounds", "reminder.wav")


def play_chime():
    """Our own chime (Windows' notification sound is often set to silent)."""
    try:
        import winsound
        if os.path.exists(SOUND):
            winsound.PlaySound(SOUND, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        else:
            winsound.PlaySound("SystemNotification", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:
        QApplication.beep()


def when_text(item, occ):
    if item.get("all_day"):
        return "All day"
    if item.get("kind") == "event" and item.get("duration"):
        return f"{time_text(occ)}–{time_text(occ + timedelta(minutes=int(item['duration'])))}"
    return time_text(occ)


def day_title(d):
    today = date.today()
    if d == today:
        prefix = "Today"
    elif d == today + timedelta(days=1):
        prefix = "Tomorrow"
    elif d == today - timedelta(days=1):
        prefix = "Yesterday"
    else:
        prefix = d.strftime("%A")
    return f"{prefix}, {d.strftime('%d %B').lstrip('0')}" + (f" {d.year}" if d.year != today.year else "")


def dot_icon(color, done=False):
    pm = QPixmap(14, 14)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(core.COLORS.get(color, color or "#3F51B5"))
    if done:
        c.setAlpha(90)
    p.setBrush(c)
    p.setPen(Qt.NoPen)
    p.drawEllipse(2, 2, 10, 10)
    p.end()
    return QIcon(pm)


# ====================================================================== add / edit dialog

class ItemDialog(QDialog):
    def __init__(self, parent, item=None, kind="reminder", on_date=None):
        super().__init__(parent)
        self.item = dict(item) if item else core.new_item(kind=kind)
        self.deleted = False
        editing = item is not None
        self.setWindowTitle(("Edit " if editing else "New ") + self.item["kind"])
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)

        kinds = QHBoxLayout()
        self.kind_group = QButtonGroup(self)
        for k, label in (("reminder", "⏰  Reminder"), ("event", "📅  Event")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(self.item["kind"] == k)
            b.setProperty("kind", k)
            self.kind_group.addButton(b)
            kinds.addWidget(b)
        self.kind_group.buttonClicked.connect(lambda _b: self._kind_changed())
        lay.addLayout(kinds)

        if not editing:
            pre = QHBoxLayout()
            pre.addWidget(QLabel("Quick start:"))
            for label, fields in PRESETS:
                b = QToolButton()
                b.setText(label)
                b.setAutoRaise(True)
                b.clicked.connect(lambda _=False, f=fields: self._preset(f))
                pre.addWidget(b)
            pre.addStretch(1)
            lay.addLayout(pre)

        form = QFormLayout()
        self.title = QLineEdit(self.item["title"])
        self.title.setPlaceholderText("e.g. Take supplements")
        form.addRow("What", self.title)

        start = core.parse_dt(self.item["start"])
        if not editing:
            d = on_date or date.today()
            t = (datetime.now() + timedelta(hours=1)).replace(minute=0)
            start = datetime.combine(d, t.time())
        row = QHBoxLayout()
        self.date = QDateEdit(qdate(start.date()))
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("ddd d MMM yyyy")
        self.time = QTimeEdit(QTime(start.hour, start.minute))
        self.time.setDisplayFormat("h:mm AP" if use_12h() else "HH:mm")
        self.all_day = QCheckBox("All day")
        self.all_day.setChecked(bool(self.item.get("all_day")))
        self.all_day.toggled.connect(self._refresh)
        row.addWidget(self.date)
        row.addWidget(self.time)
        row.addWidget(self.all_day)
        row.addStretch(1)
        form.addRow("When", row)

        self.duration = QComboBox()
        for m, label in DURATIONS:
            self.duration.addItem(label, m)
        self._select(self.duration, int(self.item.get("duration") or 60))
        self.duration_label = QLabel("Lasts")
        form.addRow(self.duration_label, self.duration)

        self.repeat = QComboBox()
        for k, label in core.REPEATS.items():
            self.repeat.addItem(label, k)
        self._select(self.repeat, self.item.get("repeat", "none"))
        self.repeat.currentIndexChanged.connect(self._refresh)
        form.addRow("Repeat", self.repeat)

        self.every_row = QWidget()
        er = QHBoxLayout(self.every_row)
        er.setContentsMargins(0, 0, 0, 0)
        er.addWidget(QLabel("every"))
        self.interval = QSpinBox()
        self.interval.setRange(1, 365)
        self.interval.setValue(int(self.item.get("interval") or 1))
        self.interval.valueChanged.connect(self._refresh)
        er.addWidget(self.interval)
        self.unit = QLabel("days")
        er.addWidget(self.unit)
        er.addStretch(1)
        form.addRow("", self.every_row)

        self.days_row = QWidget()
        dr = QHBoxLayout(self.days_row)
        dr.setContentsMargins(0, 0, 0, 0)
        self.day_boxes = []
        days = self.item.get("days") or [start.weekday()]
        for i, name in enumerate(core.DAY_NAMES):
            cb = QCheckBox(name)
            cb.setChecked(i in days)
            dr.addWidget(cb)
            self.day_boxes.append(cb)
        form.addRow("on", self.days_row)

        until_row = QHBoxLayout()
        self.until_on = QCheckBox("Stop repeating after")
        self.until = QDateEdit(qdate(date.fromisoformat(self.item["until"])) if self.item.get("until")
                               else qdate(date.today() + timedelta(days=90)))
        self.until.setCalendarPopup(True)
        self.until_on.setChecked(bool(self.item.get("until")))
        self.until_on.toggled.connect(self._refresh)
        until_row.addWidget(self.until_on)
        until_row.addWidget(self.until)
        until_row.addStretch(1)
        self.until_widget = QWidget()
        self.until_widget.setLayout(until_row)
        until_row.setContentsMargins(0, 0, 0, 0)
        form.addRow("", self.until_widget)

        alerts = list(self.item.get("alerts") or [])
        self.alert1 = QComboBox()
        self.alert2 = QComboBox()
        for m, label in ALERTS:
            self.alert1.addItem(label, m)
            self.alert2.addItem(label if m is not None else "No second alert", m)
        self._select(self.alert1, alerts[0] if alerts else None)
        self._select(self.alert2, alerts[1] if len(alerts) > 1 else None)
        form.addRow("Alert", self.alert1)
        form.addRow("Also", self.alert2)

        self.color = QComboBox()
        for name, hexc in core.COLORS.items():
            self.color.addItem(dot_icon(name), name.title(), name)
        self._select(self.color, self.item.get("color", "blue"))
        form.addRow("Colour", self.color)

        self.notes = QPlainTextEdit(self.item.get("notes", ""))
        self.notes.setPlaceholderText("Notes (optional)")
        self.notes.setMaximumHeight(70)
        form.addRow("Notes", self.notes)
        lay.addLayout(form)

        buttons = QHBoxLayout()
        if editing:
            delete = QPushButton("Delete")
            delete.clicked.connect(self._delete)
            buttons.addWidget(delete)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        lay.addLayout(buttons)
        self._refresh()
        self.title.setFocus()

    @staticmethod
    def _select(combo, value):
        i = combo.findData(value)
        combo.setCurrentIndex(max(0, i))

    def _kind(self):
        b = self.kind_group.checkedButton()
        return b.property("kind") if b else "reminder"

    def _kind_changed(self):
        k = self._kind()
        self.item["kind"] = k
        self.setWindowTitle(("Edit " if self.item.get("title") else "New ") + k)
        if self.alert1.currentData() in (0, 15):
            self._select(self.alert1, 0 if k == "reminder" else 15)
        self._refresh()

    def _preset(self, f):
        for b in self.kind_group.buttons():
            b.setChecked(b.property("kind") == f["kind"])
        self.item["kind"] = f["kind"]
        self.title.setText(f["title"])
        if "time" in f:
            h, m = map(int, f["time"].split(":"))
            self.time.setTime(QTime(h, m))
            if datetime.combine(self.date.date().toPython(), self.time.time().toPython()) < datetime.now():
                self.date.setDate(self.date.date().addDays(1))
        self.all_day.setChecked(bool(f.get("all_day")))
        self._select(self.repeat, f["repeat"])
        self._select(self.color, f["color"])
        alerts = f.get("alerts", [0])
        self._select(self.alert1, alerts[0])
        self._select(self.alert2, alerts[1] if len(alerts) > 1 else None)
        if f["title"].startswith("'"):
            self.title.setFocus()
            self.title.setCursorPosition(0)
        self._refresh()

    def _refresh(self):
        rep = self.repeat.currentData()
        event = self._kind() == "event"
        self.time.setEnabled(not self.all_day.isChecked())
        self.duration.setVisible(event and not self.all_day.isChecked())
        self.duration_label.setVisible(event and not self.all_day.isChecked())
        self.every_row.setVisible(rep in ("daily", "weekly", "monthly", "yearly"))
        n = self.interval.value()
        self.unit.setText({"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}.get(rep, "") +
                          ("s" if n > 1 else ""))
        self.days_row.setVisible(rep == "weekly")
        self.until_widget.setVisible(rep != "none")
        self.until.setEnabled(self.until_on.isChecked())

    def _save(self):
        title = self.title.text().strip()
        if not title or title.startswith("'"):
            QMessageBox.information(self, APP_NAME, "Please type what the reminder or event is.")
            self.title.setFocus()
            return
        d = self.date.date().toPython()
        t = self.time.time().toPython() if not self.all_day.isChecked() else datetime.min.time()
        rep = self.repeat.currentData()
        days = [i for i, cb in enumerate(self.day_boxes) if cb.isChecked()]
        if rep == "weekly" and not days:
            days = [d.weekday()]
        alerts = [a for a in (self.alert1.currentData(), self.alert2.currentData()) if a is not None]
        self.item.update(kind=self._kind(), title=title, start=core.fmt_dt(datetime.combine(d, t)),
                         all_day=self.all_day.isChecked(), duration=self.duration.currentData() if self._kind() == "event" else 0,
                         repeat=rep, interval=self.interval.value() if rep in ("daily", "weekly", "monthly", "yearly") else 1,
                         days=days if rep == "weekly" else [], alerts=sorted(set(alerts), reverse=True),
                         until=self.until.date().toPython().isoformat() if rep != "none" and self.until_on.isChecked() else None,
                         color=self.color.currentData(), notes=self.notes.toPlainText().strip())
        self.accept()

    def _delete(self):
        rep = self.item.get("repeat", "none") != "none"
        if QMessageBox.question(self, APP_NAME, "Delete this" + (" and all its repeats?" if rep else "?")) == QMessageBox.Yes:
            self.deleted = True
            self.accept()


# ====================================================================== the pop-up card

class ReminderPopup(QWidget):
    def __init__(self, ctl, item, occ, minutes, missed=False):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.ctl, self.item, self.occ, self.minutes = ctl, item, occ, minutes
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedWidth(360)
        color = core.COLORS.get(item.get("color"), "#3F51B5")
        self.setStyleSheet(f"""
            ReminderPopup {{ background: #FFFFFF; border: 1px solid #C9CDD3; border-left: 6px solid {color}; border-radius: 8px; }}
            QLabel {{ color: #1F2328; background: transparent; }}
            QLabel#sub {{ color: #5B6370; }}
            QPushButton {{ padding: 6px 12px; border-radius: 6px; border: 1px solid #C9CDD3; background: #F6F7F9; color: #1F2328; }}
            QPushButton:hover {{ background: #ECEEF1; }}
            QPushButton#main {{ background: {color}; color: white; border: none; font-weight: 600; }}
            QToolButton {{ border: none; color: #5B6370; font-size: 14px; }}""")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 12, 12)
        top = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(QIcon(icon_path("planner")).pixmap(20, 20))
        top.addWidget(icon)
        app_label = QLabel("Ethical Planner" + ("  ·  missed" if missed else ""))
        app_label.setObjectName("sub")
        top.addWidget(app_label, 1)
        x = QToolButton()
        x.setText("✕")
        x.setToolTip("Dismiss")
        x.clicked.connect(self.close)
        top.addWidget(x)
        lay.addLayout(top)
        title = QLabel(item["title"])
        f = title.font()
        f.setPointSize(f.pointSize() + 3)
        f.setBold(True)
        title.setFont(f)
        title.setWordWrap(True)
        lay.addWidget(title)
        sub = QLabel(self._subtitle(missed))
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        if item.get("notes"):
            n = QLabel(item["notes"])
            n.setWordWrap(True)
            lay.addWidget(n)
        row = QHBoxLayout()
        main = QPushButton("✓  Done" if item["kind"] == "reminder" else "OK")
        main.setObjectName("main")
        main.clicked.connect(self._done)
        row.addWidget(main)
        snooze = QPushButton("Snooze")
        sm = QMenu(snooze)
        for m, label in SNOOZES:
            sm.addAction(label, lambda mm=m: self._snooze(mm))
        snooze.setMenu(sm)
        row.addWidget(snooze)
        row.addStretch(1)
        lay.addLayout(row)

    def _subtitle(self, missed):
        occ = self.occ
        when = "All day" if self.item.get("all_day") else time_text(occ)
        d = occ.date()
        day = "" if d == date.today() else ("tomorrow " if d == date.today() + timedelta(days=1) else d.strftime("%a %d %b "))
        if missed:
            return f"Was due {day}{when}"
        if self.minutes and self.item["kind"] == "event":
            return f"Starts {day}at {when} ({core.describe_alert(self.minutes).replace(' before', '')} from now)" \
                if not self.item.get("all_day") else f"{day.strip().title() or 'Today'} – all day"
        rep = core.describe_repeat(self.item)
        return f"{day}{when}" + (f"  ·  {rep}" if rep else "")

    def _done(self):
        if self.item["kind"] == "reminder":
            self.ctl.set_done(self.item["id"], self.occ, True)
        self.close()

    def _snooze(self, minutes):
        self.ctl.snooze(self.item, self.occ, self.minutes, minutes)
        self.close()

    def closeEvent(self, e):
        self.ctl.popup_closed(self)
        super().closeEvent(e)


# ====================================================================== main window

class PlannerWindow(QMainWindow):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(icon_path("planner")))
        self.resize(980, 640)
        tb = QToolBar("Planner")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(tb)
        tb.addAction("⏰  New reminder", lambda: self.edit(None, "reminder")).setToolTip("New reminder (Ctrl+N)")
        tb.addAction("📅  New event", lambda: self.edit(None, "event")).setToolTip("New event (Ctrl+E)")
        tb.addSeparator()
        tb.addAction("Today", self.go_today).setToolTip("Jump to today (Ctrl+T)")
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        more = QToolButton()
        more.setText("⋯")
        more.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(self)
        self.autostart_action = m.addAction("Start when Windows starts (so reminders always pop up)")
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(autostart_enabled())
        self.autostart_action.triggered.connect(self.ctl.set_autostart)
        self.sound_action = m.addAction("Play a sound with reminders")
        self.sound_action.setCheckable(True)
        self.sound_action.setChecked(settings().value("sound", True) in (True, "true"))
        self.sound_action.triggered.connect(lambda on: settings().setValue("sound", on))
        clock = m.addMenu("Clock")
        grp = QActionGroup(clock)
        for key, label in (("12", "12-hour (8:00 PM)"), ("24", "24-hour (20:00)")):
            a = clock.addAction(label)
            a.setCheckable(True)
            a.setChecked(use_12h() == (key == "12"))
            a.triggered.connect(lambda _=False, k=key: self._set_clock(k))
            grp.addAction(a)
        m.addAction("Test a reminder pop-up (with sound)", self.ctl.test_popup)
        m.addSeparator()
        m.addAction("Help\tF1", lambda: open_guide("planner"))
        m.addAction("Quit Ethical Planner", self.ctl.quit)
        more.setMenu(m)
        tb.addWidget(more)

        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(10, 10, 4, 10)
        self.cal = QCalendarWidget()
        self.cal.setGridVisible(False)
        self.cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.cal.selectionChanged.connect(self.refresh_agenda)
        self.cal.currentPageChanged.connect(lambda *_: self.mark_calendar())
        self.cal.activated.connect(lambda d: self.edit(None, "event", d.toPython()))
        ll.addWidget(self.cal)
        self.next_label = QLabel()
        self.next_label.setWordWrap(True)
        self.next_label.setStyleSheet("padding: 8px; background: palette(alternate-base); border-radius: 6px;")
        ll.addWidget(self.next_label)
        ll.addStretch(1)
        hint = QLabel("Reminders pop up even when this window is closed – Planner keeps running in the tray "
                      "(bottom-right of the taskbar).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        ll.addWidget(hint)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 10, 10, 10)
        self.heading = QLabel()
        hf = self.heading.font()
        hf.setPointSize(hf.pointSize() + 4)
        hf.setBold(True)
        self.heading.setFont(hf)
        rl.addWidget(self.heading)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(3)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(False)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.row_menu)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._edit_row(it))
        self.tree.itemChanged.connect(self._row_checked)
        self.tree.setStyleSheet("QTreeWidget { border: none; font-size: 14px; } QTreeWidget::item { padding: 5px 2px; }")
        rl.addWidget(self.tree, 1)
        split.addWidget(right)
        split.setSizes([330, 650])
        self.setCentralWidget(split)

        for keys, fn in (("Ctrl+N", lambda: self.edit(None, "reminder")), ("Ctrl+E", lambda: self.edit(None, "event")),
                         ("Ctrl+T", self.go_today), ("F1", lambda: open_guide("planner")),
                         ("Delete", self._delete_current)):
            QShortcut(QKeySequence(keys), self, fn)
        self._filling = False
        self.refresh()

    def _set_clock(self, key):
        settings().setValue("clock", key)
        self.refresh()
        self.ctl.update_tooltip()

    # ---- data -> view
    def refresh(self):
        self.mark_calendar()
        self.refresh_agenda()
        self.refresh_next()

    def mark_calendar(self):
        self.cal.setDateTextFormat(QDate(), QTextCharFormat())
        y, m = self.cal.yearShown(), self.cal.monthShown()
        start = datetime(y, m, 1) - timedelta(days=7)
        end = start + timedelta(days=50)
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Bold)
        fmt.setForeground(QColor("#3F51B5"))
        # mark days with something special - not the every-day reminders (they'd make every day bold)
        special = [it for it in self.ctl.items if it.get("repeat") not in ("daily", "weekdays") or it["kind"] == "event"]
        for occ, it in core.agenda(special, start, end):
            self.cal.setDateTextFormat(qdate(occ.date()), fmt)
        tf = QTextCharFormat(fmt)
        tf.setBackground(QColor(63, 81, 181, 40))
        today_items = any(o.date() == date.today() for o, _ in core.agenda(special, start, end))
        if not today_items:
            tf.setForeground(QBrush())
            tf.setFontWeight(QFont.Normal)
        self.cal.setDateTextFormat(QDate.currentDate(), tf)

    def refresh_agenda(self):
        first = self.cal.selectedDate().toPython()
        self.heading.setText(day_title(first) if first != date.today() else "Today and coming up")
        start = datetime.combine(first, datetime.min.time())
        end = start + timedelta(days=7)
        rows = core.agenda(self.ctl.items, start, end)
        self._filling = True
        self.tree.clear()
        cur_day = None
        now = datetime.now()
        bold = QFont()
        bold.setBold(True)
        for occ, it in rows:
            if occ.date() != cur_day:
                cur_day = occ.date()
                head = QTreeWidgetItem([day_title(cur_day), "", ""])
                head.setFirstColumnSpanned(True)
                head.setFlags(Qt.ItemIsEnabled)
                head.setFont(0, bold)
                head.setForeground(0, QColor("#3F51B5") if cur_day == date.today() else QColor("#5B6370"))
                self.tree.addTopLevelItem(head)
                head.setFirstColumnSpanned(True)
            done = core.is_done(it, occ)
            row = QTreeWidgetItem(["   " + when_text(it, occ), it["title"], core.describe_repeat(it)])
            row.setData(0, Qt.UserRole, (it["id"], occ.isoformat()))
            row.setIcon(1, dot_icon(it.get("color"), done))
            if it["kind"] == "reminder":
                row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
                row.setCheckState(0, Qt.Checked if done else Qt.Unchecked)
            f = QFont()
            if done:
                f.setStrikeOut(True)
                for c in range(3):
                    row.setForeground(c, QColor("#9AA0A6"))
            elif it["kind"] == "reminder" and occ < now and not it.get("all_day"):
                row.setForeground(0, QColor("#C62828"))
                row.setToolTip(0, "Not done yet")
            row.setFont(1, f)
            row.setForeground(2, QColor("#80868B"))
            tip = it.get("notes") or ""
            if tip:
                row.setToolTip(1, tip)
            self.tree.addTopLevelItem(row)
        if not rows:
            empty = QTreeWidgetItem(["   Nothing planned this week. Click “⏰ New reminder” – for example "
                                     "“Take supplements, every day at 8:00”.", "", ""])
            empty.setFlags(Qt.ItemIsEnabled)
            empty.setForeground(0, QColor("#80868B"))
            self.tree.addTopLevelItem(empty)
            empty.setFirstColumnSpanned(True)
        for c in range(3):
            self.tree.resizeColumnToContents(c)
        self._filling = False

    def refresh_next(self):
        nxt = self.ctl.next_alert()
        if nxt:
            at, it, occ = nxt
            when = "today" if at.date() == date.today() else ("tomorrow" if at.date() == date.today() + timedelta(days=1)
                                                               else at.strftime("%a %d %b"))
            self.next_label.setText(f"<b>Next up</b><br>{it['title']}<br><span style='color:#5B6370'>{when} at {time_text(at)}</span>")
        else:
            self.next_label.setText("<b>Next up</b><br><span style='color:#5B6370'>Nothing in the next week.</span>")

    # ---- actions
    def go_today(self):
        self.cal.setSelectedDate(QDate.currentDate())
        self.cal.showToday()

    def edit(self, item=None, kind="reminder", on_date=None):
        if on_date is None and item is None:
            sel = self.cal.selectedDate().toPython()
            on_date = sel if sel >= date.today() else date.today()
        d = ItemDialog(self, item, kind, on_date)
        if d.exec() != QDialog.Accepted:
            return
        if d.deleted:
            self.ctl.delete(d.item["id"])
        else:
            self.ctl.save(d.item)

    def _row(self, it):
        data = it.data(0, Qt.UserRole) if it else None
        if not data:
            return None, None
        item = next((x for x in self.ctl.items if x["id"] == data[0]), None)
        return item, datetime.fromisoformat(data[1])

    def _edit_row(self, row):
        item, _ = self._row(row)
        if item:
            self.edit(item)

    def _row_checked(self, row, col):
        if self._filling or col != 0:
            return
        item, occ = self._row(row)
        if item:
            self.ctl.set_done(item["id"], occ, row.checkState(0) == Qt.Checked)

    def _delete_current(self):
        item, _ = self._row(self.tree.currentItem())
        if item and QMessageBox.question(self, APP_NAME, f"Delete “{item['title']}”" +
                                         (" and all its repeats?" if item.get("repeat") != "none" else "?")) == QMessageBox.Yes:
            self.ctl.delete(item["id"])

    def row_menu(self, pos):
        row = self.tree.itemAt(pos)
        item, occ = self._row(row)
        if not item:
            return
        m = QMenu(self)
        m.addAction("Edit…", lambda: self.edit(item))
        if item["kind"] == "reminder":
            done = core.is_done(item, occ)
            m.addAction("Not done" if done else "Mark done", lambda: self.ctl.set_done(item["id"], occ, not done))
        if item.get("repeat") != "none":
            m.addAction("Skip just this one", lambda: self.ctl.skip(item["id"], occ))
        m.addSeparator()
        m.addAction("Delete…", self._delete_current)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def closeEvent(self, e):
        e.ignore()
        self.hide()
        self.ctl.tray_tip()


# ====================================================================== controller: data, alerts, tray

class PlannerApp:
    def __init__(self, app):
        self.app = app
        self.items = core.load()["items"]
        self.state = core.load_state()
        self.last_mtime = core.file_mtime()
        self.popups = []
        self.tray = None
        self.window = PlannerWindow(self)
        self._make_tray()
        self.timer = QTimer(interval=15000, timeout=self.tick)
        self.timer.start()
        self.day = date.today()
        QTimer.singleShot(1500, self.tick)          # also pops up anything missed while the PC was off

    # ---- data
    def reload_if_changed(self):
        m = core.file_mtime()
        if m and m != self.last_mtime:
            self.last_mtime = m
            self.items = core.load()["items"]
            self.window.refresh()
            self.update_tooltip()

    def _saved(self, data):
        self.items = data["items"]
        self.last_mtime = core.file_mtime()
        self.window.refresh()
        self.update_tooltip()

    def save(self, item):
        self._saved(core.apply(changed=[item]))

    def delete(self, item_id):
        self._saved(core.apply(deleted=[item_id]))

    def _get(self, item_id):
        return next((dict(x) for x in self.items if x["id"] == item_id), None)

    def set_done(self, item_id, occ, done):
        it = self._get(item_id)
        if not it:
            return
        day = occ.date().isoformat()
        it["done"] = sorted(set(it.get("done") or []) - {day} | ({day} if done else set()))[-400:]
        self.save(it)
        for k in [k for k in self.state["snoozed"] if k.startswith(f"{item_id}|{core.fmt_dt(occ)}")]:
            self.state["snoozed"].pop(k)
        core.save_state(self.state)

    def skip(self, item_id, occ):
        it = self._get(item_id)
        if it:
            it["skip"] = sorted(set(it.get("skip") or []) | {occ.date().isoformat()})
            self.save(it)

    # ---- alerts
    def next_alert(self, within_days=7):
        now = datetime.now()
        best = None
        for it in self.items:
            for occ in core.occurrences(it, now - timedelta(days=8), now + timedelta(days=within_days + 8)):
                if core.is_done(it, occ):
                    continue
                for m, at in core.alert_times(it, occ):
                    if at > now and at <= now + timedelta(days=within_days) and (best is None or at < best[0]):
                        best = (at, it, occ)
        return best

    def tick(self):
        self.reload_if_changed()
        now = datetime.now()
        if date.today() != self.day:                 # past midnight: "Today" moved on
            self.day = date.today()
            self.window.refresh()
        last = self.state.get("last_check")
        since = max(datetime.fromisoformat(last), now - timedelta(hours=12)) if last else now - timedelta(minutes=1)
        fired_any = False
        for it in self.items:
            for occ in core.occurrences(it, since - timedelta(days=8), now + timedelta(days=8)):
                if it["kind"] == "reminder" and core.is_done(it, occ):
                    continue
                for m, at in core.alert_times(it, occ):
                    key = f"{it['id']}|{core.fmt_dt(occ)}|{m}"
                    if since < at <= now and key not in self.state["fired"]:
                        self.state["fired"][key] = now.isoformat()
                        self.show_popup(it, occ, m, missed=(now - at) > timedelta(minutes=3))
                        fired_any = True
        for key, until in list(self.state["snoozed"].items()):
            if datetime.fromisoformat(until) <= now:
                self.state["snoozed"].pop(key)
                iid, occ_s, m = key.split("|")
                it = next((x for x in self.items if x["id"] == iid), None)
                if it and not (it["kind"] == "reminder" and core.is_done(it, core.parse_dt(occ_s))):
                    self.show_popup(it, core.parse_dt(occ_s), int(m))
                fired_any = True
        self.state["last_check"] = now.isoformat()
        core.save_state(self.state)
        if fired_any:
            self.window.refresh()
        self.update_tooltip()

    def show_popup(self, item, occ, minutes, missed=False):
        p = ReminderPopup(self, item, occ, minutes, missed)
        self.popups.append(p)
        self._place_popups()
        p.show()
        if settings().value("sound", True) in (True, "true"):
            play_chime()

    def _place_popups(self):
        area = QApplication.primaryScreen().availableGeometry()
        y = area.bottom() - 12
        for p in reversed(self.popups[-6:]):
            p.adjustSize()
            y -= p.height()
            p.move(area.right() - p.width() - 12, y)
            y -= 10

    def popup_closed(self, p):
        if p in self.popups:
            self.popups.remove(p)
        self._place_popups()

    def snooze(self, item, occ, alert_minutes, minutes):
        now = datetime.now()
        until = (datetime.combine(date.today() + timedelta(days=1), datetime.min.time()).replace(hour=8)
                 if minutes < 0 else now + timedelta(minutes=minutes))
        self.state["snoozed"][f"{item['id']}|{core.fmt_dt(occ)}|{alert_minutes}"] = until.isoformat()
        core.save_state(self.state)

    def test_popup(self):
        self.show_popup(core.new_item(title="This is how a reminder looks", notes="Click Done or Snooze.",
                                      start=core.fmt_dt(core.now())), core.now(), 0)

    # ---- tray
    def _make_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(QIcon(icon_path("planner")), self.app)
        m = QMenu()
        m.addAction("New reminder", lambda: (self.show_window(), self.window.edit(None, "reminder")))
        m.addAction("New event", lambda: (self.show_window(), self.window.edit(None, "event")))
        m.addAction("Open Ethical Planner", self.show_window)
        m.addSeparator()
        m.addAction("Help", lambda: open_guide("planner"))
        m.addAction("Quit Ethical Planner", self.quit)
        self.tray_menu = m
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.show_window() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self.update_tooltip()

    def update_tooltip(self):
        if not self.tray:
            return
        nxt = self.next_alert(2)
        self.tray.setToolTip(APP_NAME + (f"\nNext: {nxt[1]['title']} – {nxt[0].strftime('%a')} {time_text(nxt[0])}" if nxt else ""))

    def tray_tip(self):
        s = settings()
        if s.value("tray_tip_shown", False) not in (True, "true") and self.tray:
            s.setValue("tray_tip_shown", True)
            self.tray.showMessage(APP_NAME, "Planner is still running here, so your reminders can pop up.",
                                  QSystemTrayIcon.Information, 5000)

    def show_window(self):
        self.window.show()
        self.window.setWindowState(self.window.windowState() & ~Qt.WindowMinimized)
        self.window.raise_()
        self.window.activateWindow()

    def maybe_ask_autostart(self):
        s = settings()
        if s.value("asked_autostart", False) in (True, "true") or autostart_enabled():
            return
        s.setValue("asked_autostart", True)
        box = QMessageBox(QMessageBox.Question, APP_NAME,
                          "Start Ethical Planner when Windows starts?",
                          QMessageBox.Yes | QMessageBox.No, self.window)
        box.setInformativeText("Reminders can only pop up while Planner is running. It waits quietly in the tray "
                               "and uses almost no memory. You can change this later in ⋯.")
        box.button(QMessageBox.Yes).setText("Yes, start with Windows")
        box.button(QMessageBox.No).setText("Not now")
        if box.exec() == QMessageBox.Yes:
            self.set_autostart(True)

    def set_autostart(self, on):
        set_autostart(on)
        self.window.autostart_action.setChecked(autostart_enabled())

    def quit(self):
        if QMessageBox.question(self.window, APP_NAME, "Quit Ethical Planner?\n\nReminders won't pop up until you "
                                "open Planner again.") != QMessageBox.Yes:
            return
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
                              " ".join(f'"{x}"' for x in launch_command("planner", "--startup")))
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
    ctl = PlannerApp(app)
    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def handle(msg):
        if msg == "new":
            ctl.show_window()
            ctl.window.edit(None, "reminder")
        elif msg == "show":
            ctl.show_window()
        else:                                      # "startup" / "check": just look at the file again
            ctl.reload_if_changed()

    def incoming():
        sock = server.nextPendingConnection()
        sock.readyRead.connect(lambda: handle(bytes(sock.readAll()).decode("utf-8", "replace").strip()))
    server.newConnection.connect(incoming)
    if message != "startup":
        handle(message)
        QTimer.singleShot(700, ctl.maybe_ask_autostart)
    code = app.exec()
    lock.unlock()
    sys.exit(code)


if __name__ == "__main__":
    main()
