"""EthicalApp launcher: one window showing every installed Ethical app.

Click a tile to start an app, use "Open a file..." or drop files on the window to open them in the right
app, and F1 / the Guide tile for help. Started by EthicalSuite.exe without arguments (Start Menu
"EthicalApp"), or from source with "EthicalApp.bat".
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtGui import QActionGroup, QIcon, QKeySequence, QShortcut  # noqa: E402
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QMessageBox,  # noqa: E402
                               QPushButton, QToolButton, QVBoxLayout, QWidget)

from suite_common import (EXT_APP, ROOT, SUITE_NAME, SUPPORT_URL, icon_path, installed_apps, launch_command,  # noqa: E402
                          make_app, open_guide)
from i18n import LANGUAGES, chosen_language, language, set_language, tr  # noqa: E402

TILES = [  # key, name, what it does
    ("pdf", tr("PDF Editor"), tr("Edit, sign, fill and organise PDFs")),
    ("document", tr("Document Editor"), tr("Write letters and reports (.docx)")),
    ("spreadsheet", tr("Spreadsheet Editor"), tr("Numbers, formulas and charts (.xlsx)")),
    ("presentation", tr("Presentation Editor"), tr("Slides and slideshows (.pptx)")),
    ("photo", tr("Photo Editor"), tr("Layers, filters and retouching (.psd)")),
    ("converter", tr("Converter"), tr("Convert, compress, trim and zip")),
    ("database", tr("Database"), tr("Tables, forms, queries and reports")),
    ("stickynotes", tr("Sticky Notes"), tr("To-do notes on your desktop")),
    ("snip", tr("Snip"), tr("Screenshots you can mark up – with your own shortcut key")),
    ("planner", tr("Planner"), tr("Reminders and a calendar that pop up on time")),
    ("guide", tr("Guide"), tr("How to use every app (F1)")),
]

STYLE = """
QWidget#launcher { background: palette(window); }
QToolButton#tile { border: 1px solid palette(mid); border-radius: 10px; background: palette(base);
                   padding: 10px 6px 8px 6px; font-size: 13px; font-weight: 600; }
QToolButton#tile:hover { border: 2px solid #2E7D32; background: palette(alternate-base); }
QToolButton#tile:pressed { background: palette(midlight); }
QLabel#desc { color: palette(placeholder-text); font-size: 11px; }
QFrame#pin { background: #E8F5E9; border: 1px solid #81C784; border-radius: 8px; }
QFrame#pin QLabel { color: #1B5E20; }
"""


def start(key, *args):
    """Start an app, the launcher or the guide without waiting for it."""
    if key == "guide":
        open_guide("")
        return
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(launch_command(key, *args), cwd=ROOT, creationflags=flags, close_fds=True)


class Launcher(QWidget):
    def __init__(self, pin_help=False):
        super().__init__()
        self.setObjectName("launcher")
        self.setWindowTitle(SUITE_NAME)
        self.setWindowIcon(QIcon(icon_path("suite")))
        self.setStyleSheet(STYLE)
        self.setAcceptDrops(True)
        self.apps = installed_apps()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(14)

        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(icon_path("suite")).pixmap(48, 48))
        head.addWidget(logo)
        title = QLabel(tr("<div style='font-size:22px; font-weight:700; color:#2E7D32'>{SUITE_NAME}</div><div "
                          "style='font-size:12px'>Pick an app, or drop a file here to open it.</div>").format(SUITE_NAME=SUITE_NAME))
        head.addWidget(title, 1)
        open_btn = QPushButton(tr("Open a file…"))
        open_btn.setToolTip(tr("Opens the file in the Ethical app that handles its type (Ctrl+O)"))
        open_btn.clicked.connect(self.open_file)
        head.addWidget(open_btn)
        lay.addLayout(head)

        # how to pin (Windows doesn't let programs pin themselves to the taskbar or Start)
        self.pin = QFrame()
        self.pin.setObjectName("pin")
        pl = QHBoxLayout(self.pin)
        pl.addWidget(QLabel(
            tr("<b>📌 Keep EthicalApp handy</b><br><b>Taskbar:</b> right-click the EthicalApp icon on the taskbar "
               "(bottom of the screen) → <b>Pin to taskbar</b>.<br><b>Start:</b> click Start, find "
               "<b>EthicalApp</b> in the list, right-click it → <b>Pin to Start</b>.")), 1)
        close = QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        close.setToolTip(tr("Hide"))
        close.clicked.connect(self.hide_pin_help)
        pl.addWidget(close, 0, Qt.AlignTop)
        lay.addWidget(self.pin)
        self.pin.setVisible(pin_help)

        grid = QGridLayout()
        grid.setSpacing(12)
        shown = [t for t in TILES if t[0] == "guide" or t[0] in self.apps]
        cols = 4 if len(shown) > 4 else len(shown)
        for i, (key, name, desc) in enumerate(shown):
            cell = QVBoxLayout()
            cell.setSpacing(4)
            b = QToolButton()
            b.setObjectName("tile")
            b.setText(name)
            b.setIcon(QIcon(icon_path(key)))
            b.setIconSize(QSize(64, 64))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setFixedSize(170, 118)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tr("Ethical {name}: {desc}").format(name=name, desc=desc))
            b.clicked.connect(lambda _=False, k=key: self.launch(k))
            cell.addWidget(b, 0, Qt.AlignHCenter)
            d = QLabel(desc)
            d.setObjectName("desc")
            d.setAlignment(Qt.AlignHCenter)
            d.setWordWrap(True)
            d.setFixedWidth(170)
            d.setMinimumHeight(d.fontMetrics().lineSpacing() * 3 + 2)   # room for 3 lines (longer languages)
            cell.addWidget(d, 0, Qt.AlignHCenter)
            grid.addLayout(cell, i // cols, i % cols)
        lay.addLayout(grid)

        missing = [n for k, n, _ in TILES if k != "guide" and k not in self.apps]
        if missing:
            note = QLabel(tr("Not installed: {apps}. Run the EthicalApp setup again to add them.").format(
                apps=", ".join(missing)))
            note.setObjectName("desc")
            note.setWordWrap(True)
            lay.addWidget(note)

        foot = QHBoxLayout()
        support = QLabel(tr("<a href='{SUPPORT_URL}' style='color:#C62828; text-decoration:none'>♥ Support "
                            "EthicalApp</a><span style='color:palette(placeholder-text)'> – free forever, kept "
                            "going by people who chip in</span>").format(SUPPORT_URL=SUPPORT_URL))
        support.setOpenExternalLinks(True)
        support.setToolTip(tr("Opens a secure payment page in your browser. Totally optional."))
        foot.addWidget(support)
        foot.addStretch(1)
        lang = QToolButton()
        lang.setText("🌐 " + LANGUAGES[language()])
        lang.setAutoRaise(True)
        lang.setToolTip(tr("Language for all Ethical apps"))
        lang.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(lang)
        group = QActionGroup(menu)
        chosen = chosen_language()
        for code, label in [("auto", tr("Same as Windows"))] + list(LANGUAGES.items()):
            a = menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(code == chosen)
            group.addAction(a)
            a.triggered.connect(lambda _=False, c=code: self.change_language(c))
            if code == "auto":
                menu.addSeparator()
        lang.setMenu(menu)
        foot.addWidget(lang)
        pin_link = QLabel(tr("<a href='#'>Pin to taskbar or Start…</a>"))
        pin_link.linkActivated.connect(self.show_pin_help)
        foot.addWidget(pin_link)
        lay.addLayout(foot)

        QShortcut(QKeySequence.Open, self, self.open_file)
        QShortcut(QKeySequence("F1"), self, lambda: open_guide(""))
        self.adjustSize()
        self.setFixedSize(self.sizeHint())

    def change_language(self, code):
        set_language(code)
        # asked in the current language - the new one shows after the restart
        if QMessageBox.question(self, SUITE_NAME, tr("Restart EthicalApp now to use the new language?\n"
                                                     "Apps that are already open change the next time you start them.")
                                ) == QMessageBox.Yes:
            start("launcher")
            self.close()

    def show_pin_help(self):
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.pin.show()
        self.adjustSize()
        self.setFixedSize(self.sizeHint())

    def hide_pin_help(self):
        self.pin.hide()
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.adjustSize()
        self.setFixedSize(self.sizeHint())

    def launch(self, key):
        start(key)
        self.setWindowTitle(tr("{SUITE_NAME} — starting {v}…").format(SUITE_NAME=SUITE_NAME, v=dict((k, n) for k, n, _ in TILES)[key]))
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2500, lambda: self.setWindowTitle(SUITE_NAME))

    def open_paths(self, paths):
        skipped = []
        for p in paths:
            ext = os.path.splitext(p)[1].lower()
            key = EXT_APP.get(ext)
            if key and key not in self.apps:
                key = None
            if not key and "converter" in self.apps:
                key = "converter"            # anything else: offer to convert / compress / zip it
            if key:
                start(key, p)
            else:
                skipped.append(os.path.basename(p))
        if skipped:
            QMessageBox.information(self, SUITE_NAME, tr("No installed Ethical app opens:\n") + "\n".join(skipped))

    def open_file(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Open a file"), os.path.expanduser("~"),
                                                tr("Supported files") + " (" + " ".join("*" + e for e in EXT_APP) + ");;" + tr("All files") + " (*)")
        if paths:
            self.open_paths(paths)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.open_paths(paths)


def main():
    app = make_app(SUITE_NAME, sys.argv)
    args = sys.argv[1:]
    w = Launcher(pin_help="--pin-help" in args)
    w.show()
    files = [a for a in args if not a.startswith("--") and os.path.exists(a)]
    if files:
        w.open_paths(files)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
