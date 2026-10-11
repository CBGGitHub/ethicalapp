"""Shared pieces used by every app in the suite."""
import os
import re
from functools import lru_cache

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QColorDialog, QToolButton

SUITE_NAME = "EthicalApp"          # the name people see (was "Ethical Suite" until 2026-10-11)
# Internal names that must NOT change - existing installs keep their settings, notes, reminders, taskbar pins and
# right-click entries: QSettings organisation / data folder name, and the Windows ID prefix.
SETTINGS_ORG = "Ethical Suite"
INTERNAL_ID = "EthicalSuite"
WEBSITE = "https://ethicalapp.org"
# The "support the project" page (same as donateUrl in website/assets/config.js).
SUPPORT_URL = "https://donate.stripe.com/cNibJ24xT4IJeefdJT5ZC00"


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_KEYS = {"EthicalApp": "suite", "Ethical PDF Editor": "pdf", "Ethical Document Editor": "document", "Ethical Spreadsheet Editor": "spreadsheet",
             "Ethical Presentation Editor": "presentation", "Ethical Photo Editor": "photo",
             "Ethical Converter": "converter", "Ethical Database": "database", "Ethical Sticky Notes": "stickynotes", "Ethical Snip": "snip", "Ethical Planner": "planner",
             "Ethical Guide": "guide"}


def icon_path(app_name_or_key):
    key = ICON_KEYS.get(app_name_or_key, app_name_or_key)
    p = os.path.join(ROOT, "branding", "icons", f"{key}.ico")
    return p if os.path.exists(p) else os.path.join(ROOT, "branding", "icons", "suite.ico")


def make_app(app_name, argv):
    if os.name == "nt":
        # give each app its own taskbar identity, so Windows shows our icon instead of Python's
        try:
            import ctypes
            short = "Suite" if app_name == SUITE_NAME else app_name.replace("Ethical ", "").replace(" ", "")
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{INTERNAL_ID}.{short}")
        except Exception:
            pass
    app = QApplication(argv)
    app.setApplicationName(app_name)
    from PySide6.QtGui import QIcon
    if os.path.exists(icon_path(app_name)):
        app.setWindowIcon(QIcon(icon_path(app_name)))
    app.setOrganizationName(SETTINGS_ORG)
    app.setStyle("Fusion")
    pal = app.palette()
    pal.setColor(QPalette.Highlight, QColor(46, 117, 214))
    app.setPalette(pal)
    return app


class ColorButton(QToolButton):
    """Tool button that shows and picks a colour."""
    colorChanged = Signal(QColor)

    def __init__(self, color, tooltip="", parent=None):
        super().__init__(parent)
        self.setToolTip(tooltip)
        self._color = QColor(color)
        self.clicked.connect(self._pick)
        self._refresh()

    def color(self):
        return QColor(self._color)

    def setColor(self, c):
        self._color = QColor(c)
        self._refresh()

    def _pick(self):
        c = QColorDialog.getColor(self._color, self, self.toolTip())
        if c.isValid():
            self.setColor(c)
            self.colorChanged.emit(c)

    def _refresh(self):
        self.setStyleSheet(
            f"QToolButton {{ background: {self._color.name()}; border: 1px solid #777;"
            f" min-width: 22px; min-height: 22px; border-radius: 3px; }}")


# ---------------------------------------------------------------- installed fonts (Windows)

_STYLE_SUFFIX = re.compile(r"\s+(Bold Italic|Bold Oblique|Bold|Italic|Oblique|Regular)$", re.I)


@lru_cache(maxsize=1)
def system_fonts():
    """Map full font name ('Arial Bold Italic') -> font file path, from the Windows registry."""
    fonts = {}
    try:
        import winreg
    except ImportError:
        return fonts
    key = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
    sys_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            k = winreg.OpenKey(root, key)
        except OSError:
            continue
        for i in range(winreg.QueryInfoKey(k)[1]):
            name, val, _ = winreg.EnumValue(k, i)
            if not isinstance(val, str) or not val.lower().endswith((".ttf", ".otf", ".ttc")):
                continue
            path = val if os.path.isabs(val) else os.path.join(sys_dir, val)
            if not os.path.exists(path):
                continue
            name = re.sub(r"\s*\((TrueType|OpenType)\)$", "", name)
            for part in name.split(" & "):
                fonts.setdefault(part.strip(), path)
    return fonts


@lru_cache(maxsize=1)
def font_families():
    return sorted({_STYLE_SUFFIX.sub("", n) for n in system_fonts()}, key=str.lower)


def font_file(family, bold=False, italic=False):
    """Best installed font file for family + style, or None."""
    fonts = system_fonts()
    wanted = ["Bold Italic"] if bold and italic else ["Bold"] if bold else ["Italic"] if italic else []
    if bold and italic:
        wanted.append("Bold Oblique")
    elif italic:
        wanted.append("Oblique")
    for style in wanted + ["Regular", ""]:
        path = fonts.get(f"{family} {style}".strip())
        if path:
            return path
    return None


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def match_family(pdf_font_name):
    """Find the installed family matching a PDF font name like 'ABCDEF+TimesNewRomanPS-BoldMT'."""
    base = _norm(pdf_font_name.split("+")[-1].split(",")[0].split("-")[0])
    best = None
    for fam in font_families():
        n = _norm(fam)
        if n and base.startswith(n) and (best is None or len(n) > len(_norm(best))):
            best = fam
    if best is None:  # classic PDF fonts -> their usual Windows equivalents
        for prefix, fam in (("helvetica", "Arial"), ("times", "Times New Roman"),
                            ("courier", "Courier New"), ("arialmt", "Arial")):
            if base.startswith(prefix) and fam in font_families():
                return fam
    return best


# ---------------------------------------------------------------- user guide (guide/index.html)

GUIDE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "guide", "index.html")


def open_guide(topic=""):
    """Open the offline guide in the browser at a topic. Windows drops '#topic' from file links, so we go
    through a tiny redirect page in the temp folder."""
    import tempfile
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    target = QUrl.fromLocalFile(GUIDE)
    if topic:
        target.setFragment(topic)
    redirect = os.path.join(tempfile.gettempdir(), "ethical_guide_open.html")
    with open(redirect, "w", encoding="utf-8") as fh:
        fh.write(f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={target.toString()}">'
                 f'<a href="{target.toString()}">Open the guide</a>')
    QDesktopServices.openUrl(QUrl.fromLocalFile(redirect))


def add_guide_action(window, menu, topic):
    from PySide6.QtGui import QAction, QKeySequence
    a = QAction("User &Guide", window)
    a.setShortcut(QKeySequence("F1"))
    a.triggered.connect(lambda: open_guide(topic))
    menu.insertAction(menu.actions()[0] if menu.actions() else None, a)
    return a


# ---------------------------------------------------------------- installed (frozen) vs. source mode

import sys as _sys

FROZEN = getattr(_sys, "frozen", False)
APP_SCRIPTS = {"pdf": "pdf_editor.py", "document": "word_processor.py", "spreadsheet": "sheets_app.py",
               "presentation": "slides_app.py", "photo": "photo_app.py", "converter": "converter_app.py",
               "database": "base_app.py", "stickynotes": "sticky_notes.py", "snip": "snip_app.py", "planner": "planner_app.py"}

# file extension -> app that opens it (launcher, MCP open_in_app, files dropped on EthicalSuite.exe)
EXT_APP = {".pdf": "pdf", ".docx": "document", ".txt": "document", ".md": "document", ".html": "document",
           ".xlsx": "spreadsheet", ".xlsm": "spreadsheet", ".csv": "spreadsheet", ".pptx": "presentation",
           ".psd": "photo", ".png": "photo", ".jpg": "photo", ".jpeg": "photo", ".webp": "photo", ".bmp": "photo",
           ".gif": "photo", ".tif": "photo", ".tiff": "photo", ".ora": "photo", ".db": "database",
           ".sqlite": "database", ".sqlite3": "database"}


def installed_apps():
    """App keys installed on this PC. The installer writes suite.ini with the chosen components; running
    from source, every app is available."""
    ini = os.path.join(ROOT, "suite.ini")
    if not (FROZEN and os.path.exists(ini)):
        return list(APP_SCRIPTS)
    import configparser
    cp = configparser.ConfigParser()
    cp.read(ini, encoding="utf-8")
    return [k for k in APP_SCRIPTS if cp.get("apps", k, fallback="0") == "1"]


def _pyw():
    exe = _sys.executable
    return exe[:-len("python.exe")] + "pythonw.exe" if exe.lower().endswith("python.exe") else exe


def launch_command(app_key, *args):
    """Command line that starts an Ethical app (works from source and when installed)."""
    if FROZEN:
        return [os.path.join(ROOT, "EthicalSuite.exe"), app_key, *args]
    if app_key == "launcher":
        return [_pyw(), os.path.join(ROOT, "apps", "suite_launcher.py"), *args]
    exe = _sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-len("python.exe")] + "pythonw.exe"
    return [exe, os.path.join(ROOT, "apps", APP_SCRIPTS[app_key]), *args]


def mcp_command(apps):
    """Command line for the MCP server (needs a console program for stdin/stdout)."""
    if FROZEN:
        return [os.path.join(ROOT, "EthicalSuiteCLI.exe"), "mcp", "--apps", ",".join(apps)]
    exe = _sys.executable
    if exe.lower().endswith("pythonw.exe"):
        exe = exe[:-len("pythonw.exe")] + "python.exe"
    return [exe, os.path.join(ROOT, "apps", "mcp_server.py"), "--apps", ",".join(apps)]


def bundled_tool(folder, exe):
    """Path of a helper program shipped with the installed suite (ffmpeg, deno), or None."""
    p = os.path.join(ROOT, folder, exe)
    return p if os.path.exists(p) else None


def start_detached(cmd, cwd=None):
    """Start a program that keeps running after whoever started it exits - e.g. an app opened by the AI tools.
    Claude may close the AI server with everything it started (a Windows "job", or killing the process tree),
    so on Windows we ask the system's process service (WMI) to start the app: then it isn't our child at all.
    Falls back to a normal detached start if that isn't possible."""
    import subprocess
    if os.name == "nt":
        line = subprocess.list2cmdline(cmd).replace("'", "''")
        folder = (cwd or ROOT).replace("'", "''")
        ps = (f"$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
              f"@{{CommandLine='{line}'; CurrentDirectory='{folder}'}}; exit $r.ReturnValue")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                               timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode == 0:
                return None
        except (OSError, subprocess.TimeoutExpired):
            pass
    base = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        return subprocess.Popen(cmd, cwd=cwd or ROOT, creationflags=base | 0x01000000, close_fds=True)  # +BREAKAWAY
    except OSError:
        return subprocess.Popen(cmd, cwd=cwd or ROOT, creationflags=base, close_fds=True)
