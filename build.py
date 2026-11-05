"""Build the ML / Data Science flashcards from the Anki decks in data/.

Usage: python build.py

Writes flashcards/index.html (cards embedded), flashcards/media/* (card images)
and flashcards/sw.js (offline cache, versioned by a hash of everything above).
"""
import csv, difflib, hashlib, html, json, os, re, shutil, sqlite3, tempfile, zipfile
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "flashcards")
MEDIA = os.path.join(OUT, "media")

# Decks shown in the app: (title, .apkg files merged into it, raw-notes rule).
# Cards in data/PP-All-notes.txt that are missing from every .apkg are added to the
# first deck whose rule matches the question. Decks not listed here (Git, Kubernetes,
# GCP migration, web dev, research) are kept in data/ but not shown.
DECKS = [
    ("Machine Learning", ["Hands On ML book - Geron.apkg"],
     r"supervised|deep belief|boltzman|instance based|model-based|generali[sz]e ml|machine learning|cluster|federated"),
    ("Deep Learning", ["PP__DL Specialization - Coursera.apkg"],
     r"convol|convnet|pooling|lenet|neural"),
    ("Data Mining & Data Engineering", ["Data_Mining_PP.apkg", "Coursera-GCP-ML-Specialization-Course1.apkg"],
     r"data pipeline|correlation|histogram|entropy|information gain|association|bigquery"),
    ("Data Structures & Algorithms", ["PP__DS-Algos-Python.apkg", "PP-DS-Algos-Python.apkg"],
     r"big-o|complexity|algorithm|recursi|divide and conquer|greedy|backtrack|brute|array|amortized|anagram|stack|bfs|dfs|breadth|depth first"),
    ("Python", ["PP__Python.apkg", "Python-PP.apkg"],
     r"python|dictionary|mutable|what is set|lambda|method|\[::-1\]|\*\*2"),
]
RAW_NOTES = "PP-All-notes.txt"
# Friendlier names for the Anki deck a card came from (shown as a chip on the card).
SOURCES = {"Hands on ML - Geron": "Hands-On ML (Géron)", "DL Specialization - Coursera": "Coursera DL Specialization",
           "Coursera - GCP- ML Specialization - Course1": "Coursera ML on GCP", "Python-PP": "Python"}


class Clean(HTMLParser):
    """Keep simple formatting from Anki fields; drop styles, scripts and unknown tags."""
    KEEP = {"b", "strong", "i", "em", "u", "s", "sub", "sup", "br", "div", "p", "ul", "ol", "li", "pre",
            "code", "table", "thead", "tbody", "tr", "td", "th", "hr", "blockquote", "span"}
    RENAME = {"h1": "strong", "h2": "strong", "h3": "strong", "h4": "strong", "h5": "strong", "h6": "strong",
              "font": "span", "tt": "code"}
    VOID = {"br", "hr", "img"}

    def __init__(self, media):
        super().__init__(convert_charrefs=True)
        self.media, self.out, self.stack, self.skip = media, [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
            return
        if tag == "img":
            src = dict(attrs).get("src") or ""
            if src in self.media:
                self.out.append('<img src="media/%s" alt="" loading="lazy">' % html.escape(src, quote=True))
            return
        tag = self.RENAME.get(tag, tag)
        if tag not in self.KEEP:
            return
        span = "".join(' %s="%s"' % (k, html.escape(v)) for k, v in attrs
                       if tag in ("td", "th") and k in ("colspan", "rowspan") and (v or "").isdigit())
        self.out.append("<%s%s>" % (tag, span))
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
            return
        tag = self.RENAME.get(tag, tag)
        if tag in self.stack:
            while self.stack:
                t = self.stack.pop()
                self.out.append("</%s>" % t)
                if t == tag:
                    break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def result(self):
        self.close()
        s = "".join(self.out) + "".join("</%s>" % t for t in reversed(self.stack))
        s = s.replace("\xa0", " ").replace("�", "’")
        for _ in range(3):  # drop empty wrappers and leading/trailing line breaks
            s = re.sub(r"<(span|div|p|b|strong|i|em|u)>\s*</\1>", "", s)
            s = re.sub(r"^(\s|<br>)+|(\s|<br>)+$", "", s)
        return s.strip()


def clean(s, media=()):
    c = Clean(set(media))
    c.feed(s or "")
    return c.result()


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", text(s).lower())


def read_apkg(path):
    """Yield (guid, model, fields, tags, deck name) for each note; copy media into MEDIA."""
    tmp = tempfile.mkdtemp()
    try:
        zipfile.ZipFile(path).extractall(tmp)
        db = next((os.path.join(tmp, f) for f in ("collection.anki21", "collection.anki2")
                   if os.path.exists(os.path.join(tmp, f))), None)
        if not db:
            raise SystemExit("%s: unsupported Anki package format" % os.path.basename(path))
        names = {}
        if os.path.exists(os.path.join(tmp, "media")):
            names = json.load(open(os.path.join(tmp, "media"), encoding="utf8"))
        for k, name in names.items():
            if os.path.exists(os.path.join(tmp, k)) and "/" not in name and "\\" not in name:
                shutil.copy(os.path.join(tmp, k), os.path.join(MEDIA, name))
        con = sqlite3.connect(db)
        col = con.execute("select models, decks from col").fetchone()
        models, decks = json.loads(col[0]), json.loads(col[1])
        rows = con.execute("select n.guid, n.mid, n.flds, n.tags, min(c.did) from notes n "
                           "left join cards c on c.nid = n.id group by n.id order by n.id").fetchall()
        con.close()
        for guid, mid, flds, tags, did in rows:
            model = models.get(str(mid), {})
            fields = dict(zip([f["name"] for f in model.get("flds", [])], flds.split("\x1f")))
            deck = decks.get(str(did), {}).get("name", "")
            yield guid, model.get("name", ""), fields, tags.strip(), deck, set(names.values())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def code(s):
    """Monospace block for code; plain prose questions/answers from code-style notes stay as text."""
    t = text(s)
    prose = re.match(r"(what|how|name|method|which|why|when|is|are|functions?)\b", t, re.I) or len(t.split()) >= 5
    return s if prose and not re.search(r"[=\[\]{}]|\bdef |<pre>", s) else '<div class="code">%s</div>' % s


def card_from_note(guid, model, f, deck, media):
    if "Code" in f:  # "Code output question": what does this code print?
        q, a = code(clean(f.get("Code"), media)), code(clean(f.get("Output"), media))
        extra = clean(f.get("Explanation"), media)
    else:
        q, a = clean(f.get("Front"), media), clean(f.get("Back"), media)
        extra = clean(f.get("Description"), media)
    src = deck.split("::")[-1].strip() if deck and deck != "Default" else ""
    if src in ("DS-Algos-Python", "Introduction"):
        src = "Basics"
    if deck.startswith("PP::Hands on ML"):
        src = "Hands-On ML (Géron)"
    return {"id": guid, "q": q, "a": a, "x": extra, "src": SOURCES.get(src, src)}


def read_raw_notes(path, media):
    """Cards from Anki's plain-text export: question <tab> [question <br><br>] answer [explanation]."""
    with open(path, encoding="utf8", newline="") as fh:
        for row in csv.reader(fh, delimiter="	", quotechar='"'):
            if len(row) < 2:
                continue
            back = re.split(r'<div class="explanation">', row[1], maxsplit=1)
            a_html = re.sub(r'^.*?<div class="code_a">', "", back[0], count=1, flags=re.S)
            q, a = clean(row[0], media), clean(a_html, media)
            x = clean(back[1], media) if len(back) > 1 else ""
            if 'class="code_q"' in row[0]:
                q, a = code(q), code(a)
            yield {"id": "t-" + hashlib.sha1(norm(q).encode()).hexdigest()[:12], "q": q, "a": a, "x": x, "src": ""}


def has_content(s):
    return bool(text(s)) or "<img" in s


def is_dup(q, seen, fuzzy=False):
    """Same question already used, or a trimmed copy of one. fuzzy (for the raw notes) also catches
    typo fixes; it is off for the decks, where similar-looking Big-O questions are distinct cards."""
    n = norm(q)
    return any(n == o or (min(len(n), len(o)) > 20 and (n in o or o in n))
               or fuzzy and difflib.SequenceMatcher(None, n, o).ratio() > 0.92 for o in seen)


CURATED = ("Surya curated", os.path.join(DATA, "surya-curated"))


def read_curated(folder):
    """Hand-written cards, simple to advanced: one file per level, lines "Front :: Back [:: Example]"."""
    for fname in sorted(os.listdir(folder)):
        if not fname.endswith(".txt"):
            continue
        level = ""
        for line in open(os.path.join(folder, fname), encoding="utf8"):
            line = line.strip()
            if line.startswith("# Level"):
                level = line[2:].strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(" :: ")]
            if len(parts) < 2:
                raise SystemExit("%s: bad line: %s" % (fname, line))
            q = parts[0]
            yield {"id": "sc-" + hashlib.sha1(norm(q).encode()).hexdigest()[:12], "q": html.escape(q, quote=False),
                   "a": html.escape(parts[1], quote=False),
                   "x": html.escape(" :: ".join(parts[2:]), quote=False), "src": level}


def rate_cards(decks):
    """Set c["c"], complexity 1-5, from data/complexity.json. Typos and unrated cards stop the build."""
    cfg = json.load(open(os.path.join(DATA, "complexity.json"), encoding="utf8"))
    overrides = {}
    for rating, fronts in cfg["curated_overrides"].items():
        for front in fronts:
            if norm(front) in overrides:
                raise SystemExit("complexity.json: rated twice: " + front)
            overrides[norm(front)] = int(rating)
    unused, missing = set(overrides) | set(cfg["anki"]), []
    for d in decks:
        for c in d["cards"]:
            if d["name"] == CURATED[0]:
                key = norm(c["q"])
                level = re.match(r"Level (\d+)", c["src"]).group(1)
                c["c"] = overrides.get(key, cfg["level_defaults"][level])
            else:
                key = c["id"]
                if key in cfg["anki"]:
                    c["c"] = cfg["anki"][key]
                else:
                    missing.append(text(c["q"])[:60])
            unused.discard(key)
    if unused or missing:
        raise SystemExit("complexity.json: not matching any card: %s; cards without a rating: %s"
                         % (sorted(unused), missing))


def main():
    shutil.rmtree(MEDIA, ignore_errors=True)
    os.makedirs(MEDIA)
    out, seen = [], []
    for title, files, _ in DECKS:
        cards = []
        for fname in files:
            for guid, model, fields, tags, deck, media in read_apkg(os.path.join(DATA, fname)):
                c = card_from_note(guid, model, fields, deck, media)
                if has_content(c["q"]) and has_content(c["a"] + c["x"]) and not is_dup(c["q"], seen):
                    seen.append(norm(c["q"]))
                    cards.append(c)
        out.append({"name": title, "cards": cards})

    media = set(os.listdir(MEDIA))
    extra = 0
    for c in read_raw_notes(os.path.join(DATA, RAW_NOTES), media):
        if not has_content(c["q"]) or not has_content(c["a"]) or is_dup(c["q"], seen, fuzzy=True):
            continue
        for (title, _, rule), deck in zip(DECKS, out):
            if re.search(rule, text(c["q"]), re.I):
                seen.append(norm(c["q"]))
                deck["cards"].append(c)
                extra += 1
                break

    # The curated deck stands alone: it is not de-duplicated against the Anki decks (and they not against it).
    curated, ids = [], set()
    for c in read_curated(CURATED[1]):
        if c["id"] in ids:
            raise SystemExit("Surya curated: duplicate card: " + c["q"])
        ids.add(c["id"])
        curated.append(c)
    out.insert(0, {"name": CURATED[0], "cards": curated})
    rate_cards(out)

    # Only ship images that a card actually shows.
    fields = " ".join(c[k] for d in out for c in d["cards"] for k in ("q", "a", "x"))
    used = {html.unescape(u) for u in re.findall(r'src="media/([^"]+)"', fields)}
    for name in media - used:
        os.remove(os.path.join(MEDIA, name))
    media = sorted(os.listdir(MEDIA))

    tpl = open(os.path.join(ROOT, "template.html"), encoding="utf8").read()
    page = tpl.replace("/*DATA*/null", json.dumps(out, ensure_ascii=False).replace("</", "<\\/"))
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf8", newline="\n") as fh:
        fh.write(page)

    # The cache version changes whenever the page, an image or the service worker changes, so returning
    # visitors get the new cards; unchanged builds keep the same version (no re-download).
    sw = open(os.path.join(ROOT, "sw-template.js"), encoding="utf8").read()
    h = hashlib.sha256(page.encode() + sw.encode())
    h.update(open(os.path.join(OUT, "privacy.html"), "rb").read())
    for name in media:
        h.update(name.encode() + b"\0" + open(os.path.join(MEDIA, name), "rb").read())
    version = h.hexdigest()[:12]
    files = ["index.html", "privacy.html"] + ["media/" + n for n in media]
    sw = sw.replace("__VERSION__", version).replace("/*FILES*/[]", json.dumps(files, ensure_ascii=False))
    with open(os.path.join(OUT, "sw.js"), "w", encoding="utf8", newline="\n") as fh:
        fh.write(sw)

    print({d["name"]: len(d["cards"]) for d in out}, "| from raw notes:", extra,
          "| images:", len(media), "| cache version:", version)


if __name__ == "__main__":
    main()
