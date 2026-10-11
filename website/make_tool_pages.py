"""Builds the online-tool pages of the website (one page per tool, for search engines) + the tools hub,
sitemap.xml and robots.txt.

    .venv\\Scripts\\python website\\make_tool_pages.py

Edit the tool panels in _panels.html and the words for each page in PAGES below, then run this again.
Set SITE_URL once the site has its address, so pages get canonical links and the sitemap gets written.
"""
import html
import json
import os
import re
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SITE_URL = "https://ethicalapp.org"   # e.g. "https://ethicalsuite.app" (no trailing slash) - needed for sitemap.xml / canonical links
SITE_NAME = "EthicalApp"
# The site is served without ".html" in addresses ("/merge-pdf"), so search engines get the short address.
# Set False if a host needs the full "merge-pdf.html".
PRETTY_URLS = True

GROUPS = [("pdf", "PDF tools", "pdf"), ("image", "Picture tools", "photo"), ("media", "Audio & video tools", "converter"),
          ("zip", "Zip tools", "suite")]

PRIVACY = ("Your files never leave your device: everything happens inside your browser, nothing is uploaded or "
           "stored, and there's no sign-up, watermark or limit.")

# slug, group, panel id, preset options, card label, card text, <title>, meta description, H1, lead, steps, FAQ
PAGES = [
    dict(slug="merge-pdf", group="pdf", panel="pdf-merge", label="Merge PDF", card="Combine several PDFs into one",
         title="Merge PDF – combine PDF files free, no upload | EthicalApp",
         desc="Merge PDF files into one PDF online for free. Drag to reorder, no upload, no watermark, no sign-up – it all runs in your browser.",
         h1="Merge PDF files", lead="Combine several PDFs into one file – in the order you choose.",
         steps=["Drop your PDF files in the box (or click to choose them).", "Use the arrows to put them in the right order.",
                "Click <b>Merge</b> and save the new PDF."],
         faq=[("Is it really free?", "Yes. No limits, no watermark and no account – merge as many PDFs as you like."),
              ("Are my PDFs uploaded?", "No. The PDFs are joined by your own browser on your own device. Nothing is sent to a server."),
              ("Can I merge password-protected PDFs?", "Not in the browser. The free Ethical PDF Editor desktop app opens protected PDFs."),
              ("Is there a size limit?", "Only your device's memory. Hundreds of pages are no problem on a normal computer.")]),
    dict(slug="split-pdf", group="pdf", panel="pdf-split", label="Split PDF", card="Extract pages or split every page",
         title="Split PDF – extract pages from a PDF free, no upload | EthicalApp",
         desc="Split a PDF or extract pages (e.g. 1-3, 5, 8-) into new PDF files. Free, private, no upload, no watermark.",
         h1="Split a PDF or extract pages", lead="Take the pages you need out of a PDF, or split every page into its own file.",
         steps=["Drop a PDF in the box.", "Choose what to do and type the pages, like <code>1-3, 5, 8-</code>.", "Click <b>Split</b> and save the new PDFs (or all of them as one .zip)."],
         faq=[("How do I write the pages?", "Use commas and dashes: <code>1-3, 5, 8-</code> means pages 1 to 3, page 5, and page 8 to the end."),
              ("Is the original PDF changed?", "No. You always get new files; your original stays as it is."),
              ("Are my files uploaded?", "No. The PDF is split in your browser on your own device.")]),
    dict(slug="rotate-pdf", group="pdf", panel="pdf-rotate", label="Rotate PDF", card="Turn sideways pages the right way",
         title="Rotate PDF pages – free online, no upload | EthicalApp",
         desc="Rotate all or some pages of a PDF by 90° or 180° and save it. Free, no upload, no watermark, no sign-up.",
         h1="Rotate PDF pages", lead="Fix sideways or upside-down scans in seconds.",
         steps=["Drop a PDF in the box.", "Choose how far to turn it, and which pages (leave empty for all).", "Click <b>Rotate</b> and save."],
         faq=[("Can I rotate only some pages?", "Yes – type them in the Pages box, like <code>2, 4-6</code>."),
              ("Does rotating lower the quality?", "No. The pages are turned, not re-drawn, so text and pictures stay exactly as sharp.")]),
    dict(slug="jpg-to-pdf", group="pdf", panel="pdf-from-images", label="JPG to PDF", card="Turn photos or scans into one PDF",
         title="JPG to PDF – convert images to PDF free, no upload | EthicalApp",
         desc="Convert JPG, PNG and other pictures to one PDF: one image per page, A4, Letter or picture size. Free and private – no upload.",
         h1="JPG to PDF", lead="Turn photos, scans or screenshots into one tidy PDF.",
         steps=["Drop your pictures in the box (JPG, PNG, WebP, GIF, BMP).", "Put them in order and pick a page size.", "Click <b>Make PDF</b> and save it."],
         faq=[("Are phone photos the right way up?", "Yes – the rotation your phone saved is used, so photos aren't sideways."),
              ("Does it work with PNG too?", "Yes: JPG, PNG, WebP, GIF and BMP."),
              ("Are my pictures uploaded?", "No. The PDF is made in your browser on your own device.")]),
    dict(slug="pdf-to-jpg", group="pdf", panel="pdf-to-images", label="PDF to JPG", card="Save each page as a picture",
         title="PDF to JPG – convert PDF pages to images free, no upload | EthicalApp",
         desc="Convert every page of a PDF to JPG or PNG images at 72, 150 or 300 dpi. Free, private, no upload, no watermark.",
         h1="PDF to JPG", lead="Save PDF pages as pictures – to share, post or put in a document.",
         steps=["Drop a PDF in the box.", "Choose JPG or PNG and the quality (dpi).", "Click <b>Convert</b> and save the pictures (or all as a .zip)."],
         faq=[("JPG or PNG?", "JPG files are smaller; PNG is sharper for text and drawings."),
              ("What dpi should I use?", "150 dpi is good for screens and email, 300 dpi for printing.")]),
    dict(slug="compress-image", group="image", panel="image-convert", preset={"format": "image/jpeg", "quality": "0.68", "max": "1920"},
         label="Compress image", card="Make photos smaller for email or the web",
         title="Compress images – reduce JPG, PNG & WebP file size free | EthicalApp",
         desc="Make photos and pictures smaller (KB/MB) without visible quality loss. Batch compress JPG, PNG, WebP – free, no upload.",
         h1="Compress images", lead="Shrink photos so they're quick to send and upload – many at once.",
         steps=["Drop your pictures in the box.", "Pick the quality and (optionally) a smaller size.", "Click <b>Convert</b> – you'll see how much smaller each one got."],
         faq=[("How much smaller do photos get?", "Phone photos usually shrink by 70–90 % with “Small file” and 1920 px."),
              ("Does it remove location data?", "Yes. The new pictures don't carry the hidden photo data (like GPS location) of the originals."),
              ("Are my photos uploaded?", "No. Everything happens in your browser on your own device.")]),
    dict(slug="convert-image", group="image", panel="image-convert", preset={"format": "image/jpeg", "quality": "0.92", "max": "0"},
         label="Convert image", card="PNG to JPG, WebP to JPG and more",
         title="Convert images – PNG to JPG, WebP to JPG, JPG to PNG free | EthicalApp",
         desc="Convert pictures between JPG, PNG and WebP – one or many at once. Free online image converter, no upload, no watermark.",
         h1="Convert images (PNG, JPG, WebP)", lead="Change pictures to the format you need – in seconds, many at once.",
         steps=["Drop your pictures in the box.", "Choose JPG, PNG or WebP.", "Click <b>Convert</b> and save."],
         faq=[("Can it convert WebP to JPG?", "Yes – and PNG to JPG, JPG to PNG, JPG to WebP and more."),
              ("What about transparent PNGs?", "PNG and WebP keep transparency. JPG can't, so transparent parts become white.")]),
    dict(slug="resize-image", group="image", panel="image-convert", preset={"format": "image/jpeg", "quality": "0.82", "max": "1280"},
         label="Resize image", card="Make pictures smaller in pixels",
         title="Resize images – change photo size in pixels free, no upload | EthicalApp",
         desc="Resize photos and pictures to 4K, 1920, 1280 or 800 px on the longest side – batch, free and private.",
         h1="Resize images", lead="Make pictures the right size for a website, email or form.",
         steps=["Drop your pictures in the box.", "Choose the longest side (e.g. 1280 px).", "Click <b>Convert</b> and save."],
         faq=[("Is the shape kept?", "Yes. Pictures are scaled evenly, never stretched."),
              ("Will small pictures be enlarged?", "No – pictures already smaller than the size you choose stay as they are.")]),
    dict(slug="mp4-to-mp3", group="media", panel="media-convert", preset={"to": "mp3"}, label="MP4 to MP3", card="Get the sound from a video",
         title="MP4 to MP3 – convert video to MP3 audio free, no upload | EthicalApp",
         desc="Convert MP4, MOV and other videos to MP3 audio, or WAV to MP3. Free online converter that runs in your browser – no upload.",
         h1="MP4 to MP3", lead="Pull the sound out of a video, or turn WAV/FLAC/M4A into MP3.",
         steps=["Drop your video or audio files in the box.", "Keep <b>MP3</b> (or choose M4A, WAV, OGG, FLAC).", "Click <b>Convert</b> and save."],
         faq=[("Which files work?", "MP4, MOV, MKV, WebM, AVI, WAV, FLAC, M4A, OGG and most other audio and video files."),
              ("Is it slow?", "Audio is quick. The converter (about 32 MB) loads the first time you use it."),
              ("Are my files uploaded?", "No – the conversion runs in your browser on your own device.")]),
    dict(slug="convert-video", group="media", panel="media-convert", preset={"to": "mp4"}, label="Convert video", card="MOV, MKV, AVI, WebM to MP4",
         title="Convert video to MP4 – MOV to MP4, MKV to MP4 free | EthicalApp",
         desc="Convert MOV, MKV, AVI and WebM videos to MP4 that plays everywhere, or to WebM. Free, private video converter – no upload.",
         h1="Convert video to MP4", lead="Make any video play on phones, TVs and websites.",
         steps=["Drop your video in the box.", "Keep <b>MP4</b> (or choose WebM).", "Click <b>Convert</b> and save."],
         faq=[("Why MP4?", "MP4 (H.264) plays on almost every phone, computer, TV and website."),
              ("Is there a size limit?", "Files up to about 1.5 GB work in a browser. For bigger videos use the free Ethical Converter desktop app – it's also much faster.")]),
    dict(slug="video-to-gif", group="media", panel="media-convert", preset={"to": "gif"}, label="Video to GIF", card="Turn a short clip into a GIF",
         title="Video to GIF – make a GIF from MP4 free, no upload | EthicalApp",
         desc="Turn a short video clip (MP4, MOV, WebM) into an animated GIF. Free GIF maker that runs in your browser – no upload, no watermark.",
         h1="Video to GIF", lead="Make an animated GIF from a short clip – no watermark.",
         steps=["Drop a short video in the box.", "Keep <b>GIF</b> selected.", "Click <b>Convert</b> and save."],
         faq=[("How long can the GIF be?", "The first 20 seconds are used, at 12 frames per second and up to 480 px wide, to keep the file small."),
              ("Is there a watermark?", "Never.")]),
    dict(slug="compress-video", group="media", panel="media-compress", label="Compress video", card="Shrink a video to send it",
         title="Compress video – reduce MP4 file size free, no upload | EthicalApp",
         desc="Make a video smaller to email it or send it in a chat: choose how small and 1080p/720p/480p. Free, private, no upload.",
         h1="Compress a video", lead="Shrink a video so you can email it or send it in a chat.",
         steps=["Drop your video in the box.", "Choose how small, and the picture size (720p is a good start).", "Click <b>Compress</b> and save the smaller MP4."],
         faq=[("How much smaller does it get?", "Phone videos often shrink by 60–90 % at 720p."),
              ("Why is it slow?", "Your own computer does the work inside the browser. The free Ethical Converter desktop app is many times faster.")]),
    dict(slug="zip-files", group="zip", panel="zip", label="Zip files", card="Pack files into one .zip",
         title="Zip files online – create a ZIP free, no upload | EthicalApp",
         desc="Put several files into one .zip file to send them together. Free, private, no upload, no sign-up.",
         h1="Zip files", lead="Pack several files into one .zip to send them together.",
         steps=["Drop your files in the box.", "Give the zip a name.", "Click <b>Make zip</b> and save it."],
         faq=[("Can I zip folders?", "Drop the files from inside the folder. The free Ethical Converter desktop app zips whole folders (and 7z)."),
              ("Are my files uploaded?", "No – the zip is made in your browser.")]),
    dict(slug="unzip-files", group="zip", panel="unzip", label="Unzip files", card="Open a .zip and save what's inside",
         title="Unzip files online – open a ZIP free, no upload | EthicalApp",
         desc="Open a .zip file and save the files inside – free, private, in your browser. No upload, no sign-up.",
         h1="Unzip files", lead="See what's inside a .zip and save the files you need.",
         steps=["Drop a .zip in the box.", "Click <b>Open</b>.", "Save the files you want (or all of them)."],
         faq=[("What about .7z and .rar?", "The free Ethical Converter desktop app opens 7z, and zips with passwords."),
              ("Is it safe?", "The files are only unpacked in your browser's memory – nothing is installed or uploaded.")]),
]

CSP = ("default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "media-src 'self' blob:; worker-src 'self' blob:; connect-src 'self' blob: data:; font-src 'self'; object-src 'none'; "
       "base-uri 'self'; form-action 'none'")
GROUP_ICON = {g: icon for g, _, icon in GROUPS}


def public_url(path):
    """The address people (and Google) should use for a page."""
    if path == "index.html":
        return SITE_URL + "/"
    return f"{SITE_URL}/{path[:-5] if PRETTY_URLS and path.endswith('.html') else path}"


def head(title, desc, path, extra=""):
    canon = f'<link rel="canonical" href="{public_url(path)}">\n' if SITE_URL else ""
    og_url = f'<meta property="og:url" content="{public_url(path)}">\n' if SITE_URL else ""
    img = f"{SITE_URL}/assets/img/shot-suite.webp" if SITE_URL else "assets/img/shot-suite.webp"
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<meta name="referrer" content="strict-origin-when-cross-origin">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
{canon}<meta property="og:type" content="website">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}">
{og_url}<meta property="og:image" content="{img}">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#2e7d32">
<link rel="icon" href="assets/img/favicon-32.png" type="image/png">
<link rel="stylesheet" href="assets/style.css">
<script src="assets/config.js"></script>
<script src="assets/site.js"></script>
{extra}</head>'''


HEADER = '''<body>
<a class="skip" href="#main">Skip to content</a>
<header class="site-header">
  <div class="wrap">
    <a class="brand" href="index.html"><img src="assets/img/logo.svg" alt="" width="32" height="32"><span data-site="name">EthicalApp</span></a>
    <button class="theme-btn menu-btn" aria-label="Menu" aria-expanded="false">☰</button>
    <nav class="nav" aria-label="Main">
      <a href="index.html#apps">Apps</a>
      <a href="tools.html"{cur}>Free tools</a>
      <a href="index.html#faq">FAQ</a>
      <a href="index.html#support">Support us</a>
      <button class="theme-btn" type="button" aria-label="Switch theme">☾</button>
      <a class="btn btn-primary btn-small" href="index.html#download">Download the apps</a>
    </nav>
  </div>
</header>
'''


def footer():
    groups = ""
    for g, name, _ in GROUPS:
        links = "".join(f'<a href="{p["slug"]}.html">{p["label"]}</a>' for p in PAGES if p["group"] == g)
        groups += f'<div class="foot-col"><b>{name}</b>{links}</div>'
    return f'''<footer class="site-footer">
  <div class="wrap foot-tools">{groups}</div>
  <div class="wrap">
    <div>
      <div><b data-site="name">EthicalApp</b> · free and open source (AGPL-3.0)</div>
      <div data-hide-empty>Made by <span data-studio></span></div>
      <div>The online tools use pdf-lib, PDF.js, ffmpeg.wasm and fflate – see <a href="licenses.html">licences</a>.</div>
    </div>
    <nav aria-label="Footer">
      <a href="index.html">Home</a><a href="tools.html">Free tools</a><a href="index.html#download">Download</a>
      <a href="privacy.html">Privacy</a><a href="terms.html">Terms</a><a href="licenses.html">Licences</a>
      <a href="index.html#support">Support us</a>
    </nav>
  </div>
</footer>
</body>
</html>
'''


def panels():
    src = open(os.path.join(HERE, "_panels.html"), encoding="utf-8").read()
    return {m.group(2): m.group(1) for m in
            re.finditer(r'(<section class="tool-panel" id="([a-z-]+)".*?</section>)', src, re.S)}


def jsonld(obj):
    return f'<script type="application/ld+json">{json.dumps(obj, ensure_ascii=False)}</script>\n'


def tool_page(p, panel_html):
    path = f"{p['slug']}.html"
    panel = panel_html.replace(" hidden>", ">", 1)
    if p.get("preset"):
        panel = panel.replace(f'id="{p["panel"]}"', f'id="{p["panel"]}" data-preset=\'{json.dumps(p["preset"])}\'', 1)
    plain = lambda s: re.sub(r"<[^>]+>", "", s)  # noqa: E731
    ld = {"@context": "https://schema.org", "@type": "WebApplication", "name": f"{p['label']} – {SITE_NAME}",
          "description": p["desc"], "applicationCategory": "UtilitiesApplication",
          "operatingSystem": "Any – runs in your web browser", "isAccessibleForFree": True,
          "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
          "publisher": {"@type": "Organization", "name": "CraftingBenchGames", "url": "https://craftingbenchgames.com/"}}
    if SITE_URL:
        ld["url"] = f"{SITE_URL}/{path}"
    faq = {"@context": "https://schema.org", "@type": "FAQPage",
           "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": plain(a)}}
                          for q, a in p["faq"]]}
    howto = {"@context": "https://schema.org", "@type": "HowTo", "name": p["h1"],
             "step": [{"@type": "HowToStep", "position": i + 1, "text": plain(s)} for i, s in enumerate(p["steps"])]}
    extra = jsonld(ld) + jsonld(faq) + jsonld(howto) + '<script type="module" src="assets/tools.js"></script>\n'
    related = [q for q in PAGES if q["slug"] != p["slug"] and q["group"] == p["group"]]
    related += [q for q in PAGES if q["group"] != p["group"]][:8 - len(related)]
    rel = "".join(f'<a class="tool-card" href="{q["slug"]}.html"><img src="assets/img/icons/{GROUP_ICON[q["group"]]}.png" alt="" '
                  f'width="34" height="34"><span><b>{q["label"]}</b><small>{q["card"]}</small></span></a>' for q in related[:8])

    steps = "".join(f"<li>{s}</li>" for s in p["steps"])
    faqs = "".join(f"<details><summary>{q}</summary><p>{a}</p></details>" for q, a in p["faq"])
    return (head(p["title"], p["desc"], path, extra) + "\n" + HEADER.format(cur="") + f'''
<main id="main" class="tool-page">
  <div class="wrap narrow">
    <nav class="crumbs" aria-label="Breadcrumb"><a href="index.html">Home</a> › <a href="tools.html">Free tools</a> › <span>{p["label"]}</span></nav>
    <h1>{p["h1"]}</h1>
    <p class="lead">{p["lead"]}</p>
    <span class="privacy-pill">🔒 Free · no upload · no sign-up · no watermark</span>
  </div>
  <div class="wrap narrow tool-holder">
{panel}
  </div>
  <div class="wrap narrow seo">
    <h2>How to {p["h1"][0].lower() + p["h1"][1:]}</h2>
    <ol class="steps">{steps}</ol>
    <h2>Private by design</h2>
    <p>{PRIVACY} Close the page and it's all gone.</p>
    <h2>Questions</h2>
    <div class="faq">{faqs}</div>
    <h2>More free tools</h2>
    <div class="tool-grid">{rel}</div>
    <div class="card app-promo">
      <img src="assets/img/icons/suite.png" alt="" width="56" height="56">
      <div><b>Want this on your PC, offline?</b><br>EthicalApp is free desktop apps for Windows – a full PDF editor, documents,
        spreadsheets, a converter and more. No subscription, no catch.</div>
      <a class="btn btn-primary" href="index.html#download">Get the free apps</a>
    </div>
  </div>
</main>
''' + footer())


def hub():
    sections = ""
    for g, name, icon in GROUPS:
        cards = "".join(f'<a class="tool-card" href="{p["slug"]}.html"><img src="assets/img/icons/{icon}.png" alt="" width="34" '
                        f'height="34"><span><b>{p["label"]}</b><small>{p["card"]}</small></span></a>'
                        for p in PAGES if p["group"] == g)
        sections += f'<h2 class="hub-h">{name}</h2><div class="tool-grid">{cards}</div>'
    ld = {"@context": "https://schema.org", "@type": "ItemList", "name": "Free online file tools",
          "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": p["label"],
                               **({"url": f"{SITE_URL}/{p['slug']}.html"} if SITE_URL else {})} for i, p in enumerate(PAGES)]}
    return (head("Free online PDF, image, video & zip tools – no upload | EthicalApp",
                 "Simple free tools that run in your browser: merge and split PDF, JPG to PDF, compress images, MP4 to MP3, "
                 "compress video, zip and unzip. No upload, no sign-up, no watermark.", "tools.html", jsonld(ld))
            + "\n" + HEADER.format(cur=' aria-current="page"') + f'''
<main id="main">
  <div class="wrap tools-hero">
    <h1 style="font-size:clamp(1.9rem,4vw,2.8rem)">Free file tools</h1>
    <p class="muted" style="font-size:1.1rem;max-width:44em">Simple, fast and actually free. Pick a tool – no sign-up, no limits, no watermarks.</p>
    <span class="privacy-pill">🔒 Your files never leave your device – everything runs inside your browser.</span>
  </div>
  <div class="wrap hub">{sections}</div>
</main>
''' + footer())


def main():
    pan = panels()
    written = []
    for p in PAGES:
        with open(os.path.join(HERE, p["slug"] + ".html"), "w", encoding="utf-8") as fh:
            fh.write(tool_page(p, pan[p["panel"]]))
        written.append(p["slug"] + ".html")
    with open(os.path.join(HERE, "tools.html"), "w", encoding="utf-8") as fh:
        fh.write(hub())
    robots = "User-agent: *\nAllow: /\nDisallow: /thanks.html\n"
    if SITE_URL:
        today = date.today().isoformat()
        urls = ["index.html", "tools.html"] + written + ["privacy.html", "terms.html", "licenses.html"]
        body = "".join(f"  <url><loc>{public_url(u)}</loc><lastmod>{today}</lastmod></url>\n" for u in urls)
        with open(os.path.join(HERE, "sitemap.xml"), "w", encoding="utf-8") as fh:
            fh.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}</urlset>\n')
        robots += f"Sitemap: {SITE_URL}/sitemap.xml\n"
    else:
        print("SITE_URL is empty: no sitemap.xml / canonical links yet (set it once the site has an address).")
    with open(os.path.join(HERE, "robots.txt"), "w", encoding="utf-8") as fh:
        fh.write(robots)
    print(f"Wrote tools.html + {len(written)} tool pages: {', '.join(written)}")


if __name__ == "__main__":
    main()
