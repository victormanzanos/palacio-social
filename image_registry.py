#!/usr/bin/env python3
"""Registro de identidad de imagen de @palaciodemanzanos.

Regla permanente de Victor (17-sep-2026): NINGUNA foto se repite en un post ni
en una story durante al menos 360 dias. La identidad es la FOTO, no el nombre
del fichero de la tarjeta: `14-sauna.jpg` (post) y `02-st-sauna.jpg` (story)
son ficheros distintos hechos de la MISMA fotografia, y el motor las publicaba
como si fueran contenido diferente.

Dos ficheros de estado:
  .image_index.json      tarjeta -> {photo, phash, src}   (quien es cada tarjeta)
  .published_images.json historial [{date, kind, card, photo, phash}]

WHY phash y no md5: la misma foto entra en el pipeline a dos tamanos (post
1080x1350, story 1080x1920) y a veces existe dos veces en disco reescalada
(fotospalacio vs public/images/palacio). El md5 no ve nada de eso; un aHash
16x16 sobre el cuadrado central si. Mismo defecto ya documentado en
[[agolfcars-ig-engine]] (md5 no basta) y [[palacio-ig-identidad-imagen]].
"""
import os
import json
import sys

LOCAL = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(LOCAL, ".image_index.json")
LEDGER_FILE = os.path.join(LOCAL, ".published_images.json")

# Carpetas donde viven las FOTOS fuente (no las tarjetas ya montadas).
SRC_DIRS = [
    "/Users/victor/Code/PalaciodeManzanosweb/fotospalacio",
    "/Users/victor/Code/PalaciodeManzanosweb/public/images/palacio",
    "/Users/victor/Code/PalaciodeManzanosweb/public/images/blog",
    os.path.join(LOCAL, ".pexels_cache"),
]

# Ventana de no-repeticion. 183 publicaciones/ano (1 de cada 2 dias) x 2 fotos
# (post + story) = 366 fotos distintas para cubrir un ano completo.
NO_REPEAT_DAYS = 360
# Distancia de Hamming por debajo de la cual dos aHash de 256 bits son "la misma
# foto". 6 es el umbral ya validado en los motores de agolfcars y habitat: caza
# reescalados y recompresiones sin juntar fotos parecidas pero distintas.
PHASH_NEAR = 6

BITS = 16  # aHash 16x16 = 256 bits

# Tarjetas cuya fuente NO se puede casar por hash y se ha verificado A OJO.
# WHY: un aHash compara cada pixel contra la media de la imagen, asi que en una
# foto de contraste plano (un valle nevado) casi todo el hash es ruido. La
# tarjeta s96 y su blog original son la MISMA foto (comprobado abriendo las dos
# el 17-sep-2026) y aun asi distan 26/31 bits. Sin esta excepcion quedarian
# fuera del indice y, al no tener phash, el guard las dejaria pasar siempre.
OVERRIDES = {
    "posts/s96-navidad-vinedo-nevado.jpg":
        "navidad-familia-rioja-vinedo-nevado-sierra-cantabria.jpg",
    "stories/s96-navidad-vinedo-nevado-story.jpg":
        "navidad-familia-rioja-vinedo-nevado-sierra-cantabria.jpg",
}


# ──────────────────────────────────────────────────────────────────────────
# HASH PERCEPTUAL
# ──────────────────────────────────────────────────────────────────────────
def phash(path, bits=BITS):
    """aHash del cuadrado central de una FOTO fuente.

    WHY el cuadrado central: make_palacio.cover() recorta CENTRADO, asi que el
    centro de la foto sobrevive intacto tanto en el recorte 4:5 del post como en
    el 9:16 de la story. Es la unica region estable entre formatos.
    """
    from PIL import Image
    im = Image.open(path).convert("L")
    w, h = im.size
    half = min(w, h) / 2 * 0.88
    im = im.crop((int(w / 2 - half), int(h / 2 - half),
                  int(w / 2 + half), int(h / 2 + half)))
    im = im.resize((bits, bits), Image.LANCZOS)
    px = list(im.getdata())
    avg = sum(px) / len(px)
    return "".join("1" if p > avg else "0" for p in px)


def hamming(a, b):
    if a is None or b is None or len(a) != len(b):
        return 9999
    return sum(1 for x, y in zip(a, b) if x != y)


def same_photo(a, b, near=PHASH_NEAR):
    return hamming(a, b) <= near


# ──────────────────────────────────────────────────────────────────────────
# INDICE tarjeta -> foto
# ──────────────────────────────────────────────────────────────────────────
def key(card):
    """Clave canonica de una tarjeta.

    WHY: el sistema de ficheros de macOS devuelve los nombres en NFD (la 'ñ' de
    `28-bano-bañera.jpg` va como 'n' + tilde combinante) mientras que CAPTIONS.md
    los trae en NFC. Sin normalizar, esa tarjeta no se encontraba en el indice,
    se quedaba sin phash y el guard la dejaba pasar SIEMPRE: en la simulacion
    salia cada 4 dias, indefinidamente. Un fallo mudo de los de siempre, la
    tarjeta rota y la sana se ven igual.
    """
    import unicodedata
    return unicodedata.normalize("NFC", card)


def load_index():
    try:
        raw = json.load(open(INDEX_FILE, encoding="utf-8"))
    except Exception:
        return {}
    return {key(k): v for k, v in raw.items()}


def save_index(idx):
    idx = {key(k): v for k, v in idx.items()}
    json.dump(idx, open(INDEX_FILE, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


def find_source(name):
    """Ruta absoluta de una foto fuente por nombre de fichero."""
    for d in SRC_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def card_phash(card, idx=None):
    """phash de la foto de una tarjeta ('posts/x.jpg' | 'stories/y.jpg')."""
    idx = idx if idx is not None else load_index()
    e = idx.get(key(card))
    return e.get("phash") if e else None


def card_photo(card, idx=None):
    idx = idx if idx is not None else load_index()
    e = idx.get(key(card))
    return e.get("photo") if e else None


# ──────────────────────────────────────────────────────────────────────────
# LEDGER de publicaciones
# ──────────────────────────────────────────────────────────────────────────
def load_ledger():
    try:
        return json.load(open(LEDGER_FILE, encoding="utf-8"))
    except Exception:
        return []


def record(date, kind, card, idx=None):
    """Anota una publicacion. Se llama JUSTO despues de confirmar el publish,
    igual que save_state: si el proceso muere despues, la foto ya cuenta como
    usada y no puede reaparecer manana."""
    idx = idx if idx is not None else load_index()
    e = idx.get(key(card)) or {}
    rows = load_ledger()
    rows.append({
        "date": str(date),
        "kind": kind,
        "card": card,
        "photo": e.get("photo", "?"),
        "phash": e.get("phash"),
    })
    json.dump(rows, open(LEDGER_FILE, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return rows


def blocked_hashes(today, days=NO_REPEAT_DAYS, rows=None):
    """phashes publicados dentro de la ventana de no-repeticion."""
    import datetime
    rows = rows if rows is not None else load_ledger()
    if isinstance(today, str):
        today = datetime.date.fromisoformat(today)
    cut = today - datetime.timedelta(days=days)
    out = []
    for r in rows:
        try:
            d = datetime.date.fromisoformat(r["date"])
        except Exception:
            continue
        if d >= cut and r.get("phash"):
            out.append((r["phash"], r["date"], r.get("photo", "?"), r.get("card", "?")))
    return out


def is_blocked(ph, blocked, near=PHASH_NEAR):
    """(bloqueada?, motivo). Fail-open solo si la tarjeta no tiene phash conocido."""
    if not ph:
        return False, ""
    for bph, date, photo, card in blocked:
        if hamming(ph, bph) <= near:
            return True, f"misma foto que {card} ({photo}) publicada el {date}"
    return False, ""


# ──────────────────────────────────────────────────────────────────────────
# CONSTRUCCION DEL INDICE
# ──────────────────────────────────────────────────────────────────────────
def build_index(verbose=True):
    """Reconstruye .image_index.json.

    Fuente de verdad, por orden:
      1. BATCH_POSTS / BATCH_STORIES / BATCH_SPECIALS de make_palacio.py, que
         mapean tarjeta -> foto EXPLICITAMENTE (mapeo verificado a ojo el
         31-jul-2026).
      2. Para el resto (tarjetas `s*` del blog y `px*` de Pexels), casar por
         hash simulando el recorte real de cada formato.
    """
    from PIL import Image
    sys.path.insert(0, LOCAL)
    import re

    mk = open(os.path.join(LOCAL, "make_palacio.py"), encoding="utf-8").read()

    def parse_batch(name, story=False, special=False):
        m = re.search(rf"^{name}\s*=\s*\[(.*?)^\]", mk, re.M | re.S)
        out = {}
        if not m:
            return out
        for line in m.group(1).splitlines():
            t = re.findall(r'"([^"]+)"', line)
            if special and len(t) >= 2:
                sub = "stories" if story else "posts"
                suffix = "-story.jpg" if story else ".jpg"
                out[f"{sub}/{t[1]}{suffix}"] = t[0]
            elif not special and len(t) >= 2:
                out[("stories/" if story else "posts/") + t[1]] = t[0]
        return out

    explicit = {}
    explicit.update(parse_batch("BATCH_POSTS"))
    explicit.update(parse_batch("BATCH_STORIES", story=True))
    explicit.update(parse_batch("BATCH_SPECIALS", special=True))
    explicit.update(parse_batch("BATCH_SPECIALS", story=True, special=True))
    explicit.update(OVERRIDES)

    # Firmas de las fuentes, simulando el recorte de cada formato
    def cover(im, w, h):
        s = max(w / im.width, h / im.height)
        nw, nh = int(im.width * s + 1), int(im.height * s + 1)
        im = im.resize((nw, nh), Image.LANCZOS)
        return im.crop(((nw - w) // 2, (nh - h) // 2, (nw - w) // 2 + w, (nh - h) // 2 + h))

    def inner(im, bits=BITS):
        im = im.convert("L")
        w, h = im.size
        im = im.crop((int(w * .10), int(h * .08), int(w * .90), int(h * .82)))
        im = im.resize((bits, bits), Image.LANCZOS)
        px = list(im.getdata())
        avg = sum(px) / len(px)
        return "".join("1" if p > avg else "0" for p in px)

    sources = {}
    for d in SRC_DIRS:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith((".jpg", ".jpeg", ".png")):
                sources.setdefault(fn, os.path.join(d, fn))

    sim = {"posts": {}, "stories": {}}
    src_ph = {}
    for fn, p in sources.items():
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            continue
        sim["posts"][fn] = inner(cover(im, 1080, 1350))
        sim["stories"][fn] = inner(cover(im, 1080, 1920))
        src_ph[fn] = phash(p)

    idx, weak = {}, []
    for sub in ("posts", "stories"):
        d = os.path.join(LOCAL, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            card = f"{sub}/{fn}"
            photo = explicit.get(card)
            how = "make_palacio"
            if not photo:
                s = inner(Image.open(os.path.join(d, fn)))
                best, bd = None, 9999
                for name, ss in sim[sub].items():
                    dd = hamming(s, ss)
                    if dd < bd:
                        best, bd = name, dd
                if best and bd <= 18:
                    photo, how = best, f"phash(d={bd})"
                else:
                    weak.append((card, best, bd))
                    continue
            if photo not in src_ph:
                weak.append((card, photo, "fuente no encontrada"))
                continue
            idx[card] = {"photo": photo, "phash": src_ph[photo],
                         "src": sources[photo], "how": how}
    save_index(idx)
    if verbose:
        print(f"indice: {len(idx)} tarjetas · {len(set(v['photo'] for v in idx.values()))} fotos distintas")
        for w in weak:
            print("  ⚠️  sin fuente:", w)
    return idx, weak


if __name__ == "__main__":
    build_index()
