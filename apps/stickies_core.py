"""Storage for Ethical Sticky Notes (shared by the app and the AI tools in mcp_server.py).

All notes live in one JSON file on this PC:  %APPDATA%\\Ethical Suite\\Sticky Notes\\notes.json
(a copy of the previous version is kept as notes.json.bak). Nothing is ever uploaded.

A note: {id, html, text, color, x, y, w, h, on_top, collapsed, open, font_size, created, modified}
  html = the formatted note (source of truth), text = Markdown copy (for search and the AI tools).
Writes are atomic (temp file + rename) and go through a small lock file, so the app and the AI tools can both
change notes safely: each saves only the notes it changed, on top of the latest file.
"""
import contextlib
import json
import os
import time
import uuid
from datetime import datetime

FOLDER = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Ethical Suite", "Sticky Notes")
FILE = os.path.join(FOLDER, "notes.json")
TRASH_KEEP = 30          # recently deleted notes kept for "Restore deleted note"

# name: (body, header, text)
COLORS = {
    "yellow": ("#FFF6A5", "#F3DF62", "#2B2B2B"),
    "green": ("#D7F2CB", "#ADDC9A", "#22301E"),
    "pink": ("#FFD8E8", "#F6ADCB", "#3A2430"),
    "purple": ("#E7DCFF", "#CBB7F5", "#2C2440"),
    "blue": ("#D3EBFF", "#A8D1F5", "#1E2C3A"),
    "orange": ("#FFE2C2", "#F7C189", "#3A2A1A"),
    "gray": ("#EDEDED", "#D0D0D0", "#2B2B2B"),
    "charcoal": ("#3B3D40", "#2C2E31", "#EFEFEF"),
}
DEFAULT_COLOR = "yellow"
FONT_SIZES = {"small": 12, "medium": 14, "large": 17}


def now():
    return datetime.now().isoformat(timespec="seconds")


def new_note(**kw):
    n = {"id": uuid.uuid4().hex[:12], "html": "", "text": "", "color": DEFAULT_COLOR, "x": None, "y": None,
         "w": 300, "h": 300, "on_top": False, "collapsed": False, "open": True, "font_size": "medium",
         "created": now(), "modified": now()}
    n.update(kw)
    return n


def empty():
    return {"version": 1, "notes": [], "trash": [], "settings": {}}


@contextlib.contextmanager
def locked(timeout=3.0):
    """Short exclusive lock so two programs never write the file at the same moment."""
    os.makedirs(FOLDER, exist_ok=True)
    path = FILE + ".lock"
    end = time.time() + timeout
    fd = None
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:                                   # a crashed writer left the lock behind
                if time.time() - os.path.getmtime(path) > 10:
                    os.remove(path)
                    continue
            except OSError:
                pass
            if time.time() > end:
                break                              # give up waiting; better to save than to lose text
            time.sleep(0.05)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
            with contextlib.suppress(OSError):
                os.remove(path)


def load():
    for path in (FILE, FILE + ".bak"):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and isinstance(data.get("notes"), list):
                data.setdefault("trash", [])
                data.setdefault("settings", {})
                for n in data["notes"]:
                    for k, v in new_note().items():
                        n.setdefault(k, v)
                return data
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            continue                               # damaged file: fall back to the backup
    return empty()


def _write(data):
    os.makedirs(FOLDER, exist_ok=True)
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    if os.path.exists(FILE):
        with contextlib.suppress(OSError):
            os.replace(FILE, FILE + ".bak")
    os.replace(tmp, FILE)


def apply(changed=(), deleted=(), settings=None):
    """Save changes on top of the latest file: `changed` notes are added/replaced, `deleted` ids move to the
    trash. Returns the new file contents."""
    with locked():
        data = load()
        by_id = {n["id"]: i for i, n in enumerate(data["notes"])}
        for n in changed:
            if n["id"] in by_id:
                data["notes"][by_id[n["id"]]] = n
            else:
                data["notes"].append(n)
                by_id[n["id"]] = len(data["notes"]) - 1
        if deleted:
            gone = [n for n in data["notes"] if n["id"] in set(deleted)]
            data["notes"] = [n for n in data["notes"] if n["id"] not in set(deleted)]
            for n in gone:
                n["deleted"] = now()
            data["trash"] = (gone + data["trash"])[:TRASH_KEEP]
        if settings:
            data["settings"].update(settings)
        _write(data)
        return data


def restore_last():
    """Bring back the most recently deleted note. Returns it, or None."""
    with locked():
        data = load()
        if not data["trash"]:
            return None
        n = data["trash"].pop(0)
        n.pop("deleted", None)
        n["open"] = True
        n["modified"] = now()
        data["notes"].append(n)
        _write(data)
        return n


def find(data, note_id):
    note_id = (note_id or "").strip()
    for n in data["notes"]:
        if n["id"] == note_id or (len(note_id) >= 4 and n["id"].startswith(note_id)):
            return n
    return None


def title_of(note, limit=60):
    for line in (note.get("text") or "").splitlines():
        line = line.strip().lstrip("#-*>0123456789.[]xX ").replace("~~", "").replace("**", "").strip()
        if line:
            return line if len(line) <= limit else line[:limit - 1] + "…"
    return "(empty note)"


def file_mtime():
    try:
        return os.path.getmtime(FILE)
    except OSError:
        return 0.0
