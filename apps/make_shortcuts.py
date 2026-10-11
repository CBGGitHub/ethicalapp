"""Create (or remove) Start Menu / Desktop shortcuts with the EthicalApp icons.

Usage:  .venv\\Scripts\\python apps\\make_shortcuts.py            -> Start Menu folder "EthicalApp"
        .venv\\Scripts\\python apps\\make_shortcuts.py --desktop  -> also put shortcuts on the Desktop
        .venv\\Scripts\\python apps\\make_shortcuts.py --remove   -> remove them again
Only affects the current user.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from suite_common import SUITE_NAME, icon_path  # noqa: E402

SHORTCUTS = [  # name, script (None = the guide), icon key, description
    ("EthicalApp", "suite_launcher.py", "suite", "All EthicalApp apps in one window"),
    ("Ethical PDF Editor", "pdf_editor.py", "pdf", "View, edit, sign and organise PDF files"),
    ("Ethical Document Editor", "word_processor.py", "document", "Write documents - opens and saves Word files"),
    ("Ethical Spreadsheet Editor", "sheets_app.py", "spreadsheet", "Spreadsheets - opens and saves Excel files"),
    ("Ethical Presentation Editor", "slides_app.py", "presentation", "Slide shows - opens and saves PowerPoint files"),
    ("Ethical Photo Editor", "photo_app.py", "photo", "Edit photos with layers - opens and saves PSD"),
    ("Ethical Converter", "converter_app.py", "converter", "Convert, compress and download files"),
    ("Ethical Database", "base_app.py", "database", "Databases: tables, forms, queries and reports"),
    ("Ethical Sticky Notes", "sticky_notes.py", "stickynotes", "Notes and to-do lists on your desktop"),
    ("Ethical Snip", "snip_app.py", "snip", "Take screenshots and mark them up"),
    ("Ethical Planner", "planner_app.py", "planner", "Reminders and a calendar that pop up on time"),
    ("Ethical Guide", None, "guide", "How to use every EthicalApp app"),
]


def folders(desktop):
    start = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", SUITE_NAME)
    old = os.path.join(os.path.dirname(start), "Ethical Suite")     # the folder's name before the rename
    if os.path.isdir(old):
        import shutil
        shutil.rmtree(old, ignore_errors=True)
    out = [start]
    if desktop:
        out.append(os.path.join(os.path.expanduser("~"), "Desktop"))
    return out


def pythonw():
    exe = sys.executable
    return exe[:-len("python.exe")] + "pythonw.exe" if exe.lower().endswith("python.exe") else exe


def ps_quote(s):
    return "'" + s.replace("'", "''") + "'"


def create(desktop=False):
    lines = ["$sh = New-Object -ComObject WScript.Shell"]
    made = []
    for folder in folders(desktop):
        os.makedirs(folder, exist_ok=True)
        for name, script, key, desc in SHORTCUTS:
            lnk = os.path.join(folder, name + ".lnk")
            if script:
                target, args = pythonw(), f'"{os.path.join(HERE, script)}"'
            else:
                target, args = os.path.join(ROOT, "guide", "index.html"), ""
            lines += [f"$s = $sh.CreateShortcut({ps_quote(lnk)})", f"$s.TargetPath = {ps_quote(target)}",
                      f"$s.Arguments = {ps_quote(args)}", f"$s.WorkingDirectory = {ps_quote(ROOT)}",
                      f"$s.IconLocation = {ps_quote(icon_path(key) + ',0')}", f"$s.Description = {ps_quote(desc)}",
                      "$s.Save()"]
            made.append(lnk)
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "; ".join(lines)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return made


def remove():
    n = 0
    for folder in folders(True):
        for name, *_ in SHORTCUTS:
            p = os.path.join(folder, name + ".lnk")
            if os.path.exists(p):
                os.remove(p)
                n += 1
    start = folders(False)[0]
    if os.path.isdir(start) and not os.listdir(start):
        os.rmdir(start)
    return n


if __name__ == "__main__":
    if "--remove" in sys.argv:
        print(f"Removed {remove()} shortcut(s).")
    else:
        made = create("--desktop" in sys.argv)
        print(f"Created {len(made)} shortcut(s) in: " + ", ".join(sorted({os.path.dirname(m) for m in made})))
