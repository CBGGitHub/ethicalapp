"""Ethical Presentation Editor - make and present slide decks; opens and saves real PowerPoint (.pptx) files."""
import math
import os
import sys

from lxml import etree
from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSettings, QSize, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QFont, QGuiApplication, QIcon, QImage,
                           QKeySequence, QPageLayout, QPageSize, QPainter, QPainterPath, QPen,
                           QPdfWriter, QPixmap, QPolygonF, QTextBlockFormat, QTextCharFormat,
                           QTextCursor, QTextDocument, QTextListFormat, QTransform)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFontComboBox, QFormLayout, QGraphicsItem, QGraphicsObject,
                               QGraphicsScene, QGraphicsTextItem, QGraphicsView, QInputDialog,
                               QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QSpinBox, QSplitter, QToolBar,
                               QToolButton, QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pptx_io import (INDENT_PX, Element, Layout, Presentation, Slide, load_pptx,  # noqa: E402
                     new_slide_from_layout, save_pptx)
from suite_common import SETTINGS_ORG, SUITE_NAME, ColorButton, make_app  # noqa: E402
from suite_common import add_guide_action  # noqa: E402

APP_NAME = "Ethical Presentation Editor"
HANDLE = 7

THEMES = {
    "Office":   dict(bg="#FFFFFF", title="#1F1F1F", text="#404040", accent="#4472C4", tfont="Calibri Light", bfont="Calibri"),
    "Midnight": dict(bg="#1E2761", title="#FFFFFF", text="#CADCFC", accent="#F96167", tfont="Segoe UI Semibold", bfont="Segoe UI"),
    "Slate":    dict(bg="#2F3C4F", title="#FFFFFF", text="#E0E6ED", accent="#4FB3BF", tfont="Segoe UI Light", bfont="Segoe UI"),
    "Forest":   dict(bg="#F4F1E8", title="#2C5F2D", text="#333333", accent="#97BC62", tfont="Georgia", bfont="Calibri"),
    "Sunset":   dict(bg="#FFF4E6", title="#B85042", text="#4A4A4A", accent="#E07A5F", tfont="Cambria", bfont="Calibri"),
    "Ocean":    dict(bg="#065A82", title="#FFFFFF", text="#D6EEF5", accent="#F4D35E", tfont="Calibri Light", bfont="Calibri"),
    "Charcoal": dict(bg="#222222", title="#F5F5F5", text="#BBBBBB", accent="#FFB400", tfont="Arial Black", bfont="Arial"),
    "Blush":    dict(bg="#FCEEF0", title="#6D2E46", text="#4D3B42", accent="#D16D8C", tfont="Georgia", bfont="Segoe UI"),
}
SHAPES = [("Rectangle", "rect"), ("Rounded Rectangle", "roundrect"), ("Ellipse", "ellipse"),
          ("Triangle", "triangle"), ("Right Triangle", "rttriangle"), ("Diamond", "diamond"),
          ("Pentagon", "pentagon"), ("Hexagon", "hexagon"), ("Octagon", "octagon"), ("Star", "star5"),
          ("Right Arrow", "rarrow"), ("Left Arrow", "larrow"), ("Up Arrow", "uarrow"), ("Down Arrow", "darrow"),
          ("Chevron", "chevron"), ("Arrow Pentagon", "homeplate"), ("Parallelogram", "parallelogram"),
          ("Trapezoid", "trapezoid"), ("Plus", "plus")]


# ====================================================================== drawing

def _poly(points, w, h):
    return QPolygonF([QPointF(x * w, y * h) for x, y in points])


def shape_path(e):
    w, h = e.w, e.h
    p = QPainterPath()
    g = e.geom
    if g == "ellipse":
        p.addEllipse(QRectF(0, 0, w, h))
    elif g == "roundrect":
        r = min(w, h) * 0.16
        p.addRoundedRect(QRectF(0, 0, w, h), r, r)
    elif g == "custom" and e.cust_xml:
        cp = custom_path(e.cust_xml, w, h)
        if cp is not None:
            return cp
        p.addRect(QRectF(0, 0, w, h))
    else:
        pts = {
            "triangle": [(0.5, 0), (1, 1), (0, 1)],
            "rttriangle": [(0, 0), (1, 1), (0, 1)],
            "diamond": [(0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5)],
            "rarrow": [(0, 0.25), (0.65, 0.25), (0.65, 0), (1, 0.5), (0.65, 1), (0.65, 0.75), (0, 0.75)],
            "larrow": [(1, 0.25), (0.35, 0.25), (0.35, 0), (0, 0.5), (0.35, 1), (0.35, 0.75), (1, 0.75)],
            "uarrow": [(0.25, 1), (0.25, 0.35), (0, 0.35), (0.5, 0), (1, 0.35), (0.75, 0.35), (0.75, 1)],
            "darrow": [(0.25, 0), (0.25, 0.65), (0, 0.65), (0.5, 1), (1, 0.65), (0.75, 0.65), (0.75, 0)],
            "pentagon": [(0.5, 0), (1, 0.38), (0.81, 1), (0.19, 1), (0, 0.38)],
            "hexagon": [(0.25, 0), (0.75, 0), (1, 0.5), (0.75, 1), (0.25, 1), (0, 0.5)],
            "octagon": [(0.29, 0), (0.71, 0), (1, 0.29), (1, 0.71), (0.71, 1), (0.29, 1), (0, 0.71), (0, 0.29)],
            "homeplate": [(0, 0), (0.8, 0), (1, 0.5), (0.8, 1), (0, 1)],
            "chevron": [(0, 0), (0.75, 0), (1, 0.5), (0.75, 1), (0, 1), (0.25, 0.5)],
            "parallelogram": [(0.25, 0), (1, 0), (0.75, 1), (0, 1)],
            "trapezoid": [(0.25, 0), (0.75, 0), (1, 1), (0, 1)],
            "plus": [(0.33, 0), (0.67, 0), (0.67, 0.33), (1, 0.33), (1, 0.67), (0.67, 0.67), (0.67, 1),
                     (0.33, 1), (0.33, 0.67), (0, 0.67), (0, 0.33), (0.33, 0.33)],
        }.get(g)
        if g == "star5":
            pts = []
            for i in range(10):
                a = -math.pi / 2 + i * math.pi / 5
                r = 0.5 if i % 2 == 0 else 0.2
                pts.append((0.5 + r * math.cos(a), 0.52 + r * math.sin(a)))
        if pts:
            p.addPolygon(_poly(pts, w, h))
            p.closeSubpath()
        else:
            p.addRect(QRectF(0, 0, w, h))
    return p


_CUST_CACHE = {}


def custom_path(xml, w, h):
    """a:custGeom -> QPainterPath scaled to w x h (numeric paths only)."""
    key = (xml, round(w, 1), round(h, 1))
    if key in _CUST_CACHE:
        return _CUST_CACHE[key]
    try:
        root = etree.fromstring(xml)
        ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
        path = QPainterPath()
        for pth in root.iter(ns + "path"):
            pw, ph = float(pth.get("w", 0) or 0), float(pth.get("h", 0) or 0)
            sx = w / pw if pw else 1 / 9525
            sy = h / ph if ph else 1 / 9525
            cur = QPointF(0, 0)

            def pt(el):
                return QPointF(float(el.get("x")) * sx, float(el.get("y")) * sy)
            for cmd in pth:
                tag = etree.QName(cmd).localname
                if tag == "moveTo":
                    cur = pt(cmd[0])
                    path.moveTo(cur)
                elif tag == "lnTo":
                    cur = pt(cmd[0])
                    path.lineTo(cur)
                elif tag == "cubicBezTo":
                    a, b, c = (pt(x) for x in cmd[:3])
                    path.cubicTo(a, b, c)
                    cur = c
                elif tag == "quadBezTo":
                    a, b = (pt(x) for x in cmd[:2])
                    path.quadTo(a, b)
                    cur = b
                elif tag == "arcTo":
                    wr, hr = float(cmd.get("wR")) * sx, float(cmd.get("hR")) * sy
                    st, sw = float(cmd.get("stAng")) / 60000, float(cmd.get("swAng")) / 60000
                    cx = cur.x() - wr * math.cos(math.radians(st))
                    cy = cur.y() - hr * math.sin(math.radians(st))
                    path.arcTo(QRectF(cx - wr, cy - hr, 2 * wr, 2 * hr), -st, -sw)
                    cur = path.currentPosition()
                elif tag == "close":
                    path.closeSubpath()
        _CUST_CACHE[key] = path
        return path
    except Exception:
        return None


_PIX = {}


def pixmap_of(data):
    key = id(data)
    entry = _PIX.get(key)
    if entry is None or entry[0] is not data:
        pm = QPixmap()
        pm.loadFromData(data)
        entry = (data, pm)
        _PIX[key] = entry
    return entry[1]


def layout_doc(e):
    l, t, r, b = e.insets
    e.doc.setTextWidth(max(1, e.w - l - r) if e.wrap or e.kind == "table" else -1)
    dh = e.doc.size().height()
    room = e.h - t - b
    off = 0 if e.anchor == "t" else (room - dh) / 2 if e.anchor == "m" else room - dh
    return QPointF(l, t + off)


def draw_arrowhead(p, a, b, size):
    ang = math.atan2(b.y() - a.y(), b.x() - a.x())
    pts = [b, QPointF(b.x() - size * math.cos(ang - 0.45), b.y() - size * math.sin(ang - 0.45)),
           QPointF(b.x() - size * math.cos(ang + 0.45), b.y() - size * math.sin(ang + 0.45))]
    p.setBrush(p.pen().color())
    p.drawPolygon(QPolygonF(pts))


def render_element(p, e, editor=False, with_text=True):
    p.save()
    p.translate(e.x, e.y)
    if e.rot:
        p.translate(e.w / 2, e.h / 2)
        p.rotate(e.rot)
        p.translate(-e.w / 2, -e.h / 2)
    draw_body(p, e)
    if with_text and e.doc is not None:
        if e.is_empty() and e.prompt:
            if editor:
                draw_prompt(p, e)
        else:
            p.save()
            p.translate(layout_doc(e))
            e.doc.drawContents(p)
            p.restore()
    p.restore()


def draw_body(p, e):
    """Everything except the text, in element-local coordinates."""
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    if e.flip_h or e.flip_v:
        p.save()
        p.translate(e.w if e.flip_h else 0, e.h if e.flip_v else 0)
        p.scale(-1 if e.flip_h else 1, -1 if e.flip_v else 1)
    if e.kind == "image":
        pm = pixmap_of(e.image)
        if not pm.isNull():
            l, t, r, b = e.crop
            src = QRectF(pm.width() * l, pm.height() * t, pm.width() * (1 - l - r), pm.height() * (1 - t - b))
            p.drawPixmap(QRectF(0, 0, e.w, e.h), pm, src)
        if e.line:
            p.setPen(QPen(QColor(e.line), e.line_w))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(0, 0, e.w, e.h))
    elif e.kind == "line":
        pen = QPen(QColor(e.line or "#000000"), max(e.line_w, 0.5))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        a, b = QPointF(0, 0), QPointF(e.w, e.h)
        p.drawLine(a, b)
        size = max(8, e.line_w * 4)
        if e.arrow_end:
            draw_arrowhead(p, a, b, size)
        if e.arrow_start:
            draw_arrowhead(p, b, a, size)
    elif e.kind == "shape":
        if e.fill or e.line:
            p.setBrush(QColor(e.fill) if e.fill else Qt.NoBrush)
            p.setPen(QPen(QColor(e.line), e.line_w) if e.line else Qt.NoPen)
            p.drawPath(shape_path(e))
    if e.flip_h or e.flip_v:
        p.restore()


def draw_prompt(p, e):
    p.save()
    p.setPen(QPen(QColor("#9a9a9a"), 1, Qt.DashLine))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(0, 0, e.w, e.h))
    cf = e.doc.begin().charFormat()
    f = QFont(cf.fontFamilies()[0] if cf.fontFamilies() else "Calibri")
    f.setPixelSize(max(8, int((cf.fontPointSize() or 18) * 96 / 72)))
    p.setFont(f)
    p.setPen(QColor("#8a8a8a"))
    al = e.doc.begin().blockFormat().alignment()
    va = {"t": Qt.AlignTop, "m": Qt.AlignVCenter, "b": Qt.AlignBottom}[e.anchor]
    l, t, r, b = e.insets
    p.drawText(QRectF(l, t, e.w - l - r, e.h - t - b), (al & Qt.AlignHorizontal_Mask) | va | Qt.TextWordWrap, e.prompt)
    p.restore()


def draw_background(p, pres, slide):
    rect = QRectF(0, 0, pres.width, pres.height)
    bg = slide.bg
    if bg and bg[0] == "image":
        pm = pixmap_of(bg[1])
        p.drawPixmap(rect, pm, QRectF(pm.rect()))
    else:
        p.fillRect(rect, QColor(bg[1]) if bg else Qt.white)
    for d in slide.decor:
        render_element(p, d)


def render_slide(p, pres, slide, target, editor=False):
    p.save()
    p.translate(target.topLeft())
    p.scale(target.width() / pres.width, target.height() / pres.height)
    p.setClipRect(QRectF(0, 0, pres.width, pres.height))
    draw_background(p, pres, slide)
    for e in slide.elements:
        render_element(p, e, editor)
    p.restore()


def slide_image(pres, slide, width):
    h = int(width * pres.height / pres.width)
    img = QImage(width, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.white)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    render_slide(p, pres, slide, QRectF(0, 0, width, h))
    p.end()
    return img


# ====================================================================== built-in layouts / themes

def text_element(role, x, y, w, h, size, color, font, align=Qt.AlignLeft, anchor="t", bold=False,
                 bullets=False, prompt=""):
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setIndentWidth(INDENT_PX)
    doc.setDefaultFont(QFont(font, size))
    c = QTextCursor(doc)
    bf = QTextBlockFormat()
    bf.setAlignment(align | Qt.AlignAbsolute)
    if bullets:
        bf.setBottomMargin(10)
    c.setBlockFormat(bf)
    cf = QTextCharFormat()
    cf.setFontFamilies([font])
    cf.setFontPointSize(size)
    cf.setForeground(QColor(color))
    cf.setFontWeight(QFont.Bold if bold else QFont.Normal)
    c.setBlockCharFormat(cf)
    c.setCharFormat(cf)
    if bullets:
        lf = QTextListFormat()
        lf.setStyle(QTextListFormat.ListDisc)
        lf.setIndent(1)
        c.createList(lf)
    doc.setModified(False)
    return Element(kind="shape", x=x, y=y, w=w, h=h, doc=doc, anchor=anchor, role=role, prompt=prompt)


def builtin_layouts(pres, theme):
    W, H = pres.width, pres.height
    t = theme
    bg = ("color", t["bg"])
    m = W * 0.06

    def title(y, h, size=40, align=Qt.AlignLeft, anchor="b", prompt="Click to add title"):
        return text_element("title", m, y, W - 2 * m, h, size, t["title"], t["tfont"], align, anchor, prompt=prompt)

    def body(x, y, w, h, prompt="Click to add text"):
        return text_element("body", x, y, w, h, 24, t["text"], t["bfont"], bullets=True, prompt=prompt)
    return [
        Layout("Title Slide", None, [], bg, [
            title(H * 0.26, H * 0.28, 54, Qt.AlignHCenter, "b"),
            text_element("body", m * 2, H * 0.57, W - 4 * m, H * 0.16, 24, t["text"], t["bfont"], Qt.AlignHCenter,
                         prompt="Click to add subtitle")]),
        Layout("Title and Content", None, [], bg, [title(H * 0.05, H * 0.16), body(m, H * 0.25, W - 2 * m, H * 0.66)]),
        Layout("Section Header", None, [], bg, [
            title(H * 0.30, H * 0.28, 48, Qt.AlignLeft, "b"),
            text_element("body", m, H * 0.60, W - 2 * m, H * 0.14, 22, t["text"], t["bfont"],
                         prompt="Click to add text")]),
        Layout("Two Content", None, [], bg, [title(H * 0.05, H * 0.16), body(m, H * 0.25, (W - 3 * m) / 2, H * 0.66),
                                             body(m * 2 + (W - 3 * m) / 2, H * 0.25, (W - 3 * m) / 2, H * 0.66)]),
        Layout("Title Only", None, [], bg, [title(H * 0.05, H * 0.16)]),
        Layout("Blank", None, [], bg, []),
    ]


def new_presentation(theme_name="Office"):
    pres = Presentation(width=1280, height=720)
    pres.theme = dict(THEMES[theme_name], name=theme_name)
    pres.layouts = builtin_layouts(pres, pres.theme)
    pres.slides = [new_slide_from_layout(pres, 0)]
    return pres


def recolor_doc(doc, color, font):
    c = QTextCursor(doc)
    c.select(QTextCursor.Document)
    cf = QTextCharFormat()
    cf.setForeground(QColor(color))
    cf.setFontFamilies([font])
    c.mergeCharFormat(cf)
    b = doc.begin()
    while b.isValid():
        bc = QTextCursor(b)
        bc.mergeBlockCharFormat(cf)
        b = b.next()


# ====================================================================== editor items

class ElementItem(QGraphicsObject):
    def __init__(self, win, el):
        super().__init__()
        self.win, self.el = win, el
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges | QGraphicsItem.ItemIsFocusable)
        self.setPos(el.x, el.y)
        self.setTransformOriginPoint(el.w / 2, el.h / 2)
        self.setRotation(el.rot)
        self.text = None
        self.resizing = None
        self.editing = False
        if el.doc is not None:
            self._make_text()

    def _make_text(self):
        if self.el.doc is None:
            self.el.doc = QTextDocument()
            self.el.doc.setDocumentMargin(0)
            self.el.doc.setIndentWidth(INDENT_PX)
            self.el.doc.setDefaultFont(QFont("Calibri", 18))
            bf = QTextBlockFormat()
            bf.setAlignment(Qt.AlignHCenter | Qt.AlignAbsolute)
            QTextCursor(self.el.doc).setBlockFormat(bf)
            self.el.anchor = "m"
            cf = QTextCharFormat()
            cf.setFontPointSize(18)
            cf.setForeground(QColor("#FFFFFF" if self.el.fill else "#000000"))
            QTextCursor(self.el.doc).setBlockCharFormat(cf)
        if self.el.doc.parent() is None:
            # QGraphicsTextItem would adopt (and later delete) a parentless document
            self.el.doc.setParent(QApplication.instance())
        self.text = QGraphicsTextItem(self)
        self.text.setDocument(self.el.doc)
        self.text.setTextInteractionFlags(Qt.NoTextInteraction)
        self.text.setAcceptedMouseButtons(Qt.NoButton)
        self.text.setDefaultTextColor(Qt.black)
        self.el.doc.contentsChanged.connect(self._text_changed)
        self.layout_text()

    def _text_changed(self):
        self.layout_text()
        self.update()
        self.win.slide_changed(light=True)

    def layout_text(self):
        if self.text is None:
            return
        l, t, r, b = self.el.insets
        self.text.setTextWidth(max(1, self.el.w - l - r) if self.el.wrap or self.el.kind == "table" else -1)
        pos = layout_doc(self.el)
        self.text.setPos(pos)
        self.text.setVisible(not (self.el.is_empty() and self.el.prompt and not self.editing))

    def boundingRect(self):
        return QRectF(-HANDLE, -HANDLE, self.el.w + 2 * HANDLE, self.el.h + 2 * HANDLE)

    def shape(self):
        path = QPainterPath()
        if self.el.kind == "line":
            stroker_w = max(8, self.el.line_w + 6)
            path.moveTo(0, 0)
            path.lineTo(self.el.w, self.el.h)
            from PySide6.QtGui import QPainterPathStroker
            s = QPainterPathStroker()
            s.setWidth(stroker_w)
            path = s.createStroke(path)
        else:
            path.addRect(QRectF(0, 0, self.el.w, self.el.h))
        if self.isSelected():
            for hr in self.handle_rects():
                path.addRect(hr)
        return path

    def handle_rects(self):
        w, h = self.el.w, self.el.h
        pts = ([(0, 0), (w, h)] if self.el.kind == "line" else
               [(0, 0), (w / 2, 0), (w, 0), (w, h / 2), (w, h), (w / 2, h), (0, h), (0, h / 2)])
        return [QRectF(x - HANDLE / 2, y - HANDLE / 2, HANDLE, HANDLE) for x, y in pts]

    def paint(self, p, opt, widget=None):
        e = self.el
        draw_body(p, e)
        if e.doc is not None and e.is_empty() and e.prompt and not self.editing:
            draw_prompt(p, e)
        if self.isSelected():
            p.setRenderHint(QPainter.Antialiasing, False)
            pen = QPen(QColor("#2b78e4"), 1, Qt.DashLine if self.editing else Qt.SolidLine)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            if e.kind != "line":
                p.drawRect(QRectF(0, 0, e.w, e.h))
            p.setBrush(QColor("white"))
            pen.setStyle(Qt.SolidLine)
            p.setPen(pen)
            for hr in self.handle_rects():
                p.drawRect(hr)

    # ---- interaction
    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.el.x, self.el.y = self.pos().x(), self.pos().y()
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.prepareGeometryChange()
            self.win.selection_changed()
        return super().itemChange(change, value)

    def mousePressEvent(self, e):
        if self.editing:
            return super().mousePressEvent(e)
        self.win.begin_interaction()
        if self.isSelected() and e.button() == Qt.LeftButton:
            for i, hr in enumerate(self.handle_rects()):
                if hr.adjusted(-3, -3, 3, 3).contains(e.pos()):
                    self.resizing = (i, QRectF(self.el.x, self.el.y, self.el.w, self.el.h), e.scenePos())
                    e.accept()
                    return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.resizing is None:
            return super().mouseMoveEvent(e)
        i, r0, start = self.resizing
        d = e.scenePos() - start
        x0, y0, x1, y1 = r0.left(), r0.top(), r0.right(), r0.bottom()
        if self.el.kind == "line":
            if i == 0:
                x0, y0 = x0 + d.x(), y0 + d.y()
            else:
                x1, y1 = x1 + d.x(), y1 + d.y()
            self.set_geometry(x0, y0, x1 - x0, y1 - y0)
            return
        if i in (0, 6, 7):
            x0 += d.x()
        if i in (2, 3, 4):
            x1 += d.x()
        if i in (0, 1, 2):
            y0 += d.y()
        if i in (4, 5, 6):
            y1 += d.y()
        keep = (self.el.kind == "image") != bool(e.modifiers() & Qt.ShiftModifier)
        if keep and i in (0, 2, 4, 6) and r0.width() and r0.height():
            ratio = r0.width() / r0.height()
            nw = max(10, x1 - x0)
            nh = nw / ratio
            if i in (0, 2):
                y0 = y1 - nh
            else:
                y1 = y0 + nh
        if x1 - x0 < 10:
            x0, x1 = (x1 - 10, x1) if i in (0, 6, 7) else (x0, x0 + 10)
        if y1 - y0 < 10:
            y0, y1 = (y1 - 10, y1) if i in (0, 1, 2) else (y0, y0 + 10)
        self.set_geometry(x0, y0, x1 - x0, y1 - y0)

    def set_geometry(self, x, y, w, h):
        self.prepareGeometryChange()
        if self.el.kind == "line":
            self.el.flip_h, self.el.flip_v = False, False
            self.el.w, self.el.h = w, h
        else:
            self.el.w, self.el.h = w, h
        self.setPos(x, y)
        self.setTransformOriginPoint(self.el.w / 2, self.el.h / 2)
        self.layout_text()
        self.update()

    def mouseReleaseEvent(self, e):
        self.resizing = None
        super().mouseReleaseEvent(e)
        self.win.end_interaction()

    def mouseDoubleClickEvent(self, e):
        if self.el.kind in ("shape", "table"):
            self.start_edit()
            # place the caret where the user clicked
            if self.text is not None:
                pos = self.text.mapFromParent(e.pos())
                cur = self.text.document().documentLayout().hitTest(pos, Qt.FuzzyHit)
                if cur >= 0:
                    c = self.text.textCursor()
                    c.setPosition(cur)
                    self.text.setTextCursor(c)
        else:
            super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if not self.editing and e.text() and e.text().isprintable() and self.el.kind in ("shape", "table") \
                and not e.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            self.start_edit(select_all=True)
            QApplication.sendEvent(self.win.scene, e)
            return
        super().keyPressEvent(e)

    def start_edit(self, select_all=False):
        if self.editing:
            return
        if self.text is None:
            self._make_text()
        self.win.begin_text_edit(self)
        self.editing = True
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.text.setVisible(True)
        self.text.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.text.setAcceptedMouseButtons(Qt.AllButtons)
        self.win.view.setFocus()
        self.text.setFocus()
        c = self.text.textCursor()
        if select_all:
            c.select(QTextCursor.Document)
        else:
            c.movePosition(QTextCursor.End)
        self.text.setTextCursor(c)
        self.update()

    def stop_edit(self):
        if not self.editing:
            return
        self.editing = False
        c = self.text.textCursor()
        c.clearSelection()
        self.text.setTextCursor(c)
        self.text.setTextInteractionFlags(Qt.NoTextInteraction)
        self.text.setAcceptedMouseButtons(Qt.NoButton)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.layout_text()
        self.update()
        self.win.end_text_edit(self)


class SlideScene(QGraphicsScene):
    def __init__(self, win):
        super().__init__()
        self.win = win

    def drawBackground(self, p, rect):
        p.fillRect(rect, QColor("#d7d9de"))
        pres, slide = self.win.pres, self.win.slide
        if slide is None:
            return
        p.fillRect(QRectF(4, 4, pres.width, pres.height), QColor(0, 0, 0, 40))
        p.save()
        p.setClipRect(QRectF(0, 0, pres.width, pres.height))
        draw_background(p, pres, slide)
        p.restore()

    def drawForeground(self, p, rect):
        pres = self.win.pres
        # cover anything that spills outside the slide
        outer = QPainterPath()
        outer.addRect(rect.united(QRectF(-5000, -5000, 10000 + pres.width, 10000 + pres.height)))
        inner = QPainterPath()
        inner.addRect(QRectF(0, 0, pres.width, pres.height))
        p.save()
        p.setOpacity(0.55)
        p.fillPath(outer.subtracted(inner), QColor("#d7d9de"))
        p.restore()

    def mousePressEvent(self, e):
        item = self.itemAt(e.scenePos(), QTransform())
        owner = item.parentItem() if isinstance(item, QGraphicsTextItem) else item
        ed = self.win.editing_item
        if ed is not None and owner is not ed:
            ed.stop_edit()
        super().mousePressEvent(e)


class SlideView(QGraphicsView):
    def __init__(self, win):
        super().__init__(win.scene)
        self.win = win
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.fit = True  # (no view background brush: it would stop the scene drawing the slide)

    def fit_slide(self):
        pres = self.win.pres
        self.setSceneRect(QRectF(-40, -40, pres.width + 80, pres.height + 80))
        self.fitInView(QRectF(-20, -20, pres.width + 40, pres.height + 40), Qt.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit:
            self.fit_slide()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.fit = False
            f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            self.scale(f, f)
        else:
            super().wheelEvent(e)

    def keyPressEvent(self, e):
        win = self.win
        if win.editing_item is None:
            sel = win.selected_items()
            k = e.key()
            if sel and k in (Qt.Key_Delete, Qt.Key_Backspace):
                win.delete_selected()
                return
            if sel and k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
                step = 10 if e.modifiers() & Qt.ShiftModifier else 1
                dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(k, 0)
                dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(k, 0)
                win.begin_interaction()
                for it in sel:
                    it.moveBy(dx, dy)
                win.end_interaction()
                return
            if sel and k in (Qt.Key_F2, Qt.Key_Return, Qt.Key_Enter) and len(sel) == 1:
                sel[0].start_edit(select_all=k != Qt.Key_F2)
                return
            if not sel and k in (Qt.Key_PageDown, Qt.Key_Down, Qt.Key_Right):
                win.goto_slide(win.index + 1)
                return
            if not sel and k in (Qt.Key_PageUp, Qt.Key_Up, Qt.Key_Left):
                win.goto_slide(win.index - 1)
                return
        elif e.key() == Qt.Key_Escape:
            win.editing_item.stop_edit()
            return
        super().keyPressEvent(e)


# ====================================================================== slideshow

class SlideShow(QWidget):
    def __init__(self, win, start):
        super().__init__()
        self.win = win
        self.order = [i for i, s in enumerate(win.pres.slides) if not s.hidden] or [0]
        self.pos = next((n for n, i in enumerate(self.order) if i >= start), 0)
        self.cache = {}
        self.blank = None
        self.setWindowTitle("Slide Show")
        self.setStyleSheet("background: black;")
        self.setCursor(Qt.BlankCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.timer = QTimer(self, singleShot=True, interval=2500)
        self.timer.timeout.connect(lambda: self.setCursor(Qt.BlankCursor))
        self.setMouseTracking(True)

    def image(self, n):
        if n not in self.cache:
            self.cache[n] = slide_image(self.win.pres, self.win.pres.slides[self.order[n]], max(self.width(), 1280))
        return self.cache[n]

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black if self.blank != "white" else Qt.white)
        if self.blank:
            return
        if self.pos >= len(self.order):
            p.setPen(QColor("#bbb"))
            p.setFont(QFont("Segoe UI", 16))
            p.drawText(self.rect(), Qt.AlignCenter, "End of slide show. Click or press Esc to exit.")
            return
        img = self.image(self.pos)
        size = img.size().scaled(self.size(), Qt.KeepAspectRatio)
        r = QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2, size.width(), size.height())
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(r, img)

    def step(self, d):
        self.blank = None
        if self.pos >= len(self.order) and d > 0:
            self.close()
            return
        self.pos = max(0, min(len(self.order), self.pos + d))
        self.update()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Escape,):
            self.close()
        elif k in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Space, Qt.Key_PageDown, Qt.Key_Return, Qt.Key_Enter, Qt.Key_N):
            self.step(1)
        elif k in (Qt.Key_Left, Qt.Key_Up, Qt.Key_PageUp, Qt.Key_Backspace, Qt.Key_P):
            self.step(-1)
        elif k == Qt.Key_Home:
            self.pos = 0
            self.update()
        elif k == Qt.Key_End:
            self.pos = len(self.order) - 1
            self.update()
        elif k in (Qt.Key_B, Qt.Key_Period):
            self.blank = None if self.blank == "black" else "black"
            self.update()
        elif k in (Qt.Key_W, Qt.Key_Comma):
            self.blank = None if self.blank == "white" else "white"
            self.update()

    def mousePressEvent(self, e):
        self.step(-1 if e.button() == Qt.RightButton else 1)

    def mouseMoveEvent(self, e):
        self.setCursor(Qt.ArrowCursor)
        self.timer.start()

    def wheelEvent(self, e):
        self.step(-1 if e.angleDelta().y() > 0 else 1)

    def closeEvent(self, e):
        self.win.goto_slide(self.order[min(self.pos, len(self.order) - 1)])
        super().closeEvent(e)


# ====================================================================== main window

class SlidesWindow(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        self.settings = QSettings(SETTINGS_ORG, APP_NAME)
        self.path = None
        self.modified = False
        self.lossy = []
        self.pres = None
        self.slide = None
        self.index = 0
        self.items = []
        self._graveyard = []
        self.editing_item = None
        self.undo_stack, self.redo_stack = [], []
        self._pending = None
        self._edit_snapshot = None
        self.clipboard = []
        self.show_window = None
        self.resize(1400, 880)
        self.setAcceptDrops(True)

        self.scene = SlideScene(self)
        self.view = SlideView(self)
        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.IconMode)
        self.thumbs.setFlow(QListWidget.TopToBottom)
        self.thumbs.setWrapping(False)
        self.thumbs.setIconSize(QSize(176, 99))
        self.thumbs.setGridSize(QSize(196, 124))
        self.thumbs.setMovement(QListWidget.Snap)
        self.thumbs.setDragDropMode(QListWidget.InternalMove)
        self.thumbs.setDefaultDropAction(Qt.MoveAction)
        self.thumbs.setSelectionMode(QListWidget.SingleSelection)
        self.thumbs.setMinimumWidth(215)
        self.thumbs.setStyleSheet("QListWidget { background: #eceef1; }")
        self.thumbs.currentRowChanged.connect(self._thumb_selected)
        self.thumbs.model().rowsMoved.connect(self._thumbs_moved)
        self.thumbs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.thumbs.customContextMenuRequested.connect(self._thumb_menu)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Click to add speaker notes")
        self.notes.textChanged.connect(self._notes_changed)
        self.notes.setMaximumHeight(160)

        right = QSplitter(Qt.Vertical)
        right.addWidget(self.view)
        right.addWidget(self.notes)
        right.setStretchFactor(0, 5)
        right.setStretchFactor(1, 1)
        main = QSplitter(Qt.Horizontal)
        main.addWidget(self.thumbs)
        main.addWidget(right)
        main.setStretchFactor(1, 1)
        main.setSizes([220, 1180])
        self.setCentralWidget(main)
        self.slide_label = QLabel()
        self.statusBar().addPermanentWidget(self.slide_label)
        self.thumb_timer = QTimer(self, singleShot=True, interval=350)
        self.thumb_timer.timeout.connect(lambda: self.update_thumb(self.index))

        self._build_actions()
        self.load_presentation(new_presentation(), None)
        if path:
            self.open_path(path)

    # ------------------------------------------------------------ actions
    def act(self, text, slot, shortcut=None, menu=None, tip=None, checkable=False):
        a = QAction(text, self)
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        if menu is not None:
            menu.addAction(a)
        return a

    def _build_actions(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        a_new = self.act("&New", self.new_file, "Ctrl+N", f)
        a_open = self.act("&Open...", self.open_dialog, "Ctrl+O", f)
        self.recent_menu = f.addMenu("Open &Recent")
        self._refresh_recent()
        f.addSeparator()
        a_save = self.act("&Save", self.save, "Ctrl+S", f)
        self.act("Save &As...", self.save_as, "Ctrl+Shift+S", f)
        a_pdf = self.act("Export as &PDF...", self.export_pdf, None, f)
        self.act("Export Slides as &Images...", self.export_images, None, f)
        self.act("&Print...", self.print_slides, "Ctrl+P", f)
        f.addSeparator()
        self.act("Slide &Size...", self.slide_size, None, f)
        f.addSeparator()
        self.act("E&xit", self.close, None, f)

        e = mb.addMenu("&Edit")
        a_undo = self.act("&Undo", self.undo, "Ctrl+Z", e)
        a_redo = self.act("&Redo", self.redo, "Ctrl+Y", e)
        e.addSeparator()
        self.act("Cu&t", self.cut, "Ctrl+X", e)
        self.act("&Copy", self.copy, "Ctrl+C", e)
        self.act("&Paste", self.paste, "Ctrl+V", e)
        self.act("&Duplicate", self.duplicate_selected, "Ctrl+D", e)
        self.act("De&lete", self.delete_selected, None, e)
        self.act("Select &All", self.select_all, "Ctrl+A", e)

        sm = mb.addMenu("&Slide")
        self.new_slide_menu = sm.addMenu("&New Slide")
        self.act("New Slide (same layout)", lambda: self.add_slide(None), "Ctrl+M", sm)
        self.act("D&uplicate Slide", self.duplicate_slide, None, sm)
        self.act("&Delete Slide", self.delete_slide, None, sm)
        self.act("&Hide / Show Slide", self.toggle_hidden, None, sm)
        sm.addSeparator()
        self.act("Move Slide &Up", lambda: self.move_slide(-1), None, sm)
        self.act("Move Slide Do&wn", lambda: self.move_slide(1), None, sm)

        ins = mb.addMenu("&Insert")
        a_tb = self.act("&Text Box", self.insert_textbox, None, ins)
        a_pic = self.act("&Picture...", self.insert_picture, None, ins)
        shp = ins.addMenu("&Shape")
        for label, g in SHAPES:
            self.act(label, lambda _=False, g=g: self.insert_shape(g), None, shp)
        shp.addSeparator()
        self.act("Line", lambda: self.insert_line(False), None, shp)
        self.act("Arrow", lambda: self.insert_line(True), None, shp)
        self.shape_menu = shp
        a_table = self.act("T&able...", self.insert_table, None, ins)

        fm = mb.addMenu("F&ormat")
        self.act("&Bold", lambda: self.char_toggle("bold"), "Ctrl+B", fm)
        self.act("&Italic", lambda: self.char_toggle("italic"), "Ctrl+I", fm)
        self.act("&Underline", lambda: self.char_toggle("underline"), "Ctrl+U", fm)
        self.act("Bigger Text", lambda: self.grow_font(1), "Ctrl+]", fm)
        self.act("Smaller Text", lambda: self.grow_font(-1), "Ctrl+[", fm)
        fm.addSeparator()
        self.act("Align &Left", lambda: self.align(Qt.AlignLeft), "Ctrl+L", fm)
        self.act("&Centre", lambda: self.align(Qt.AlignHCenter), "Ctrl+E", fm)
        self.act("Align &Right", lambda: self.align(Qt.AlignRight), "Ctrl+R", fm)
        self.act("&Justify", lambda: self.align(Qt.AlignJustify), "Ctrl+J", fm)
        va = fm.addMenu("&Vertical Alignment")
        for t, v in (("Top", "t"), ("Middle", "m"), ("Bottom", "b")):
            self.act(t, lambda _=False, v=v: self.set_anchor(v), None, va)
        self.act("&Bullets", lambda: self.toggle_list(QTextListFormat.ListDisc), None, fm)
        self.act("&Numbering", lambda: self.toggle_list(QTextListFormat.ListDecimal), None, fm)
        fm.addSeparator()
        self.act("Shape &Fill Colour...", self.pick_fill, None, fm)
        self.act("No Fill", lambda: self.set_shape_prop("fill", None), None, fm)
        self.act("Shape &Outline Colour...", self.pick_line, None, fm)
        self.act("No Outline", lambda: self.set_shape_prop("line", None), None, fm)
        self.act("Outline &Width...", self.pick_line_width, None, fm)

        ar = mb.addMenu("&Arrange")
        self.act("Bring to &Front", lambda: self.reorder("front"), "Ctrl+Shift+]", ar)
        self.act("Bring &Forward", lambda: self.reorder("forward"), None, ar)
        self.act("Send &Backward", lambda: self.reorder("backward"), None, ar)
        self.act("Send to Bac&k", lambda: self.reorder("back"), "Ctrl+Shift+[", ar)
        ar.addSeparator()
        al = ar.addMenu("&Align on Slide")
        for t, k in (("Left", "left"), ("Centre", "hcenter"), ("Right", "right"), ("Top", "top"),
                     ("Middle", "vcenter"), ("Bottom", "bottom")):
            self.act(t, lambda _=False, k=k: self.align_on_slide(k), None, al)
        ar.addSeparator()
        self.act("Rotate Right 90°", lambda: self.rotate(90), None, ar)
        self.act("Rotate Left 90°", lambda: self.rotate(-90), None, ar)
        self.act("Rotation...", self.rotation_dialog, None, ar)
        self.act("Flip Horizontal", lambda: self.flip("h"), None, ar)
        self.act("Flip Vertical", lambda: self.flip("v"), None, ar)

        dm = mb.addMenu("&Design")
        th = dm.addMenu("&Theme (apply to all slides)")
        for name in THEMES:
            self.act(name, lambda _=False, n=name: self.apply_theme(n), None, th)
        self.act("Slide &Background Colour...", lambda: self.pick_background(False), None, dm)
        self.act("Background Colour for &All Slides...", lambda: self.pick_background(True), None, dm)
        self.act("Background &Picture...", self.background_picture, None, dm)

        sh = mb.addMenu("Slide S&how")
        a_show = self.act("From &Beginning", lambda: self.slideshow(0), "F5", sh)
        self.act("From &Current Slide", lambda: self.slideshow(self.index), "Shift+F5", sh)
        h = mb.addMenu("&Help")
        add_guide_action(self, h, "slides-basics")
        self.act("Slide Show &Keys", lambda: QMessageBox.information(
            self, APP_NAME, "Next: Space, →, ↓, Page Down, Enter, click\nPrevious: ←, ↑, Page Up, Backspace,"
            " right-click\nBlack screen: B    White screen: W\nFirst/last: Home / End    Exit: Esc"), None, h)
        self.act("&About", lambda: QMessageBox.about(
            self, APP_NAME, f"<b>{APP_NAME}</b><br>Part of {SUITE_NAME}."), None, h)

        tb = QToolBar("Main")
        tb.setObjectName("main")
        self.addToolBar(tb)
        for a in (a_new, a_open, a_save, a_pdf):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(a_undo)
        tb.addAction(a_redo)
        tb.addSeparator()
        nb = QToolButton()
        nb.setText("New Slide")
        nb.setPopupMode(QToolButton.MenuButtonPopup)
        nb.setMenu(self.new_slide_menu)
        nb.clicked.connect(lambda: self.add_slide(None))
        tb.addWidget(nb)
        tb.addAction(a_tb)
        tb.addAction(a_pic)
        sb = QToolButton()
        sb.setText("Shapes")
        sb.setPopupMode(QToolButton.InstantPopup)
        sb.setMenu(self.shape_menu)
        tb.addWidget(sb)
        tb.addAction(a_table)
        tb.addSeparator()
        tb.addAction(a_show)
        a_show.setIconText("▶ Present")

        self.addToolBarBreak()
        ft = QToolBar("Format")
        ft.setObjectName("format")
        self.addToolBar(ft)
        self.font_box = QFontComboBox()
        self.font_box.setMaxVisibleItems(20)
        self.font_box.activated.connect(lambda _: self.merge_char(family=self.font_box.currentFont().family()))
        ft.addWidget(self.font_box)
        self.size_box = QComboBox()
        self.size_box.setEditable(True)
        self.size_box.addItems([str(s) for s in (10, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 44, 48, 54, 60, 72, 88)])
        self.size_box.setFixedWidth(60)
        self.size_box.activated.connect(lambda _: self._size_from_box())
        self.size_box.lineEdit().returnPressed.connect(self._size_from_box)
        ft.addWidget(self.size_box)
        for t, k in (("B", "bold"), ("I", "italic"), ("U", "underline")):
            a = self.act(t, lambda _=False, k=k: self.char_toggle(k))
            fnt = QFont()
            fnt.setBold(t == "B")
            fnt.setItalic(t == "I")
            fnt.setUnderline(t == "U")
            a.setFont(fnt)
            ft.addAction(a)
        ft.addAction(self.act("A+", lambda: self.grow_font(1)))
        ft.addAction(self.act("A-", lambda: self.grow_font(-1)))
        self.text_color = ColorButton(QColor("#C00000"), "Text colour")
        self.text_color.colorChanged.connect(lambda c: self.merge_char(color=c))
        ft.addAction(self.act("A", lambda: self.merge_char(color=self.text_color.color()), tip="Apply text colour"))
        ft.addWidget(self.text_color)
        ft.addSeparator()
        for t, al in (("Left", Qt.AlignLeft), ("Centre", Qt.AlignHCenter), ("Right", Qt.AlignRight)):
            ft.addAction(self.act(t, lambda _=False, al=al: self.align(al)))
        ft.addAction(self.act("• List", lambda: self.toggle_list(QTextListFormat.ListDisc)))
        ft.addAction(self.act("1. List", lambda: self.toggle_list(QTextListFormat.ListDecimal)))
        ft.addSeparator()
        ft.addWidget(QLabel(" Fill "))
        self.fill_color = ColorButton(QColor("#4472C4"), "Shape fill")
        self.fill_color.colorChanged.connect(lambda c: self.set_shape_prop("fill", c.name().upper()))
        ft.addWidget(self.fill_color)
        ft.addWidget(QLabel(" Outline "))
        self.line_color = ColorButton(QColor("#2F528F"), "Shape outline")
        self.line_color.colorChanged.connect(lambda c: self.set_shape_prop("line", c.name().upper()))
        ft.addWidget(self.line_color)
        ft.addAction(self.act("Front", lambda: self.reorder("front")))
        ft.addAction(self.act("Back", lambda: self.reorder("back")))
        for w in (self.font_box, self.size_box):
            w.setFocusPolicy(Qt.ClickFocus)

    # ------------------------------------------------------------ presentation lifecycle
    def load_presentation(self, pres, path):
        for it in self.items:
            self.scene.removeItem(it)
        self.items = []
        self._graveyard = []
        self.slide = None
        self.pres = pres
        self.path = path
        self.modified = False
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._rebuild_layout_menu()
        self.rebuild_thumbs()
        self.view.fit = True
        self.view.fit_slide()
        self.goto_slide(0, force=True)
        self.update_title()

    def _rebuild_layout_menu(self):
        self.new_slide_menu.clear()
        for i, lay in enumerate(self.pres.layouts):
            self.new_slide_menu.addAction(lay.name, lambda i=i: self.add_slide(i))

    def update_title(self):
        name = os.path.basename(self.path) if self.path else "Presentation1"
        self.setWindowTitle(f"{'*' if self.modified else ''}{name} - {APP_NAME}")

    def mark_modified(self):
        if not self.modified:
            self.modified = True
            self.update_title()

    def maybe_save(self):
        self.finish_editing()
        if not self.modified:
            return True
        r = QMessageBox.question(self, APP_NAME, "Save changes to this presentation?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def closeEvent(self, e):
        if self.maybe_save():
            e.accept()
        else:
            e.ignore()

    def new_file(self):
        if not self.maybe_save():
            return
        name, ok = QInputDialog.getItem(self, "New Presentation", "Theme:", list(THEMES), 0, False)
        if ok:
            self.lossy = []
            self.load_presentation(new_presentation(name), None)

    def open_dialog(self):
        f, _ = QFileDialog.getOpenFileName(self, "Open", self.settings.value("last_dir", ""),
                                           "PowerPoint (*.pptx);;All files (*)")
        if f:
            self.open_path(f)

    def open_path(self, path):
        if not self.maybe_save():
            return
        if path.lower().endswith(".ppt"):
            QMessageBox.information(self, APP_NAME, "The old .ppt format isn't supported. Please save it as .pptx first.")
            return
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pres, warnings = load_pptx(path)
        except Exception as ex:
            QGuiApplication.restoreOverrideCursor()
            QMessageBox.critical(self, APP_NAME, f"Could not open the file:\n{ex}")
            return
        QGuiApplication.restoreOverrideCursor()
        self.lossy = warnings
        self.load_presentation(pres, path)
        self._add_recent(path)
        if warnings:
            QMessageBox.information(
                self, APP_NAME, "This presentation contains " + ", ".join(warnings) + ".\n\n"
                f"{APP_NAME} can't show or keep these yet - they will be missing if you save over the "
                "original. Use File > Save As to keep the original file unchanged.")

    def save(self):
        if not self.path:
            return self.save_as()
        if self.lossy:
            r = QMessageBox.question(self, APP_NAME, "Saving over the original will remove: " + ", ".join(self.lossy)
                                     + ".\nSave anyway? (No = Save As instead.)",
                                     QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if r == QMessageBox.No:
                return self.save_as()
            if r != QMessageBox.Yes:
                return False
        return self.write(self.path)

    def save_as(self):
        start = self.path or os.path.join(self.settings.value("last_dir", ""), "Presentation1.pptx")
        f, _ = QFileDialog.getSaveFileName(self, "Save As", start, "PowerPoint (*.pptx)")
        if not f:
            return False
        if not f.lower().endswith(".pptx"):
            f += ".pptx"
        ok = self.write(f)
        if ok:
            self.lossy = []
        return ok

    def write(self, path):
        self.finish_editing()
        try:
            save_pptx(self.pres, path)
        except PermissionError:
            QMessageBox.critical(self, APP_NAME, "Could not save - the file may be open in another program.")
            return False
        except Exception as ex:
            QMessageBox.critical(self, APP_NAME, f"Could not save:\n{ex}")
            return False
        self.path = path
        self.modified = False
        self.update_title()
        self._add_recent(path)
        self.statusBar().showMessage(f"Saved {path}", 4000)
        return True

    def _add_recent(self, path):
        path = os.path.abspath(path)
        self.settings.setValue("last_dir", os.path.dirname(path))
        recent = self.settings.value("recent") or []
        if isinstance(recent, str):
            recent = [recent]
        self.settings.setValue("recent", ([path] + [p for p in recent if p != path])[:10])
        self._refresh_recent()

    def _refresh_recent(self):
        self.recent_menu.clear()
        recent = self.settings.value("recent") or []
        if isinstance(recent, str):
            recent = [recent]
        for p in recent:
            if os.path.exists(p):
                self.recent_menu.addAction(os.path.basename(p), lambda p=p: self.open_path(p))
        self.recent_menu.setEnabled(bool(self.recent_menu.actions()))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(".pptx"):
                self.open_path(p)
                return
            if p.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp")):
                self.insert_picture(p)
                return

    # ------------------------------------------------------------ undo
    def _snapshot(self):
        return ([s.clone() for s in self.pres.slides], self.index)

    def push_undo(self, snap=None):
        self.undo_stack.append(snap or self._snapshot())
        del self.undo_stack[:-50]
        self.redo_stack.clear()
        self.mark_modified()

    def _restore(self, snap):
        slides, idx = snap
        self.pres.slides = slides
        self.rebuild_thumbs()
        self.goto_slide(min(idx, len(slides) - 1), force=True)
        self.mark_modified()

    def undo(self):
        if self.editing_item is not None:
            self.editing_item.text.document().undo()
            return
        if self.undo_stack:
            self.redo_stack.append(self._snapshot())
            self._restore(self.undo_stack.pop())

    def redo(self):
        if self.editing_item is not None:
            self.editing_item.text.document().redo()
            return
        if self.redo_stack:
            self.undo_stack.append(self._snapshot())
            self._restore(self.redo_stack.pop())

    def begin_interaction(self):
        self._pending = (self._snapshot(), [(it.el.x, it.el.y, it.el.w, it.el.h) for it in self.items])

    def end_interaction(self):
        if self._pending is None:
            return
        snap, geo = self._pending
        self._pending = None
        now = [(it.el.x, it.el.y, it.el.w, it.el.h) for it in self.items]
        if now != geo:
            self.push_undo(snap)
            self.slide_changed()

    def begin_text_edit(self, item):
        if self.editing_item is not None and self.editing_item is not item:
            self.editing_item.stop_edit()
        self.editing_item = item
        self._edit_snapshot = (self._snapshot(), item.el.doc.toHtml())

    def end_text_edit(self, item):
        if self.editing_item is item:
            self.editing_item = None
        if self._edit_snapshot:
            snap, html = self._edit_snapshot
            self._edit_snapshot = None
            if item.el.doc.toHtml() != html:
                self.push_undo(snap)
                self.slide_changed()

    def finish_editing(self):
        if self.editing_item is not None:
            self.editing_item.stop_edit()

    # ------------------------------------------------------------ slides
    def rebuild_thumbs(self):
        self.thumbs.blockSignals(True)
        self.thumbs.clear()
        for i, s in enumerate(self.pres.slides):
            it = QListWidgetItem(self._thumb_label(i))
            it.setIcon(QIcon(QPixmap.fromImage(slide_image(self.pres, s, 352))))
            self.thumbs.addItem(it)
        self.thumbs.blockSignals(False)

    def _thumb_label(self, i):
        return f"{i + 1}" + ("  (hidden)" if self.pres.slides[i].hidden else "")

    def update_thumb(self, i):
        if 0 <= i < self.thumbs.count():
            it = self.thumbs.item(i)
            it.setIcon(QIcon(QPixmap.fromImage(slide_image(self.pres, self.pres.slides[i], 352))))
            it.setText(self._thumb_label(i))

    def slide_changed(self, light=False):
        self.mark_modified()
        self.thumb_timer.start()

    def goto_slide(self, i, force=False):
        if not self.pres.slides:
            return
        i = max(0, min(i, len(self.pres.slides) - 1))
        if i == self.index and not force and self.slide is self.pres.slides[i]:
            return
        self.finish_editing()
        self.index = i
        self.slide = self.pres.slides[i]
        self.scene.clearSelection()
        for it in self.items:
            self._discard_item(it)
        self.items = []
        for el in self.slide.elements:
            self._add_item(el)
        self.notes.blockSignals(True)
        self.notes.setPlainText(self.slide.notes)
        self.notes.blockSignals(False)
        self.thumbs.blockSignals(True)
        self.thumbs.setCurrentRow(i)
        self.thumbs.blockSignals(False)
        self.slide_label.setText(f"  Slide {i + 1} of {len(self.pres.slides)}  ")
        self.scene.update()

    def _discard_item(self, it):
        # PySide ties a QGraphicsTextItem's document to the item's lifetime, so deleting the item
        # would delete the slide's text. Keep removed items alive until another file is loaded.
        if it.text is not None:
            try:
                it.el.doc.contentsChanged.disconnect(it._text_changed)
            except (RuntimeError, TypeError):
                pass
        self.scene.removeItem(it)
        self._graveyard.append(it)

    def _add_item(self, el):
        it = ElementItem(self, el)
        self.scene.addItem(it)
        self.items.append(it)
        return it

    def _thumb_selected(self, row):
        if row >= 0:
            self.goto_slide(row)

    def _thumbs_moved(self, parent, start, end, dest, row):
        self.push_undo()
        s = self.pres.slides.pop(start)
        new = row if row < start else row - 1
        self.pres.slides.insert(new, s)
        self.rebuild_thumbs()
        self.goto_slide(new, force=True)

    def _thumb_menu(self, pos):
        m = QMenu(self)
        m.addMenu(self.new_slide_menu)
        m.addAction("Duplicate Slide", self.duplicate_slide)
        m.addAction("Delete Slide", self.delete_slide)
        m.addAction("Hide / Show Slide", self.toggle_hidden)
        m.addAction("Move Up", lambda: self.move_slide(-1))
        m.addAction("Move Down", lambda: self.move_slide(1))
        m.exec(self.thumbs.mapToGlobal(pos))

    def add_slide(self, layout_index):
        self.finish_editing()
        if layout_index is None:
            cur = self.slide.layout if self.slide is not None and self.slide.layout is not None else 0
            # after a title slide, PowerPoint offers "Title and Content"
            name = self.pres.layouts[cur].name.lower() if cur < len(self.pres.layouts) else ""
            if "title slide" in name:
                cur = next((i for i, l in enumerate(self.pres.layouts) if "content" in l.name.lower()), cur)
            layout_index = min(cur, len(self.pres.layouts) - 1)
        self.push_undo()
        s = new_slide_from_layout(self.pres, layout_index)
        if self.pres.theme and self.slide is not None and self.pres.template is None:
            s.bg = self.slide.bg
        self.pres.slides.insert(self.index + 1, s)
        self.rebuild_thumbs()
        self.goto_slide(self.index + 1, force=True)

    def duplicate_slide(self):
        self.push_undo()
        self.pres.slides.insert(self.index + 1, self.slide.clone())
        self.rebuild_thumbs()
        self.goto_slide(self.index + 1, force=True)

    def delete_slide(self):
        if len(self.pres.slides) == 1:
            QMessageBox.information(self, APP_NAME, "A presentation needs at least one slide.")
            return
        self.push_undo()
        del self.pres.slides[self.index]
        self.rebuild_thumbs()
        self.goto_slide(min(self.index, len(self.pres.slides) - 1), force=True)

    def toggle_hidden(self):
        self.push_undo()
        self.slide.hidden = not self.slide.hidden
        self.update_thumb(self.index)

    def move_slide(self, d):
        j = self.index + d
        if not 0 <= j < len(self.pres.slides):
            return
        self.push_undo()
        s = self.pres.slides
        s[self.index], s[j] = s[j], s[self.index]
        self.rebuild_thumbs()
        self.goto_slide(j, force=True)

    def _notes_changed(self):
        if self.slide is not None:
            self.slide.notes = self.notes.toPlainText()
            self.mark_modified()

    # ------------------------------------------------------------ selection helpers
    def selected_items(self):
        return [it for it in self.items if it.isSelected()]

    def selection_changed(self):
        sel = self.selected_items()
        if len(sel) == 1 and sel[0].el.doc is not None:
            b = sel[0].el.doc.begin()
            it = b.begin()
            cf = it.fragment().charFormat() if not it.atEnd() else b.charFormat()
            fams = cf.fontFamilies()
            if fams:
                self.font_box.blockSignals(True)
                self.font_box.setCurrentFont(QFont(fams[0]))
                self.font_box.blockSignals(False)
            if cf.fontPointSize():
                self.size_box.setEditText(f"{cf.fontPointSize():g}")

    def select_all(self):
        if self.editing_item is not None:
            c = self.editing_item.text.textCursor()
            c.select(QTextCursor.Document)
            self.editing_item.text.setTextCursor(c)
            return
        for it in self.items:
            it.setSelected(True)

    def _target_docs(self):
        """(cursor-or-None, [docs]) for formatting commands."""
        if self.editing_item is not None:
            return self.editing_item.text.textCursor(), [self.editing_item.el.doc]
        return None, [it.el.doc for it in self.selected_items() if it.el.doc is not None]

    # ------------------------------------------------------------ text formatting
    def merge_char(self, family=None, size=None, color=None, bold=None, italic=None, underline=None):
        cf = QTextCharFormat()
        if family:
            cf.setFontFamilies([family])
        if size:
            cf.setFontPointSize(size)
        if color is not None:
            cf.setForeground(QColor(color))
        if bold is not None:
            cf.setFontWeight(QFont.Bold if bold else QFont.Normal)
        if italic is not None:
            cf.setFontItalic(italic)
        if underline is not None:
            cf.setFontUnderline(underline)
        cursor, docs = self._target_docs()
        if cursor is not None:
            if cursor.hasSelection():
                cursor.mergeCharFormat(cf)
            else:
                cursor.mergeCharFormat(cf)
                self.editing_item.text.setTextCursor(cursor)
            return
        if not docs:
            return
        self.push_undo()
        for d in docs:
            c = QTextCursor(d)
            c.select(QTextCursor.Document)
            c.mergeCharFormat(cf)
            b = d.begin()
            while b.isValid():
                QTextCursor(b).mergeBlockCharFormat(cf)
                b = b.next()
        self._refresh_items()

    def char_toggle(self, kind):
        cursor, docs = self._target_docs()
        if not docs:
            return
        cf = cursor.charFormat() if cursor is not None else QTextCursor(docs[0]).charFormat()
        if cursor is None:
            c = QTextCursor(docs[0])
            c.movePosition(QTextCursor.NextCharacter)
            cf = c.charFormat()
        if kind == "bold":
            self.merge_char(bold=cf.fontWeight() < QFont.DemiBold)
        elif kind == "italic":
            self.merge_char(italic=not cf.fontItalic())
        else:
            self.merge_char(underline=not cf.fontUnderline())

    def _size_from_box(self):
        try:
            v = float(self.size_box.currentText())
        except ValueError:
            return
        if 1 <= v <= 400:
            self.merge_char(size=v)

    def grow_font(self, step):
        cursor, docs = self._target_docs()
        if not docs:
            return
        sizes = [8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 44, 48, 54, 60, 72, 88, 96, 120]
        if cursor is None:
            self.push_undo()
        for d in docs:
            c = cursor if cursor is not None else QTextCursor(d)
            if cursor is None:
                c.select(QTextCursor.Document)
            start, end = c.selectionStart(), c.selectionEnd()
            if start == end:
                cur = c.charFormat().fontPointSize() or 18
                new = next((s for s in sizes if s > cur), cur + 8) if step > 0 else \
                    next((s for s in reversed(sizes) if s < cur), max(1, cur - 2))
                cf = QTextCharFormat()
                cf.setFontPointSize(new)
                c.mergeCharFormat(cf)
                continue
            pos = start
            while pos < end:  # resize each run relative to its own size
                cc = QTextCursor(d)
                cc.setPosition(pos)
                cc.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
                cur = cc.charFormat().fontPointSize() or 18
                new = next((s for s in sizes if s > cur), cur + 8) if step > 0 else \
                    next((s for s in reversed(sizes) if s < cur), max(1, cur - 2))
                cf = QTextCharFormat()
                cf.setFontPointSize(new)
                cc.mergeCharFormat(cf)
                pos += 1
        self._refresh_items()

    def _blocks_for(self, cursor, doc):
        if cursor is None:
            b, out = doc.begin(), []
            while b.isValid():
                out.append(b)
                b = b.next()
            return out
        b = doc.findBlock(cursor.selectionStart())
        end = doc.findBlock(cursor.selectionEnd())
        out = [b]
        while b != end and b.isValid():
            b = b.next()
            out.append(b)
        return out

    def align(self, al):
        cursor, docs = self._target_docs()
        if not docs:
            return
        if cursor is None:
            self.push_undo()
        for d in docs:
            for b in self._blocks_for(cursor, d):
                bf = QTextBlockFormat()
                bf.setAlignment(al | Qt.AlignAbsolute)
                QTextCursor(b).mergeBlockFormat(bf)
        self._refresh_items()

    def toggle_list(self, style):
        cursor, docs = self._target_docs()
        if not docs:
            return
        if cursor is None:
            self.push_undo()
        for d in docs:
            blocks = self._blocks_for(cursor, d)
            lst = blocks[0].textList()
            bullet = style in (QTextListFormat.ListDisc, QTextListFormat.ListCircle, QTextListFormat.ListSquare)
            same = lst is not None and (lst.format().style() in (QTextListFormat.ListDisc, QTextListFormat.ListCircle,
                                                                  QTextListFormat.ListSquare)) == bullet
            if same:
                for b in blocks:
                    if b.textList():
                        b.textList().remove(b)
                        bf = b.blockFormat()
                        bf.setIndent(0)
                        bf.setLeftMargin(0)
                        QTextCursor(b).setBlockFormat(bf)
            elif lst is not None:
                fmt = lst.format()
                fmt.setStyle(style)
                lst.setFormat(fmt)
            else:
                lf = QTextListFormat()
                lf.setStyle(style)
                lf.setIndent(1)
                new = QTextCursor(blocks[0]).createList(lf)
                for b in blocks[1:]:
                    new.add(b)
        self._refresh_items()

    def set_anchor(self, v):
        sel = self.selected_items() or ([self.editing_item] if self.editing_item else [])
        if sel:
            self.push_undo()
            for it in sel:
                it.el.anchor = v
                it.layout_text()
            self.slide_changed()

    def _refresh_items(self):
        for it in self.items:
            it.layout_text()
            it.update()
        self.slide_changed()

    # ------------------------------------------------------------ shape formatting
    def set_shape_prop(self, prop, value):
        sel = [it for it in self.selected_items() if it.el.kind in ("shape", "line", "image")]
        if not sel:
            return
        self.push_undo()
        for it in sel:
            if prop == "fill" and it.el.kind != "shape":
                continue
            setattr(it.el, prop, value)
            it.update()
        self.slide_changed()

    def pick_fill(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(self.fill_color.color(), self, "Shape fill")
        if c.isValid():
            self.fill_color.setColor(c)
            self.set_shape_prop("fill", c.name().upper())

    def pick_line(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(self.line_color.color(), self, "Outline colour")
        if c.isValid():
            self.line_color.setColor(c)
            self.set_shape_prop("line", c.name().upper())

    def pick_line_width(self):
        w, ok = QInputDialog.getDouble(self, "Outline Width", "Width (points):", 1, 0.25, 50, 2)
        if ok:
            self.set_shape_prop("line_w", w * 96 / 72)

    # ------------------------------------------------------------ insert
    def _place_new(self, el, edit=False):
        self.finish_editing()
        self.push_undo()
        self.slide.elements.append(el)
        it = self._add_item(el)
        self.scene.clearSelection()
        it.setSelected(True)
        self.view.setFocus()
        if edit:
            it.start_edit()
        self.slide_changed()
        return it

    def _theme(self):
        return self.pres.theme or THEMES["Office"]

    def insert_textbox(self):
        W, H = self.pres.width, self.pres.height
        t = self._theme()
        el = text_element("other", W * 0.3, H * 0.4, W * 0.4, 60, 20, t["text"], t["bfont"])
        el.prompt = ""
        self._place_new(el, edit=True)

    def insert_shape(self, geom):
        W, H = self.pres.width, self.pres.height
        t = self._theme()
        el = Element(kind="shape", geom=geom, x=W / 2 - 110, y=H / 2 - 80, w=220, h=160, fill=t["accent"],
                     line=QColor(t["accent"]).darker(130).name().upper(), anchor="m")
        it = self._place_new(el)
        it._make_text()

    def insert_line(self, arrow):
        W, H = self.pres.width, self.pres.height
        el = Element(kind="line", geom="line", x=W / 2 - 150, y=H / 2, w=300, h=0.01, line=self._theme()["title"],
                     line_w=3, arrow_end=arrow)
        self._place_new(el)

    def insert_picture(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Insert Picture", self.settings.value("last_dir", ""),
                                                  "Images (*.png *.jpg *.jpeg *.gif *.bmp)")
        if not path:
            return
        with open(path, "rb") as fh:
            data = fh.read()
        img = QImage.fromData(data)
        if img.isNull():
            QMessageBox.warning(self, APP_NAME, "Couldn't read that image.")
            return
        W, H = self.pres.width, self.pres.height
        scale = min(1.0, W * 0.6 / img.width(), H * 0.6 / img.height())
        w, h = img.width() * scale, img.height() * scale
        self._place_new(Element(kind="image", image=data, x=(W - w) / 2, y=(H - h) / 2, w=w, h=h))

    def insert_table(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Insert Table")
        rows, cols = QSpinBox(), QSpinBox()
        rows.setRange(1, 30)
        cols.setRange(1, 15)
        rows.setValue(3)
        cols.setValue(3)
        form = QFormLayout(dlg)
        form.addRow("Rows:", rows)
        form.addRow("Columns:", cols)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if not dlg.exec():
            return
        from PySide6.QtGui import QTextLength, QTextTableFormat
        W, H = self.pres.width, self.pres.height
        t = self._theme()
        w = W * 0.8
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(QFont(t["bfont"], 18))
        tf = QTextTableFormat()
        tf.setBorder(1)
        tf.setBorderBrush(QBrush(QColor("#FFFFFF")))
        tf.setBorderCollapse(True)
        tf.setCellPadding(6)
        tf.setCellSpacing(0)
        tf.setColumnWidthConstraints([QTextLength(QTextLength.FixedLength, w / cols.value())] * cols.value())
        table = QTextCursor(doc).insertTable(rows.value(), cols.value(), tf)
        accent = QColor(t["accent"])
        for r in range(rows.value()):
            for c in range(cols.value()):
                cell = table.cellAt(r, c)
                f = cell.format().toTableCellFormat()
                f.setBackground(accent if r == 0 else accent.lighter(170 if r % 2 else 185))
                cell.setFormat(f)
                cf = QTextCharFormat()
                cf.setFontPointSize(18)
                cf.setFontFamilies([t["bfont"]])
                cf.setForeground(QColor("#FFFFFF" if r == 0 else "#000000"))
                if r == 0:
                    cf.setFontWeight(QFont.Bold)
                cc = cell.firstCursorPosition()
                cc.setBlockCharFormat(cf)
                cc.setCharFormat(cf)
        el = Element(kind="table", x=(W - w) / 2, y=H * 0.3, w=w, h=rows.value() * 44, doc=doc, insets=(0, 0, 0, 0))
        self._place_new(el)

    # ------------------------------------------------------------ edit commands
    def delete_selected(self):
        sel = self.selected_items()
        if not sel:
            return
        self.push_undo()
        for it in sel:
            self.slide.elements.remove(it.el)
            self.items.remove(it)
            self._discard_item(it)
        self.slide_changed()

    def copy(self):
        if self.editing_item is not None:
            self.editing_item.text.copy() if hasattr(self.editing_item.text, "copy") else None
            c = self.editing_item.text.textCursor()
            QGuiApplication.clipboard().setText(c.selectedText().replace(" ", "\n"))
            return
        self.clipboard = [it.el.clone() for it in self.selected_items()]

    def cut(self):
        if self.editing_item is not None:
            c = self.editing_item.text.textCursor()
            QGuiApplication.clipboard().setText(c.selectedText().replace(" ", "\n"))
            c.removeSelectedText()
            return
        self.copy()
        self.delete_selected()

    def paste(self):
        if self.editing_item is not None:
            self.editing_item.text.textCursor().insertText(QGuiApplication.clipboard().text())
            return
        cb = QGuiApplication.clipboard()
        if not self.clipboard and cb.mimeData().hasImage():
            img = QImage(cb.image())
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")
            W, H = self.pres.width, self.pres.height
            s = min(1.0, W * 0.6 / img.width(), H * 0.6 / img.height())
            self._place_new(Element(kind="image", image=bytes(ba), x=(W - img.width() * s) / 2,
                                    y=(H - img.height() * s) / 2, w=img.width() * s, h=img.height() * s))
            return
        if not self.clipboard:
            return
        self.push_undo()
        self.scene.clearSelection()
        for el in self.clipboard:
            new = el.clone()
            new.x += 20
            new.y += 20
            self.slide.elements.append(new)
            self._add_item(new).setSelected(True)
        self.clipboard = [e.clone() for e in self.clipboard]
        for e in self.clipboard:
            e.x += 20
            e.y += 20
        self.slide_changed()

    def duplicate_selected(self):
        self.copy()
        self.paste()

    def reorder(self, where):
        sel = self.selected_items()
        if not sel:
            return
        self.push_undo()
        els = self.slide.elements
        for it in sel:
            i = els.index(it.el)
            els.pop(i)
            if where == "front":
                els.append(it.el)
            elif where == "back":
                els.insert(0, it.el)
            elif where == "forward":
                els.insert(min(i + 1, len(els)), it.el)
            else:
                els.insert(max(i - 1, 0), it.el)
        keep = [it.el for it in sel]
        self.goto_slide(self.index, force=True)
        for it in self.items:
            it.setSelected(it.el in keep)
        self.slide_changed()

    def align_on_slide(self, how):
        sel = self.selected_items()
        if not sel:
            return
        self.push_undo()
        W, H = self.pres.width, self.pres.height
        for it in sel:
            e = it.el
            x = {"left": 0, "hcenter": (W - e.w) / 2, "right": W - e.w}.get(how, e.x)
            y = {"top": 0, "vcenter": (H - e.h) / 2, "bottom": H - e.h}.get(how, e.y)
            it.setPos(x, y)
        self.slide_changed()

    def rotate(self, deg):
        sel = self.selected_items()
        if not sel:
            return
        self.push_undo()
        for it in sel:
            it.el.rot = (it.el.rot + deg) % 360
            it.setRotation(it.el.rot)
        self.slide_changed()

    def rotation_dialog(self):
        sel = self.selected_items()
        if not sel:
            return
        v, ok = QInputDialog.getDouble(self, "Rotation", "Degrees:", sel[0].el.rot, -360, 360, 1)
        if ok:
            self.push_undo()
            for it in sel:
                it.el.rot = v % 360
                it.setRotation(it.el.rot)
            self.slide_changed()

    def flip(self, axis):
        sel = self.selected_items()
        if not sel:
            return
        self.push_undo()
        for it in sel:
            if axis == "h":
                it.el.flip_h = not it.el.flip_h
            else:
                it.el.flip_v = not it.el.flip_v
            it.update()
        self.slide_changed()

    # ------------------------------------------------------------ design
    def apply_theme(self, name):
        self.finish_editing()
        t = dict(THEMES[name], name=name)
        self.push_undo()
        for s in self.pres.slides:
            s.bg = ("color", t["bg"])
            s.bg_override = True
            for e in s.elements:
                if e.doc is not None and e.role in ("title", "body") and e.kind == "shape" and not e.fill:
                    recolor_doc(e.doc, t["title"] if e.role == "title" else t["text"],
                                t["tfont"] if e.role == "title" else t["bfont"])
        self.pres.theme = t
        if self.pres.template is None:
            self.pres.layouts = builtin_layouts(self.pres, t)
        else:
            for lay in self.pres.layouts:
                lay.bg = ("color", t["bg"])
        self.rebuild_thumbs()
        self.goto_slide(self.index, force=True)

    def pick_background(self, all_slides):
        from PySide6.QtWidgets import QColorDialog
        cur = QColor(self.slide.bg[1]) if self.slide.bg and self.slide.bg[0] == "color" else QColor("white")
        c = QColorDialog.getColor(cur, self, "Background colour")
        if not c.isValid():
            return
        self.push_undo()
        for s in (self.pres.slides if all_slides else [self.slide]):
            s.bg = ("color", c.name().upper())
            s.bg_override = True
        self.rebuild_thumbs()
        self.goto_slide(self.index, force=True)

    def background_picture(self):
        f, _ = QFileDialog.getOpenFileName(self, "Background Picture", self.settings.value("last_dir", ""),
                                           "Images (*.png *.jpg *.jpeg *.bmp)")
        if not f:
            return
        with open(f, "rb") as fh:
            data = fh.read()
        r = QMessageBox.question(self, APP_NAME, "Use this picture on all slides?",
                                 QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        if r == QMessageBox.Cancel:
            return
        self.push_undo()
        for s in (self.pres.slides if r == QMessageBox.Yes else [self.slide]):
            s.bg = ("image", data)
            s.bg_override = True
        self.rebuild_thumbs()
        self.goto_slide(self.index, force=True)

    def slide_size(self):
        options = ["Widescreen 16:9", "Standard 4:3", "A4 Paper", "Square 1:1"]
        sizes = [(1280, 720), (960, 720), (1123, 794), (720, 720)]
        cur = next((i for i, s in enumerate(sizes) if abs(s[0] - self.pres.width) < 2 and abs(s[1] - self.pres.height) < 2), 0)
        name, ok = QInputDialog.getItem(self, "Slide Size", "Size:", options, cur, False)
        if not ok:
            return
        w, h = sizes[options.index(name)]
        if (w, h) == (self.pres.width, self.pres.height):
            return
        self.push_undo()
        sx, sy = w / self.pres.width, h / self.pres.height
        s = min(sx, sy)
        ox, oy = (w - self.pres.width * s) / 2, (h - self.pres.height * s) / 2
        for sl in self.pres.slides:
            for e in sl.elements + [d for d in sl.decor]:
                e.x, e.y, e.w, e.h = ox + e.x * s, oy + e.y * s, e.w * s, e.h * s
        self.pres.width, self.pres.height = w, h
        if self.pres.template is None:
            self.pres.layouts = builtin_layouts(self.pres, self._theme())
        self.view.fit_slide()
        self.rebuild_thumbs()
        self.goto_slide(self.index, force=True)

    # ------------------------------------------------------------ show / export
    def slideshow(self, start):
        self.finish_editing()
        self.show_window = SlideShow(self, start)
        screen = self.screen()
        self.show_window.setGeometry(screen.geometry())
        self.show_window.showFullScreen()
        self.show_window.setFocus()

    def _visible_slides(self):
        return [s for s in self.pres.slides if not s.hidden]

    def export_pdf(self):
        self.finish_editing()
        start = os.path.splitext(self.path)[0] + ".pdf" if self.path else "Presentation1.pdf"
        f, _ = QFileDialog.getSaveFileName(self, "Export as PDF", start, "PDF files (*.pdf)")
        if not f:
            return
        if not f.lower().endswith(".pdf"):
            f += ".pdf"
        w = QPdfWriter(f)
        w.setResolution(144)
        size = QPageSize(QSizeF(self.pres.width / 96, self.pres.height / 96), QPageSize.Inch, "Slide",
                         QPageSize.ExactMatch)
        w.setPageLayout(QPageLayout(size, QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
        w.setCreator(f"{SUITE_NAME} {APP_NAME}")
        p = QPainter(w)
        try:
            for n, s in enumerate(self._visible_slides()):
                if n:
                    w.newPage()
                render_slide(p, self.pres, s, QRectF(0, 0, w.width(), w.height()))
        finally:
            p.end()
        self.statusBar().showMessage(f"Exported {f}", 5000)

    def export_images(self):
        folder = QFileDialog.getExistingDirectory(self, "Folder for the slide images")
        if not folder:
            return
        base = os.path.splitext(os.path.basename(self.path or "Presentation1"))[0]
        for n, s in enumerate(self._visible_slides()):
            slide_image(self.pres, s, 1920).save(os.path.join(folder, f"{base}_slide{n + 1}.png"))
        self.statusBar().showMessage(f"Saved {len(self._visible_slides())} images to {folder}", 5000)

    def print_slides(self):
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageOrientation(QPageLayout.Landscape)
        if not QPrintDialog(printer, self).exec():
            return
        p = QPainter(printer)
        try:
            for n, s in enumerate(self._visible_slides()):
                if n:
                    printer.newPage()
                vp = p.viewport()
                size = QSizeF(self.pres.width, self.pres.height).scaled(QSizeF(vp.size()), Qt.KeepAspectRatio)
                render_slide(p, self.pres, s, QRectF((vp.width() - size.width()) / 2, (vp.height() - size.height()) / 2,
                                                     size.width(), size.height()))
        finally:
            p.end()


def main():
    app = make_app(APP_NAME, sys.argv)
    win = SlidesWindow(sys.argv[1] if len(sys.argv) > 1 else None)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
