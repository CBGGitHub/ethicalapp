"""Ethical Photo core: layered image document, compositing, adjustments, filters and file I/O."""
import io
import struct
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

import numpy as np
from PIL import Image, ImageFilter, ImageOps
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QRegion
from i18n import N_

FMT = QImage.Format_ARGB32_Premultiplied

BLEND_MODES = {  # name (English, kept in files) -> (QPainter mode, PSD key)
    N_("Normal"): (QPainter.CompositionMode_SourceOver, b"norm"),
    N_("Multiply"): (QPainter.CompositionMode_Multiply, b"mul "),
    N_("Screen"): (QPainter.CompositionMode_Screen, b"scrn"),
    N_("Overlay"): (QPainter.CompositionMode_Overlay, b"over"),
    N_("Darken"): (QPainter.CompositionMode_Darken, b"dark"),
    N_("Lighten"): (QPainter.CompositionMode_Lighten, b"lite"),
    N_("Color Dodge"): (QPainter.CompositionMode_ColorDodge, b"div "),
    N_("Color Burn"): (QPainter.CompositionMode_ColorBurn, b"idiv"),
    N_("Soft Light"): (QPainter.CompositionMode_SoftLight, b"sLit"),
    N_("Hard Light"): (QPainter.CompositionMode_HardLight, b"hLit"),
    N_("Difference"): (QPainter.CompositionMode_Difference, b"diff"),
    N_("Exclusion"): (QPainter.CompositionMode_Exclusion, b"smud"),
    N_("Linear Dodge (Add)"): (QPainter.CompositionMode_Plus, b"lddg"),
}
PSD_TO_MODE = {v[1]: k for k, v in BLEND_MODES.items()}


# ====================================================================== model

@dataclass
class Layer:
    name: str
    image: QImage
    x: int = 0
    y: int = 0
    visible: bool = True
    opacity: float = 1.0
    blend: str = "Normal"
    locked: bool = False
    text: dict = None            # text layer settings (re-editable)

    def rect(self):
        return QRect(self.x, self.y, self.image.width(), self.image.height())

    def copy(self):
        return Layer(self.name, QImage(self.image), self.x, self.y, self.visible, self.opacity, self.blend,
                     self.locked, dict(self.text) if self.text else None)


@dataclass
class Document:
    width: int
    height: int
    layers: list = field(default_factory=list)
    active: int = 0
    selection: QImage = None     # Grayscale8 mask (canvas size) or None = everything
    dpi: int = 72

    def snapshot(self):
        # QImage is copy-on-write, so this is cheap until something is painted
        return ([l.copy() for l in self.layers], self.active, self.width, self.height,
                QImage(self.selection) if self.selection is not None else None)

    def restore(self, snap):
        layers, self.active, self.width, self.height, sel = snap
        self.layers = [l.copy() for l in layers]
        self.selection = QImage(sel) if sel is not None else None

    @property
    def layer(self):
        return self.layers[self.active] if self.layers else None


def blank(w, h, color=Qt.transparent):
    img = QImage(max(1, w), max(1, h), FMT)
    img.fill(color)
    return img


def new_document(w, h, background="white"):
    doc = Document(w, h)
    if background == "transparent":
        doc.layers = [Layer("Layer 1", blank(w, h))]
    else:
        doc.layers = [Layer("Background", blank(w, h, QColor(background)))]
    return doc


def composite(doc, rect=None, background=None):
    """Flatten visible layers into one image (canvas size)."""
    out = blank(doc.width, doc.height, background if background is not None else Qt.transparent)
    p = QPainter(out)
    for l in doc.layers:
        if not l.visible or l.opacity <= 0:
            continue
        p.setOpacity(l.opacity)
        p.setCompositionMode(BLEND_MODES.get(l.blend, BLEND_MODES["Normal"])[0])
        p.drawImage(l.x, l.y, l.image)
    p.end()
    return out


# ====================================================================== numpy helpers

def to_array(img):
    """QImage -> HxWx4 uint8 RGBA (straight alpha)."""
    im = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = im.width(), im.height()
    ptr = im.constBits()
    arr = np.frombuffer(ptr, dtype=np.uint8, count=im.sizeInBytes()).reshape(h, im.bytesPerLine())
    return arr[:, :w * 4].reshape(h, w, 4).copy()


def from_array(arr):
    arr = np.ascontiguousarray(arr.astype(np.uint8))
    h, w = arr.shape[:2]
    img = QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
    return img.convertToFormat(FMT)


def to_pil(img):
    return Image.fromarray(to_array(img), "RGBA")


def from_pil(im):
    return from_array(np.asarray(im.convert("RGBA")))


def mask_array(mask):
    """Grayscale8 QImage -> HxW float 0..1."""
    w, h = mask.width(), mask.height()
    arr = np.frombuffer(mask.constBits(), dtype=np.uint8, count=mask.sizeInBytes()).reshape(h, mask.bytesPerLine())
    return arr[:, :w].astype(np.float32) / 255.0


def mask_from_array(a):
    a = np.ascontiguousarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
    h, w = a.shape
    return QImage(a.data, w, h, w, QImage.Format_Grayscale8).copy()


def apply_with_mask(layer, new_img, doc):
    """Replace layer pixels with new_img, but only inside the selection (soft-edged)."""
    if doc.selection is None:
        layer.image = new_img
        return
    m = mask_array(doc.selection)
    r = layer.rect().intersected(QRect(0, 0, doc.width, doc.height))
    old = to_array(layer.image).astype(np.float32)
    new = to_array(new_img).astype(np.float32)
    full = np.zeros(old.shape[:2], np.float32)
    lx, ly = r.x() - layer.x, r.y() - layer.y
    full[ly:ly + r.height(), lx:lx + r.width()] = m[r.y():r.y() + r.height(), r.x():r.x() + r.width()]
    f = full[..., None]
    layer.image = from_array(old * (1 - f) + new * f)


# ====================================================================== adjustments

def adj_brightness_contrast(arr, brightness=0, contrast=0):
    rgb = arr[..., :3].astype(np.float32)
    rgb += brightness * 2.55
    c = (100 + contrast) / 100.0
    rgb = (rgb - 128) * (c * c if contrast > 0 else c) + 128
    out = arr.copy()
    out[..., :3] = np.clip(rgb, 0, 255)
    return out


def adj_levels(arr, black=0, white=255, gamma=1.0, out_black=0, out_white=255):
    rgb = arr[..., :3].astype(np.float32)
    rgb = np.clip((rgb - black) / max(white - black, 1), 0, 1) ** (1 / max(gamma, 0.01))
    rgb = out_black + rgb * (out_white - out_black)
    out = arr.copy()
    out[..., :3] = np.clip(rgb, 0, 255)
    return out


def rgb_to_hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    m = d > 1e-6
    rm = m & (mx == r)
    gm = m & (mx == g) & ~rm
    bm = m & ~rm & ~gm
    h[rm] = ((g - b)[rm] / d[rm]) % 6
    h[gm] = (b - r)[gm] / d[gm] + 2
    h[bm] = (r - g)[bm] / d[bm] + 4
    h /= 6
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    return h, s, mx


def hsv_to_rgb(h, s, v):
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    choices = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)]
    out = np.zeros(h.shape + (3,), np.float32)
    for k, (a, b, c) in enumerate(choices):
        sel = i == k
        out[sel, 0], out[sel, 1], out[sel, 2] = a[sel], b[sel], c[sel]
    return out


def adj_hue_saturation(arr, hue=0, saturation=0, lightness=0, colorize=False):
    rgb = arr[..., :3].astype(np.float32) / 255
    h, s, v = rgb_to_hsv(rgb)
    if colorize:
        h = np.full_like(h, (hue % 360) / 360)
        s = np.full_like(s, max(0, saturation + 50) / 100)
    else:
        h = (h + hue / 360) % 1
        s = np.clip(s * (1 + saturation / 100), 0, 1)
    rgb = hsv_to_rgb(h, s, v)
    if lightness > 0:
        rgb = rgb + (1 - rgb) * lightness / 100
    elif lightness < 0:
        rgb = rgb * (1 + lightness / 100)
    out = arr.copy()
    out[..., :3] = np.clip(rgb * 255, 0, 255)
    return out


def adj_color_balance(arr, cyan_red=0, magenta_green=0, yellow_blue=0):
    rgb = arr[..., :3].astype(np.float32)
    rgb[..., 0] += cyan_red * 1.0
    rgb[..., 1] += magenta_green * 1.0
    rgb[..., 2] += yellow_blue * 1.0
    out = arr.copy()
    out[..., :3] = np.clip(rgb, 0, 255)
    return out


def adj_exposure(arr, exposure=0.0, gamma=1.0):
    rgb = (arr[..., :3].astype(np.float32) / 255) ** 2.2
    rgb = rgb * (2 ** exposure)
    rgb = np.clip(rgb, 0, 1) ** (1 / 2.2 / max(gamma, 0.01))
    out = arr.copy()
    out[..., :3] = np.clip(rgb * 255, 0, 255)
    return out


def adj_vibrance(arr, vibrance=0):
    rgb = arr[..., :3].astype(np.float32)
    mx, mn = rgb.max(-1, keepdims=True), rgb.min(-1, keepdims=True)
    sat = (mx - mn) / 255
    avg = rgb.mean(-1, keepdims=True)
    amt = vibrance / 100 * (1 - sat)
    rgb = rgb + (rgb - avg) * amt
    out = arr.copy()
    out[..., :3] = np.clip(rgb, 0, 255)
    return out


def adj_black_white(arr, **_):
    g = arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114
    out = arr.copy()
    out[..., 0] = out[..., 1] = out[..., 2] = np.clip(g, 0, 255)
    return out


def adj_sepia(arr, **_):
    rgb = arr[..., :3].astype(np.float32)
    m = np.array([[0.393, 0.769, 0.189], [0.349, 0.686, 0.168], [0.272, 0.534, 0.131]], np.float32)
    out = arr.copy()
    out[..., :3] = np.clip(rgb @ m.T, 0, 255)
    return out


def adj_invert(arr, **_):
    out = arr.copy()
    out[..., :3] = 255 - out[..., :3]
    return out


def adj_threshold(arr, level=128):
    g = arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114
    v = np.where(g >= level, 255, 0)
    out = arr.copy()
    out[..., 0] = out[..., 1] = out[..., 2] = v
    return out


def adj_posterize(arr, levels=4):
    levels = max(2, int(levels))
    step = 255 / (levels - 1)
    out = arr.copy()
    out[..., :3] = np.clip(np.round(arr[..., :3] / step) * step, 0, 255)
    return out


def adj_temperature(arr, temperature=0, tint=0):
    rgb = arr[..., :3].astype(np.float32)
    rgb[..., 0] += temperature * 0.6
    rgb[..., 2] -= temperature * 0.6
    rgb[..., 1] -= tint * 0.5
    out = arr.copy()
    out[..., :3] = np.clip(rgb, 0, 255)
    return out


def auto_contrast(arr, **_):
    out = arr.copy()
    for c in range(3):
        ch = arr[..., c][arr[..., 3] > 0] if (arr[..., 3] > 0).any() else arr[..., c]
        lo, hi = np.percentile(ch, 0.5), np.percentile(ch, 99.5)
        if hi > lo:
            out[..., c] = np.clip((arr[..., c].astype(np.float32) - lo) * 255 / (hi - lo), 0, 255)
    return out


# ====================================================================== filters (Pillow / numpy)

def _pil_filter(fn):
    def run(arr, **kw):
        im = Image.fromarray(arr, "RGBA")
        rgb, a = im.convert("RGB"), im.getchannel("A")
        out = fn(rgb, **kw).convert("RGB")
        out.putalpha(a)
        return np.asarray(out).copy()
    return run


def _blur_all(arr, radius=4):
    # blur premultiplied colour so transparent edges don't turn dark
    a = arr[..., 3:4].astype(np.float32) / 255
    pre = np.concatenate([arr[..., :3] * a, a * 255], -1).astype(np.float32)
    from scipy.ndimage import gaussian_filter
    out = np.stack([gaussian_filter(pre[..., c], radius / 2) for c in range(4)], -1)
    alpha = out[..., 3:4] / 255
    rgb = np.where(alpha > 1e-4, out[..., :3] / np.maximum(alpha, 1e-4), 0)
    return np.clip(np.concatenate([rgb, out[..., 3:4]], -1), 0, 255).astype(np.uint8)


def f_motion_blur(arr, distance=20, angle=0):
    from scipy.ndimage import convolve
    n = max(3, int(distance) | 1)
    k = np.zeros((n, n), np.float32)
    c = n // 2
    rad = np.radians(angle)
    for i in range(n):
        t = i - c
        x, y = int(round(c + t * np.cos(rad))), int(round(c - t * np.sin(rad)))
        k[y, x] = 1
    k /= k.sum()
    out = arr.copy()
    for ch in range(3):
        out[..., ch] = np.clip(convolve(arr[..., ch].astype(np.float32), k, mode="nearest"), 0, 255)
    return out


def f_noise(arr, amount=10, mono=True):
    rng = np.random.default_rng()
    shape = arr.shape[:2] + ((1,) if mono else (3,))
    n = rng.normal(0, amount * 2.55, shape)
    out = arr.copy()
    out[..., :3] = np.clip(arr[..., :3] + n, 0, 255)
    return out


def f_pixelate(arr, size=10):
    size = max(2, int(size))
    h, w = arr.shape[:2]
    im = Image.fromarray(arr, "RGBA")
    small = im.resize((max(1, w // size), max(1, h // size)), Image.BOX)
    return np.asarray(small.resize((w, h), Image.NEAREST)).copy()


def f_vignette(arr, amount=50, size=60):
    h, w = arr.shape[:2]
    y, x = np.ogrid[:h, :w]
    d = np.sqrt(((x - w / 2) / (w / 2)) ** 2 + ((y - h / 2) / (h / 2)) ** 2)
    start = size / 100
    f = np.clip((d - start) / max(1.42 - start, 0.01), 0, 1) ** 1.5 * amount / 100
    out = arr.copy()
    out[..., :3] = np.clip(arr[..., :3] * (1 - f[..., None]), 0, 255)
    return out


def f_oil(arr, radius=3):
    return _pil_filter(lambda im, radius=3: im.filter(ImageFilter.ModeFilter(max(3, int(radius) * 2 + 1))))(arr, radius=radius)


FILTERS = {
    N_("Gaussian Blur"): (lambda arr, radius=4: _blur_all(arr, radius), [("radius", N_("Radius"), 0.5, 100, 4)]),
    N_("Motion Blur"): (f_motion_blur, [("distance", N_("Distance"), 3, 200, 20), ("angle", N_("Angle"), -180, 180, 0)]),
    N_("Sharpen"): (_pil_filter(lambda im, amount=100, radius=2: im.filter(ImageFilter.UnsharpMask(radius, int(amount), 2))),
                [("amount", N_("Amount %"), 10, 500, 100), ("radius", N_("Radius"), 0.5, 20, 2)]),
    N_("Reduce Noise (Median)"): (_pil_filter(lambda im, size=3: im.filter(ImageFilter.MedianFilter(max(3, int(size) | 1)))),
                              [("size", N_("Size"), 3, 15, 3)]),
    N_("Add Noise"): (f_noise, [("amount", N_("Amount"), 1, 100, 10)]),
    N_("Pixelate"): (f_pixelate, [("size", N_("Cell size"), 2, 200, 10)]),
    N_("Vignette"): (f_vignette, [("amount", N_("Amount"), 0, 100, 50), ("size", N_("Clear centre %"), 0, 100, 60)]),
    N_("Emboss"): (_pil_filter(lambda im: im.filter(ImageFilter.EMBOSS)), []),
    N_("Find Edges"): (_pil_filter(lambda im: ImageOps.invert(im.filter(ImageFilter.FIND_EDGES))), []),
    N_("Oil Paint"): (f_oil, [("radius", N_("Brush"), 1, 8, 3)]),
}

ADJUSTMENTS = {
    N_("Brightness/Contrast"): (adj_brightness_contrast, [("brightness", N_("Brightness"), -100, 100, 0),
                                                      ("contrast", N_("Contrast"), -100, 100, 0)]),
    N_("Levels"): (adj_levels, [("black", N_("Input black"), 0, 254, 0), ("white", N_("Input white"), 1, 255, 255),
                            ("gamma", N_("Midtones (gamma)"), 0.1, 5, 1.0), ("out_black", N_("Output black"), 0, 255, 0),
                            ("out_white", N_("Output white"), 0, 255, 255)]),
    N_("Hue/Saturation"): (adj_hue_saturation, [("hue", N_("Hue"), -180, 180, 0), ("saturation", N_("Saturation"), -100, 100, 0),
                                            ("lightness", N_("Lightness"), -100, 100, 0)]),
    N_("Vibrance"): (adj_vibrance, [("vibrance", N_("Vibrance"), -100, 100, 30)]),
    N_("Exposure"): (adj_exposure, [("exposure", N_("Exposure (stops)"), -5, 5, 0), ("gamma", N_("Gamma"), 0.1, 3, 1.0)]),
    N_("Color Balance"): (adj_color_balance, [("cyan_red", N_("Cyan ↔ Red"), -100, 100, 0),
                                          ("magenta_green", N_("Magenta ↔ Green"), -100, 100, 0),
                                          ("yellow_blue", N_("Yellow ↔ Blue"), -100, 100, 0)]),
    N_("Temperature/Tint"): (adj_temperature, [("temperature", N_("Cool ↔ Warm"), -100, 100, 0),
                                           ("tint", N_("Green ↔ Magenta"), -100, 100, 0)]),
    N_("Threshold"): (adj_threshold, [("level", N_("Level"), 1, 255, 128)]),
    N_("Posterize"): (adj_posterize, [("levels", N_("Levels"), 2, 32, 4)]),
}
INSTANT = {N_("Invert"): adj_invert, N_("Black & White"): adj_black_white, N_("Sepia"): adj_sepia,
           N_("Auto Contrast"): auto_contrast}


# ====================================================================== selection helpers

def region_mask(doc, x, y, tolerance=32, contiguous=True, sample_all=False):
    """Magic wand / bucket: mask of pixels similar to the one at (x, y)."""
    src = composite(doc) if sample_all else None
    if src is None:
        l = doc.layer
        src = blank(doc.width, doc.height)
        p = QPainter(src)
        p.drawImage(l.x, l.y, l.image)
        p.end()
    arr = to_array(src).astype(np.int16)
    if not (0 <= x < doc.width and 0 <= y < doc.height):
        return None
    ref = arr[y, x]
    diff = np.abs(arr - ref).max(-1)
    sim = diff <= tolerance
    if contiguous:
        from scipy.ndimage import label
        lab, _ = label(sim)
        sim = lab == lab[y, x]
    return mask_from_array(sim.astype(np.float32))


def path_mask(doc, path, antialias=True):
    m = QImage(doc.width, doc.height, QImage.Format_Grayscale8)
    m.fill(0)
    p = QPainter(m)
    p.setRenderHint(QPainter.Antialiasing, antialias)
    p.fillPath(path, QColor(255, 255, 255))
    p.end()
    return m


def combine_masks(a, b, mode):
    if a is None or mode == "replace":
        return b
    ma, mb = mask_array(a), mask_array(b)
    if mode == "add":
        r = np.maximum(ma, mb)
    elif mode == "subtract":
        r = np.clip(ma - mb, 0, 1)
    else:
        r = np.minimum(ma, mb)
    return mask_from_array(r)


def mask_outline(mask):
    """Selection outline as a QPainterPath (for marching ants)."""
    from PySide6.QtGui import QBitmap
    inv = QImage(mask)
    inv.invertPixels()  # QRegion(QBitmap) takes the black (color1) pixels
    bm = QBitmap.fromImage(inv.convertToFormat(QImage.Format_Mono, Qt.ThresholdDither), Qt.ThresholdDither)
    path = QPainterPath()
    path.addRegion(QRegion(bm))
    return path.simplified()


def mask_bounds(mask):
    a = mask_array(mask) > 0.01
    ys, xs = np.nonzero(a)
    if len(xs) == 0:
        return None
    return QRect(int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))


def feather_mask(mask, radius):
    from scipy.ndimage import gaussian_filter
    return mask_from_array(gaussian_filter(mask_array(mask), radius / 2))


def grow_mask(mask, px):
    from scipy.ndimage import binary_dilation, binary_erosion
    a = mask_array(mask) > 0.5
    a = binary_dilation(a, iterations=px) if px > 0 else binary_erosion(a, iterations=-px)
    return mask_from_array(a.astype(np.float32))


# ====================================================================== file I/O

READ_FORMATS = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff *.ico *.psd *.ora);;All files (*)"  # app: tr()


def load_image_file(path):
    """-> (Document, warnings)."""
    low = path.lower()
    if low.endswith(".psd"):
        return load_psd(path)
    if low.endswith(".ora"):
        return load_ora(path), []
    im = Image.open(path)
    try:
        dpi = int(im.info.get("dpi", (72, 72))[0])
    except Exception:
        dpi = 72
    im = ImageOps.exif_transpose(im)
    img = from_pil(im)
    doc = Document(img.width(), img.height(), dpi=dpi)
    doc.layers = [Layer("Background", img)]
    return doc, []


def load_psd(path):
    from psd_tools import PSDImage
    psd = PSDImage.open(path)
    doc = Document(psd.width, psd.height)
    warnings = set()

    def walk(group):
        for layer in group:
            if layer.is_group():
                if not layer.visible:
                    continue
                walk(layer)
                continue
            if layer.kind in ("adjustment", "fill") and layer.kind == "adjustment":
                warnings.add(N_("adjustment layers"))
                continue
            try:
                if layer.has_effects():
                    warnings.add(N_("layer effects (shadows, strokes…)"))
            except Exception:
                pass
            im = layer.topil()
            if im is None:
                continue
            l = Layer(layer.name or "Layer", from_pil(im), layer.left, layer.top, layer.visible,
                      layer.opacity / 255, PSD_TO_MODE.get(layer.blend_mode.value if hasattr(layer.blend_mode, "value")
                                                           else b"norm", "Normal"))
            if layer.kind == "type":
                warnings.add(N_("text layers (kept as pictures)"))
            doc.layers.append(l)
    walk(psd)
    if not doc.layers:
        doc.layers = [Layer("Background", from_pil(psd.composite()))]
    doc.active = len(doc.layers) - 1
    return doc, sorted(warnings)


def save_flat(doc, path, quality=90):
    img = composite(doc)
    low = path.lower()
    im = to_pil(img)
    if low.endswith((".jpg", ".jpeg")):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        bg.save(path, quality=quality, optimize=True, dpi=(doc.dpi, doc.dpi))
    elif low.endswith(".bmp"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        bg.save(path)
    elif low.endswith(".webp"):
        im.save(path, quality=quality)
    elif low.endswith(".ico"):
        im.save(path, sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256) if s <= max(im.size)] or [(16, 16)])
    elif low.endswith(".gif"):
        im.save(path)
    elif low.endswith((".tif", ".tiff")):
        im.save(path, compression="tiff_lzw", dpi=(doc.dpi, doc.dpi))
    elif low.endswith(".pdf"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        bg.save(path, resolution=doc.dpi)
    else:
        im.save(path, optimize=True, dpi=(doc.dpi, doc.dpi))


def _png_bytes(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def save_ora(doc, path):
    """OpenRaster: an open, layered format (zip of PNGs + stack.xml)."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "image/openraster", compress_type=zipfile.ZIP_STORED)
        stack = ET.Element("image", w=str(doc.width), h=str(doc.height), xres=str(doc.dpi), yres=str(doc.dpi))
        st = ET.SubElement(stack, "stack")
        for i, l in enumerate(reversed(doc.layers)):
            name = f"data/layer{i}.png"
            z.writestr(name, _png_bytes(l.image))
            attrs = dict(src=name, name=l.name, x=str(l.x), y=str(l.y), opacity=f"{l.opacity:.3f}",
                         visibility="visible" if l.visible else "hidden",
                         **{"composite-op": "svg:" + l.blend.lower().split(" (")[0].replace(" ", "-")})
            if l.text:
                attrs["ethical-text"] = repr(l.text)
            ET.SubElement(st, "layer", **attrs)
        z.writestr("stack.xml", ET.tostring(stack, encoding="unicode"))
        z.writestr("mergedimage.png", _png_bytes(composite(doc)))
        thumb = composite(doc).scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        z.writestr("Thumbnails/thumbnail.png", _png_bytes(thumb))


def load_ora(path):
    import ast
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("stack.xml"))
        doc = Document(int(root.get("w")), int(root.get("h")), dpi=int(float(root.get("xres", 72))))
        names = {k.lower().replace(" ", "-").split(" (")[0]: k for k in BLEND_MODES}
        names["plus"] = "Linear Dodge (Add)"
        layers = []
        for el in root.iter("layer"):
            img = QImage.fromData(z.read(el.get("src")))
            op = el.get("composite-op", "svg:src-over").replace("svg:", "")
            l = Layer(el.get("name", "Layer"), img.convertToFormat(FMT), int(el.get("x", 0)), int(el.get("y", 0)),
                      el.get("visibility", "visible") != "hidden", float(el.get("opacity", 1)),
                      names.get(op, "Normal"))
            if el.get("ethical-text"):
                try:
                    l.text = ast.literal_eval(el.get("ethical-text"))
                except Exception:
                    pass
            layers.append(l)
    doc.layers = list(reversed(layers))
    doc.active = len(doc.layers) - 1
    return doc


def save_psd(doc, path):
    """Layered Photoshop file (8-bit RGB, uncompressed channels)."""
    def pascal(name):
        raw = name.encode("latin-1", "replace")[:255]
        data = bytes([len(raw)]) + raw
        return data + b"\0" * ((4 - len(data) % 4) % 4)

    def luni(name):
        u = name.encode("utf-16-be")
        body = struct.pack(">I", len(name)) + u
        if len(body) % 4:
            body += b"\0" * (4 - len(body) % 4)
        return b"8BIM" + b"luni" + struct.pack(">I", len(body)) + body

    records, channel_data = b"", b""
    for l in doc.layers:
        arr = to_array(l.image)
        h, w = arr.shape[:2]
        top, left = l.y, l.x
        chans = [(-1, arr[..., 3]), (0, arr[..., 0]), (1, arr[..., 1]), (2, arr[..., 2])]
        rec = struct.pack(">iiiiH", top, left, top + h, left + w, len(chans))
        for cid, plane in chans:
            rec += struct.pack(">hI", cid, 2 + plane.size)
            channel_data += struct.pack(">H", 0) + plane.astype(np.uint8).tobytes()
        flags = 0 if l.visible else 2
        rec += b"8BIM" + BLEND_MODES.get(l.blend, BLEND_MODES["Normal"])[1]
        rec += struct.pack(">BBBB", int(round(l.opacity * 255)), 0, flags, 0)
        extra = struct.pack(">I", 0) + struct.pack(">I", 0) + pascal(l.name) + luni(l.name)
        rec += struct.pack(">I", len(extra)) + extra
        records += rec
    layer_info = struct.pack(">h", len(doc.layers)) + records + channel_data
    if len(layer_info) % 2:
        layer_info += b"\0"
    layer_info = struct.pack(">I", len(layer_info)) + layer_info
    lmi = layer_info + struct.pack(">I", 0)
    flat = to_array(composite(doc, background=QColor("white")))
    with open(path, "wb") as f:
        f.write(b"8BPS" + struct.pack(">H6sHIIHH", 1, b"\0" * 6, 3, doc.height, doc.width, 8, 3))
        f.write(struct.pack(">I", 0))       # colour mode data
        f.write(struct.pack(">I", 0))       # image resources
        f.write(struct.pack(">I", len(lmi)) + lmi)
        f.write(struct.pack(">H", 0))       # merged image, raw
        for c in range(3):
            f.write(flat[..., c].tobytes())
