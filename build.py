"""Build HTML flashcards from the .apkg files in data/. Usage: python build.py"""
import sqlite3, json, re, zipfile, tempfile, shutil, os, html

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "flashcards")
MEDIA = os.path.join(OUT, "media")
os.makedirs(MEDIA, exist_ok=True)


def fix(s):
    return (s or "").replace("�", "’").strip()


def strip(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(s))).strip()


def lines(s):
    return [strip(p) for p in re.split(r"<br\s*/?>", s) if strip(p)]


decks = []
for apkg in sorted(os.listdir(os.path.join(ROOT, "data"))):
    if not apkg.endswith(".apkg"):
        continue
    tmp = tempfile.mkdtemp()
    zipfile.ZipFile(os.path.join(ROOT, "data", apkg)).extractall(tmp)
    dbf = next(os.path.join(tmp, f) for f in ("collection.anki21", "collection.anki2")
               if os.path.exists(os.path.join(tmp, f)))
    media = json.load(open(os.path.join(tmp, "media"), encoding="utf8"))
    for k, name in media.items():
        shutil.copy(os.path.join(tmp, k), os.path.join(MEDIA, name))
    db = sqlite3.connect(dbf)
    cards = []
    for flds, tags in db.execute("select flds, tags from notes order by id"):
        f = [fix(x) for x in flds.split("\x1f")]
        if len(f) == 3:  # Phrase/Idiom, Definition, Example
            cards.append({"idiom": strip(f[0]), "meaning": strip(f[1]),
                          "examples": [strip(f[2])] if f[2] else []})
        else:  # meaning, voice, idiom(+synonyms), voice, picture, sentences, voice, synonyms
            parts = lines(f[2])
            img = [i for i in re.findall(r'src="([^"]+)"', f[4]) if os.path.exists(os.path.join(MEDIA, i))]
            tag = ""
            if "<" not in tags:  # Anki split multi-word tags like "Games & Sports" into sorted words
                t = fix(tags)
                sep = " & " if "&" in t else " / " if "/" in t else " "
                tag = sep.join(w.capitalize() for w in t.replace("&", " ").replace("/", " ").split())
            cards.append({"idiom": parts[0] if parts else "", "meaning": strip(f[0]),
                          "examples": [e.strip('"') for e in lines(f[5])],
                          "synonyms": parts[1:] + lines(f[7]),
                          "img": "media/" + img[0] if img else "", "cat": tag})
    cards = [c for c in cards if c["idiom"] and c["meaning"]]
    decks.append({"name": apkg[:-5].replace("__", " & ").replace("_", " "), "cards": cards})
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)

tpl = open(os.path.join(ROOT, "template.html"), encoding="utf8").read()
with open(os.path.join(OUT, "index.html"), "w", encoding="utf8") as fh:
    fh.write(tpl.replace("/*DATA*/null", json.dumps(decks, ensure_ascii=False)))
print({d["name"]: len(d["cards"]) for d in decks})
