"""Add (or with --remove, take away) the suite's right-click menu entries and "Open with" options.

Only touches the current user's settings (HKEY_CURRENT_USER), so no admin rights are needed.
Usage:  pythonw register_windows.py [--remove]
"""
import os
import sys
import winreg

from suite_common import INTERNAL_ID, SUITE_NAME, icon_path

HERE = os.path.dirname(os.path.abspath(__file__))
PREFIX = INTERNAL_ID          # keep the old ids so existing entries are replaced, not doubled

ICONS = {"PDF": "pdf", "Write": "document", "Sheets": "spreadsheet", "Slides": "presentation", "Photo": "photo",
         "Base": "database", "Converter": "converter"}

# (app id, menu label, script, file description, extensions)
APPS = [
    ("PDF", "Open with Ethical PDF Editor", "pdf_editor.py", "PDF Document", [".pdf"]),
    ("Write", "Open with Ethical Document Editor", "word_processor.py", "Word Document", [".docx"]),
    ("Sheets", "Open with Ethical Spreadsheet Editor", "sheets_app.py", "Excel Workbook", [".xlsx", ".csv"]),
    ("Slides", "Open with Ethical Presentation Editor", "slides_app.py", "PowerPoint Presentation", [".pptx"]),
    ("Photo", "Open with Ethical Photo Editor", "photo_app.py", "Image", [".psd", ".png", ".jpg", ".jpeg", ".webp", ".bmp",
                                                                ".gif", ".tif", ".tiff", ".ora"]),
    ("Base", "Open with Ethical Database", "base_app.py", "Database", [".db", ".sqlite", ".sqlite3", ".edb",
                                                                   ".accdb", ".mdb"]),
    # "*" = every file type, "Directory" = folders: only a right-click entry, no "Open with"
    ("Converter", "Convert / compress with Ethical Converter", "converter_app.py", "", ["*", "Directory"]),
]
GLOBAL_KEYS = ("*", "Directory")


def command_for(script):
    from suite_common import FROZEN, launch_command
    if FROZEN:
        key = next(k for k, v in __import__("suite_common").APP_SCRIPTS.items() if v == script)
        return " ".join(f'"{x}"' for x in launch_command(key)) + ' "%1"'
    exe = sys.executable
    if exe.lower().endswith("python.exe"):  # use the windowless interpreter
        exe = exe[:-len("python.exe")] + "pythonw.exe"
    return f'"{exe}" "{os.path.join(HERE, script)}" "%1"'


def set_value(path, value, name=""):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def delete_tree(path):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    delete_tree(path + "\\" + winreg.EnumKey(k, 0))
                except OSError:
                    break
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        pass


def register():
    for app_id, label, script, desc, exts in APPS:
        progid = f"{PREFIX}.{app_id}"
        cmd = command_for(script)
        base = rf"Software\Classes\{progid}"
        icon = icon_path(ICONS.get(app_id, "suite"))
        if desc:
            set_value(base, desc)
            set_value(base + r"\DefaultIcon", f'"{icon}",0')
            set_value(base + r"\shell\open\command", cmd)
        for ext in exts:
            if ext in GLOBAL_KEYS:
                verb = rf"Software\Classes\{ext}\shell\{progid}"
            else:
                set_value(rf"Software\Classes\{ext}\OpenWithProgids", "", progid)
                verb = rf"Software\Classes\SystemFileAssociations\{ext}\shell\{progid}"
            set_value(verb, label)
            set_value(verb, icon, "Icon")
            set_value(verb + r"\command", cmd)
    _notify_shell()


def unregister():
    for app_id, _, _, _, exts in APPS:
        progid = f"{PREFIX}.{app_id}"
        delete_tree(rf"Software\Classes\{progid}")
        for ext in exts:
            if ext in GLOBAL_KEYS:
                delete_tree(rf"Software\Classes\{ext}\shell\{progid}")
                continue
            delete_tree(rf"Software\Classes\SystemFileAssociations\{ext}\shell\{progid}")
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                    rf"Software\Classes\{ext}\OpenWithProgids", 0,
                                    winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, progid)
            except OSError:
                pass
    _notify_shell()


def _notify_shell():
    import ctypes
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED


if __name__ == "__main__":
    if "--remove" in sys.argv:
        unregister()
        print("Removed right-click entries.")
    else:
        register()
        print("Added right-click entries.")
