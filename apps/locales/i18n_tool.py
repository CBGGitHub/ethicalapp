"""Translation helper for EthicalApp.

  .venv\\Scripts\\python apps\\locales\\i18n_tool.py              collect every tr("…") / N_("…") text into template.json
                                                              and show what each language is still missing
  .venv\\Scripts\\python apps\\locales\\i18n_tool.py missing es   write es.missing.txt: numbered English texts to translate
  .venv\\Scripts\\python apps\\locales\\i18n_tool.py merge es es.done.txt
                                                              add translations written as "number<TAB>translation" lines
                                                              (numbers from the .missing.txt file) to es.json
  .venv\\Scripts\\python apps\\locales\\i18n_tool.py check        check every language: {placeholders}, HTML tags and the
                                                              one & accelerator must match the English text

Translations live in <code>.json as {"English text": "translation"}; texts no longer used are dropped on merge.
"""
import ast
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = os.path.dirname(HERE)
sys.path.insert(0, APPS)
from i18n import LANGUAGES  # noqa: E402

SKIP = {"mcp_server.py", "i18n.py"}           # the AI tools stay in English (the AI reads them)


def collect():
    texts = {}
    for path in sorted(glob.glob(os.path.join(APPS, "*.py"))):
        name = os.path.basename(path)
        if name in SKIP:
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and node.args and
                    (getattr(node.func, "id", None) in ("tr", "N_")) and
                    isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                s = node.args[0].value
                if s.strip():
                    texts.setdefault(s, set()).add(f"{name}:{node.lineno}")
    return texts


def load(code):
    p = os.path.join(HERE, code + ".json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def save(code, data, texts):
    data = {k: data[k] for k in sorted(data) if k in texts and data[k]}
    with open(os.path.join(HERE, code + ".json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=0, sort_keys=True)
        fh.write("\n")


def numbered(texts):
    return sorted(texts)


def esc(s):
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")


def unesc(s):
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t", "\\": "\\"}.get(m.group(1), "\\" + m.group(1)), s)


def marks(s):
    """What must survive translation."""
    ph = sorted(re.findall(r"\{[^{}]*\}", s.replace("{{", "").replace("}}", "")))
    tags = sorted(re.findall(r"</?\w+", s))
    amp = len(re.findall(r"&(?!&)\w", s.replace("&&", "")))
    pats = sorted(re.findall(r"\*\.\w+", s))
    return ph, tags, min(amp, 1), pats


def problems(en, tr_):
    out = []
    a, b = marks(en), marks(tr_)
    if a[0] != b[0]:
        out.append(f"placeholders {a[0]} vs {b[0]}")
    if a[1] != b[1]:
        out.append("HTML tags differ")
    if a[2] != b[2]:
        out.append("& accelerator")
    if a[3] != b[3]:
        out.append("file patterns differ")
    return out


def main():
    texts = collect()
    args = sys.argv[1:]
    with open(os.path.join(HERE, "template.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({t: sorted(texts[t])[:3] for t in sorted(texts)}, fh, ensure_ascii=False, indent=0)
        fh.write("\n")
    keys = numbered(texts)
    if not args:
        print(f"{len(keys)} texts.")
        for code in LANGUAGES:
            if code != "en":
                d = load(code)
                print(f"  {code:6} {sum(1 for k in keys if k in d):5} translated, {sum(1 for k in keys if k not in d):5} missing")
    elif args[0] == "missing":
        code = args[1]
        d = load(code)
        with open(os.path.join(HERE, code + ".missing.txt"), "w", encoding="utf-8", newline="\n") as fh:
            for i, k in enumerate(keys):
                if k not in d:
                    fh.write(f"{i}\t{esc(k)}\n")
        print("wrote", code + ".missing.txt")
    elif args[0] == "merge":
        code, src = args[1], args[2]
        d = load(code)
        bad = 0
        for line in open(src, encoding="utf-8"):
            line = line.rstrip("\n")
            if not line.strip() or "\t" not in line:
                continue
            num, text = line.split("\t", 1)
            k = keys[int(num)]
            text = unesc(text)
            p = problems(k, text)
            if p:
                bad += 1
                print(f"  {code} #{num}: {', '.join(p)}\n     EN: {k!r}\n     TR: {text!r}")
            d[k] = text
        save(code, d, texts)
        print(f"{code}: merged; {bad} with problems; {sum(1 for k in keys if k in d)}/{len(keys)} translated")
    elif args[0] == "check":
        for code in LANGUAGES:
            if code == "en":
                continue
            for k, v in load(code).items():
                p = problems(k, v)
                if p:
                    print(f"{code}: {k!r} -> {v!r}: {', '.join(p)}")


if __name__ == "__main__":
    main()
