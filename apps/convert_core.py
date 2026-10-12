"""Ethical Converter engine: what can become what, and the code that does each conversion.

Audio/video use the FFmpeg binary shipped by the `imageio-ffmpeg` package (GPL build from gyan.dev).
Everything else uses Pillow, PyMuPDF, python-docx and the suite's own document code.
"""
import gzip
import io
import os
import re
import shutil
import subprocess
import tarfile
import threading
import zipfile
from i18n import N_, tr

AUDIO = {".mp3", ".wav", ".flac", ".ogg", ".oga", ".m4a", ".aac", ".wma", ".opus", ".aiff", ".aif", ".amr", ".ac3", ".mka"}
VIDEO = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".flv", ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".mts",
         ".m2ts", ".vob", ".ogv"}
IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".ico", ".psd", ".tga", ".jfif"}
ARCHIVE = {".zip", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz"}
DOCS = {".pdf", ".docx", ".txt", ".md", ".html", ".htm", ".pptx", ".xlsx", ".csv"}

# target label -> output extension, per category
AUDIO_TARGETS = {"MP3": ".mp3", "WAV": ".wav", N_("FLAC (lossless)"): ".flac", "M4A / AAC": ".m4a",
                 N_("OGG Vorbis"): ".ogg", "OPUS": ".opus", "AIFF": ".aiff", "WMA": ".wma",
                 N_("MP4 video (audio + picture)"): ".mp4"}
VIDEO_TARGETS = {"MP4 (H.264)": ".mp4", N_("MP4 (H.265, smaller)"): ".mp4", "MKV": ".mkv", "WebM": ".webm",
                 "MOV": ".mov", "AVI": ".avi", "WMV": ".wmv", N_("GIF (animated)"): ".gif",
                 N_("MP3 (audio only)"): ".mp3", N_("WAV (audio only)"): ".wav", N_("M4A (audio only)"): ".m4a",
                 N_("FLAC (audio only)"): ".flac"}
IMAGE_TARGETS = {"PNG": ".png", "JPG": ".jpg", "WebP": ".webp", "BMP": ".bmp", "GIF": ".gif", "TIFF": ".tif",
                 N_("ICO (icon)"): ".ico", "PDF": ".pdf"}
DOC_TARGETS = {
    ".pdf": {N_("PNG images (one per page)"): ".png", N_("JPG images (one per page)"): ".jpg", N_("Word (.docx)"): ".docx",
             N_("Text (.txt)"): ".txt"},
    ".docx": {"PDF": ".pdf", N_("Text (.txt)"): ".txt", N_("Web page (.html)"): ".html", N_("Markdown (.md)"): ".md",
              N_("OpenDocument (.odt)"): ".odt"},
    ".txt": {"PDF": ".pdf", N_("Word (.docx)"): ".docx"},
    ".md": {"PDF": ".pdf", N_("Word (.docx)"): ".docx", N_("Web page (.html)"): ".html"},
    ".html": {"PDF": ".pdf", N_("Word (.docx)"): ".docx", N_("Text (.txt)"): ".txt"},
    ".htm": {"PDF": ".pdf", N_("Word (.docx)"): ".docx", N_("Text (.txt)"): ".txt"},
    ".pptx": {"PDF": ".pdf", N_("PNG images (one per slide)"): ".png"},
    ".xlsx": {N_("CSV (one per sheet)"): ".csv"},
    ".csv": {N_("Excel (.xlsx)"): ".xlsx"},
}
GUI_JOBS = {".docx", ".txt", ".md", ".html", ".htm", ".pptx"}   # need Qt text/painting on the main thread


def category(path):
    ext = os.path.splitext(path)[1].lower()
    if path.lower().endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        return "archive"
    for name, exts in (("audio", AUDIO), ("video", VIDEO), ("image", IMAGE), ("document", DOCS), ("archive", ARCHIVE)):
        if ext in exts:
            return name
    return "other"


def targets_for(path):
    cat = category(path)
    ext = os.path.splitext(path)[1].lower()
    if cat == "audio":
        return dict(AUDIO_TARGETS)
    if cat == "video":
        return dict(VIDEO_TARGETS)
    if cat == "image":
        return dict(IMAGE_TARGETS)
    if cat == "document":
        return dict(DOC_TARGETS.get(ext, {}))
    if cat == "archive":
        return {N_("Extract (unpack)"): ""}
    return {}


def default_target(path):
    cat = category(path)
    ext = os.path.splitext(path)[1].lower()
    t = targets_for(path)
    if not t:
        return None
    if cat == "audio":
        return "MP3" if ext != ".mp3" else "WAV"
    if cat == "video":
        return "MP4 (H.264)" if ext != ".mp4" else "MP3 (audio only)"
    if cat == "image":
        return "PNG" if ext not in (".png",) else "JPG"
    return next(iter(t))


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    if base.endswith(".tar"):
        base, ext = base[:-4], ".tar" + ext
    i = 1
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


def out_path(src, ext, folder=None, suffix=""):
    base = os.path.splitext(os.path.basename(src))[0]
    return unique_path(os.path.join(folder or os.path.dirname(src), base + suffix + ext))


class Cancelled(Exception):
    pass


# ====================================================================== ffmpeg

def ffmpeg_exe():
    from suite_common import bundled_tool
    if bundled_tool("ffmpeg", "ffmpeg.exe"):          # installed suite ships ffmpegfmpeg.exe
        return bundled_tool("ffmpeg", "ffmpeg.exe")
    here = os.path.dirname(os.path.abspath(__file__))
    bundled = os.path.join(here, "ffmpeg.exe")   # the installer can drop ffmpeg.exe next to the app
    if os.path.exists(bundled):
        return bundled
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg") or "ffmpeg"


NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def probe(path):
    """-> dict(duration seconds, video bool, audio bool, width, height)."""
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    err = r.stderr
    info = {"duration": 0.0, "video": False, "audio": False, "width": 0, "height": 0}
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    for line in err.splitlines():
        if "Stream #" in line and "Video:" in line and "attached pic" not in line:
            info["video"] = True
            m = re.search(r"(\d{2,5})x(\d{2,5})", line)
            if m:
                info["width"], info["height"] = int(m.group(1)), int(m.group(2))
        if "Stream #" in line and "Audio:" in line:
            info["audio"] = True
    return info


def run_ffmpeg(args, duration, progress, cancel):
    cmd = [ffmpeg_exe(), "-hide_banner", "-y", "-nostdin", "-progress", "pipe:1", "-nostats"] + args
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                         errors="replace", creationflags=NO_WINDOW)
    tail = []

    def read_err():
        for line in p.stderr:
            tail.append(line.rstrip())
            del tail[:-30]
    t = threading.Thread(target=read_err, daemon=True)
    t.start()
    for line in p.stdout:
        if cancel.is_set():
            p.kill()
            p.wait()
            raise Cancelled()
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                us = int(line.split("=")[1])
                if duration > 0:
                    progress(min(99, us / 1e6 / duration * 100))
            except ValueError:
                pass
    p.wait()
    t.join(timeout=2)
    if cancel.is_set():
        raise Cancelled()
    if p.returncode != 0:
        msg = next((l for l in reversed(tail) if l and not l.startswith("[")), "") or (tail[-1] if tail else "")
        raise RuntimeError(f"FFmpeg failed: {msg}")


VIDEO_QUALITY = {N_("High quality"): 20, N_("Balanced"): 23, N_("Small file"): 28}
AUDIO_BITRATES = ["320k", "256k", "192k", "160k", "128k", "96k", "64k"]


def _scale_filter(max_h):
    return [] if not max_h else ["-vf", f"scale=-2:'min(ih,{max_h})'"]


def audio_codec_args(ext, bitrate="192k"):
    return {
        ".mp3": ["-c:a", "libmp3lame", "-b:a", bitrate],
        ".wav": ["-c:a", "pcm_s16le"],
        ".flac": ["-c:a", "flac"],
        ".m4a": ["-c:a", "aac", "-b:a", bitrate],
        ".ogg": ["-c:a", "libvorbis", "-b:a", bitrate],
        ".opus": ["-c:a", "libopus", "-b:a", min(bitrate, "256k", key=lambda b: int(b[:-1]))],
        ".aiff": ["-c:a", "pcm_s16be"],
        ".wma": ["-c:a", "wmav2", "-b:a", bitrate],
    }[ext]


def convert_media(src, target, dst, opts, progress, cancel):
    info = probe(src)
    dur = info["duration"]
    ext = os.path.splitext(dst)[1].lower()
    crf = VIDEO_QUALITY.get(opts.get("video_quality", "Balanced"), 23)
    max_h = opts.get("max_height") or None
    abr = opts.get("audio_bitrate", "192k")
    if target == "MP4 video (audio + picture)":
        pic = opts.get("picture")
        if pic and os.path.exists(pic):
            inputs = ["-loop", "1", "-framerate", "2", "-i", pic, "-i", src]
            vf = ["-vf", "scale='min(1920,iw)':-2,pad=ceil(iw/2)*2:ceil(ih/2)*2"]
        else:
            inputs = ["-f", "lavfi", "-i", "color=c=black:s=1280x720:r=2", "-i", src]
            vf = []
        args = inputs + ["-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
                         *vf, "-c:a", "aac", "-b:a", abr, "-shortest", "-movflags", "+faststart", dst]
    elif ext in (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aiff", ".wma"):
        if not info["audio"]:
            raise RuntimeError(tr("This file has no sound to convert."))
        args = ["-i", src, "-vn", "-map", "0:a:0"] + audio_codec_args(ext, abr) + [dst]
    elif ext == ".gif":
        width = int(opts.get("gif_width", 480))
        fps = int(opts.get("gif_fps", 12))
        args = ["-i", src, "-vf", f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];"
                                  f"[b][p]paletteuse=dither=bayer:bayer_scale=4", "-loop", "0", dst]
    else:
        if not info["video"]:
            raise RuntimeError(tr("This file has no video picture."))
        if target == "MP4 (H.265, smaller)":
            v = ["-c:v", "libx265", "-preset", "medium", "-crf", str(crf + 4), "-tag:v", "hvc1", "-pix_fmt", "yuv420p"]
        elif ext == ".webm":
            v = ["-c:v", "libvpx-vp9", "-crf", str(crf + 10), "-b:v", "0", "-deadline", "good", "-cpu-used", "4",
                 "-row-mt", "1", "-pix_fmt", "yuv420p"]
        elif ext == ".avi":
            v = ["-c:v", "mpeg4", "-q:v", "3", "-tag:v", "XVID"]
        elif ext == ".wmv":
            v = ["-c:v", "wmv2", "-b:v", "3M"]
        else:
            v = ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p"]
        a = {".webm": ["-c:a", "libopus", "-b:a", "128k"], ".avi": ["-c:a", "libmp3lame", "-b:a", abr],
             ".wmv": ["-c:a", "wmav2", "-b:a", abr]}.get(ext, ["-c:a", "aac", "-b:a", abr])
        extra = ["-movflags", "+faststart"] if ext in (".mp4", ".mov") else []
        args = ["-i", src, "-map", "0:v:0", "-map", "0:a?"] + _scale_filter(max_h) + v + (a if info["audio"] else ["-an"]) \
            + extra + [dst]
    run_ffmpeg(args, dur, progress, cancel)
    return [dst]


COMPRESS = {  # level -> settings
    1: dict(crf=24, max_h=None, abr="160k", jpg=85, max_dim=None, pdf_dpi=150, pdf_q=80, png_colors=None),
    2: dict(crf=28, max_h=1080, abr="128k", jpg=72, max_dim=2560, pdf_dpi=120, pdf_q=65, png_colors=256),
    3: dict(crf=32, max_h=720, abr="96k", jpg=55, max_dim=1600, pdf_dpi=96, pdf_q=50, png_colors=128),
}


def video_frame(path, seconds, max_w=640):
    """One frame of a video at `seconds` as JPEG bytes (for the trimmer's preview), or b"" if there is none."""
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, seconds):.3f}", "-i", path,
                        "-frames:v", "1", "-vf", f"scale='min({max_w},iw)':-2", "-f", "image2pipe", "-vcodec", "mjpeg",
                        "-q:v", "4", "pipe:1"], capture_output=True, creationflags=NO_WINDOW)
    return r.stdout if r.returncode == 0 else b""


ROTATIONS = {0: None, 90: "transpose=1", 270: "transpose=2", 180: "transpose=1,transpose=1"}


def trim_video(src, start, end, folder, progress, cancel, exact=True, max_h=0, rotate=0, mute=False):
    """Keep start..end (seconds) of a video, optionally smaller (max_h), rotated (90/180/270 clockwise) and without
    sound. Fast mode (exact=False) copies the streams - no quality loss, but cuts land on the nearest keyframe;
    resizing or rotating always re-encodes. Returns the new file's path."""
    length = max(0.1, end - start)
    exact = exact or bool(max_h) or bool(rotate)
    ext = ".mp4" if exact else (os.path.splitext(src)[1].lower() or ".mp4")
    dst = out_path(src, ext, folder, " (trimmed)")
    args = ["-ss", f"{start:.3f}", "-i", src, "-t", f"{length:.3f}"]
    if exact:
        filters = []
        if max_h:
            filters.append(f"scale=-2:'min(ih,{max_h})'")
        if ROTATIONS.get(rotate):
            filters.append(ROTATIONS[rotate])
        if filters:
            args += ["-vf", ",".join(filters)]
        args += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]
        args += ["-an"] if mute else ["-c:a", "aac", "-b:a", "192k"]
        args += ["-movflags", "+faststart", "-metadata:s:v", "rotate=0"]
    else:
        args += ["-map", "0:v?"] + ([] if mute else ["-map", "0:a?"]) + ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        if ext in (".mp4", ".mov", ".m4v"):
            args += ["-movflags", "+faststart"]
    run_ffmpeg(args + [dst], length, progress, cancel)
    return dst


def compress_media(src, level, folder, progress, cancel):
    s = COMPRESS[level]
    info = probe(src)
    ext = os.path.splitext(src)[1].lower()
    if category(src) == "video" and info["video"]:
        dst = out_path(src, ".mp4", folder, " (compressed)")
        args = ["-i", src, "-map", "0:v:0", "-map", "0:a?"] + _scale_filter(s["max_h"]) + \
               ["-c:v", "libx264", "-preset", "medium", "-crf", str(s["crf"]), "-pix_fmt", "yuv420p"] + \
               (["-c:a", "aac", "-b:a", s["abr"]] if info["audio"] else ["-an"]) + ["-movflags", "+faststart", dst]
    else:
        out_ext = ext if ext in (".mp3", ".m4a", ".ogg", ".opus", ".wma") else ".mp3"
        dst = out_path(src, out_ext, folder, " (compressed)")
        args = ["-i", src, "-vn", "-map", "0:a:0"] + audio_codec_args(out_ext, s["abr"]) + [dst]
    run_ffmpeg(args, info["duration"], progress, cancel)
    return [dst]


# ====================================================================== images

def open_image(path):
    from PIL import Image, ImageOps
    if path.lower().endswith(".psd"):
        from psd_tools import PSDImage
        return PSDImage.open(path).composite()
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    return im


def _flatten(im, bg=(255, 255, 255)):
    from PIL import Image
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        out = Image.new("RGB", im.size, bg)
        out.paste(im, mask=im.getchannel("A"))
        return out
    return im.convert("RGB")


def save_image(im, dst, quality=90, max_dim=None, png_colors=None):
    from PIL import Image
    if max_dim and max(im.size) > max_dim:
        im = im.copy()
        im.thumbnail((max_dim, max_dim), Image.LANCZOS)
    ext = os.path.splitext(dst)[1].lower()
    if ext in (".jpg", ".jpeg", ".jfif"):
        _flatten(im).save(dst, "JPEG", quality=quality, optimize=True, progressive=True)
    elif ext == ".png":
        im = im.convert("RGBA") if im.mode not in ("RGB", "RGBA", "L", "LA", "P") else im
        if png_colors:
            im = im.convert("RGBA").quantize(colors=png_colors, method=Image.FASTOCTREE, dither=Image.FLOYDSTEINBERG)
        im.save(dst, "PNG", optimize=True)
    elif ext == ".webp":
        im.save(dst, "WEBP", quality=quality, method=5)
    elif ext == ".bmp":
        _flatten(im).save(dst, "BMP")
    elif ext == ".gif":
        im.convert("RGBA").save(dst, "GIF")
    elif ext in (".tif", ".tiff"):
        im.save(dst, "TIFF", compression="tiff_lzw")
    elif ext == ".ico":
        sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= max(im.size)] or [(16, 16)]
        im.convert("RGBA").save(dst, "ICO", sizes=sizes)
    elif ext == ".pdf":
        _flatten(im).save(dst, "PDF", resolution=150)
    else:
        im.save(dst)
    return dst


def convert_image(src, dst, opts):
    im = open_image(src)
    max_dim = opts.get("image_max") or None
    return [save_image(im, dst, int(opts.get("image_quality", 90)), max_dim)]


def compress_image(src, level, folder):
    s = COMPRESS[level]
    ext = os.path.splitext(src)[1].lower()
    out_ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"
    dst = out_path(src, out_ext, folder, " (compressed)")
    save_image(open_image(src), dst, s["jpg"], s["max_dim"], s["png_colors"] if out_ext == ".png" else None)
    return [dst]


# ====================================================================== documents

def pdf_to_images(src, ext, folder, opts, progress, cancel):
    import pymupdf
    doc = pymupdf.open(src)
    dpi = int(opts.get("pdf_dpi", 150))
    base = os.path.splitext(os.path.basename(src))[0]
    folder = folder or os.path.dirname(src)
    outs = []
    for i, page in enumerate(doc):
        if cancel.is_set():
            raise Cancelled()
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        dst = unique_path(os.path.join(folder, f"{base}_page{i + 1}{ext}"))
        if ext == ".png":
            pix.save(dst)
        else:
            pix.pil_save(dst, quality=int(opts.get("image_quality", 90))) if hasattr(pix, "pil_save") else pix.save(dst)
        outs.append(dst)
        progress((i + 1) / doc.page_count * 100)
    return outs


def pdf_to_docx(src, dst, progress, cancel):
    import docx
    import pymupdf
    from docx.shared import Inches, Pt, RGBColor
    pdf = pymupdf.open(src)
    out = docx.Document()
    for i, page in enumerate(pdf):
        if cancel.is_set():
            raise Cancelled()
        if i:
            out.add_page_break()
        for b in page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT)["blocks"]:
            if b["type"] == 1:
                try:
                    out.add_picture(io.BytesIO(b["image"]), width=Inches(min((b["bbox"][2] - b["bbox"][0]) / 72, 6.5)))
                except Exception:
                    pass
                continue
            para = out.add_paragraph()
            for li, line in enumerate(b["lines"]):
                for s in line["spans"]:
                    run = para.add_run(s["text"])
                    run.font.size = Pt(round(s["size"] * 2) / 2)
                    run.bold = bool(s["flags"] & 16)
                    run.italic = bool(s["flags"] & 2)
                    run.font.color.rgb = RGBColor.from_string(f"{s['color']:06X}")
                    run.font.name = s["font"].split("+")[-1].split("-")[0]
                if li < len(b["lines"]) - 1:
                    para.add_run(" ")
        progress((i + 1) / pdf.page_count * 100)
    out.save(dst)
    return [dst]


def pdf_to_text(src, dst):
    import pymupdf
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write("\n\f".join(p.get_text() for p in pymupdf.open(src)))
    return [dst]


def compress_pdf(src, level, folder):
    import pymupdf
    s = COMPRESS[level]
    dst = out_path(src, ".pdf", folder, " (compressed)")
    doc = pymupdf.open(src)
    if hasattr(doc, "rewrite_images"):
        try:
            doc.rewrite_images(dpi_threshold=s["pdf_dpi"] + 30, dpi_target=s["pdf_dpi"], quality=s["pdf_q"])
        except Exception:
            pass
    try:
        doc.subset_fonts()
    except Exception:
        pass
    doc.save(dst, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True)
    return [dst]


def compress_office(src, level, folder):
    """docx/xlsx/pptx are zip files: shrink the pictures inside and re-zip at maximum compression."""
    from PIL import Image
    s = COMPRESS[level]
    ext = os.path.splitext(src)[1].lower()
    dst = out_path(src, ext, folder, " (compressed)")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            low = item.filename.lower()
            if "/media/" in low and low.endswith((".png", ".jpg", ".jpeg")):
                try:
                    im = Image.open(io.BytesIO(data))
                    buf = io.BytesIO()
                    if s["max_dim"] and max(im.size) > s["max_dim"]:
                        im.thumbnail((s["max_dim"], s["max_dim"]), Image.LANCZOS)
                    if low.endswith(".png"):
                        if s["png_colors"]:
                            im = im.convert("RGBA").quantize(colors=s["png_colors"], method=Image.FASTOCTREE)
                        im.save(buf, "PNG", optimize=True)
                    else:
                        _flatten(im).save(buf, "JPEG", quality=s["jpg"], optimize=True)
                    if buf.tell() < len(data):
                        data = buf.getvalue()
                except Exception:
                    pass
            zout.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED)
    return [dst]


def text_document(src):
    """Load .docx/.txt/.md/.html into (QTextDocument, PageSetup)."""
    from PySide6.QtCore import QUrl
    from docx_io import PageSetup, load_docx
    ext = os.path.splitext(src)[1].lower()
    if ext == ".docx":
        return load_docx(src)
    from word_processor import new_document
    with open(src, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    doc = new_document()
    doc.setBaseUrl(QUrl.fromLocalFile(os.path.dirname(src) + "/"))
    if ext in (".html", ".htm"):
        doc.setHtml(text)
    elif ext == ".md":
        doc.setMarkdown(text)
    else:
        doc.setPlainText(text)
    return doc, PageSetup()


def textdoc_to_pdf(qdoc, setup, dst):
    from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
    from PySide6.QtGui import (QAbstractTextDocumentLayout, QPageLayout, QPageSize, QPainter, QPalette,
                               QPdfWriter)
    from word_processor import draw_header_footer
    w, h = setup.size_px
    ff = qdoc.rootFrame().frameFormat()
    ff.setLeftMargin(setup.margin_left * 96)
    ff.setRightMargin(setup.margin_right * 96)
    ff.setTopMargin(setup.margin_top * 96)
    ff.setBottomMargin(setup.margin_bottom * 96)
    qdoc.rootFrame().setFrameFormat(ff)
    qdoc.setPageSize(QSizeF(w, h))
    writer = QPdfWriter(dst)
    writer.setResolution(300)
    win, hin = setup.width_in, setup.height_in
    writer.setPageLayout(QPageLayout(QPageSize(QSizeF(min(win, hin), max(win, hin)), QPageSize.Inch, "",
                                               QPageSize.ExactMatch),
                                     QPageLayout.Landscape if win > hin else QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
    scale = writer.resolution() / 96
    pages = max(1, qdoc.pageCount())
    p = QPainter(writer)
    try:
        for i in range(pages):
            if i:
                writer.newPage()
            p.save()
            p.scale(scale, scale)
            p.save()
            p.translate(0, -i * h)
            clip = QRectF(0, i * h, w, h)
            p.setClipRect(clip)
            ctx = QAbstractTextDocumentLayout.PaintContext()
            ctx.clip = clip
            pal = ctx.palette
            pal.setColor(QPalette.Text, Qt.black)
            ctx.palette = pal
            qdoc.documentLayout().draw(p, ctx)
            p.restore()
            draw_header_footer(p, setup, i, pages)
            p.restore()
    finally:
        p.end()
    return [dst]


def convert_text_doc(src, ext, dst):
    from PySide6.QtGui import QTextDocumentWriter
    from docx_io import save_docx
    qdoc, setup = text_document(src)
    if ext == ".pdf":
        return textdoc_to_pdf(qdoc, setup, dst)
    if ext == ".docx":
        save_docx(qdoc, setup, dst)
    elif ext == ".odt":
        QTextDocumentWriter(dst, b"odf").write(qdoc)
    else:
        text = qdoc.toHtml() if ext == ".html" else qdoc.toMarkdown() if ext == ".md" else qdoc.toPlainText()
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(text)
    return [dst]


def convert_pptx(src, ext, dst, folder, progress):
    from PySide6.QtCore import QMarginsF, QRectF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter
    from pptx_io import load_pptx
    from slides_app import render_slide, slide_image
    pres, _ = load_pptx(src)
    slides = [s for s in pres.slides if not s.hidden]
    if ext == ".png":
        base = os.path.splitext(os.path.basename(src))[0]
        outs = []
        for i, s in enumerate(slides):
            path = unique_path(os.path.join(folder or os.path.dirname(src), f"{base}_slide{i + 1}.png"))
            slide_image(pres, s, 1920).save(path)
            outs.append(path)
            progress((i + 1) / len(slides) * 100)
        return outs
    w = QPdfWriter(dst)
    w.setResolution(144)
    size = QPageSize(QSizeF(pres.width / 96, pres.height / 96), QPageSize.Inch, "Slide", QPageSize.ExactMatch)
    w.setPageLayout(QPageLayout(size, QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
    p = QPainter(w)
    try:
        for i, s in enumerate(slides):
            if i:
                w.newPage()
            render_slide(p, pres, s, QRectF(0, 0, w.width(), w.height()))
            progress((i + 1) / len(slides) * 100)
    finally:
        p.end()
    return [dst]


def convert_sheet(src, ext, dst, folder):
    from xlsx_io import load_csv, load_xlsx, save_csv, save_xlsx
    if ext == ".xlsx":
        save_xlsx(load_csv(src), dst)
        return [dst]
    wb, _ = load_xlsx(src)
    base = os.path.splitext(os.path.basename(src))[0]
    outs = []
    for sh in wb.sheets:
        name = base if len(wb.sheets) == 1 else f"{base}_{re.sub(r'[^A-Za-z0-9_ -]', '_', sh.name)}"
        path = unique_path(os.path.join(folder or os.path.dirname(src), name + ".csv"))
        save_csv(wb, sh, path)
        outs.append(path)
    return outs


# ====================================================================== archives

def extract_archive(src, folder, progress, cancel):
    base = os.path.basename(src)
    for suffix in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz", ".zip", ".7z", ".tar", ".gz", ".bz2", ".xz"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    dest = unique_path(os.path.join(folder or os.path.dirname(src), base))
    low = src.lower()
    if low.endswith(".zip"):
        with zipfile.ZipFile(src) as z:
            names = z.namelist()
            for i, n in enumerate(names):
                if cancel.is_set():
                    raise Cancelled()
                z.extract(n, dest)
                progress((i + 1) / max(len(names), 1) * 100)
    elif low.endswith(".7z"):
        import py7zr
        with py7zr.SevenZipFile(src, "r") as z:
            z.extractall(dest)
    elif tarfile.is_tarfile(src):
        with tarfile.open(src) as t:
            t.extractall(dest, filter="data")
    elif low.endswith((".gz", ".bz2", ".xz")):
        import bz2
        import lzma
        opener = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}[os.path.splitext(low)[1]]
        os.makedirs(dest, exist_ok=True)
        with opener(src, "rb") as fin, open(os.path.join(dest, base), "wb") as fout:
            shutil.copyfileobj(fin, fout)
    else:
        raise RuntimeError(tr("Unsupported archive type."))
    return [dest]


def make_archive(files, dst, kind, progress, cancel):
    """Pack files (and folders) into one .zip or .7z."""
    entries = []
    for f in files:
        if os.path.isdir(f):
            root = os.path.dirname(f.rstrip("\\/"))
            for dp, _, names in os.walk(f):
                for n in names:
                    full = os.path.join(dp, n)
                    entries.append((full, os.path.relpath(full, root)))
        else:
            entries.append((f, os.path.basename(f)))
    if kind == "7z":
        import py7zr
        with py7zr.SevenZipFile(dst, "w") as z:
            for i, (full, arc) in enumerate(entries):
                if cancel.is_set():
                    raise Cancelled()
                z.write(full, arc)
                progress((i + 1) / len(entries) * 100)
    else:
        seen = set()
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for i, (full, arc) in enumerate(entries):
                if cancel.is_set():
                    raise Cancelled()
                n, k = arc, 1
                while n in seen:
                    b, e = os.path.splitext(arc)
                    n, k = f"{b} ({k}){e}", k + 1
                seen.add(n)
                z.write(full, n)
                progress((i + 1) / len(entries) * 100)
    return [dst]


def combine_pdf(files, dst, progress, cancel):
    """Images and PDFs -> one PDF, in the given order."""
    import pymupdf
    out = pymupdf.open()
    for i, f in enumerate(files):
        if cancel.is_set():
            raise Cancelled()
        c = category(f)
        if f.lower().endswith(".pdf"):
            out.insert_pdf(pymupdf.open(f))
        elif c == "image":
            buf = io.BytesIO()
            _flatten(open_image(f)).save(buf, "PDF", resolution=150)
            out.insert_pdf(pymupdf.open("pdf", buf.getvalue()))
        progress((i + 1) / len(files) * 100)
    if out.page_count == 0:
        raise RuntimeError(tr("Nothing to combine - add images or PDFs."))
    out.save(dst, garbage=3, deflate=True)
    return [dst]


def join_media(files, dst, progress, cancel):
    """Join audio (or same-format videos) end to end."""
    import tempfile
    total = sum(probe(f)["duration"] for f in files)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as lst:
        for f in files:
            lst.write("file '" + f.replace("'", "'\\''") + "'\n")
        name = lst.name
    try:
        ext = os.path.splitext(dst)[1].lower()
        if ext in (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus"):
            n = len(files)
            inputs = []
            for f in files:
                inputs += ["-i", f]
            filt = "".join(f"[{i}:a:0]" for i in range(n)) + f"concat=n={n}:v=0:a=1[a]"
            args = inputs + ["-filter_complex", filt, "-map", "[a]"] + audio_codec_args(ext, "192k") + [dst]
        else:
            args = ["-f", "concat", "-safe", "0", "-i", name, "-c:v", "libx264", "-crf", "22", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "160k", dst]
        run_ffmpeg(args, total, progress, cancel)
    finally:
        os.unlink(name)
    return [dst]


# ====================================================================== dispatcher

def run_convert(src, target, folder, opts, progress, cancel):
    cat = category(src)
    t = targets_for(src)
    if target not in t:
        raise RuntimeError(tr("Can't convert this file to that format."))
    ext = t[target]
    src_ext = os.path.splitext(src)[1].lower()
    if cat == "archive":
        return extract_archive(src, folder, progress, cancel)
    if ext == src_ext and cat in ("audio", "video", "image"):
        suffix = " (converted)"
    else:
        suffix = ""
    dst = out_path(src, ext, folder, suffix)
    if cat in ("audio", "video"):
        return convert_media(src, target, dst, opts, progress, cancel)
    if cat == "image":
        return convert_image(src, dst, opts)
    if src_ext == ".pdf":
        if ext in (".png", ".jpg"):
            return pdf_to_images(src, ext, folder, opts, progress, cancel)
        if ext == ".docx":
            return pdf_to_docx(src, dst, progress, cancel)
        return pdf_to_text(src, dst)
    if src_ext == ".pptx":
        return convert_pptx(src, ext, dst, folder, progress)
    if src_ext in (".xlsx", ".csv"):
        return convert_sheet(src, ext, dst, folder)
    return convert_text_doc(src, ext, dst)


def compress_kind(src):
    cat = category(src)
    ext = os.path.splitext(src)[1].lower()
    if cat in ("audio", "video"):
        return N_("Re-encode smaller (MP4)") if cat == "video" else N_("Re-encode smaller")
    if cat == "image":
        return N_("Smaller picture")
    if ext == ".pdf":
        return N_("Shrink PDF")
    if ext in (".docx", ".xlsx", ".pptx"):
        return N_("Shrink pictures inside")
    return N_("Zip it")


def run_compress(src, level, folder, progress, cancel):
    cat = category(src)
    ext = os.path.splitext(src)[1].lower()
    if cat in ("audio", "video"):
        return compress_media(src, level, folder, progress, cancel)
    if cat == "image":
        return compress_image(src, level, folder)
    if ext == ".pdf":
        return compress_pdf(src, level, folder)
    if ext in (".docx", ".xlsx", ".pptx"):
        return compress_office(src, level, folder)
    kind = "7z" if level == 3 else "zip"
    dst = unique_path(os.path.join(folder or os.path.dirname(src), os.path.basename(src) + "." + kind))
    return make_archive([src], dst, kind, progress, cancel)


def needs_gui_thread(src, task):
    ext = os.path.splitext(src)[1].lower()
    return task == "convert" and ext in GUI_JOBS
