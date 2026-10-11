"""Ethical Converter - video/audio link downloader (yt-dlp) with safety checks.

Safety design (every download):
  1. Only http(s) links to public hosts are accepted (no file://, localhost or private network addresses).
  2. Files are downloaded into a private quarantine folder first, never straight to the user's folder.
  3. Only audio/video file types may leave quarantine (.mp4 .webm .mkv .mov .m4a .mp3 .opus .ogg .aac .flac .wav).
  4. Each file must *really* be audio/video: no executable signature (MZ/ELF/script), and FFmpeg must find an
     audio or video stream in it.
  5. Microsoft Defender scans it (if available). Anything flagged is deleted.
  6. Nothing downloaded is ever opened or run by the app.
"""
import ipaddress
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

import convert_core as cc


def available():
    """False in public builds of the suite, which leave the link downloader (yt-dlp) out on purpose."""
    import importlib.util
    if os.environ.get("ETHICAL_PUBLIC_BUILD"):      # act like the public build (screenshots, testing)
        return False
    return importlib.util.find_spec("yt_dlp") is not None

ALLOWED_EXT = {".mp4", ".webm", ".mkv", ".mov", ".m4a", ".mp3", ".opus", ".ogg", ".aac", ".flac", ".wav"}
BAD_MAGIC = (b"MZ", b"\x7fELF", b"#!", b"PK\x03\x04", b"Rar!", b"7z\xbc\xaf", b"%PDF", b"<html", b"<!DOC", b"<?xml")
QUALITIES = {"Best available": None, "4K (2160p)": 2160, "1440p": 1440, "1080p": 1080, "720p": 720, "480p": 480,
             "360p": 360}
MAX_SIZE = 8 * 1024 ** 3   # 8 GB safety cap
NO_WINDOW = cc.NO_WINDOW


class Blocked(Exception):
    """A safety check refused the link or the file."""


class _QuietLogger:
    """Keep yt-dlp from printing to the console; errors still raise and are shown in the app."""
    def debug(self, msg):
        pass

    info = warning = debug

    def error(self, msg):
        pass


def friendly(ex):
    msg = str(ex).replace("ERROR: ", "").strip()
    low = msg.lower()
    if "sign in" in low or "login" in low or "private video" in low or "members-only" in low:
        return "This video needs a login or is private, so it can't be downloaded."
    if "unsupported url" in low:
        return "This website isn't supported, or the link doesn't point to a video."
    if "not available in your country" in low or "geo" in low and "restrict" in low:
        return "This video is blocked in your country."
    if "video unavailable" in low or "has been removed" in low or "404" in low:
        return "This video is unavailable (removed, private or the link is wrong)."
    if "getaddrinfo" in low or "timed out" in low or "connection" in low:
        return "Couldn't connect - check your internet connection."
    return msg[:300]


def check_url(url):
    url = url.strip()
    if not url:
        raise Blocked("Empty link.")
    if "://" not in url:
        url = "https://" + url
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise Blocked("Only web links (http/https) can be downloaded.")
    host = (u.hostname or "").lower()
    if not host or host in ("localhost",) or host.endswith((".local", ".internal", ".lan")):
        raise Blocked("That link points to this computer or a private network.")
    try:
        ip = ipaddress.ip_address(host)
        addrs = [ip]
    except ValueError:
        try:
            addrs = [ipaddress.ip_address(a[4][0]) for a in socket.getaddrinfo(host, None)]
        except socket.gaierror:
            raise Blocked(f"Can't find the website “{host}” - check the link and your internet connection.")
    if any(a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast for a in addrs):
        raise Blocked("That link points to this computer or a private network.")
    return url


def js_runtimes():
    """yt-dlp needs a JavaScript runtime for YouTube; use whichever is installed."""
    found = {}
    from suite_common import bundled_tool
    if bundled_tool("deno", "deno.exe"):               # installed suite ships deno\deno.exe
        found["deno"] = {"path": bundled_tool("deno", "deno.exe")}
    try:  # the `deno` pip package ships deno.exe with the suite, so friends don't need to install anything
        import deno
        path = deno.find_deno_bin()
        if path and os.path.exists(path):
            found["deno"] = {"path": path}
    except Exception:
        pass
    for name in ("deno", "node", "bun"):
        if name in found:
            continue
        path = shutil.which(name)
        if path:
            found[name] = {"path": path}
    return found


def defender_path():
    p = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Windows Defender", "MpCmdRun.exe")
    return p if os.path.exists(p) else None


def defender_scan(path):
    """-> 'clean', 'threat' or 'unavailable'."""
    exe = defender_path()
    if not exe:
        return "unavailable"
    try:
        r = subprocess.run([exe, "-Scan", "-ScanType", "3", "-File", path, "-DisableRemediation"],
                           capture_output=True, text=True, timeout=600, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    if r.returncode == 0:
        return "clean"
    if r.returncode == 2 or "found" in (r.stdout or "").lower() and "threat" in (r.stdout or "").lower():
        return "threat"
    return "unavailable"


def verify_media(path):
    """Raise Blocked unless the file is genuine audio/video."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in ALLOWED_EXT:
        raise Blocked(f"Blocked a “{ext or 'unknown'}” file - only audio and video files are allowed.")
    with open(path, "rb") as fh:
        head = fh.read(16)
    if any(head.startswith(m) for m in BAD_MAGIC):
        raise Blocked("Blocked: the file isn't really audio/video (it looks like a program, archive or web page).")
    info = cc.probe(path)
    if not (info["audio"] or info["video"]):
        raise Blocked("Blocked: no audio or video found inside the file.")
    if os.path.getsize(path) > MAX_SIZE:
        raise Blocked("Blocked: the file is larger than the 8 GB safety limit.")
    return info


def _base_opts(tmp, playlist, progress, cancel):
    import yt_dlp

    def hook(d):
        if cancel.is_set():
            raise yt_dlp.utils.DownloadCancelled()
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            speed = d.get("speed") or 0
            idx = d.get("info_dict", {}).get("playlist_index")
            label = f"{cc.human(done)}" + (f" of {cc.human(total)}" if total else "") + \
                    (f" · {cc.human(speed)}/s" if speed else "") + (f" · item {idx}" if idx else "")
            progress(min(97, done / total * 97) if total else -1, label)
        elif d.get("status") == "finished":
            progress(97, "Processing…")
    opts = {
        "outtmpl": os.path.join(tmp, "%(title).120B [%(id)s].%(ext)s"),
        "windowsfilenames": True,
        "noplaylist": not playlist,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "ffmpeg_location": cc.ffmpeg_exe(),
        "max_filesize": MAX_SIZE,
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
        "overwrites": True,
        "playlistend": 200,
        "socket_timeout": 30,
        "logger": _QuietLogger(),
    }
    rt = js_runtimes()
    if rt:
        opts["js_runtimes"] = rt
    return opts


def get_info(url):
    import yt_dlp
    url = check_url(url)
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": "in_playlist",
            "noplaylist": False, "playlistend": 200, "socket_timeout": 30, "logger": _QuietLogger()}
    rt = js_runtimes()
    if rt:
        opts["js_runtimes"] = rt
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as ex:
        raise RuntimeError(friendly(ex))
    entries = info.get("entries")
    return {"title": info.get("title") or url, "uploader": info.get("uploader") or info.get("channel") or "",
            "duration": info.get("duration"), "site": info.get("extractor_key") or "",
            "playlist": entries is not None, "count": len(list(entries)) if entries is not None else 1,
            "thumbnail": info.get("thumbnail")}


def download(url, folder, mode="video", quality=None, audio_format="mp3", container="mp4", playlist=False,
             scan=True, progress=lambda pct, text: None, cancel=None):
    """Download one link. Returns (saved file paths, notes). Raises Blocked / cc.Cancelled / Exception."""
    import threading
    import yt_dlp
    cancel = cancel or threading.Event()
    url = check_url(url)
    os.makedirs(folder, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="ethical_quarantine_")
    notes = []
    try:
        opts = _base_opts(tmp, playlist, progress, cancel)
        h = quality
        hf = f"[height<={h}]" if h else ""
        if mode == "audio":
            opts["format"] = "bestaudio/best"
            codec = {"mp3": "mp3", "m4a": "m4a", "opus": "opus", "wav": "wav", "flac": "flac"}[audio_format]
            pp = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
            if codec in ("mp3", "m4a", "opus"):
                pp["preferredquality"] = "192" if codec != "opus" else "160"
            opts["postprocessors"] = [pp, {"key": "FFmpegMetadata"}]
        elif container == "mp4":
            # prefer H.264 + AAC so it plays everywhere; fall back to anything, merged into MP4
            opts["format"] = (f"bv*{hf}[vcodec^=avc1]+ba[ext=m4a]/b{hf}[ext=mp4]/bv*{hf}+ba/b{hf}/bv*+ba/b")
            opts["merge_output_format"] = "mp4"
            opts["postprocessors"] = [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}]
        else:
            opts["format"] = f"bv*{hf}+ba/b{hf}/bv*+ba/b"
            opts["merge_output_format"] = "mkv"
        progress(-1, "Connecting…")
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except yt_dlp.utils.DownloadCancelled:
            raise cc.Cancelled()
        except yt_dlp.utils.DownloadError as ex:
            if cancel.is_set():
                raise cc.Cancelled()
            raise RuntimeError(friendly(ex))
        files = [os.path.join(tmp, f) for f in os.listdir(tmp)
                 if os.path.isfile(os.path.join(tmp, f)) and not f.endswith((".part", ".ytdl", ".temp"))]
        if not files:
            raise RuntimeError("Nothing was downloaded (the video may be too big, blocked in your country, or removed).")
        saved = []
        for f in sorted(files):
            if cancel.is_set():
                raise cc.Cancelled()
            name = os.path.basename(f)
            try:
                progress(98, "Safety check…")
                verify_media(f)
                if scan:
                    progress(99, "Virus scan…")
                    result = defender_scan(f)
                    if result == "threat":
                        raise Blocked("Microsoft Defender found a threat in the download - it was deleted.")
                    if result == "unavailable" and "Defender scan unavailable" not in notes:
                        notes.append("Defender scan unavailable")
            except Blocked as ex:
                os.remove(f)
                notes.append(f"{name}: {ex}")
                continue
            dst = cc.unique_path(os.path.join(folder, name))
            shutil.move(f, dst)
            saved.append(dst)
        if not saved:
            raise Blocked(notes[-1].split(": ", 1)[-1] if notes else "Every downloaded file failed the safety check.")
        progress(100, "Done")
        return saved, notes
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def update_downloader():
    """Websites change often; newer yt-dlp versions keep downloads working. Returns (ok, message)."""
    if getattr(sys, "frozen", False):
        return False, "Updates come with new versions of EthicalApp."
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"], capture_output=True,
                       text=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout)[-400:]
    v = subprocess.run([sys.executable, "-c", "import yt_dlp; print(yt_dlp.version.__version__)"],
                       capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip()
    return True, f"The downloader is up to date (version {v}). Restart Ethical Converter to use it."
