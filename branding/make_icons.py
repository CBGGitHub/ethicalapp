"""Builds every EthicalApp icon from simple vector drawings.

One shared design: a rounded tile in the app's colour, a white picture of what the app does, and the
suite's leaf logo as a badge (large sizes only). Run:  .venv\\Scripts\\python branding\\make_icons.py
Outputs: branding/svg/*.svg (editable sources), branding/icons/*.ico (multi-size Windows icons),
branding/icons/png/*_<size>.png, branding/preview.png (contact sheet).
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256, 512]
SMALL = 32          # sizes up to this use the simplified drawing (fewer details)
BADGE_FROM = 64     # the leaf badge only appears at this size and up (too fiddly below)
SUITE_GREEN = "#2E7D32"

APPS = {  # key: (name, colour)
    "suite": ("EthicalApp", SUITE_GREEN),
    "pdf": ("Ethical PDF Editor", "#C0392B"),
    "document": ("Ethical Document Editor", "#2471A3"),
    "spreadsheet": ("Ethical Spreadsheet Editor", "#1E8449"),
    "presentation": ("Ethical Presentation Editor", "#D35400"),
    "photo": ("Ethical Photo Editor", "#7B3FA0"),
    "converter": ("Ethical Converter", "#C98A00"),
    "database": ("Ethical Database", "#7B1F3A"),
    "stickynotes": ("Ethical Sticky Notes", "#0E8A7E"),
    "snip": ("Ethical Snip", "#C2185B"),
    "planner": ("Ethical Planner", "#3F51B5"),
    "guide": ("Ethical Guide", "#455A64"),
}


def mix(hexc, other, t):
    a = [int(hexc[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02X%02X%02X" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


LEAF = ("M70 186 C 62 112 112 58 196 58 C 198 142 146 196 70 186 Z", "M84 172 C 116 140 146 110 178 78")


def page(fold_fill):
    return (f'<path d="M80 40 H150 L196 86 V206 Q196 216 186 216 H80 Q70 216 70 206 V50 Q70 40 80 40 Z" fill="#FFFFFF"/>'
            f'<path d="M150 40 V76 Q150 86 160 86 H196 Z" fill="{fold_fill}"/>')


def glyph(key, c, small):
    light = mix(c, "#FFFFFF", 0.55)
    if key == "suite":
        return (f'<path d="{LEAF[0]}" fill="#FFFFFF"/>'
                + ("" if small else f'<path d="{LEAF[1]}" stroke="{c}" stroke-width="9" fill="none" stroke-linecap="round"/>'))
    if key == "pdf":
        if small:
            return page(light) + f'<rect x="84" y="128" width="98" height="44" rx="8" fill="{c}"/>'
        return (page(light) + f'<rect x="84" y="126" width="98" height="50" rx="8" fill="{c}"/>'
                f'<text x="133" y="164" font-family="Segoe UI, Arial" font-weight="bold" font-size="38" '
                f'fill="#FFFFFF" text-anchor="middle">PDF</text>')
    if key == "document":
        lines = [(104, 96), (128, 96), (152, 96), (176, 64)] if not small else [(112, 96), (148, 96), (184, 64)]
        h = 10 if not small else 16
        return page(light) + "".join(f'<rect x="85" y="{y}" width="{w}" height="{h}" rx="{h // 2}" fill="{c}"/>'
                                     for y, w in lines)
    if key == "spreadsheet":
        if small:
            return (f'<rect x="50" y="56" width="156" height="144" rx="16" fill="#FFFFFF"/>'
                    f'<rect x="50" y="56" width="156" height="44" rx="16" fill="{light}"/>'
                    f'<rect x="50" y="84" width="156" height="16" fill="{light}"/>'
                    f'<rect x="120" y="56" width="16" height="144" fill="{c}"/><rect x="50" y="140" width="156" height="14" fill="{c}"/>')
        out = (f'<rect x="48" y="56" width="160" height="144" rx="14" fill="#FFFFFF"/>'
               f'<path d="M48 70 Q48 56 62 56 H194 Q208 56 208 70 V92 H48 Z" fill="{light}"/>')
        for x in (100, 154):
            out += f'<rect x="{x}" y="56" width="6" height="144" fill="{c}"/>'
        for y in (92, 128, 164):
            out += f'<rect x="48" y="{y}" width="160" height="6" fill="{c}"/>'
        return out
    if key == "presentation":
        bars = [(80, 120, 30), (116, 100, 50), (152, 82, 68)] if not small else [(84, 108, 42), (136, 84, 66)]
        bw = 24 if not small else 34
        out = f'<rect x="40" y="48" width="176" height="122" rx="12" fill="#FFFFFF"/>'
        out += "".join(f'<rect x="{x}" y="{y}" width="{bw}" height="{h}" rx="4" fill="{c}"/>' for x, y, h in bars)
        out += ('<path d="M128 170 V198 M128 198 L98 218 M128 198 L158 218" stroke="#FFFFFF" stroke-width="12" '
                'stroke-linecap="round" fill="none"/>')
        return out
    if key == "photo":
        out = (f'<rect x="44" y="58" width="168" height="140" rx="16" fill="#FFFFFF"/>'
               f'<path d="M58 184 L108 116 L140 156 L160 134 L198 184 Z" fill="{c}"/>'
               f'<circle cx="166" cy="96" r="{16 if not small else 20}" fill="{mix(c, "#FFB300", 0.65)}"/>')
        return out
    if key == "converter":
        w = 22 if not small else 28
        arrow = (f'<path d="M66.9 138.8 A62 62 0 0 1 175.5 88.1" stroke="#FFFFFF" stroke-width="{w}" fill="none"/>'
                 '<path d="M152 104 L201 66 L200 122 Z" fill="#FFFFFF"/>')
        return arrow + f'<g transform="rotate(180 128 128)">{arrow}</g>'
    if key == "database":
        out = ('<path d="M62 72 V184 A66 22 0 0 0 194 184 V72 Z" fill="#FFFFFF"/>'
               '<ellipse cx="128" cy="72" rx="66" ry="22" fill="#FFFFFF"/>'
               f'<ellipse cx="128" cy="72" rx="52" ry="13" fill="{light}"/>')
        for y in ((110, 147) if not small else (124,)):
            out += f'<path d="M62 {y} A66 22 0 0 0 194 {y}" stroke="{c}" stroke-width="{9 if not small else 12}" fill="none"/>'
        return out
    if key == "guide":
        out = ('<path d="M124 82 C 100 66 66 64 44 72 V190 C 66 182 100 184 124 200 Z" fill="#FFFFFF"/>'
               '<path d="M132 82 C 156 66 190 64 212 72 V190 C 190 182 156 184 132 200 Z" fill="#FFFFFF"/>')
        if not small:
            for y in (100, 122, 144):
                out += (f'<path d="M62 {y} C 80 {y - 6} 98 {y - 4} 110 {y + 4}" stroke="{light}" stroke-width="7" '
                        f'fill="none" stroke-linecap="round"/>'
                        f'<path d="M146 {y + 4} C 158 {y - 4} 176 {y - 6} 194 {y}" stroke="{light}" stroke-width="7" '
                        f'fill="none" stroke-linecap="round"/>')
        return out
    if key == "stickynotes":
        note = ('<path d="M66 50 H190 Q202 50 202 62 V158 L160 202 H66 Q54 202 54 190 V62 Q54 50 66 50 Z" fill="#FFFFFF"/>'
                f'<path d="M202 158 H170 Q160 158 160 168 V202 Z" fill="{light}"/>')
        if small:
            return note + "".join(f'<rect x="76" y="{y}" width="{w}" height="18" rx="9" fill="{c}"/>'
                                  for y, w in ((84, 104), (124, 72)))
        out = note
        for i, y in enumerate((78, 120)):
            out += f'<rect x="76" y="{y}" width="28" height="28" rx="6" fill="none" stroke="{c}" stroke-width="7"/>'
            if i == 0:
                out += (f'<path d="M81 {y + 14} L88 {y + 21} L101 {y + 6}" stroke="{c}" stroke-width="7" fill="none" '
                        'stroke-linecap="round" stroke-linejoin="round"/>')
            out += f'<rect x="116" y="{y + 8}" width="{62 if i == 0 else 48}" height="12" rx="6" fill="{c}"/>'
        return out
    if key == "snip":
        w = 22 if small else 17
        out = ""
        if not small:   # dashed "selection" corners behind the scissors
            out += ('<path d="M48 82 V56 Q48 46 58 46 H84 M172 46 H198 Q208 46 208 56 V82" stroke="#FFFFFF" '
                    'stroke-width="9" fill="none" stroke-linecap="round" opacity="0.55"/>')
        out += (f'<path d="M100 150 L164 42" stroke="#FFFFFF" stroke-width="{w}" stroke-linecap="round"/>'
                f'<path d="M156 150 L92 42" stroke="#FFFFFF" stroke-width="{w}" stroke-linecap="round"/>'
                f'<circle cx="88" cy="180" r="{30 if small else 27}" stroke="#FFFFFF" stroke-width="{18 if small else 14}" fill="none"/>'
                f'<circle cx="168" cy="180" r="{30 if small else 27}" stroke="#FFFFFF" stroke-width="{18 if small else 14}" fill="none"/>')
        if not small:
            out += f'<circle cx="128" cy="103" r="8" fill="{c}"/>'
        return out
    if key == "planner":
        out = ('<rect x="50" y="58" width="156" height="146" rx="16" fill="#FFFFFF"/>'
               f'<path d="M50 74 Q50 58 66 58 H190 Q206 58 206 74 V96 H50 Z" fill="{light}"/>'
               f'<rect x="84" y="42" width="14" height="34" rx="7" fill="#FFFFFF" stroke="{c}" stroke-width="5"/>'
               f'<rect x="158" y="42" width="14" height="34" rx="7" fill="#FFFFFF" stroke="{c}" stroke-width="5"/>')
        if small:
            return out + "".join(f'<rect x="{x}" y="{y}" width="26" height="22" rx="5" fill="{c}"/>'
                                 for y in (114, 152) for x in (72, 115, 158))
        out += "".join(f'<rect x="{x}" y="{y}" width="20" height="17" rx="4" fill="{light}"/>'
                       for y in (110, 136, 162) for x in (68, 98, 128, 158) if not (x == 128 and y == 136))
        # bell
        out += (f'<path d="M138 116 Q138 98 156 98 Q174 98 174 116 V140 L182 150 H130 L138 140 Z" fill="{c}"/>'
                f'<circle cx="156" cy="158" r="7" fill="{c}"/>')
        return out
    raise KeyError(key)


def svg(key, small=False, badge=True):
    _, c = APPS[key]
    top, bottom = mix(c, "#FFFFFF", 0.18), mix(c, "#000000", 0.18)
    want_badge, badge = badge, ""
    if want_badge and not small and key != "suite":
        badge = (f'<circle cx="204" cy="204" r="38" fill="#FFFFFF"/>'
                 f'<circle cx="204" cy="204" r="31" fill="{SUITE_GREEN}"/>'
                 f'<g transform="translate(178.5 178.5) scale(0.2)"><path d="{LEAF[0]}" fill="#FFFFFF"/></g>')
    inset = 8 if not small else 2
    size = 256 - 2 * inset
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient></defs>
  <rect x="{inset}" y="{inset + (4 if not small else 0)}" width="{size}" height="{size}" rx="{56 if not small else 48}" fill="#000000" opacity="{0.18 if not small else 0}"/>
  <rect x="{inset}" y="{inset}" width="{size}" height="{size}" rx="{56 if not small else 48}" fill="url(#g)"/>
  <rect x="{inset}" y="{inset}" width="{size}" height="{size / 2}" rx="{56 if not small else 48}" fill="#FFFFFF" opacity="0.07"/>
  {glyph(key, c, small)}
  {badge}
</svg>'''


def render(svg_text, px):
    from PySide6.QtCore import QByteArray, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    r = QSvgRenderer(QByteArray(svg_text.encode()))
    # draw big then scale down = cleaner small icons
    big = max(px * 4, 256)
    img = QImage(big, big, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    r.render(p, QRectF(0, 0, big, big))
    p.end()
    return img.scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def to_pil(qimg):
    from PIL import Image
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    qimg.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(ba))).convert("RGBA")


def main():
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    os.makedirs(os.path.join(HERE, "svg"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "icons", "png"), exist_ok=True)
    sheet = []
    for key in APPS:
        big_svg, small_svg, mid_svg = svg(key), svg(key, small=True), svg(key, badge=False)
        with open(os.path.join(HERE, "svg", f"{key}.svg"), "w", encoding="utf-8") as fh:
            fh.write(big_svg)
        with open(os.path.join(HERE, "svg", f"{key}_small.svg"), "w", encoding="utf-8") as fh:
            fh.write(small_svg)
        frames = {}
        for s in SIZES:
            img = render(small_svg if s <= SMALL else mid_svg if s < BADGE_FROM else big_svg, s)
            img.save(os.path.join(HERE, "icons", "png", f"{key}_{s}.png"))
            frames[s] = to_pil(img)
        ico_sizes = [s for s in SIZES if s <= 256]
        frames[256].save(os.path.join(HERE, "icons", f"{key}.ico"), format="ICO",
                         sizes=[(s, s) for s in ico_sizes], append_images=[frames[s] for s in ico_sizes if s != 256])
        sheet.append((key, frames))
    # contact sheet for reviewing the designs
    from PIL import Image, ImageDraw, ImageFont
    cols, cell = len(sheet), 150
    W, H = cols * cell + 20, 420
    out = Image.new("RGBA", (W, H), (245, 246, 248, 255))
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("segoeui.ttf", 13)
    except OSError:
        font = ImageFont.load_default()
    for i, (key, frames) in enumerate(sheet):
        x = 10 + i * cell
        out.alpha_composite(frames[128], (x + 11, 14))
        for j, s in enumerate((48, 32, 24, 16)):
            out.alpha_composite(frames[s], (x + 6 + sum((48, 32, 24, 16)[:j]) + 6 * j, 168 + (48 - s)))
        name = APPS[key][0].replace("Ethical ", "")
        d.text((x + cell // 2 - 6, 236), name, fill=(40, 40, 40, 255), font=font, anchor="ma")
        # on a dark taskbar
        d.rectangle([x, 270, x + cell - 12, 330], fill=(32, 32, 32, 255))
        out.alpha_composite(frames[32], (x + 14, 284))
        out.alpha_composite(frames[24], (x + 60, 288))
        out.alpha_composite(frames[16], (x + 98, 292))
    d.text((10, 350), "Top: 128 px · Row 2: 48 / 32 / 24 / 16 px · Dark strip: taskbar sizes", fill=(90, 90, 90, 255), font=font)
    out.save(os.path.join(HERE, "preview.png"))
    print("built", len(APPS), "icons")


if __name__ == "__main__":
    main()
