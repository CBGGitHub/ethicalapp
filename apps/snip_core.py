"""Screen capture helpers for Ethical Snip (also used by the AI tool in mcp_server.py). Windows only.

- grab_screens(): a frozen picture of every monitor (taken before the snip overlay appears)
- list_windows(): visible top-level windows in front-to-back order with their real on-screen frame
- capture_window(hwnd): a window's own pixels via PrintWindow (works even if it's partly covered)
Coordinates: Win32 gives physical pixels. Qt (per-monitor DPI aware) keeps each screen's top-left in physical
pixels and scales its size by devicePixelRatio, so physical -> screen-local pixmap pixels = phys - screen origin.
"""
import ctypes
import os
from ctypes import wintypes
from datetime import datetime

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
dwmapi = ctypes.windll.dwmapi
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
PW_RENDERFULLCONTENT = 2

user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetWindowDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                            ctypes.c_void_p, wintypes.UINT]

IGNORE_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow", "WorkerW",
                  "Progman", "Shell_InputSwitchTopLevelWindow", "NotifyIconOverflowWindow"}


def default_folder():
    """Pictures\\Ethical Snips (created when first needed)."""
    buf = ctypes.create_unicode_buffer(260)
    pictures = os.path.join(os.path.expanduser("~"), "Pictures")
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x27, None, 0, buf) == 0:   # CSIDL_MYPICTURES
        pictures = buf.value
    return os.path.join(pictures, "Ethical Snips")


def new_file_name(folder, ext="png"):
    stamp = datetime.now().strftime("%Y-%m-%d %H.%M.%S")
    base = os.path.join(folder, f"Snip {stamp}")
    path, k = f"{base}.{ext}", 2
    while os.path.exists(path):
        path, k = f"{base} ({k}).{ext}", k + 1
    return path


def _frame(hwnd):
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def _cloaked(hwnd):
    v = ctypes.c_int(0)
    dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v))
    return v.value != 0


def window_title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def list_windows(skip_pid=None):
    """[(hwnd, title, (l, t, r, b) physical)] for visible normal windows, frontmost first."""
    out = []
    cls = ctypes.create_unicode_buffer(256)

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd) or _cloaked(hwnd):
            return True
        if user32.GetAncestor(hwnd, 3) != hwnd:            # GA_ROOTOWNER: skip owned pop-ups' duplicates
            pass
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value in IGNORE_CLASSES:
            return True
        if skip_pid is not None:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == skip_pid:
                return True
        title = window_title(hwnd)
        l, t, r, b = _frame(hwnd)
        if r - l < 40 or b - t < 30 or not title.strip():
            return True
        out.append((hwnd, title, (l, t, r, b)))
        return True
    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(cb), 0)
    return out


def find_window(title_part):
    title_part = (title_part or "").lower().strip()
    for hwnd, title, rect in list_windows(skip_pid=os.getpid()):
        if title_part in title.lower():
            return hwnd, title, rect
    return None


def capture_window(hwnd):
    """The window's own pixels (even when partly covered by other windows), cropped to its visible frame.
    Returns a QImage, or None if the window can't be drawn (some apps refuse PrintWindow)."""
    from PySide6.QtGui import QImage
    wr = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wr))
    w, h = wr.right - wr.left, wr.bottom - wr.top
    if w <= 0 or h <= 0:
        return None
    hdc_win = user32.GetWindowDC(hwnd)
    hdc = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(hdc, bmp)
    try:
        if not user32.PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT):
            return None

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]
        bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(hdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
        img = QImage(buf.raw, w, h, w * 4, QImage.Format_RGB32).copy()
    finally:
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(hdc)
        user32.ReleaseDC(hwnd, hdc_win)
    l, t, r, b = _frame(hwnd)                    # drop the invisible resize border around Windows 10/11 windows
    return img.copy(l - wr.left, t - wr.top, r - l, b - t)


def grab_screens():
    """[(QScreen, QPixmap)] - a picture of each monitor at full resolution."""
    from PySide6.QtGui import QGuiApplication
    return [(s, s.grabWindow(0)) for s in QGuiApplication.screens()]


def grab_all_screens():
    """One QImage of the whole desktop (all monitors), in physical pixels."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    shots = grab_screens()
    rects = []
    for s, pm in shots:
        o = s.geometry().topLeft()
        rects.append(QRect(o.x(), o.y(), pm.width(), pm.height()))
    union = rects[0]
    for r in rects[1:]:
        union = union.united(r)
    img = QImage(union.size(), QImage.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    for (s, pm), r in zip(shots, rects):
        p.drawImage(r.topLeft() - union.topLeft(), pm.toImage())
    p.end()
    return img
