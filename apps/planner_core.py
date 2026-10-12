"""Storage and repeat rules for Ethical Planner (shared by the app and the AI tools in mcp_server.py).

Files (on this PC only, never uploaded):
  %APPDATA%\\Ethical Suite\\Planner\\planner.json        reminders and events (+ .bak)
  %APPDATA%\\Ethical Suite\\Planner\\planner_state.json  which alerts already popped up / are snoozed (app only)

An item:
  id, kind ("reminder" | "event"), title, notes, start ("YYYY-MM-DDTHH:MM", local time), all_day (bool),
  duration (minutes, events), repeat ("none" | "daily" | "weekly" | "monthly" | "yearly"), interval (every N),
  days ([0-6] Monday=0, for weekly), until ("YYYY-MM-DD" or None), alerts ([minutes before]), color,
  done (["YYYY-MM-DD" of occurrences ticked off]), skip (["YYYY-MM-DD" occurrences removed]), created, modified
All times are local wall-clock times.
"""
import calendar
import contextlib
import json
import os
import time
import uuid
from datetime import date, datetime, timedelta
from i18n import N_, day_name, tr

FOLDER = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Ethical Suite", "Planner")
FILE = os.path.join(FOLDER, "planner.json")
STATE = os.path.join(FOLDER, "planner_state.json")
ALL_DAY_ALERT_HOUR = 9           # all-day items alert at 9:00 (minus their alert offset)

REPEATS = {"none": N_("Never"), "daily": N_("Every day"), "weekdays": N_("Every weekday (Mon–Fri)"), "weekly": N_("Every week"),
           "monthly": N_("Every month"), "yearly": N_("Every year")}
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
COLORS = {"blue": "#3F51B5", "green": "#2E7D32", "orange": "#EF6C00", "red": "#C62828", "purple": "#7B1FA2",
          "teal": "#00897B", "gray": "#546E7A"}


def now():
    return datetime.now().replace(second=0, microsecond=0)


def stamp():
    return datetime.now().isoformat(timespec="seconds")


def parse_dt(s):
    s = (s or "").strip().replace(" ", "T")
    if len(s) == 10:
        s += "T00:00"
    return datetime.fromisoformat(s[:16])


def fmt_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M")


def new_item(**kw):
    kind = kw.get("kind", "reminder")
    it = {"id": uuid.uuid4().hex[:10], "kind": kind, "title": "", "notes": "", "start": fmt_dt(now()),
          "all_day": False, "duration": 60 if kind == "event" else 0, "repeat": "none", "interval": 1, "days": [],
          "until": None, "alerts": [0] if kind == "reminder" else [15], "color": "blue" if kind == "event" else "green",
          "done": [], "skip": [], "created": stamp(), "modified": stamp()}
    it.update(kw)
    return it


# ---------------------------------------------------------------- repeat rules

def _last_day(y, m):
    return calendar.monthrange(y, m)[1]


def occurs_on(item, d):
    """Does `item` happen on date `d`?"""
    base = parse_dt(item["start"]).date()
    if d < base:
        return False
    until = item.get("until")
    if until and d > date.fromisoformat(until):
        return False
    if d.isoformat() in (item.get("skip") or []):
        return False
    rep = item.get("repeat", "none")
    n = max(1, int(item.get("interval") or 1))
    if rep == "none":
        return d == base
    if rep == "daily":
        return (d - base).days % n == 0
    if rep == "weekdays":
        return d.weekday() < 5
    if rep == "weekly":
        days = item.get("days") or [base.weekday()]
        if d.weekday() not in days:
            return False
        weeks = ((d - timedelta(days=d.weekday())) - (base - timedelta(days=base.weekday()))).days // 7
        return weeks % n == 0
    if rep == "monthly":
        months = (d.year - base.year) * 12 + d.month - base.month
        return months % n == 0 and d.day == min(base.day, _last_day(d.year, d.month))
    if rep == "yearly":
        return (d.year - base.year) % n == 0 and d.month == base.month and \
            d.day == min(base.day, _last_day(d.year, d.month))
    return False


def occurrences(item, start, end):
    """Datetimes (start of each occurrence) with start <= dt < end."""
    t = parse_dt(item["start"]).time()
    d = max(start.date(), parse_dt(item["start"]).date())
    out = []
    while d <= end.date():
        if occurs_on(item, d):
            dt = datetime.combine(d, t)
            if start <= dt < end or (item.get("all_day") and start.date() <= d < end.date() + timedelta(days=1)
                                     and dt < end):
                out.append(dt)
        d += timedelta(days=1)
    return out


def alert_times(item, occ):
    """When the alerts for one occurrence go off."""
    base = occ.replace(hour=ALL_DAY_ALERT_HOUR, minute=0) if item.get("all_day") else occ
    return [(m, base - timedelta(minutes=int(m))) for m in (item.get("alerts") or [])]


def agenda(items, start, end):
    """[(datetime, item)] for every occurrence in [start, end), sorted."""
    rows = []
    for it in items:
        for occ in occurrences(it, start, end):
            rows.append((occ, it))
    rows.sort(key=lambda r: (r[0].date(), not r[1].get("all_day"), r[0], r[1]["title"].lower()))
    return rows


def is_done(item, occ):
    return occ.date().isoformat() in (item.get("done") or [])


def describe_repeat(item):
    rep = item.get("repeat", "none")
    n = max(1, int(item.get("interval") or 1))
    until = item.get("until")
    if rep == "none":
        return ""
    if rep == "weekly":
        days = item.get("days") or [parse_dt(item["start"]).weekday()]
        names = ", ".join(day_name(d, short=True) for d in sorted(days))
        txt = (tr("Every week on {days}") if n == 1 else tr("Every {n} weeks on {days}")).format(n=n, days=names)
    elif n > 1 and rep in ("daily", "monthly", "yearly"):
        txt = {"daily": tr("Every {n} days"), "monthly": tr("Every {n} months"), "yearly": tr("Every {n} years")}[rep].format(n=n)
    else:
        txt = tr(REPEATS.get(rep, rep))
    return txt + (" " + tr("until {date}").format(date=until) if until else "")


def describe_alert(minutes):
    m = int(minutes)
    if m == 0:
        return tr("At the time")
    if m % 1440 == 0:
        return tr("1 day before") if m == 1440 else tr("{n} days before").format(n=m // 1440)
    if m % 60 == 0:
        return tr("1 hour before") if m == 60 else tr("{n} hours before").format(n=m // 60)
    return tr("{n} minutes before").format(n=m)


# ---------------------------------------------------------------- files

@contextlib.contextmanager
def locked(timeout=3.0):
    os.makedirs(FOLDER, exist_ok=True)
    path = FILE + ".lock"
    end = time.time() + timeout
    fd = None
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            with contextlib.suppress(OSError):
                if time.time() - os.path.getmtime(path) > 10:
                    os.remove(path)
                    continue
            if time.time() > end:
                break
            time.sleep(0.05)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
            with contextlib.suppress(OSError):
                os.remove(path)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load():
    for path in (FILE, FILE + ".bak"):
        try:
            data = _read(path)
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                for it in data["items"]:
                    for k, v in new_item(kind=it.get("kind", "reminder")).items():
                        it.setdefault(k, v)
                data.setdefault("settings", {})
                return data
        except (OSError, ValueError):
            continue
    return {"version": 1, "items": [], "settings": {}}


def _write(path, data, backup=True):
    os.makedirs(FOLDER, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    if backup and os.path.exists(path):
        with contextlib.suppress(OSError):
            os.replace(path, path + ".bak")
    os.replace(tmp, path)


def apply(changed=(), deleted=()):
    """Save changed items / delete ids on top of the latest file. Returns the new data."""
    with locked():
        data = load()
        idx = {it["id"]: i for i, it in enumerate(data["items"])}
        for it in changed:
            it["modified"] = stamp()
            if it["id"] in idx:
                data["items"][idx[it["id"]]] = it
            else:
                data["items"].append(it)
                idx[it["id"]] = len(data["items"]) - 1
        if deleted:
            data["items"] = [it for it in data["items"] if it["id"] not in set(deleted)]
        _write(FILE, data)
        return data


def find(data, item_id):
    item_id = (item_id or "").strip()
    for it in data["items"]:
        if it["id"] == item_id or (len(item_id) >= 4 and it["id"].startswith(item_id)):
            return it
    return None


def load_state():
    try:
        s = _read(STATE)
        if isinstance(s, dict):
            s.setdefault("fired", {})
            s.setdefault("snoozed", {})
            return s
    except (OSError, ValueError):
        pass
    return {"fired": {}, "snoozed": {}}


def save_state(state):
    cutoff = (datetime.now() - timedelta(days=3)).isoformat()
    state["fired"] = {k: v for k, v in state["fired"].items() if v >= cutoff}
    _write(STATE, state, backup=False)


def file_mtime():
    try:
        return os.path.getmtime(FILE)
    except OSError:
        return 0.0
