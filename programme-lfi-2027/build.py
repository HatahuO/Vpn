#!/usr/bin/env python3
"""
Extraction du programme présidentiel 2027 de la France insoumise (melenchon2027.fr)
vers un jeu de données unique : JSON + Markdown + CSV + HTML autonome et interrogeable.

Périmètre (programme 2027 officiel) :
  1. « L'Avenir en commun » (livre) : introduction, 6 parties, 22 chapitres
  2. Les plans thématiques (santé, enseignement supérieur/recherche, ruralité)
  3. Les plans d'investissement productif (BTP-logement, automobile)
  4. Deux documents PDF « Autour du programme » (pôle public bancaire, comptes publics)

Exclus volontairement : synthèse des contributions citoyennes, auditions, actualités
2022-2025, comparateurs d'autres partis, programmes historiques (NFP 2024, NUPES 2022).

Usage :
  python3 build.py --out . --cache ./.cache            # tout (télécharge si besoin)
  python3 build.py --out . --cache ./.cache --refresh   # ignore le cache

Dépendances : beautifulsoup4, lxml ; pdftotext (poppler-utils) pour les PDF.
"""
import argparse
import copy
import csv
import datetime as dt
import hashlib
import html
import json
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

BASE = "https://melenchon2027.fr"
UA = "Mozilla/5.0 (compatible; programme-archiver/1.0; usage personnel)"
WARNINGS = []  # alimenté par assign_ids
EXPECTED_MEASURES = 1069  # chiffre annoncé par le site (page « Découvrir le programme »)

PLANS = [
    # (code, kind, chemin du lien)
    ("PT-SANTE", "plan_thematique", "/programme/plans-thematiques/sante/"),
    ("PT-ESR", "plan_thematique", "/programme/plans-thematiques/esr/"),
    ("PT-RURALITE", "plan_thematique", "/programme/plans-thematiques/ruralite/"),
    ("PI-BTP", "plan_investissement", "/programme/plans-investissement/btp-logement/"),
    ("PI-AUTO", "plan_investissement", "/programme/plans-investissement/automobile/"),
]
PDFS = [
    ("DOC-BANQUE", "Pour un pôle public bancaire au service des besoins",
     "/wp-content/uploads/2026/10/DP-POLE-PUBLIC-BANCAIRE_ST.pdf"),
    ("DOC-COMPTES", "Comment nous allons remettre de l'ordre dans les comptes publics",
     "/wp-content/uploads/2026/10/Comment-nous-allons-remettre-de-l-ordre-dans-les-comptes-publics.pdf"),
]
SHORT = {
    "LAEC": "L'Avenir en commun", "PT-SANTE": "Plan santé", "PT-ESR": "Plan enseignement supérieur & recherche",
    "PT-RURALITE": "Plan ruralités", "PI-BTP": "Investissement BTP & logement", "PI-AUTO": "Investissement automobile",
    "DOC-BANQUE": "Pôle public bancaire", "DOC-COMPTES": "Comptes publics",
}
KIND_LABEL = {
    "livre": "Livre-programme",
    "plan_thematique": "Plan thématique",
    "plan_investissement": "Plan d'investissement",
    "pdf": "Document PDF (annexe)",
}

# ----------------------------------------------------------------------------- réseau


class Fetcher:
    def __init__(self, cache: Path, refresh: bool = False, delay: float = 0.4):
        self.cache, self.refresh, self.delay = cache, refresh, delay
        cache.mkdir(parents=True, exist_ok=True)
        self.n_net = 0

    def get(self, url: str, binary: bool = False):
        key = hashlib.sha256(url.encode()).hexdigest()[:24]
        f = self.cache / (key + (".bin" if binary else ".txt"))
        if f.exists() and not self.refresh:
            return f.read_bytes() if binary else f.read_text(encoding="utf-8")
        last = None
        for i in range(4):
            try:
                time.sleep(self.delay)  # politesse envers le serveur
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=90) as r:
                    data = r.read()
                self.n_net += 1
                f.write_bytes(data) if binary else f.write_text(data.decode("utf-8"), encoding="utf-8")
                return data if binary else data.decode("utf-8")
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
                time.sleep(2 ** i)
        raise SystemExit(f"Échec de téléchargement : {url} ({last})")


# ----------------------------------------------------------------------------- texte

WS = re.compile(r"[ \t\r\f\v\n]+")


# Espaces insécables / typographiques (U+00A0, U+2000-200A, U+202F…) ramenés à l'espace simple, et caractères de
# largeur nulle supprimés : sans cela « 1 700 euros » ne serait pas retrouvé par une recherche avec espace normale.
SPACES = re.compile("[" + "".join(map(chr, (0x00A0, 0x1680, *range(0x2000, 0x200B), 0x202F, 0x205F, 0x3000))) + "]")
ZEROW = re.compile("[" + "".join(map(chr, (*range(0x200B, 0x200E), 0x2060, 0xFEFF))) + "]")



def clean(s: str) -> str:
    """Normalise les espaces : le site emploie des espaces fines/insécables que la recherche ne retrouverait pas."""
    return WS.sub(" ", SPACES.sub(" ", ZEROW.sub("", s))).strip()


def inline(node, md: bool) -> str:
    """Texte d'un élément. md=True conserve gras/italique/liens en Markdown."""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag) or node.name in ("script", "style"):
        return ""
    if node.name == "br":
        return " "
    inner = "".join(inline(c, md) for c in node.children)
    if not md:
        return inner
    if node.name in ("strong", "b") and inner.strip():
        lead, trail = inner[: len(inner) - len(inner.lstrip())], inner[len(inner.rstrip()):]
        return f"{lead}**{inner.strip()}**{trail}"
    if node.name in ("em", "i") and inner.strip():
        lead, trail = inner[: len(inner) - len(inner.lstrip())], inner[len(inner.rstrip()):]
        return f"{lead}*{inner.strip()}*{trail}"
    if node.name == "a" and node.get("href") and inner.strip():
        href = node["href"]
        if href.startswith("/"):
            href = BASE + href
        if href.startswith("http"):
            return f"[{inner.strip()}]({href})"
    return inner


def text_of(node) -> str:
    return clean(inline(node, md=False))


def md_of(node) -> str:
    s = clean(inline(node, md=True))
    return re.sub(r"\*\*\s*\*\*", " ", s)


def fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


# ----------------------------------------------------------------------------- HTML -> blocs

BLOCK_TAGS = {"p", "ul", "ol", "table", "figure", "div", "section", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}


class Walker:
    """Parcourt un conteneur HTML dans l'ordre du document et émet des évènements
    ('h', niveau, texte) et ('b', kind, texte, md, extra). Garde la trace des éléments
    consommés pour pouvoir contrôler qu'aucun texte n'a été oublié."""

    def __init__(self):
        self.events, self.done = [], set()

    def consume(self, t):
        self.done.add(id(t))

    def run(self, container):
        for ch in container.children:
            if isinstance(ch, Tag):
                self.handle(ch)
        return self.events

    def handle(self, t: Tag):
        if id(t) in self.done:  # déjà consommé (ou explicitement ignoré) par l'appelant
            return
        n, cls = t.name, t.get("class", [])
        if n in ("script", "style", "noscript", "svg"):
            self.consume(t)
            return
        if re.fullmatch(r"h[1-6]", n):
            self.consume(t)
            if text_of(t):
                self.events.append(("h", int(n[1]), text_of(t), md_of(t), {}))
            return
        if n == "div" and "mesure-cle" in cls:
            self.consume(t)
            ps = [p for p in t.find_all("p")]
            txt = " ".join(text_of(p) for p in ps) or text_of(t)
            md = " ".join(md_of(p) for p in ps) or md_of(t)
            self.events.append(("b", "mesure_cle", txt, md, {}))
            return
        if n in ("ul", "ol"):
            self.consume(t)
            self.list_items(t, 0)
            return
        if n == "table" or (n == "figure" and t.find("table")):
            self.consume(t)
            self.table(t)
            return
        if n == "p" or n == "blockquote":
            self.consume(t)
            if text_of(t):
                self.events.append(("b", "texte", text_of(t), md_of(t), {}))
            return
        if t.find(list(BLOCK_TAGS)) is None:  # feuille « inline » portant du texte
            self.consume(t)
            if text_of(t):
                self.events.append(("b", "texte", text_of(t), md_of(t), {}))
            return
        # conteneur : on descend (en rattrapant le texte nu éventuel)
        for ch in t.children:
            if isinstance(ch, Tag):
                self.handle(ch)
            elif isinstance(ch, NavigableString) and clean(str(ch)):
                self.events.append(("b", "texte", clean(str(ch)), clean(str(ch)), {}))

    def list_items(self, ul: Tag, depth: int):
        for li in ul.find_all("li", recursive=False):
            self.consume(li)
            nested = [c for c in li.children if isinstance(c, Tag) and c.name in ("ul", "ol")]
            own = copy.copy(li)  # copie sans les sous-listes : le texte propre de l'item
            for sub in own.find_all(["ul", "ol"]):
                sub.decompose()
            txt, md = text_of(own), md_of(own)
            if txt:
                kind = "mesure" if "mesure" in li.get("class", []) else "puce"
                self.events.append(("b", kind, txt, md, {"depth": depth}))
            for sub in nested:
                self.consume(sub)
                self.list_items(sub, depth + 1)

    def table(self, t: Tag):
        tbl = t if t.name == "table" else t.find("table")
        rows = []
        for tr in tbl.find_all("tr"):
            cells = [text_of(c) for c in tr.find_all(["th", "td"])]
            if any(cells):
                rows.append(cells)
        cap = t.find("figcaption")
        if rows:
            flat = "\n".join(" | ".join(r) for r in rows)
            self.events.append(("b", "tableau", flat, flat, {"rows": rows}))
        if cap and text_of(cap):
            self.events.append(("b", "texte", text_of(cap), md_of(cap), {}))


def uncovered_text(container, done: set) -> list:
    """Chaînes de texte du conteneur non couvertes par un élément consommé."""
    missing = []
    for s in container.find_all(string=True):
        if not clean(str(s)):
            continue
        if any(id(a) in done for a in s.parents):
            continue
        if s.parent and s.parent.name in ("script", "style"):
            continue
        missing.append(clean(str(s))[:80])
    return missing


def sectionize(events, base_level=None):
    """Évènements -> sections (titre, chemin hiérarchique, blocs)."""
    sections, stack = [], []
    cur = None

    def new(level, title):
        nonlocal cur
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        cur = {"title": title, "depth": len(stack), "path": [s[1] for s in stack], "blocks": []}
        sections.append(cur)

    for ev in events:
        if ev[0] == "h":
            new(ev[1], ev[2])
        else:
            if cur is None:
                cur = {"title": "", "depth": 0, "path": [], "blocks": []}
                sections.append(cur)
            _, kind, txt, md, extra = ev
            blk = {"kind": kind, "text": txt}
            if md != txt:
                blk["md"] = md
            blk.update(extra)
            cur["blocks"].append(blk)
    return [s for s in sections if s["blocks"] or s["title"]]


# ----------------------------------------------------------------------------- sources


def parse_livre(fx: Fetcher, warnings: list):
    idx_html = fx.get(BASE + "/programme/livre/")
    soup = BeautifulSoup(idx_html, "lxml")
    nav = soup.find("nav", class_="tdm")
    units_def = []  # (code, part_label, title, url)
    for d in nav.find_all("div", class_="partie", recursive=False):
        slug = d["class"][1]
        h2 = d.find("h2")
        title = text_of(h2)
        if slug == "introduction":
            units_def.append(("INTRO", None, title, f"/programme/livre/{slug}"))
            continue
        pnum = len([u for u in units_def if u[0].endswith("-PRESENTATION")]) + 1
        units_def.append((f"P{pnum}-PRESENTATION", title, title, f"/programme/livre/{slug}"))
        chaps = [a for a in d.find_all("a") if "/chapitre" in a.get("href", "")]
        for a in chaps:
            cnum = int(re.search(r"chapitre(\d+)", a["href"]).group(1))
            units_def.append((f"P{pnum}C{cnum}", title, text_of(a), a["href"]))
    # Partie 5 : l'en-tête n'a pas toujours de lien ; chapitres éventuellement hors <div.partie>
    known = {u[3] for u in units_def}
    for a in nav.find_all("a"):
        h = a.get("href", "")
        if "/chapitre" in h and h not in known:
            warnings.append(f"Chapitre trouvé hors structure attendue : {h}")

    units, total_missing = [], 0
    for code, part, title, path in units_def:
        url = BASE + path
        page = BeautifulSoup(fx.get(url), "lxml")
        main = page.find("main")
        if main is None:
            warnings.append(f"Pas de <main> pour {url}")
            continue
        w = Walker()
        if code == "INTRO":
            events = w.run(main)
            unit_title = title
        elif code.endswith("-PRESENTATION"):
            # page de partie : texte d'introduction + table des chapitres (non reprise)
            for nav_el in main.find_all(["nav", "header"]) + main.find_all("a", class_="next"):
                w.consume(nav_el)  # sommaire des chapitres + lien « Partie suivante » : navigation, pas du contenu
            for h in main.find_all("h2"):
                if text_of(h).startswith("Partie"):
                    w.consume(h)  # intitulé déjà porté par la partie
            events = w.run(main)
            unit_title = "Présentation de la partie"
        else:
            header = main.find("header")
            if header:
                w.consume(header)
            events = w.run(main)  # section.chapitre (intro) + div.chapitre_sections
            h1 = main.find("h1")
            unit_title = text_of(h1) if h1 else title
        miss = uncovered_text(main, w.done | {id(x) for x in main.find_all(["nav", "header"])})
        if miss:
            total_missing += len(miss)
            warnings.append(f"{code}: {len(miss)} fragment(s) de texte non repris, ex. {miss[:2]}")
        sections = sectionize(events)
        units.append({"code": code, "part": part, "title": unit_title, "url": url, "sections": sections})
    return {
        "code": "LAEC", "kind": "livre", "title": "L'Avenir en commun — Le programme de la Nouvelle France (6e édition)",
        "url": BASE + "/programme/livre/", "units": units,
    }


def parse_plan(fx: Fetcher, rest_pages: dict, code, kind, path, warnings: list):
    url = BASE + path
    page = rest_pages.get(path)
    if page is None:
        warnings.append(f"Plan introuvable dans l'API : {path}")
        return None
    soup = BeautifulSoup(page["content"]["rendered"], "lxml")
    root = soup.body or soup
    w = Walker()
    events = w.run(root)
    miss = uncovered_text(root, w.done)
    if miss:
        warnings.append(f"{code}: {len(miss)} fragment(s) non repris, ex. {miss[:2]}")
    title = text_of(BeautifulSoup(page["title"]["rendered"], "lxml"))
    sections = sectionize(events)
    return {
        "code": code, "kind": kind, "title": title, "url": url, "modified": page.get("modified"),
        "units": [{"code": code, "part": None, "title": title, "url": url, "sections": sections}],
    }


def parse_pdf(fx: Fetcher, code, title, path, warnings: list):
    url = BASE + path
    raw = fx.get(url, binary=True)
    tmp = fx.cache / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".pdf")
    tmp.write_bytes(raw)
    res = subprocess.run(["pdftotext", "-enc", "UTF-8", str(tmp), "-"], capture_output=True)
    pages = res.stdout.decode("utf-8", "replace").split("\f")
    sections = []
    for i, ptxt in enumerate(pages, 1):
        paras = [clean(p) for p in re.split(r"\n\s*\n", ptxt) if clean(p)]
        paras = [p for p in paras if len(p) > 2]
        if paras:
            sections.append({"title": f"Page {i}", "depth": 1, "path": [f"Page {i}"],
                             "blocks": [{"kind": "texte", "text": p} for p in paras]})
    warnings.append(f"{code}: extraction PDF — graphiques et tableaux chiffrés peu fiables (texte courant OK).")
    return {
        "code": code, "kind": "pdf", "title": title, "url": url,
        "units": [{"code": code, "part": None, "title": title, "url": url, "sections": sections}],
    }


def load_rest_pages(fx: Fetcher):
    pages, p = {}, 1
    while True:
        url = f"{BASE}/wp-json/wp/v2/pages?per_page=100&page={p}&_fields=id,link,title,modified,content"
        try:
            batch = json.loads(fx.get(url))
        except SystemExit:
            break
        for x in batch:
            pages[x["link"].replace(BASE, "")] = x
        if len(batch) < 100:
            break
        p += 1
    return pages


# ----------------------------------------------------------------------------- identifiants & contrôles


def assign_ids(docs):
    for d in docs:
        for u in d["units"]:
            n_m = n_k = n_p = n_s = 0
            parent = None
            for s in u["sections"]:
                for b in s["blocks"]:
                    if b["kind"] == "mesure":
                        n_m += 1
                        b["id"] = parent = f"{u['code']}-M{n_m:03d}"
                    elif b["kind"] == "mesure_cle":
                        n_k += 1
                        b["id"] = f"{u['code']}-K{n_k:02d}"
                    elif b["kind"] == "puce" and d["kind"] == "livre":
                        # puce imbriquée sous une mesure du livre = sous-mesure (comptée par le site)
                        n_s += 1
                        b["kind"] = "sous_mesure"
                        b["id"] = f"{u['code']}-S{n_s:03d}"
                        if parent:
                            b["parent"] = parent
                        else:
                            WARNINGS.append(f"{b['id']}: sous-mesure sans mesure parente")
                    elif b["kind"] == "puce":
                        n_p += 1
                        b["id"] = f"{u['code']}-L{n_p:03d}"


def stats(docs):
    out = {}
    for d in docs:
        c = {"mesure": 0, "sous_mesure": 0, "mesure_cle": 0, "puce": 0, "texte": 0, "tableau": 0}
        for u in d["units"]:
            for s in u["sections"]:
                for b in s["blocks"]:
                    c[b["kind"]] = c.get(b["kind"], 0) + 1
        out[d["code"]] = c
    return out


def flat_blocks(docs):
    for d in docs:
        for u in d["units"]:
            for s in u["sections"]:
                for b in s["blocks"]:
                    yield d, u, s, b


# ----------------------------------------------------------------------------- sorties


def anchor(*parts):
    return re.sub(r"[^a-z0-9]+", "-", fold(" ".join(parts))).strip("-")


def render_markdown(data) -> str:
    L = []
    m = data["meta"]
    L += [f"# {m['title']}", "",
          f"> Source : <{m['source']}> — extrait le {m['generated_at']}.  ",
          f"> {m['scope']}", ""]
    st = m["stats"]["LAEC"]
    tot = st["mesure"] + st["sous_mesure"] + st["mesure_cle"]
    L += [f"**Contenu** : le livre-programme compte {tot} mesures ({st['mesure']} mesures + {st['sous_mesure']} sous-mesures "
          f"+ {st['mesure_cle']} mesures clés ; le site en annonce {m['expected_measures']}), "
          f"plus {len(data['documents']) - 1} documents complémentaires (plans thématiques, plans d'investissement, annexes PDF).", "",
          "**Identifiants** : `PnCm` = partie n, chapitre m ; `-Mxxx` = mesure, `-Sxxx` = sous-mesure (puce imbriquée sous une mesure), "
          "`-Kxx` = mesure clé, `-Lxxx` = élément de liste d'un plan (les plans ne distinguent pas mesures et simples énumérations).", "",
          "## Sommaire", ""]
    for d in data["documents"]:
        L.append(f"- [{d['title']}](#{anchor(d['code'])})")
        if d["kind"] == "livre":
            for u in d["units"]:
                if u["code"].endswith("-PRESENTATION"):
                    continue
                prefix = "" if u["code"] == "INTRO" else f"{u['code']} — "
                L.append(f"  - [{prefix}{u['title']}](#{anchor(u['code'])})")
    L.append("")
    for d in data["documents"]:
        L += [f"<a id=\"{anchor(d['code'])}\"></a>", f"## {d['title']}", "",
              f"*{KIND_LABEL[d['kind']]} — <{d['url']}>*", ""]
        if d["kind"] == "pdf":
            L += ["> ⚠️ Texte extrait d'un PDF : les graphiques et tableaux chiffrés sont mal restitués.", ""]
        last_part = None
        for u in d["units"]:
            single = len(d["units"]) == 1
            if d["kind"] == "livre" and u["part"] and u["part"] != last_part:
                last_part = u["part"]
                L += [f"### {u['part']}", ""]
            if not single:
                head = "####" if d["kind"] == "livre" and u["part"] else "###"
                L += [f"<a id=\"{anchor(u['code'])}\"></a>", f"{head} {u['title']}", "",
                      f"<sub>{u['code']} · <{u['url']}></sub>", ""]
            base = 2 if single else (4 if (d["kind"] == "livre" and u["part"]) else 3)
            for s in u["sections"]:
                if s["title"]:
                    L += [f"{'#' * min(6, base + max(0, s['depth'] - 1) + 1)} {s['title']}", ""]
                for b in s["blocks"]:
                    t = b.get("md", b["text"])
                    k = b["kind"]
                    if k == "mesure":
                        L.append(f"- [{b['id']}] {t}")
                    elif k == "mesure_cle":
                        L += ["", f"> ⭐ **Mesure clé** [{b['id']}] — {t}", ""]
                    elif k == "sous_mesure":
                        L.append(f"{'  ' * b.get('depth', 1)}- [{b['id']}] {t}")
                    elif k == "puce":
                        L.append(f"{'  ' * b.get('depth', 0)}- {t}")
                    elif k == "tableau":
                        rows = b["rows"]
                        w = max(len(r) for r in rows)
                        rows = [r + [""] * (w - len(r)) for r in rows]
                        esc = lambda c: c.replace("|", "\\|")
                        L += ["", "| " + " | ".join(esc(c) for c in rows[0]) + " |", "|" + "---|" * w]
                        L += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows[1:]] + [""]
                    else:
                        if L and L[-1].startswith("- "):
                            L.append("")
                        L += [t, ""]
                if L and L[-1] != "":
                    L.append("")
    return "\n".join(L).rstrip() + "\n"


def write_csv(data, path: Path):
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM : ouverture directe dans Excel
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "document", "type_document", "partie", "unite", "section", "type", "texte", "url"])
        for d, u, s, b in flat_blocks(data["documents"]):
            if b["kind"] in ("mesure", "sous_mesure", "mesure_cle", "puce"):
                w.writerow([b["id"], d["title"], KIND_LABEL[d["kind"]], u["part"] or "", u["title"],
                            " > ".join(s["path"]), b["kind"], b["text"], u["url"]])


def render_html(data, template: str) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return template.replace("/*__DATA__*/null", payload)


# ----------------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".")
    ap.add_argument("--cache", default="./.cache")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    out, here = Path(a.out), Path(__file__).parent
    fx = Fetcher(Path(a.cache), a.refresh)
    warnings = []

    print("→ livre-programme…", file=sys.stderr)
    docs = [parse_livre(fx, warnings)]
    print("→ plans (API REST)…", file=sys.stderr)
    rest = load_rest_pages(fx)
    for code, kind, path in PLANS:
        d = parse_plan(fx, rest, code, kind, path, warnings)
        if d:
            docs.append(d)
    print("→ PDF…", file=sys.stderr)
    for code, title, path in PDFS:
        docs.append(parse_pdf(fx, code, title, path, warnings))

    assign_ids(docs)
    warnings.extend(WARNINGS)
    for d in docs:
        d["short"] = SHORT[d["code"]]
    for d in docs:  # empreinte du contenu : permet de détecter une modification du site
        d["content_sha256"] = hashlib.sha256(
            json.dumps(d["units"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    st = stats(docs)
    data = {
        "meta": {
            "title": "Programme de la France insoumise — Présidentielle 2027",
            "source": BASE, "generated_at": dt.date.today().isoformat(),
            "scope": "Périmètre : livre « L'Avenir en commun », plans thématiques, plans d'investissement productif, "
                     "deux documents PDF d'accompagnement. Exclus : contributions citoyennes, auditions, archives 2022-2025.",
            "expected_measures": EXPECTED_MEASURES, "stats": st, "warnings": warnings,
        },
        "documents": docs,
    }

    (out / "programme_lfi_2027.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "programme_lfi_2027.md").write_text(render_markdown(data), encoding="utf-8")
    write_csv(data, out / "mesures.csv")
    tpl = here / "viewer_template.html"
    if tpl.exists():
        (out / "programme_lfi_2027.html").write_text(render_html(data, tpl.read_text(encoding="utf-8")), encoding="utf-8")

    # ------------------------------------------------------------ rapport de contrôle
    print("\n=== CONTRÔLE ===")
    for d in docs:
        print(f"{d['code']:12s} {st[d['code']]}")
    laec = st["LAEC"]
    tot = laec["mesure"] + laec["sous_mesure"] + laec["mesure_cle"]
    flag = "OK" if tot == EXPECTED_MEASURES else f"ÉCART de {tot - EXPECTED_MEASURES:+d}"
    print(f"\nLivre : {laec['mesure']} mesures + {laec['sous_mesure']} sous-mesures + {laec['mesure_cle']} clés = {tot} ; annoncé {EXPECTED_MEASURES} → {flag}")
    texts = [b["text"] for _, _, _, b in flat_blocks(docs[:1]) if b["kind"] in ("mesure", "sous_mesure")]
    dup_keys = [b["id"] for _, _, _, b in flat_blocks(docs[:1]) if b["kind"] == "mesure_cle" and b["text"] in texts]
    print(f"Mesures clés dont le texte est aussi une mesure listée : {len(dup_keys)} {dup_keys[:5]}")
    dups = {t for t in texts if texts.count(t) > 1}
    print(f"Textes de mesures strictement identiques (doublons) : {len(dups)}")
    empty = [b["id"] for _, _, _, b in flat_blocks(docs) if "id" in b and len(b["text"]) < 15]
    print(f"Éléments très courts (<15 car.) à vérifier : {len(empty)} {empty[:8]}")
    for u in docs[0]["units"]:
        n = sum(1 for s in u["sections"] for b in s["blocks"] if b["kind"] == "mesure")
        sm = sum(1 for s in u["sections"] for b in s["blocks"] if b["kind"] == "sous_mesure")
        k = sum(1 for s in u["sections"] for b in s["blocks"] if b["kind"] == "mesure_cle")
        print(f"   {u['code']:16s} {n:4d} mes. {sm:3d} s-mes. {k:3d} clés  {u['title'][:55]}")
    print(f"\nRequêtes réseau (hors cache) : {fx.n_net}")
    for w in warnings:
        print("⚠", w)


if __name__ == "__main__":
    main()
