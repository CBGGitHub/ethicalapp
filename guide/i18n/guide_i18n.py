"""Guide translations.

  .venv\\Scripts\\python guide\\i18n\\guide_i18n.py export          writes guide/i18n/en.txt (the English source, from index.html)
  .venv\\Scripts\\python guide\\i18n\\guide_i18n.py build es        turns guide/i18n/es.txt into guide/i18n/es.js
  .venv\\Scripts\\python guide\\i18n\\guide_i18n.py build-all       rebuilds every <lang>.js from its .txt
  .venv\\Scripts\\python guide\\i18n\\guide_i18n.py status          which articles each language has / is missing

Translation files (<lang>.txt, optionally continued in <lang>.part2.txt …) are plain text, one block per article (plus "@ui" and "@sections" blocks):

  @@ article-id
  title: The title
  keywords: extra search words
  ---
  <p>The body HTML. Keep tags, href="#…" links, ${K("Ctrl S")} shortcuts and image paths unchanged.</p>

Articles missing from a language simply show in English, so a guide change never breaks a translation.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GUIDE = os.path.join(os.path.dirname(HERE), "index.html")

UI = {  # texts of the guide page itself (the app code reads them with T("…"))
    "guide_title": "EthicalApp Guide",
    "search": "Search the guide…  (press / )",
    "theme": "Light / dark",
    "footer": "EthicalApp Guide · works offline",
    "result_one": "1 result for “{q}”",
    "result_many": "{n} results for “{q}”",
    "nothing": "Nothing found. Try fewer or different words — e.g. “pdf merge”, “sum”, “layer”.",
    "english_only": "This article is only in English so far.",
}


def articles():
    src = open(GUIDE, encoding="utf-8").read()
    out = []
    pat = re.compile(r'\{ id: "([^"]+)", section: "([^"]+)", title: "((?:[^"\\]|\\.)*)", keywords: "((?:[^"\\]|\\.)*)",\s*'
                     r'body: `(.*?)` \},?\n', re.S)
    for m in pat.finditer(src):
        out.append(dict(id=m.group(1), section=m.group(2), title=json.loads('"' + m.group(3) + '"'),
                        keywords=json.loads('"' + m.group(4) + '"'), body=m.group(5)))
    sections = re.search(r"const SECTIONS = \[(.*?)\];", src, re.S).group(1)
    secs = re.findall(r'\["(\w+)", "([^"]+)"', sections)
    return out, secs


def export():
    arts, secs = articles()
    with open(os.path.join(HERE, "en.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("@ui\n")
        for k, v in UI.items():
            fh.write(f"{k}: {v}\n")
        fh.write("\n@sections\n")
        for k, v in secs:
            fh.write(f"{k}: {v}\n")
        for a in arts:
            fh.write(f"\n@@ {a['id']}\ntitle: {a['title']}\nkeywords: {a['keywords']}\n---\n{a['body'].strip()}\n")
    print(len(arts), "articles ->", os.path.join(HERE, "en.txt"))


def parse(path):
    """Reads <lang>.txt plus any <lang>.part2.txt, <lang>.part3.txt … (big translations can be split)."""
    name = os.path.basename(path)[:-4]
    parts = [path] + sorted(os.path.join(HERE, f) for f in os.listdir(HERE)
                            if f.startswith(name + ".part") and f.endswith(".txt"))
    text = "\n".join(open(f, encoding="utf-8").read().replace("\r\n", "\n") for f in parts)
    ui, secs, arts = {}, {}, {}
    blocks = re.split(r"\n(?=@)", "\n" + text)
    for b in blocks:
        b = b.strip("\n")
        if not b:
            continue
        if b.startswith("@ui") or b.startswith("@sections"):
            target = ui if b.startswith("@ui") else secs
            for line in b.split("\n")[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    target[k.strip()] = v.strip()
        elif b.startswith("@@"):
            head, _, body = b.partition("\n---\n")
            lines = head.split("\n")
            aid = lines[0][2:].strip()
            meta = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            arts[aid] = dict(title=meta.get("title", ""), keywords=meta.get("keywords", ""), body=body.strip())
    return ui, secs, arts


def check(en, tr, aid):
    """The parts of an article that must not change."""
    problems = []
    for what, pat in (("links", r'href="#[^"]*"'), ("shortcuts", r"\$\{[^}]*\}"), ("images", r'src="[^"]*"')):
        a, b = sorted(re.findall(pat, en)), sorted(re.findall(pat, tr))
        if a != b:
            problems.append(what)
    tags = lambda s: sorted(re.findall(r"</?(?:h2|h3|ul|ol|li|table|tr|td|th|div|p|b|i|code|kbd|a|img|br)\b", s))
    if tags(en) != tags(tr):
        problems.append("tags")
    if "`" in tr:
        problems.append("backtick")
    return problems


def build(lang):
    ui, secs, arts = parse(os.path.join(HERE, lang + ".txt"))
    en_arts = {a["id"]: a for a in articles()[0]}
    bad = 0
    for aid, a in arts.items():
        if aid not in en_arts:
            print(f"  {lang}: unknown article {aid}")
            continue
        p = check(en_arts[aid]["body"], a["body"], aid)
        if p:
            bad += 1
            print(f"  {lang}: {aid}: {', '.join(p)}")
    js = ["// Generated by guide_i18n.py from " + lang + ".txt - edit the .txt, then run: guide_i18n.py build " + lang,
          "window.GUIDE_TR = {",
          "ui: " + json.dumps(ui, ensure_ascii=False) + ",",
          "sections: " + json.dumps(secs, ensure_ascii=False) + ",",
          "articles: {"]
    for aid, a in arts.items():
        if aid in en_arts:
            js.append(f"{json.dumps(aid)}: {{ title: {json.dumps(a['title'], ensure_ascii=False)}, "
                      f"keywords: {json.dumps(a['keywords'], ensure_ascii=False)},\nbody: `{a['body']}` }},")
    js += ["}};", ""]
    with open(os.path.join(HERE, lang + ".js"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(js))
    print(f"{lang}: {len(arts)}/{len(en_arts)} articles, {bad} with problems")


def main():
    cmd = sys.argv[1:] or ["status"]
    if cmd[0] == "export":
        export()
    elif cmd[0] == "build":
        build(cmd[1])
    elif cmd[0] == "build-all":
        for f in sorted(os.listdir(HERE)):
            if f.endswith(".txt") and f != "en.txt" and ".part" not in f:
                build(f[:-4])
    else:
        en = [a["id"] for a in articles()[0]]
        for f in sorted(os.listdir(HERE)):
            if f.endswith(".txt") and f != "en.txt" and ".part" not in f:
                have = parse(os.path.join(HERE, f))[2]
                missing = [a for a in en if a not in have]
                print(f"{f[:-4]:6} {len(en) - len(missing)}/{len(en)}" + (f"  missing: {', '.join(missing)}" if missing else ""))


if __name__ == "__main__":
    main()
