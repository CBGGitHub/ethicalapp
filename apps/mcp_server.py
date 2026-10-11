"""EthicalApp MCP server - lets AI assistants (Claude Desktop / Claude Code) use the suite's apps on files.

Run:   python apps/mcp_server.py [--apps pdf,document,spreadsheet,presentation,photo,converter,database]
(stdio transport). Install into Claude with apps/install_mcp.py. Every tool works on files using the same
code as the desktop apps, so the app windows don't need to be open.

Tools are async on purpose: Qt text/painting code must run on the main thread, and async tools run there.
"""
import argparse
import html as html_mod
import json
import os
import re
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

ALL_APPS = ["pdf", "document", "spreadsheet", "presentation", "photo", "converter", "database", "stickynotes", "snip", "planner"]
APP_SCRIPTS = {"pdf": "pdf_editor.py", "document": "word_processor.py", "spreadsheet": "sheets_app.py",
               "presentation": "slides_app.py", "photo": "photo_app.py", "converter": "converter_app.py",
               "database": "base_app.py", "stickynotes": "sticky_notes.py", "snip": "snip_app.py", "planner": "planner_app.py"}
from suite_common import EXT_APP  # noqa: E402  (file extension -> app key)

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
NET = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)

INSTRUCTIONS = """EthicalApp: free desktop apps (PDF Editor, Document Editor, Spreadsheet Editor, Presentation
Editor, Photo Editor, Converter, Database, Sticky Notes, Snip, Planner). These tools work directly on files on this PC.

Conventions:
- Always pass full (absolute) Windows paths, e.g. C:\\Users\\Name\\Documents\\report.docx.
- Editing tools never overwrite the input unless you pass `output` equal to the input path. Without `output`
  they save a new copy next to the original (e.g. "report (edited).pdf") and return its path.
- Creating tools refuse to overwrite an existing file unless `overwrite=True`.
- Documents (.docx) are created/appended from Markdown (# headings, **bold**, *italic*, - lists, 1. lists,
  | tables |). Spreadsheet cells use A1 references; values starting with = are formulas (Excel syntax,
  143 functions). PDF coordinates are points (72 per inch) from the top-left of the page; pages are 1-based.
- After making something for the user, offer `open_in_app` so they can see it in the matching Ethical app.
- Sticky notes (to-do lists on the user's desktop) are Markdown: "- [ ] task" / "- [x] done", "- bullet",
  **bold**. Use notes_list to find a note's id. Changes appear on the user's screen within a couple of seconds.
- For how-to questions about the apps themselves (menus, shortcuts, what's supported), use `guide_search`
  then `guide_read` — the full user guide is available there.
"""

server = MCPServer("ethical-suite", title="EthicalApp", instructions=INSTRUCTIONS, version="1.0")
_REGISTRY = []   # (group, fn, annotations)


def tool(group, ann=WRITE):
    def deco(fn):
        _REGISTRY.append((group, fn, ann))
        return fn
    return deco


# ====================================================================== helpers

_qt_app = None


def qt():
    """A hidden Qt application (needed for text layout, fonts and drawing). Created once on the main thread."""
    global _qt_app
    if _qt_app is None:
        from PySide6.QtGui import QGuiApplication
        _qt_app = QGuiApplication.instance() or QGuiApplication(["ethical-mcp"])
    return _qt_app


def src_path(path):
    p = os.path.abspath(os.path.expanduser(str(path).strip().strip('"')))
    if not os.path.exists(p):
        raise ValueError(f"File not found: {p}")
    return p


def new_path(path, overwrite=False):
    p = os.path.abspath(os.path.expanduser(str(path).strip().strip('"')))
    if os.path.exists(p) and not overwrite:
        raise ValueError(f"{p} already exists. Pass overwrite=True to replace it, or choose another name.")
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    return p


def out_path(src, output, suffix=" (edited)", ext=None):
    import convert_core as cc
    if output:
        p = os.path.abspath(os.path.expanduser(str(output).strip().strip('"')))
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        return p
    base, e = os.path.splitext(src)
    return cc.unique_path(base + suffix + (ext or e))


def parse_pages(spec, n):
    """'1-3,5' (1-based) -> sorted 0-based list; None/'' = all pages."""
    if spec in (None, "", "all"):
        return list(range(n))
    out = set()
    for part in str(spec).replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            a = int(a) if a else 1
            b = int(b) if b else n
            out.update(range(a - 1, min(b, n)))
        elif part:
            out.add(int(part) - 1)
    bad = [p + 1 for p in out if not 0 <= p < n]
    if bad:
        raise ValueError(f"Page(s) {bad} don't exist - the document has {n} page(s).")
    return sorted(out)


def as_json(obj):
    return json.dumps(obj, indent=1, ensure_ascii=False, default=str)


# ====================================================================== guide & general

_GUIDE = None


def guide_articles():
    global _GUIDE
    if _GUIDE is None:
        text = open(os.path.join(ROOT, "guide", "index.html"), encoding="utf-8").read()
        arts = []
        for m in re.finditer(r'\{ id: "([^"]+)", section: "([^"]+)", title: "([^"]+)", keywords: "([^"]*)",\s*body: `(.*?)` \}',
                             text, re.S):
            body = m.group(5)
            body = re.sub(r'\$\{K\("([^"]+)"\)\}', lambda k: "+".join(k.group(1).replace("_", " ").split()), body)
            body = re.sub(r"<(h2|h3)>(.*?)</\1>", lambda h: "\n## " + h.group(2) + "\n", body)
            body = re.sub(r"<li>", "\n- ", body)
            body = re.sub(r"</tr>", "\n", body)
            body = re.sub(r"</t[dh]>", " | ", body)
            body = re.sub(r"<br\s*/?>|</p>|<p>|</div>", "\n", body)
            body = re.sub(r"<[^>]+>", "", body)
            body = html_mod.unescape(body).replace("\\\\", "\\")
            body = re.sub(r"\n\s*\n+", "\n\n", body).strip()
            arts.append({"id": m.group(1), "section": m.group(2), "title": m.group(3), "keywords": m.group(4),
                         "text": body})
        _GUIDE = arts
    return _GUIDE


@tool("core", READ)
async def guide_search(query: str) -> str:
    """Search the EthicalApp user guide (how to use every app: menus, tools, shortcuts, file compatibility,
    troubleshooting). Returns matching article ids and titles; read one with guide_read."""
    terms = query.lower().split()
    scored = []
    for a in guide_articles():
        hay = (a["title"] + " " + a["keywords"]).lower()
        body = a["text"].lower()
        s = sum(10 * (t in a["title"].lower()) + 5 * (t in hay) + min(body.count(t), 5) for t in terms)
        if s and all(t in hay or t in body for t in terms):
            scored.append((s, a))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return "No guide articles matched. Try other words. Article list: " + ", ".join(a["id"] for a in guide_articles())
    return "\n".join(f"{a['id']}: {a['title']}" for _, a in scored[:10])


@tool("core", READ)
async def guide_read(article_id: str) -> str:
    """Read one article of the EthicalApp user guide as plain text (ids from guide_search, e.g. 'pdf-redact',
    'sheets-functions', 'conv-download', 'base-queries')."""
    for a in guide_articles():
        if a["id"] == article_id.strip():
            return f"# {a['title']}\n\n{a['text']}"
    raise ValueError(f"No article '{article_id}'. Use guide_search to find ids.")


@tool("core", READ)
async def suite_info() -> str:
    """What this EthicalApp installation can do: enabled apps and their tools, file locations, versions."""
    groups = {}
    for g, fn, _ in _REGISTRY:
        if g in ENABLED or g == "core":
            groups.setdefault(g, []).append(fn.__name__)
    return as_json({"suite_folder": ROOT, "enabled_apps": ENABLED, "tools": groups,
                    "python": sys.version.split()[0]})


@tool("core", WRITE)
async def open_in_app(path: str) -> str:
    """Open a file in the matching EthicalApp desktop app so the user can see/edit it
    (PDF→PDF Editor, docx→Document Editor, xlsx/csv→Spreadsheet Editor, pptx→Presentation Editor,
    images/psd→Photo Editor, .db→Database)."""
    p = src_path(path)
    app = EXT_APP.get(os.path.splitext(p)[1].lower())
    if not app:
        raise ValueError("No Ethical app opens this type of file.")
    from suite_common import launch_command, start_detached
    start_detached(launch_command(app, p))
    return f"Opened {os.path.basename(p)} in Ethical {app.title()} app."


# ====================================================================== PDF

def _pdf(path):
    import pymupdf
    doc = pymupdf.open(src_path(path))
    if doc.needs_pass:
        raise ValueError("This PDF is password protected.")
    return doc


def _save_pdf(doc, path):
    data = doc.tobytes(garbage=3, deflate=True)
    try:
        import pymupdf
        tmp = pymupdf.open(stream=data, filetype="pdf")
        tmp.subset_fonts()
        data = tmp.tobytes(garbage=3, deflate=True)
    except Exception:
        pass
    with open(path, "wb") as fh:
        fh.write(data)
    return path


@tool("pdf", READ)
async def pdf_info(path: str) -> str:
    """Page count, page size, metadata, form fields, outline and whether a PDF has selectable text."""
    doc = _pdf(path)
    p0 = doc[0].rect if doc.page_count else None
    fields = sum(1 for pg in doc for _ in pg.widgets())
    return as_json({"pages": doc.page_count, "first_page_size_pt": [round(p0.width, 1), round(p0.height, 1)] if p0 else None,
                    "metadata": {k: v for k, v in (doc.metadata or {}).items() if v},
                    "form_fields": fields, "outline": [t[1] for t in doc.get_toc()[:30]],
                    "has_text": any(pg.get_text().strip() for pg in doc.pages(0, min(doc.page_count, 5)))})


@tool("pdf", READ)
async def pdf_extract_text(path: str, pages: str | None = None) -> str:
    """Text of a PDF (optionally only some pages, e.g. '1-3,7'). Scanned PDFs without a text layer return little text."""
    doc = _pdf(path)
    out = []
    for i in parse_pages(pages, doc.page_count):
        out.append(f"--- Page {i + 1} ---\n{doc[i].get_text()}")
    text = "\n".join(out)
    return text[:150000] + ("\n…(truncated)" if len(text) > 150000 else "")


@tool("pdf", WRITE)
async def pdf_merge(paths: list[str], output: str, overwrite: bool = False) -> str:
    """Combine several PDFs (and/or images) into one PDF, in the given order."""
    import convert_core as cc
    import threading
    dst = new_path(output, overwrite)
    cc.combine_pdf([src_path(p) for p in paths], dst, lambda *_: None, threading.Event())
    return f"Saved {dst}"


@tool("pdf", WRITE)
async def pdf_split(path: str, output_folder: str | None = None) -> str:
    """Save every page of a PDF as its own PDF file."""
    import pymupdf
    import convert_core as cc
    doc = _pdf(path)
    folder = os.path.abspath(output_folder) if output_folder else os.path.dirname(src_path(path))
    os.makedirs(folder, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    outs = []
    for i in range(doc.page_count):
        o = pymupdf.open()
        o.insert_pdf(doc, from_page=i, to_page=i)
        p = cc.unique_path(os.path.join(folder, f"{base}_page{i + 1}.pdf"))
        o.save(p, garbage=3, deflate=True)
        outs.append(p)
    return f"Saved {len(outs)} files in {folder}"


@tool("pdf", WRITE)
async def pdf_extract_pages(path: str, pages: str, output: str | None = None) -> str:
    """Copy some pages (e.g. '2-4,9') into a new PDF."""
    import pymupdf
    doc = _pdf(path)
    o = pymupdf.open()
    for i in parse_pages(pages, doc.page_count):
        o.insert_pdf(doc, from_page=i, to_page=i)
    dst = out_path(src_path(path), output, " (pages)")
    o.save(dst, garbage=3, deflate=True)
    return f"Saved {o.page_count} page(s) to {dst}"


@tool("pdf", WRITE)
async def pdf_delete_pages(path: str, pages: str, output: str | None = None) -> str:
    """Remove pages (e.g. '1,3-4') and save the result."""
    doc = _pdf(path)
    pg = parse_pages(pages, doc.page_count)
    if len(pg) >= doc.page_count:
        raise ValueError("Can't delete every page.")
    doc.delete_pages(pg)
    return f"Saved {_save_pdf(doc, out_path(src_path(path), output))} ({doc.page_count} pages left)"


@tool("pdf", WRITE)
async def pdf_rotate_pages(path: str, degrees: int, pages: str | None = None, output: str | None = None) -> str:
    """Rotate pages by 90, 180 or 270 degrees clockwise (all pages if `pages` is empty)."""
    doc = _pdf(path)
    if degrees % 90:
        raise ValueError("degrees must be a multiple of 90")
    for i in parse_pages(pages, doc.page_count):
        doc[i].set_rotation((doc[i].rotation + degrees) % 360)
    return f"Saved {_save_pdf(doc, out_path(src_path(path), output))}"


def _write_pdf_text(page, x, y_top, text, font, size, color, bold, italic):
    import pymupdf
    from suite_common import font_file
    path = font_file(font, bold, italic)
    f = pymupdf.Font(fontfile=path) if path else pymupdf.Font({(0, 0): "helv", (1, 0): "hebo", (0, 1): "heit",
                                                                (1, 1): "hebi"}[(bool(bold), bool(italic))])
    c = color.lstrip("#")
    rgb = tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    tw = pymupdf.TextWriter(page.rect)
    y = y_top + size * (f.ascender or 0.8)
    for line in text.split("\n"):
        tw.append((x, y), line, font=f, fontsize=size)
        y += size * 1.2
    tw.write_text(page, color=rgb)


@tool("pdf", WRITE)
async def pdf_add_text(path: str, page: int, x: float, y: float, text: str, font: str = "Arial", size: float = 12,
                       color: str = "#000000", bold: bool = False, italic: bool = False, output: str | None = None) -> str:
    """Write new text on a PDF page (real page text, any installed font). x/y = top-left of the text in points
    from the page's top-left (72 points = 1 inch). Use \\n for several lines."""
    doc = _pdf(path)
    if not 1 <= page <= doc.page_count:
        raise ValueError(f"Page {page} doesn't exist ({doc.page_count} pages).")
    _write_pdf_text(doc[page - 1], x, y, text, font, size, color, bold, italic)
    return f"Saved {_save_pdf(doc, out_path(src_path(path), output))}"


@tool("pdf", WRITE)
async def pdf_replace_text(path: str, find: str, replace: str, pages: str | None = None,
                           output: str | None = None) -> str:
    """Find text in a PDF and replace it everywhere (keeps the size/colour and uses the closest installed font).
    Good for fixing typos, dates, names. The original words are removed for real."""
    import pymupdf
    from suite_common import match_family
    doc = _pdf(path)
    n = 0
    for i in parse_pages(pages, doc.page_count):
        page = doc[i]
        hits = page.search_for(find)
        if not hits:
            continue
        spans = [s for b in page.get_text("dict")["blocks"] if b["type"] == 0 for l in b["lines"] for s in l["spans"]]
        jobs = []
        for r in hits:
            sp = next((s for s in spans if pymupdf.Rect(s["bbox"]).intersects(r)), None)
            size = sp["size"] if sp else r.height * 0.8
            color = f"#{sp['color']:06X}" if sp else "#000000"
            name = sp["font"] if sp else "Helvetica"
            fam = match_family(name) or ("Times New Roman" if "times" in name.lower() or "serif" in name.lower() else "Arial")
            bold = bool(sp and (sp["flags"] & 16 or "bold" in name.lower()))
            baseline = sp["origin"][1] if sp else r.y1 - r.height * 0.2
            jobs.append((r, size, color, fam, bold, baseline))
            page.add_redact_annot(r + (0, r.height * 0.15, 0, -r.height * 0.15), fill=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
        for r, size, color, fam, bold, baseline in jobs:
            _write_pdf_text(page, r.x0, baseline - size * 0.8, replace, fam, size, color, bold, False)
            n += 1
    if not n:
        return f"'{find}' wasn't found."
    return f"Replaced {n} occurrence(s). Saved {_save_pdf(doc, out_path(src_path(path), output))}"


@tool("pdf", WRITE)
async def pdf_redact(path: str, terms: list[str], output: str | None = None, case_sensitive: bool = False) -> str:
    """Permanently remove sensitive text (names, account numbers…) from a PDF: every occurrence of each term is
    deleted from the file and covered with a black box. Always saves a new file unless `output` says otherwise."""
    import pymupdf
    doc = _pdf(path)
    n = 0
    for page in doc:
        for t in terms:
            flags = 0 if case_sensitive else pymupdf.TEXT_PRESERVE_WHITESPACE
            for r in page.search_for(t, flags=flags):
                page.add_redact_annot(r, fill=(0, 0, 0))
                n += 1
        page.apply_redactions()
    return f"Redacted {n} occurrence(s). Saved {_save_pdf(doc, out_path(src_path(path), output, ' (redacted)'))}"


@tool("pdf", READ)
async def pdf_list_form_fields(path: str) -> str:
    """List the fillable form fields in a PDF (name, type, current value, choices)."""
    doc = _pdf(path)
    out = []
    for i, page in enumerate(doc):
        for w in page.widgets():
            out.append({"page": i + 1, "name": w.field_name, "label": w.field_label, "type": w.field_type_string,
                        "value": w.field_value, "choices": w.choice_values or None})
    return as_json(out) if out else "This PDF has no form fields."


@tool("pdf", WRITE)
async def pdf_fill_form(path: str, values: dict[str, str | bool | int | float], output: str | None = None) -> str:
    """Fill PDF form fields: values = {field name: value}. Checkboxes take true/false."""
    doc = _pdf(path)
    done = set()
    for page in doc:
        for w in page.widgets():
            if w.field_name in values:
                v = values[w.field_name]
                w.field_value = bool(v) if w.field_type_string in ("CheckBox", "RadioButton") else str(v)
                w.update()
                done.add(w.field_name)
    missing = set(values) - done
    msg = f"Filled {len(done)} field(s). Saved {_save_pdf(doc, out_path(src_path(path), output, ' (filled)'))}"
    return msg + (f". Not found: {sorted(missing)}" if missing else "")


@tool("pdf", WRITE)
async def pdf_add_image(path: str, page: int, image_path: str, x: float, y: float, width: float,
                        output: str | None = None) -> str:
    """Place a picture (logo, signature, stamp) on a PDF page. x/y = top-left in points, width in points
    (height keeps the picture's proportions)."""
    import pymupdf
    from PIL import Image
    doc = _pdf(path)
    img = src_path(image_path)
    w, h = Image.open(img).size
    rect = pymupdf.Rect(x, y, x + width, y + width * h / w)
    doc[page - 1].insert_image(rect, filename=img, keep_proportion=True)
    return f"Saved {_save_pdf(doc, out_path(src_path(path), output))}"


# ====================================================================== documents

def _style_markdown_doc(doc):
    """Give Markdown headings the Ethical Document Editor heading look (sizes/colours) so Word shows them right."""
    from PySide6.QtGui import QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor
    from docx_io import HEADING_LOOK, PX_PER_PT
    b = doc.begin()
    while b.isValid():
        bf = b.blockFormat()
        lvl = bf.headingLevel()
        c = QTextCursor(b)
        if lvl:
            size, color = HEADING_LOOK[min(lvl, 6)]
            cf = QTextCharFormat()
            cf.setFontPointSize(size)
            cf.setForeground(QColor(color))
            cf.setFontWeight(QFont.Bold if lvl <= 2 else QFont.Normal)
            c.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
            c.mergeCharFormat(cf)
            nb = QTextBlockFormat()
            nb.setTopMargin((12 if lvl == 1 else 6) * PX_PER_PT)
            nb.setBottomMargin(3 * PX_PER_PT)
            c.mergeBlockFormat(nb)
        elif not b.textList() and not QTextCursor(b).currentTable():
            nb = QTextBlockFormat()
            nb.setBottomMargin(8 * PX_PER_PT)
            c.mergeBlockFormat(nb)
        b = b.next()


def _page_setup(page_size):
    from docx_io import PageSetup
    s = PageSetup()
    if str(page_size).upper() == "A4":
        s.width_in, s.height_in = 8.27, 11.69
    return s


@tool("document", READ)
async def docx_read(path: str) -> str:
    """Read a Word document (.docx, also .txt/.md/.html) and return its content as Markdown
    (headings, bold/italic, lists, tables)."""
    qt()
    import convert_core as cc
    doc, setup = cc.text_document(src_path(path))
    return doc.toMarkdown()[:150000]


@tool("document", WRITE)
async def docx_create(path: str, markdown: str, page_size: str = "Letter", font: str = "Calibri",
                      font_size: int = 11, overwrite: bool = False) -> str:
    """Create a new Word document (.docx) from Markdown: # / ## / ### headings, **bold**, *italic*, - bullets,
    1. numbered lists, | tables |, blank lines between paragraphs. page_size: 'Letter' or 'A4'.
    Also works for .odt, .html, .md, .txt, or .pdf output (by the file extension)."""
    qt()
    from PySide6.QtGui import QFont
    from docx_io import save_docx
    from word_processor import new_document
    dst = new_path(path, overwrite)
    doc = new_document()
    doc.setDefaultFont(QFont(font, font_size))
    doc.setMarkdown(markdown)
    _style_markdown_doc(doc)
    setup = _page_setup(page_size)
    ext = os.path.splitext(dst)[1].lower()
    if ext == ".pdf":
        import convert_core as cc
        cc.textdoc_to_pdf(doc, setup, dst)
    elif ext == ".docx":
        save_docx(doc, setup, dst)
    else:
        from PySide6.QtGui import QTextDocumentWriter
        if ext == ".odt":
            QTextDocumentWriter(dst, b"odf").write(doc)
        else:
            open(dst, "w", encoding="utf-8").write(doc.toHtml() if ext in (".html", ".htm") else
                                                     doc.toMarkdown() if ext == ".md" else doc.toPlainText())
    return f"Created {dst}"


@tool("document", WRITE)
async def docx_append(path: str, markdown: str, output: str | None = None) -> str:
    """Add Markdown content (headings, paragraphs, lists, tables) to the end of an existing Word document."""
    qt()
    from PySide6.QtGui import QTextCursor
    from docx_io import load_docx, save_docx
    src = src_path(path)
    doc, setup = load_docx(src)
    c = QTextCursor(doc)
    c.movePosition(QTextCursor.End)
    c.insertBlock()
    c.insertMarkdown(markdown)
    _style_markdown_doc(doc)
    dst = out_path(src, output)
    save_docx(doc, setup, dst)
    return f"Saved {dst}"


@tool("document", WRITE)
async def docx_replace_text(path: str, find: str, replace: str, output: str | None = None,
                            match_case: bool = True) -> str:
    """Find and replace text everywhere in a Word document (body, tables, headers, footers), keeping formatting
    where the text sits inside one run."""
    import docx
    src = src_path(path)
    d = docx.Document(src)
    flags = 0 if match_case else re.I
    pat = re.compile(re.escape(find), flags)
    count = 0

    def paras():
        yield from d.paragraphs
        for t in d.tables:
            for row in t.rows:
                for cell in row.cells:
                    yield from cell.paragraphs
        for s in d.sections:
            for part in (s.header, s.footer):
                yield from part.paragraphs
    for p in paras():
        if not pat.search(p.text):
            continue
        done = False
        for r in p.runs:
            if pat.search(r.text):
                count += len(pat.findall(r.text))
                r.text = pat.sub(replace, r.text)
                done = True
        if not done or pat.search(p.text):   # text split across runs: rebuild in the first run
            new = pat.sub(replace, p.text)
            count += len(pat.findall(p.text))
            for i, r in enumerate(p.runs):
                r.text = new if i == 0 else ""
    dst = out_path(src, output)
    d.save(dst)
    return f"Replaced {count} occurrence(s). Saved {dst}"


# ====================================================================== spreadsheets

def _load_wb(path, create=False):
    import sheet_engine as se
    from xlsx_io import load_csv, load_xlsx
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(p):
        if create:
            return se.Workbook(), p
        raise ValueError(f"File not found: {p}")
    if p.lower().endswith((".csv", ".tsv")):
        return load_csv(p), p
    return load_xlsx(p)[0], p


def _sheet(wb, name):
    if not name:
        return wb.sheets[0]
    s = wb.sheet(name)
    if s is None:
        raise ValueError(f"No sheet '{name}'. Sheets: {[x.name for x in wb.sheets]}")
    return s


def _save_wb(wb, path, sheet):
    from xlsx_io import save_csv, save_xlsx
    if path.lower().endswith(".csv"):
        save_csv(wb, sheet, path)
    else:
        save_xlsx(wb, path)


@tool("spreadsheet", READ)
async def xlsx_read(path: str, sheet: str | None = None, cell_range: str | None = None, show_formulas: bool = False,
                    max_rows: int = 200) -> str:
    """Read an Excel workbook (.xlsx/.csv): lists the sheets and returns cells as a table with column letters and
    row numbers. Values are calculated; show_formulas=True shows formulas instead (e.g. =SUM(B2:B9))."""
    import sheet_engine as se
    wb, _ = _load_wb(src_path(path))
    sh = _sheet(wb, sheet)
    if cell_range:
        rng = se.parse_range(cell_range)
        if not rng:
            raise ValueError("cell_range must look like A1:D20")
        r1, c1, r2, c2 = rng
    else:
        r1, c1, r2, c2 = 0, 0, sh.max_row(), sh.max_col()
    r2 = min(r2, r1 + max_rows - 1)
    lines = [f"Sheets: {[s.name for s in wb.sheets]}  ·  showing '{sh.name}' {se.cell_name(r1, c1)}:{se.cell_name(max(r2, r1), max(c2, c1))}"]
    if r2 < 0:
        return lines[0] + "\n(empty sheet)"
    lines.append("row | " + " | ".join(se.col_name(c) for c in range(c1, c2 + 1)))
    for r in range(r1, r2 + 1):
        cells = []
        for c in range(c1, c2 + 1):
            cell = sh.get(r, c)
            if cell is None:
                cells.append("")
            elif show_formulas and cell.is_formula():
                cells.append(cell.value)
            else:
                cells.append(se.format_value(wb.value(sh, r, c), cell.style.get("numfmt", "General")))
        lines.append(f"{r + 1} | " + " | ".join(cells))
    if sh.max_row() > r2:
        lines.append(f"… {sh.max_row() - r2} more row(s); use cell_range to see them")
    return "\n".join(lines)


@tool("spreadsheet", WRITE)
async def xlsx_write(path: str, cells: dict[str, str | int | float | bool | None], sheet: str | None = None,
                     create_if_missing: bool = True) -> str:
    """Set cells in an Excel workbook and save it: cells = {"A1": "Name", "B2": 42, "C2": "=B2*1.2"}.
    Text like '25%', '$5', '2026-10-11' is understood like Excel does; None clears a cell. Creates the file (and
    sheet) if needed. Returns the calculated values of the cells you wrote."""
    import sheet_engine as se
    wb, p = _load_wb(path, create=create_if_missing)
    if sheet and wb.sheet(sheet) is None:
        if not wb.sheets[0].cells and wb.sheets[0].name == "Sheet1" and len(wb.sheets) == 1 and not os.path.exists(p):
            wb.sheets[0].name = sheet
        else:
            wb.sheets.append(se.Sheet(sheet))
    sh = _sheet(wb, sheet)
    for ref, val in cells.items():
        rc = se.parse_cell(ref)
        if rc is None:
            raise ValueError(f"Bad cell reference {ref!r} (use A1 style)")
        v, fmt = se.parse_input(val if isinstance(val, str) else ("" if val is None else val))
        if v is None:
            sh.cells.pop(rc, None)
            continue
        cell = sh.cells.setdefault(rc, se.Cell())
        cell.value, cell.cached = v, None
        if fmt and fmt != "@" and "numfmt" not in cell.style:
            cell.style = dict(cell.style, numfmt=fmt)
    wb.recalc_all()
    _save_wb(wb, p, sh)
    res = {ref: se.format_value(wb.value(sh, *se.parse_cell(ref)),
                                (sh.get(*se.parse_cell(ref)).style.get("numfmt", "General") if sh.get(*se.parse_cell(ref)) else "General"))
           for ref in cells}
    return f"Saved {p}\n" + as_json(res)


@tool("spreadsheet", WRITE)
async def xlsx_format(path: str, cell_range: str, sheet: str | None = None, bold: bool | None = None,
                      italic: bool | None = None, font_color: str | None = None, fill_color: str | None = None,
                      number_format: str | None = None, align: str | None = None, borders: bool | None = None,
                      column_width_px: int | None = None) -> str:
    """Format a range of cells (e.g. 'A1:D1'): bold/italic, font_color/fill_color ('#RRGGBB'), number_format
    (Excel codes like '$#,##0.00', '0.0%', 'yyyy-mm-dd'), align ('left'|'center'|'right'), borders (thin all
    round), column_width_px."""
    import sheet_engine as se
    wb, p = _load_wb(src_path(path))
    sh = _sheet(wb, sheet)
    rng = se.parse_range(cell_range)
    if not rng:
        raise ValueError("cell_range must look like A1:D20")
    r1, c1, r2, c2 = rng
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            cell = sh.cells.setdefault((r, c), se.Cell())
            st = dict(cell.style)
            for key, val in (("bold", bold), ("italic", italic), ("color", font_color), ("fill", fill_color),
                             ("numfmt", number_format), ("halign", align)):
                if val is not None:
                    if val is False or val == "":
                        st.pop(key, None)
                    else:
                        st[key] = val.upper() if key in ("color", "fill") else val
            if borders is not None:
                if borders:
                    st["border"] = {s: "thin" for s in ("left", "right", "top", "bottom")}
                else:
                    st.pop("border", None)
            cell.style = st
    if column_width_px:
        for c in range(c1, c2 + 1):
            sh.col_widths[c] = column_width_px
    wb.recalc_all()
    _save_wb(wb, p, sh)
    return f"Formatted {cell_range}. Saved {p}"


@tool("spreadsheet", WRITE)
async def xlsx_add_chart(path: str, data_range: str, chart_type: str = "column", title: str = "",
                         sheet: str | None = None, anchor_cell: str | None = None) -> str:
    """Add a chart to a sheet. data_range includes a header row (series names) and a first column of labels,
    e.g. 'A1:C6'. chart_type: column, bar, line or pie. anchor_cell = top-left cell of the chart."""
    import sheet_engine as se
    wb, p = _load_wb(src_path(path))
    sh = _sheet(wb, sheet)
    rng = se.parse_range(data_range)
    if not rng or rng[2] - rng[0] < 1 or rng[3] - rng[1] < 1:
        raise ValueError("data_range needs at least 2 rows and 2 columns, e.g. A1:B6")
    if chart_type not in ("column", "bar", "line", "pie"):
        raise ValueError("chart_type must be column, bar, line or pie")
    ar, ac = se.parse_cell(anchor_cell) if anchor_cell else (rng[0], rng[3] + 2)
    sh.charts.append({"type": chart_type, "ref": rng, "title": title, "row": ar, "col": ac, "w": 480, "h": 288})
    _save_wb(wb, p, sh)
    return f"Added a {chart_type} chart. Saved {p}"


@tool("spreadsheet", READ)
async def xlsx_calculate(formula: str, path: str | None = None, sheet: str | None = None) -> str:
    """Evaluate an Excel formula (e.g. '=PMT(5%/12,360,-200000)' or '=SUM(B2:B50)' against a workbook) without
    changing any file."""
    import sheet_engine as se
    wb = _load_wb(src_path(path))[0] if path else se.Workbook()
    sh = _sheet(wb, sheet)
    f = formula if formula.startswith("=") else "=" + formula
    try:
        v = se.Evaluator(wb, sh).run(f)
    except se.ExcelError as e:
        v = e
    return se.format_value(v) if not isinstance(v, float) else repr(v)


@tool("spreadsheet", WRITE)
async def xlsx_add_sheet(path: str, name: str) -> str:
    """Add an empty sheet (tab) to a workbook."""
    import sheet_engine as se
    wb, p = _load_wb(src_path(path))
    if wb.sheet(name):
        raise ValueError("A sheet with that name already exists.")
    wb.sheets.append(se.Sheet(name))
    _save_wb(wb, p, wb.sheets[-1])
    return f"Added sheet '{name}'. Saved {p}"


# ====================================================================== presentations

def _fill_text(el, text):
    """Replace an element's text, keeping its formatting (lines → paragraphs / bullets)."""
    from PySide6.QtGui import QTextCursor
    from pptx_io import clone_doc
    doc = el.doc
    c = QTextCursor(doc)
    c.movePosition(QTextCursor.Start)
    fmt, bf = c.charFormat(), c.blockFormat()
    c.select(QTextCursor.Document)
    c.removeSelectedText()
    for i, line in enumerate(str(text).split("\n")):
        if i:
            c.insertBlock(bf, fmt)
        c.insertText(line, fmt)


def _add_slides(pres, slides):
    from PySide6.QtGui import QFont, QImage
    from pptx_io import Element, new_slide_from_layout
    from slides_app import text_element
    names = [l.name.lower() for l in pres.layouts]

    def layout_index(name, has_body):
        if name:
            for i, n in enumerate(names):
                if n == name.lower():
                    return i
        want = "title and content" if has_body else "title only"
        for i, n in enumerate(names):
            if want in n or (has_body and "content" in n):
                return i
        return 0
    added = 0
    for spec in slides:
        bullets = spec.get("bullets")
        body = "\n".join(bullets) if bullets else spec.get("text", "")
        li = layout_index(spec.get("layout"), bool(body))
        s = new_slide_from_layout(pres, li)
        title_el = next((e for e in s.elements if e.role == "title"), None)
        body_el = next((e for e in s.elements if e.role == "body"), None)
        if spec.get("title"):
            if title_el is None:
                t = pres.theme or {"title": "#1F1F1F", "tfont": "Calibri Light"}
                title_el = text_element("title", pres.width * 0.06, pres.height * 0.05, pres.width * 0.88, pres.height * 0.16,
                                        40, t.get("title", "#1F1F1F"), t.get("tfont", "Calibri Light"), anchor="b")
                s.elements.append(title_el)
            _fill_text(title_el, spec["title"])
        if body:
            if body_el is None:
                t = pres.theme or {"text": "#404040", "bfont": "Calibri"}
                body_el = text_element("body", pres.width * 0.06, pres.height * 0.25, pres.width * 0.88, pres.height * 0.66,
                                       24, t.get("text", "#404040"), t.get("bfont", "Calibri"), bullets=bool(bullets))
                s.elements.append(body_el)
            _fill_text(body_el, body)
        if spec.get("image"):
            data = open(src_path(spec["image"]), "rb").read()
            img = QImage.fromData(data)
            W, H = pres.width, pres.height
            if body_el is not None:
                body_el.w = W * 0.46
                box = (W * 0.52, H * 0.25, W * 0.42, H * 0.66)
            else:
                box = (W * 0.1, H * 0.25, W * 0.8, H * 0.68)
            sc = min(box[2] / img.width(), box[3] / img.height())
            w, h = img.width() * sc, img.height() * sc
            s.elements.append(Element(kind="image", image=data, x=box[0] + (box[2] - w) / 2, y=box[1] + (box[3] - h) / 2, w=w, h=h))
        s.elements = [e for e in s.elements if not (e.role in ("title", "body") and e.is_empty())]
        s.notes = spec.get("notes", "")
        pres.slides.append(s)
        added += 1
    return added


@tool("presentation", READ)
async def pptx_read(path: str) -> str:
    """Read a PowerPoint deck (.pptx): each slide's title, text, pictures/tables count and speaker notes."""
    qt()
    from pptx_io import load_pptx
    pres, warnings = load_pptx(src_path(path))
    out = [f"{len(pres.slides)} slide(s), {round(pres.width)}x{round(pres.height)} px. Layouts: "
           f"{[l.name for l in pres.layouts]}" + (f". Not editable here: {warnings}" if warnings else "")]
    for i, s in enumerate(pres.slides, 1):
        title = next((e.doc.toPlainText() for e in s.elements if e.role == "title" and e.doc and not e.is_empty()), "")
        texts = [e.doc.toPlainText().strip() for e in s.elements if e.doc and e.role != "title" and not e.is_empty()]
        imgs = sum(1 for e in s.elements if e.kind == "image")
        out.append(f"\n## Slide {i}{' (hidden)' if s.hidden else ''}: {title}\n" + "\n".join(texts)
                   + (f"\n[{imgs} picture(s)]" if imgs else "") + (f"\nNotes: {s.notes}" if s.notes.strip() else ""))
    return "\n".join(out)


@tool("presentation", WRITE)
async def pptx_create(path: str, slides: list[dict], theme: str = "Office", overwrite: bool = False) -> str:
    """Create a PowerPoint deck (.pptx). slides = [{"title": "...", "bullets": ["...", "..."], "notes": "...",
    "image": "C:\\\\pic.png", "layout": "Title Slide"}]. Use "text" instead of "bullets" for a plain paragraph;
    the first slide is usually {"title": ..., "text": subtitle, "layout": "Title Slide"}.
    Themes: Office, Midnight, Slate, Forest, Sunset, Ocean, Charcoal, Blush. Also saves .pdf if the path ends in .pdf."""
    qt()
    from pptx_io import save_pptx
    from slides_app import THEMES, new_presentation
    if theme not in THEMES:
        raise ValueError(f"Unknown theme. Choose from {list(THEMES)}")
    dst = new_path(path, overwrite)
    pres = new_presentation(theme)
    pres.slides = []
    n = _add_slides(pres, slides)
    if dst.lower().endswith(".pdf"):
        _deck_pdf(pres, dst)
    else:
        save_pptx(pres, dst)
    return f"Created {dst} with {n} slide(s)"


def _deck_pdf(pres, dst):
    from PySide6.QtCore import QMarginsF, QRectF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter
    from slides_app import render_slide
    w = QPdfWriter(dst)
    w.setResolution(144)
    w.setPageLayout(QPageLayout(QPageSize(QSizeF(pres.width / 96, pres.height / 96), QPageSize.Inch, "Slide",
                                          QPageSize.ExactMatch), QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
    p = QPainter(w)
    for i, s in enumerate([s for s in pres.slides if not s.hidden]):
        if i:
            w.newPage()
        render_slide(p, pres, s, QRectF(0, 0, w.width(), w.height()))
    p.end()


@tool("presentation", WRITE)
async def pptx_add_slides(path: str, slides: list[dict], output: str | None = None) -> str:
    """Add slides to the end of an existing PowerPoint deck, using the deck's own layouts and design.
    Same slide format as pptx_create."""
    qt()
    from pptx_io import load_pptx, save_pptx
    src = src_path(path)
    pres, _ = load_pptx(src)
    n = _add_slides(pres, slides)
    dst = out_path(src, output)
    save_pptx(pres, dst)
    return f"Added {n} slide(s). Saved {dst}"


# ====================================================================== photos

def _image_ops_doc():
    import photo_core as pc
    adj = "; ".join(f"{k} ({', '.join(p[0] for p in v[1])})" for k, v in pc.ADJUSTMENTS.items())
    fil = "; ".join(f"{k} ({', '.join(p[0] for p in v[1]) or 'no options'})" for k, v in pc.FILTERS.items())
    return adj, fil


@tool("photo", READ)
async def image_info(path: str) -> str:
    """Size, resolution and (for .psd/.ora) the layers of an image."""
    qt()
    import photo_core as pc
    doc, warnings = pc.load_image_file(src_path(path))
    return as_json({"width": doc.width, "height": doc.height, "dpi": doc.dpi, "file_size_bytes": os.path.getsize(path),
                    "layers": [{"name": l.name, "visible": l.visible, "opacity": round(l.opacity, 2), "blend": l.blend,
                                "x": l.x, "y": l.y, "w": l.image.width(), "h": l.image.height()} for l in doc.layers],
                    "notes": warnings})


@tool("photo", WRITE)
async def image_edit(path: str, operations: list[dict], output: str | None = None, jpg_quality: int = 90) -> str:
    """Edit a picture with a list of operations applied in order, then save (format from the output extension:
    png, jpg, webp, tif, bmp, gif, ico, pdf, psd, ora). Operations:
    {"op":"resize","width":800} or {"op":"resize","height":600} or {"op":"resize","percent":50};
    {"op":"crop","x":0,"y":0,"width":400,"height":300}; {"op":"rotate","degrees":90} (any angle);
    {"op":"flip","direction":"horizontal"|"vertical"};
    {"op":"adjust","name":"Brightness/Contrast","brightness":10,"contrast":20} (see image_operations for names);
    {"op":"filter","name":"Gaussian Blur","radius":4}; {"op":"effect","name":"Black & White"|"Sepia"|"Invert"|"Auto Contrast"};
    {"op":"text","text":"Hello","x":20,"y":20,"size":48,"color":"#FFFFFF","font":"Arial","bold":true,"outline":2,"shadow":true};
    {"op":"canvas","width":1200,"height":800,"color":"#FFFFFF"} (centre on a bigger/smaller canvas)."""
    qt()
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QPainter, QTransform
    import photo_core as pc
    from photo_app import render_text
    src = src_path(path)
    doc, _ = pc.load_image_file(src)
    img = pc.composite(doc)
    for op in operations:
        kind = op.get("op")
        w, h = img.width(), img.height()
        if kind == "resize":
            if op.get("percent"):
                nw, nh = round(w * op["percent"] / 100), round(h * op["percent"] / 100)
            elif op.get("width") and op.get("height"):
                nw, nh = int(op["width"]), int(op["height"])
            elif op.get("width"):
                nw, nh = int(op["width"]), round(h * op["width"] / w)
            elif op.get("height"):
                nw, nh = round(w * op["height"] / h), int(op["height"])
            else:
                raise ValueError("resize needs width, height or percent")
            img = img.scaled(max(1, nw), max(1, nh), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        elif kind == "crop":
            img = img.copy(QRect(int(op["x"]), int(op["y"]), int(op["width"]), int(op["height"])))
        elif kind == "rotate":
            img = img.transformed(QTransform().rotate(float(op["degrees"])), Qt.SmoothTransformation)
        elif kind == "flip":
            hz = op.get("direction", "horizontal").startswith("h")
            img = img.mirrored(hz, not hz)
        elif kind in ("adjust", "filter"):
            table = pc.ADJUSTMENTS if kind == "adjust" else pc.FILTERS
            name = op.get("name")
            if name not in table:
                raise ValueError(f"Unknown {kind} '{name}'. Choose from {list(table)}")
            fn, params = table[name]
            kw = {p[0]: op.get(p[0], p[4]) for p in params}
            img = pc.from_array(fn(pc.to_array(img), **kw))
        elif kind == "effect":
            if op.get("name") not in pc.INSTANT:
                raise ValueError(f"Unknown effect. Choose from {list(pc.INSTANT)}")
            img = pc.from_array(pc.INSTANT[op["name"]](pc.to_array(img)))
        elif kind == "text":
            t = dict(text=str(op["text"]), font=op.get("font", "Arial"), size=int(op.get("size", 48)), bold=op.get("bold", False),
                     italic=op.get("italic", False), color=op.get("color", "#000000"), align=op.get("align", "Left"),
                     outline=int(op.get("outline", 0)), outline_color=op.get("outline_color", "#FFFFFF"),
                     shadow=bool(op.get("shadow", False)))
            timg, off = render_text(t)
            p = QPainter(img)
            p.drawImage(int(op.get("x", 0)) + off.x(), int(op.get("y", 0)) + off.y(), timg)
            p.end()
        elif kind == "canvas":
            nw, nh = int(op["width"]), int(op["height"])
            new = pc.blank(nw, nh, QColor(op.get("color", "#FFFFFF")) if op.get("color") != "transparent" else Qt.transparent)
            p = QPainter(new)
            p.drawImage((nw - w) // 2, (nh - h) // 2, img)
            p.end()
            img = new
        else:
            raise ValueError(f"Unknown operation {kind!r}")
    result = pc.Document(img.width(), img.height(), [pc.Layer("Background", img.convertToFormat(pc.FMT))], dpi=doc.dpi)
    dst = out_path(src, output, " (edited)", ".png" if src.lower().endswith((".psd", ".ora")) and not output else None)
    low = dst.lower()
    if low.endswith(".psd"):
        pc.save_psd(result, dst)
    elif low.endswith(".ora"):
        pc.save_ora(result, dst)
    else:
        pc.save_flat(result, dst, jpg_quality)
    return f"Saved {dst} ({img.width()}x{img.height()})"


@tool("photo", READ)
async def image_operations() -> str:
    """List the adjustment and filter names (and their settings) that image_edit understands."""
    adj, fil = _image_ops_doc()
    import photo_core as pc
    return f"Adjustments: {adj}\nFilters: {fil}\nEffects: {', '.join(pc.INSTANT)}"


# ====================================================================== converter

def _cc():
    import threading
    import convert_core as cc
    return cc, (lambda *_: None), threading.Event()


@tool("converter", READ)
async def list_conversions(path: str) -> str:
    """What a file can be converted to (labels and file extensions) with convert_file."""
    import convert_core as cc
    t = cc.targets_for(src_path(path))
    return as_json(t) if t else "This file type can't be converted (try compress_file or archive_files)."


@tool("converter", WRITE)
async def convert_file(path: str, to: str, output_folder: str | None = None, video_quality: str = "Balanced",
                       max_height: int | None = None, audio_bitrate: str = "192k", image_quality: int = 90,
                       picture_for_video: str | None = None) -> str:
    """Convert a file to another format. `to` = an extension ('mp3', 'mp4', 'pdf', 'png', 'docx', 'csv'…) or a
    label from list_conversions (e.g. 'MP4 (H.265, smaller)', 'GIF (animated)'). Works for audio, video, pictures,
    PDF, Word, PowerPoint, Excel/CSV, text/Markdown/HTML, and extracts archives. Options: video_quality
    ('High quality'|'Balanced'|'Small file'), max_height (e.g. 720), audio_bitrate ('320k'…'64k'),
    image_quality (1-100), picture_for_video (cover image when turning audio into MP4)."""
    qt()
    cc, prog, cancel = _cc()
    src = src_path(path)
    targets = cc.targets_for(src)
    label = to if to in targets else None
    if label is None:
        ext = "." + to.lower().lstrip(".")
        label = next((k for k, v in targets.items() if v == ext), None)
    if label is None:
        raise ValueError(f"Can't convert to {to!r}. Options: {list(targets)}")
    opts = dict(video_quality=video_quality, max_height=max_height, audio_bitrate=audio_bitrate,
                image_quality=image_quality, picture=picture_for_video or "", pdf_dpi=150)
    outs = cc.run_convert(src, label, os.path.abspath(output_folder) if output_folder else None, opts, prog, cancel)
    return "Created:\n" + "\n".join(outs)


@tool("converter", WRITE)
async def compress_file(path: str, level: int = 2, output_folder: str | None = None) -> str:
    """Make a file smaller. level 1 = light (best quality), 2 = balanced, 3 = strong (smallest). Videos → smaller
    MP4, audio → lower bitrate, pictures → smaller JPG/PNG/WebP, PDFs and Word/Excel/PowerPoint → shrink the
    pictures inside, other files → zip/7z. Reports the size saving."""
    cc, prog, cancel = _cc()
    src = src_path(path)
    before = os.path.getsize(src)
    outs = cc.run_compress(src, max(1, min(3, level)), os.path.abspath(output_folder) if output_folder else None, prog, cancel)
    after = sum(os.path.getsize(o) for o in outs if os.path.isfile(o))
    return f"Created {outs[0]}: {cc.human(before)} → {cc.human(after)} ({(1 - after / before) * 100:.0f}% smaller)"


@tool("converter", WRITE)
async def combine_files(paths: list[str], output: str, overwrite: bool = False) -> str:
    """Join files in order: pictures/PDFs → one PDF (output ends .pdf), audio → one audio file (.mp3/.m4a/.wav…),
    videos → one MP4 (output ends .mp4)."""
    cc, prog, cancel = _cc()
    dst = new_path(output, overwrite)
    files = [src_path(p) for p in paths]
    if dst.lower().endswith(".pdf"):
        cc.combine_pdf(files, dst, prog, cancel)
    else:
        cc.join_media(files, dst, prog, cancel)
    return f"Created {dst}"


@tool("converter", WRITE)
async def archive_files(paths: list[str], output: str, overwrite: bool = False) -> str:
    """Pack files and folders into one .zip or .7z archive (by the output extension)."""
    cc, prog, cancel = _cc()
    dst = new_path(output, overwrite)
    kind = "7z" if dst.lower().endswith(".7z") else "zip"
    cc.make_archive([src_path(p) for p in paths], dst, kind, prog, cancel)
    return f"Created {dst} ({cc.human(os.path.getsize(dst))})"


@tool("converter", WRITE)
async def extract_archive(path: str, output_folder: str | None = None) -> str:
    """Unpack a .zip, .7z, .tar, .tar.gz/.tgz, .tar.bz2, .tar.xz, .gz, .bz2 or .xz into a new folder."""
    cc, prog, cancel = _cc()
    outs = cc.extract_archive(src_path(path), os.path.abspath(output_folder) if output_folder else None, prog, cancel)
    return f"Extracted into {outs[0]}"


@tool("converter", READ)
async def media_info(path: str) -> str:
    """Duration, whether it has video/audio, and resolution of an audio/video file."""
    import convert_core as cc
    return as_json(cc.probe(src_path(path)))


def _seconds(t):
    """'90', '1:30', '1:02:03.5' -> seconds."""
    if isinstance(t, (int, float)):
        return float(t)
    parts = [float(x) for x in str(t).strip().split(":")]
    secs = 0.0
    for x in parts:
        secs = secs * 60 + x
    return secs


@tool("converter")
async def video_trim(path: str, start: str = "0", end: str | None = None, exact: bool = False,
                     max_height: int | None = None, rotate: int = 0, remove_sound: bool = False,
                     output_folder: str | None = None) -> str:
    """Keep part of a video: start/end as seconds or "m:ss" ("1:30"); end defaults to the end of the video.
    exact=False is fast and lossless but cuts at the nearest keyframe; exact=True is frame-precise (re-encodes).
    Optional: max_height (1080/720/480) to make it smaller, rotate (90 = clockwise, 270, 180), remove_sound.
    Saves "<name> (trimmed)" next to the original (or in output_folder) and returns its path."""
    import threading
    import convert_core as cc
    src = src_path(path)
    info = cc.probe(src)
    if not info.get("video"):
        raise ValueError("That file has no video.")
    s = _seconds(start)
    e = _seconds(end) if end not in (None, "") else info["duration"]
    if not 0 <= s < e:
        raise ValueError(f"start must be before end (got {s} s → {e} s; the video is {info['duration']:.1f} s long).")
    if rotate not in (0, 90, 180, 270):
        raise ValueError("rotate must be 0, 90, 180 or 270.")
    folder = output_folder
    if folder:
        os.makedirs(folder, exist_ok=True)
    dst = cc.trim_video(src, s, min(e, info["duration"]), folder, lambda p: None, threading.Event(), exact=exact,
                        max_h=max_height or 0, rotate=rotate, mute=remove_sound)
    out = cc.probe(dst)
    return f"Saved {dst} ({out['duration']:.1f} s, {out['width']}×{out['height']}, {cc.human(os.path.getsize(dst))})"


@tool("converter", NET)
async def download_media(url: str, output_folder: str | None = None, mode: str = "video", quality: int | None = 1080,
                         audio_format: str = "mp3", playlist: bool = False) -> str:
    """Download a video (or just its audio) from a link (YouTube, X/Twitter, TikTok, Instagram, Vimeo, Reddit,
    SoundCloud, 1000+ sites). mode 'video' (quality = max height like 1080, or null for best) or 'audio'
    (audio_format mp3|m4a|opus|wav|flac). Safety: only public web links; files are quarantined, must be real
    audio/video and are virus-scanned with Microsoft Defender before being saved. Only download content the user
    has the right to (their own, or creator-permitted e.g. Creative Commons)."""
    import download_core as dc
    folder = os.path.abspath(output_folder) if output_folder else os.path.join(os.path.expanduser("~"), "Downloads")
    saved, notes = dc.download(url, folder, mode="audio" if mode == "audio" else "video", quality=quality,
                               audio_format=audio_format, container="mp4", playlist=playlist, scan=True)
    return "Saved:\n" + "\n".join(saved) + (f"\nNotes: {notes}" if notes else "")


# ====================================================================== database

def _db(path, create=False):
    import base_core as bc
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(p) and not create:
        raise ValueError(f"Database not found: {p} (create one with db_create)")
    return bc.Database(p)


@tool("database", READ)
async def db_overview(path: str) -> str:
    """Everything in an Ethical Database / SQLite file: tables (fields, types, record counts), saved queries (SQL),
    relationships and saved reports."""
    db = _db(path)
    try:
        out = {"tables": {t: {"records": db.count(t), "fields": {f.name: f.kind + (" (required)" if f.required else "")
                                                                   + (" (unique)" if f.unique else "") for f in db.fields(t)}}
                          for t in db.tables()},
               "queries": {v: db.view_sql(v) for v in db.views()},
               "relationships": [f"{r.parent}.{r.parent_field} 1→∞ {r.child}.{r.child_field}"
                                 + (" (cascade delete)" if r.cascade_delete else "") for r in db.relations()],
               "reports": db.reports()}
        return as_json(out)
    finally:
        db.close()


@tool("database", READ)
async def db_query(path: str, sql: str, params: list | None = None, limit: int = 200) -> str:
    """Run a read-only SQL query (SELECT …) on a database and return the rows as a table. Identifiers with spaces
    need double quotes: SELECT "First Name" FROM "Contacts". Saved queries can be selected like tables."""
    p = src_path(path)
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        con.execute("PRAGMA query_only = ON")
        cur = con.execute(sql, params or [])
        if cur.description is None:
            return "That statement returns no rows (use db_execute to change data)."
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(max(1, min(limit, 5000)))
        more = cur.fetchone() is not None
    finally:
        con.close()
    lines = [" | ".join(cols)] + [" | ".join("" if v is None else str(v) for v in r) for r in rows]
    return "\n".join(lines) + (f"\n… more rows (raise limit, max 5000)" if more else f"\n({len(rows)} row(s))")


@tool("database", WRITE)
async def db_execute(path: str, sql: str, params: list | None = None) -> str:
    """Run SQL that changes a database (INSERT, UPDATE, DELETE, CREATE …). Relationship rules are enforced.
    Prefer db_insert / db_create_table for simple cases."""
    db = _db(path)
    try:
        if params:
            cur = db.con.execute(sql, params)
        else:
            cur = db.con.executescript(sql) if sql.count(";") > 1 else db.con.execute(sql)
        db.con.commit()
        return f"Done. Rows affected: {cur.rowcount if cur.rowcount >= 0 else 'n/a'}"
    except sqlite3.Error as ex:
        db.con.rollback()
        raise ValueError(f"SQL error: {ex}")
    finally:
        db.close()


@tool("database", WRITE)
async def db_create(path: str, template: str = "Blank database", overwrite: bool = False) -> str:
    """Create a new database file (.db). Templates: 'Blank database', 'Contacts', 'Tasks', 'Inventory',
    'Customers & Orders' (the templates include sample data, queries and relationships)."""
    import base_core as bc
    if template not in bc.TEMPLATES:
        raise ValueError(f"Unknown template. Choose from {list(bc.TEMPLATES)}")
    dst = new_path(path, overwrite)
    bc.create_from_template(dst, template).close()
    return f"Created {dst}"


@tool("database", WRITE)
async def db_create_table(path: str, table: str, fields: list[dict]) -> str:
    """Create a table. fields = [{"name": "Name", "type": "Short Text", "required": true, "unique": false,
    "default": ""}]. Types: AutoNumber, Short Text, Long Text, Whole Number, Decimal Number, Currency, Date,
    Date & Time, Yes/No. An AutoNumber "ID" key is added automatically if you don't include one."""
    import base_core as bc
    db = _db(path, create=True)
    try:
        fs = [bc.Field(f["name"], f.get("type", "Short Text"), bool(f.get("required")), bool(f.get("unique")),
                       str(f.get("default", "") or ""), f.get("type") == "AutoNumber") for f in fields]
        for f in fs:
            if f.kind not in bc.FIELD_TYPES:
                raise ValueError(f"Unknown type {f.kind!r}. Use one of {bc.FIELD_TYPES}")
        if not any(f.kind == "AutoNumber" for f in fs):
            fs.insert(0, bc.Field("ID", "AutoNumber", pk=True))
        db.create_table(table, fs)
        return f"Created table {table} with fields {[f.name for f in fs]}"
    finally:
        db.close()


@tool("database", WRITE)
async def db_insert(path: str, table: str, records: list[dict]) -> str:
    """Add records to a table: records = [{"Name": "Ann", "Joined": "2026-10-11", "Active": true}, …].
    Values are converted to each field's type (dates, numbers, currency, Yes/No)."""
    import base_core as bc
    db = _db(path)
    try:
        kinds = db.kinds(table)
        ids = []
        for rec in records:
            unknown = [k for k in rec if k not in kinds]
            if unknown:
                raise ValueError(f"Unknown field(s) {unknown}. Fields: {list(kinds)}")
            vals = {k: bc.to_db(v, kinds[k]) for k, v in rec.items()}
            cols = list(vals)
            cur = db.con.execute(f"INSERT INTO {bc.q(table)} ({', '.join(bc.q(c) for c in cols)}) VALUES "
                                 f"({', '.join('?' for _ in cols)})", [vals[c] for c in cols])
            ids.append(cur.lastrowid)
        db.con.commit()
        return f"Added {len(ids)} record(s) (row ids {ids[:20]}{'…' if len(ids) > 20 else ''})"
    except (sqlite3.Error, ValueError) as ex:
        db.con.rollback()
        raise ValueError(str(ex))
    finally:
        db.close()


@tool("database", WRITE)
async def db_add_relationship(path: str, child_table: str, child_field: str, parent_table: str,
                              parent_field: str = "ID", cascade_delete: bool = False) -> str:
    """Link two tables one-to-many (each child record belongs to one parent record, e.g. Orders."Customer ID" →
    Customers.ID). The child field must be a Whole Number. Existing data must already match."""
    import base_core as bc
    db = _db(path)
    try:
        db.add_relation(bc.Relation(child_table, child_field, parent_table, parent_field, cascade_delete))
        return f"Linked {parent_table}.{parent_field} → {child_table}.{child_field}"
    finally:
        db.close()


@tool("database", WRITE)
async def db_save_query(path: str, name: str, sql: str) -> str:
    """Save a SELECT query under a name (it then appears under Queries in the app and can be used like a table)."""
    db = _db(path)
    try:
        db.save_query(name, sql)
        return f"Saved query {name}"
    finally:
        db.close()


@tool("database", WRITE)
async def db_import(path: str, file: str, table: str | None = None) -> str:
    """Import an Excel (.xlsx, every sheet), CSV or Access (.accdb/.mdb) file into new tables of a database
    (created if missing). Field types are detected automatically."""
    import base_core as bc
    f = src_path(file)
    db = _db(path, create=True)
    try:
        low = f.lower()
        if low.endswith((".csv", ".txt")):
            sources = {table or os.path.splitext(os.path.basename(f))[0]: bc.read_csv(f)}
        elif low.endswith(".xlsx"):
            sources = bc.read_xlsx(f)
        else:
            sources = bc.read_access(f)
        done = []
        for name, (header, rows) in sources.items():
            t, k = name, 2
            while t in db.tables() or t in db.views():
                t, k = f"{name} {k}", k + 1
            done.append(f"{t}: {bc.import_rows(db, t, header, rows)} records")
        return "Imported " + "; ".join(done)
    finally:
        db.close()


@tool("database", WRITE)
async def db_export(path: str, source: str, output: str, overwrite: bool = False) -> str:
    """Export a table or saved query to .xlsx, .csv or .pdf (a printable report), by the output extension."""
    import base_core as bc
    db = _db(path)
    dst = new_path(output, overwrite)
    try:
        if dst.lower().endswith(".csv"):
            n = bc.export_csv(db, source, dst)
            return f"Exported {n} rows to {dst}"
        if dst.lower().endswith(".pdf"):
            _report_pdf(db, {"source": source, "title": source}, dst)
            return f"Exported {dst}"
        bc.export_xlsx(db, [source], dst)
        return f"Exported {dst}"
    finally:
        db.close()


def _report_pdf(db, spec, dst):
    qt()
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
    import base_core as bc
    doc = QTextDocument()
    doc.setHtml(bc.report_html(db, spec))
    w = QPdfWriter(dst)
    w.setResolution(150)
    w.setPageLayout(QPageLayout(QPageSize(QPageSize.Letter), QPageLayout.Landscape if spec.get("landscape") else
                                QPageLayout.Portrait, QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter))
    doc.print_(w)


@tool("database", WRITE)
async def db_report(path: str, source: str, output_pdf: str, title: str = "", fields: list[str] | None = None,
                    group_by: str | None = None, sort_by: str | None = None, totals: dict[str, str] | None = None,
                    landscape: bool = False, save_as: str | None = None, overwrite: bool = False) -> str:
    """Make a printable PDF report from a table or query: choose fields, group_by (one section per value),
    sort_by, totals ({"Total": "Sum", "Price": "Average", "ID": "Count"}). save_as also saves the report in the
    database so it appears under Reports in the app."""
    db = _db(path)
    try:
        spec = {"source": source, "title": title or source, "fields": fields or [], "group_by": group_by or "",
                "sort": sort_by or "", "totals": totals or {}, "landscape": landscape}
        dst = new_path(output_pdf, overwrite)
        _report_pdf(db, spec, dst)
        if save_as:
            db.save_report(save_as, spec)
        return f"Created {dst}"
    finally:
        db.close()


# ====================================================================== sticky notes

DELETE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)


def _show_stickies():
    """Make sure the Sticky Notes app is running so changes appear on screen. If it's already running it notices
    the change in the notes file by itself (within ~2 s), so we only start it when it isn't."""
    qt()
    from PySide6.QtNetwork import QLocalSocket
    from suite_common import launch_command, start_detached
    sock = QLocalSocket()
    sock.connectToServer("EthicalStickyNotes-" + os.environ.get("USERNAME", "user"))
    if sock.waitForConnected(200):
        sock.write(b"startup")          # harmless "hello" - the app ignores it
        sock.flush()
        sock.disconnectFromServer()
        return
    start_detached(launch_command("stickynotes", "--startup"))


def _note(data, note_id):
    import stickies_core as sc
    n = sc.find(data, note_id)
    if n is None:
        raise ValueError(f"No sticky note with id {note_id!r}. Use notes_list to see the ids.")
    return n


def _color(color):
    import stickies_core as sc
    c = (color or "").strip().lower()
    if c not in sc.COLORS:
        raise ValueError(f"Unknown colour {color!r}. Choose from: {', '.join(sc.COLORS)}")
    return c


@tool("stickynotes", READ)
async def notes_list(search: str | None = None) -> str:
    """List the user's sticky notes (newest first): id, colour, title (first line), open tasks, whether it's on
    screen. Optional `search` filters by text."""
    import stickies_core as sc
    out = []
    for n in sorted(sc.load()["notes"], key=lambda n: n.get("modified", ""), reverse=True):
        text = n.get("text") or ""
        if search and search.lower() not in text.lower():
            continue
        out.append({"id": n["id"], "color": n.get("color"), "title": sc.title_of(n), "modified": n.get("modified"),
                    "open_tasks": text.count("- [ ]"), "done_tasks": text.lower().count("- [x]"),
                    "on_screen": bool(n.get("open"))})
    return as_json(out) if out else "No sticky notes" + (" match that search." if search else " yet.")


@tool("stickynotes", READ)
async def note_read(note_id: str) -> str:
    """Read one sticky note as Markdown ("- [ ]" open task, "- [x]" done task; done tasks may show as ~~text~~)."""
    import stickies_core as sc
    n = _note(sc.load(), note_id)
    return f"id: {n['id']}  colour: {n.get('color')}  modified: {n.get('modified')}\n\n{n.get('text') or '(empty)'}"


@tool("stickynotes")
async def note_create(markdown: str, color: str = "yellow", on_top: bool = False) -> str:
    """Put a new sticky note on the user's desktop. markdown: e.g. "**Today**\\n- [ ] call the bank\\n- [ ] buy milk".
    color: yellow, green, pink, purple, blue, orange, gray or charcoal. on_top keeps it above other windows."""
    import stickies_core as sc
    n = sc.new_note(text=markdown.strip(), color=_color(color), on_top=bool(on_top))
    sc.apply(changed=[n])
    _show_stickies()
    return f"Created sticky note {n['id']} – it's on the desktop now."


@tool("stickynotes")
async def note_update(note_id: str, markdown: str | None = None, append: str | None = None,
                      color: str | None = None, on_top: bool | None = None) -> str:
    """Change a sticky note: replace its text (`markdown`), add lines at the end (`append`, e.g. "- [ ] new task"),
    change `color`, or keep it on top. Replacing text keeps Markdown formatting (bold/italic/lists/checkboxes)."""
    import stickies_core as sc
    n = dict(_note(sc.load(), note_id))
    if markdown is not None:
        n["text"], n["html"] = markdown.strip(), ""
    if append:
        n["text"], n["html"] = ((n.get("text") or "").rstrip() + "\n" + append.strip()).strip(), ""
    if color:
        n["color"] = _color(color)
    if on_top is not None:
        n["on_top"] = bool(on_top)
    n["open"] = True
    n["modified"] = sc.now()
    sc.apply(changed=[n])
    _show_stickies()
    return f"Updated sticky note {n['id']}."


@tool("stickynotes")
async def note_set_task(note_id: str, task: str, done: bool = True) -> str:
    """Tick (done=True) or untick a to-do item in a sticky note. `task` = part of the item's text (case-insensitive)."""
    import re
    import stickies_core as sc
    n = dict(_note(sc.load(), note_id))
    lines = (n.get("text") or "").splitlines()
    pat = re.compile(r"^(\s*[-*+]\s+)\[( |x|X)\]\s*(.*)$")
    hits = [i for i, l in enumerate(lines) if (m := pat.match(l)) and task.lower() in m.group(3).replace("~~", "").lower()]
    if not hits:
        raise ValueError(f"No to-do item containing {task!r} in that note. Use note_read to see its items.")
    if len(hits) > 1:
        raise ValueError(f"{len(hits)} items contain {task!r}; use more of the item's text.")
    m = pat.match(lines[hits[0]])
    lines[hits[0]] = f"{m.group(1)}[{'x' if done else ' '}] {m.group(3).replace('~~', '').strip()}"
    n["text"], n["html"], n["modified"] = "\n".join(lines), "", sc.now()
    sc.apply(changed=[n])
    _show_stickies()
    return f"{'Ticked' if done else 'Unticked'}: {m.group(3).replace('~~', '').strip()}"


@tool("stickynotes", DELETE)
async def note_delete(note_id: str) -> str:
    """Delete a sticky note (the user can bring it back with “Restore deleted note” in the tray menu)."""
    import stickies_core as sc
    n = _note(sc.load(), note_id)
    sc.apply(deleted=[n["id"]])
    return f"Deleted sticky note {n['id']} ({sc.title_of(n)})."


# ====================================================================== snip (screenshots)

@tool("snip", READ)
async def screenshot_list_windows() -> str:
    """List the titles of the windows open on the user's screen (front to back), for screenshot_take."""
    import snip_core
    wins = snip_core.list_windows(skip_pid=os.getpid())
    return "\n".join(f"- {title}" for _, title, _ in wins) or "No windows found."


@tool("snip")
async def screenshot_take(target: str = "screen", window_title: str | None = None, output: str | None = None,
                          show_to_ai: bool = True):
    """Take a screenshot of the user's screen and save it as a picture. Only do this when the user asks.
    target: "screen" (all monitors) or "window" (one window: give part of its title in window_title - see
    screenshot_list_windows; works even if the window is partly covered). output: .png/.jpg path; default
    Pictures\\Ethical Snips\\Snip <date>.png. show_to_ai=True also returns a smaller copy so you can see it."""
    qt()
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from mcp.server.mcpserver import Image
    import snip_core
    if target not in ("screen", "window"):
        raise ValueError('target must be "screen" or "window".')
    if target == "window":
        found = snip_core.find_window(window_title or "")
        if not window_title or not found:
            titles = [t for _, t, _ in snip_core.list_windows(skip_pid=os.getpid())][:25]
            raise ValueError(f"No open window has {window_title!r} in its title. Open windows: " + "; ".join(titles))
        hwnd, title, _ = found
        img = snip_core.capture_window(hwnd)
        if img is None or img.isNull():
            raise RuntimeError(f"Windows wouldn't draw “{title}” off-screen. Ask the user to bring it to the front, then use target='screen'.")
        what = f"window “{title}”"
    else:
        img = snip_core.grab_all_screens()
        what = "the whole screen"
    if output:
        dst = new_path(output, True)
    else:
        os.makedirs(snip_core.default_folder(), exist_ok=True)
        dst = snip_core.new_file_name(snip_core.default_folder())
    if not img.save(dst, quality=92):
        raise OSError(f"Couldn't save {dst}")
    msg = f"Saved a screenshot of {what} ({img.width()}×{img.height()}): {dst}"
    if not show_to_ai:
        return msg
    small = img
    if max(img.width(), img.height()) > 1568:
        small = img.scaled(1568, 1568, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    small.save(buf, "JPG", 80)
    return [msg, Image(data=bytes(data), format="jpeg")]


# ====================================================================== planner (reminders & calendar)

def _wake_planner():
    """Start Ethical Planner if it isn't running (it's what pops the reminders up); else make it re-read the file."""
    qt()
    from PySide6.QtNetwork import QLocalSocket
    from suite_common import launch_command, start_detached
    sock = QLocalSocket()
    sock.connectToServer("EthicalPlanner-" + os.environ.get("USERNAME", "user"))
    if sock.waitForConnected(200):
        sock.write(b"check")
        sock.flush()
        sock.waitForBytesWritten(200)
        sock.disconnectFromServer()
        return
    start_detached(launch_command("planner", "--startup"))


def _planner_fields(it, when=None, repeat=None, every=None, days=None, until=None, alert_minutes_before=None,
                    duration_minutes=None, all_day=None):
    import planner_core as pc
    if when is not None:
        w = when.strip()
        it["start"] = pc.fmt_dt(pc.parse_dt(w))
        if all_day is None:
            all_day = len(w) == 10 if it["kind"] == "event" else None
    if all_day is not None:
        it["all_day"] = bool(all_day)
    if repeat is not None:
        r = repeat.strip().lower()
        r = {"never": "none", "day": "daily", "every day": "daily", "week": "weekly", "month": "monthly",
             "year": "yearly", "weekday": "weekdays"}.get(r, r)
        if r not in pc.REPEATS:
            raise ValueError(f"repeat must be one of {list(pc.REPEATS)}")
        it["repeat"] = r
    if every is not None:
        it["interval"] = max(1, int(every))
    if days is not None:
        names = [d.strip().lower()[:3] for d in days.replace(";", ",").split(",") if d.strip()]
        lookup = {n.lower(): i for i, n in enumerate(pc.DAY_NAMES)}
        bad = [n for n in names if n not in lookup]
        if bad:
            raise ValueError(f"Unknown day(s) {bad}. Use mon, tue, wed, thu, fri, sat, sun.")
        it["days"] = sorted({lookup[n] for n in names})
        if it["days"] and it.get("repeat", "none") == "none":
            it["repeat"] = "weekly"
    if until is not None:
        it["until"] = until.strip()[:10] or None
    if alert_minutes_before is not None:
        it["alerts"] = sorted({int(m) for m in alert_minutes_before}, reverse=True)
    if duration_minutes is not None:
        it["duration"] = int(duration_minutes)
    return it


def _describe_item(it):
    import planner_core as pc
    start = pc.parse_dt(it["start"])
    return {"id": it["id"], "kind": it["kind"], "title": it["title"],
            "starts": start.strftime("%Y-%m-%d") + ("" if it.get("all_day") else start.strftime(" %H:%M")),
            "repeat": pc.describe_repeat(it) or "once", "alerts": [pc.describe_alert(m) for m in it.get("alerts") or []],
            "notes": it.get("notes", "")}


@tool("planner", READ)
async def planner_upcoming(days: int = 7) -> str:
    """What's coming up in the user's Ethical Planner (reminders and events) for the next `days` days, including
    whether each reminder has been ticked off. Also lists every item with its id (needed to change one)."""
    from datetime import datetime, timedelta
    import planner_core as pc
    items = pc.load()["items"]
    start = datetime.combine(datetime.now().date(), datetime.min.time())
    rows = [{"when": occ.strftime("%a %Y-%m-%d") + (" all day" if it.get("all_day") else occ.strftime(" %H:%M")),
             "title": it["title"], "kind": it["kind"], "id": it["id"],
             **({"done": pc.is_done(it, occ)} if it["kind"] == "reminder" else {})}
            for occ, it in pc.agenda(items, start, start + timedelta(days=max(1, min(int(days), 366))))]
    return as_json({"upcoming": rows, "all_items": [_describe_item(it) for it in items]})


@tool("planner")
async def planner_add(title: str, when: str, kind: str = "reminder", repeat: str = "none", every: int = 1,
                      days: str | None = None, until: str | None = None, alert_minutes_before: list[int] | None = None,
                      duration_minutes: int | None = None, notes: str = "") -> str:
    """Add a reminder or event to Ethical Planner; it pops up on the user's screen at the right time.
    when: local "YYYY-MM-DD HH:MM" (or just "YYYY-MM-DD" for an all-day event). kind: "reminder" (has a Done
    button, e.g. "Take supplements") or "event" (calendar entry with a heads-up, e.g. "Dentist").
    repeat: none, daily, weekdays, weekly, monthly, yearly; every: every N days/weeks/months/years;
    days: for weekly, e.g. "mon,wed,fri"; until: last date "YYYY-MM-DD". alert_minutes_before: e.g. [0] (default
    for reminders), [15] (default for events), [1440, 60] = a day before and an hour before."""
    import planner_core as pc
    if kind not in ("reminder", "event"):
        raise ValueError('kind must be "reminder" or "event".')
    if not title.strip():
        raise ValueError("title is empty.")
    it = pc.new_item(kind=kind, title=title.strip(), notes=notes.strip())
    _planner_fields(it, when=when, repeat=repeat, every=every, days=days, until=until,
                    alert_minutes_before=alert_minutes_before, duration_minutes=duration_minutes)
    pc.apply(changed=[it])
    _wake_planner()
    return "Added: " + json.dumps(_describe_item(it), ensure_ascii=False)


@tool("planner")
async def planner_update(item_id: str, title: str | None = None, when: str | None = None, repeat: str | None = None,
                         every: int | None = None, days: str | None = None, until: str | None = None,
                         alert_minutes_before: list[int] | None = None, duration_minutes: int | None = None,
                         notes: str | None = None) -> str:
    """Change a Planner reminder/event (only the fields you pass). Find item_id with planner_upcoming."""
    import planner_core as pc
    it = pc.find(pc.load(), item_id)
    if it is None:
        raise ValueError(f"No Planner item with id {item_id!r}. Use planner_upcoming to see the ids.")
    it = dict(it)
    if title is not None:
        it["title"] = title.strip()
    if notes is not None:
        it["notes"] = notes.strip()
    _planner_fields(it, when=when, repeat=repeat, every=every, days=days, until=until,
                    alert_minutes_before=alert_minutes_before, duration_minutes=duration_minutes)
    pc.apply(changed=[it])
    _wake_planner()
    return "Updated: " + json.dumps(_describe_item(it), ensure_ascii=False)


@tool("planner")
async def planner_mark_done(item_id: str, date: str | None = None, done: bool = True) -> str:
    """Tick off (or untick) a reminder for one day (default today), e.g. after the user says they took their pills."""
    from datetime import datetime
    import planner_core as pc
    it = pc.find(pc.load(), item_id)
    if it is None:
        raise ValueError(f"No Planner item with id {item_id!r}.")
    it = dict(it)
    day = (date or datetime.now().date().isoformat())[:10]
    it["done"] = sorted(set(it.get("done") or []) - {day} | ({day} if done else set()))
    pc.apply(changed=[it])
    _wake_planner()
    return f"{'Ticked off' if done else 'Unticked'} “{it['title']}” for {day}."


@tool("planner", DELETE)
async def planner_delete(item_id: str) -> str:
    """Delete a Planner reminder/event and all its repeats."""
    import planner_core as pc
    it = pc.find(pc.load(), item_id)
    if it is None:
        raise ValueError(f"No Planner item with id {item_id!r}.")
    pc.apply(deleted=[it["id"]])
    _wake_planner()
    return f"Deleted “{it['title']}”."


# ====================================================================== start

ENABLED = list(ALL_APPS)


def _readable_errors(fn):
    """Problems (missing file, bad SQL, safety block…) reach the AI as a readable message instead of the SDK's
    generic 'Error executing tool', so it can explain or fix its request."""
    import functools
    from mcp.server.mcpserver.exceptions import ToolError

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ToolError:
            raise
        except sqlite3.Error as ex:
            raise ToolError(f"Database error: {ex}") from ex
        except (ValueError, RuntimeError, OSError) as ex:
            raise ToolError(str(ex) or ex.__class__.__name__) from ex
        except Exception as ex:
            raise ToolError(f"{ex.__class__.__name__}: {ex}") from ex
    return wrapper


def build(apps):
    global ENABLED
    ENABLED = [a for a in apps if a in ALL_APPS]
    import download_core
    for group, fn, ann in _REGISTRY:
        if fn.__name__ == "download_media" and not download_core.available():
            continue                       # public build without the link downloader
        if group == "core" or group in ENABLED:
            server.add_tool(_readable_errors(fn), name=fn.__name__, annotations=ann)
    return server


def main():
    ap = argparse.ArgumentParser(description="EthicalApp MCP server (stdio)")
    ap.add_argument("--apps", default=",".join(ALL_APPS), help="comma list of: " + ",".join(ALL_APPS))
    args = ap.parse_args()
    apps = [a.strip() for a in args.apps.split(",") if a.strip()]
    os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false;qt.qpa.*=false")
    qt()
    build(apps).run("stdio")


if __name__ == "__main__":
    main()
