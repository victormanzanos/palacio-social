#!/usr/bin/env python3
"""Palacio de Manzanos — DAILY ENGINE para @palaciodemanzanos.

Clonado del motor de @manzanoswinesusa con:
- Credenciales propias (PALACIO_IG_ACCESS_TOKEN / PALACIO_IG_ACCOUNT_ID)
- Repo público propio: github.com/victormanzanos/palacio-social
- Captions parseadas de CAPTIONS.md (single source of truth)
- Cadencia en día distinto: Manzanos Wines USA publica los días ordinal%4==0,
  JMC los %4==2; Palacio publica los **%4==1** — nunca coinciden, distribuye
  carga en cuentas IG distintas y reduce huella anti-bot.
- Misma idempotencia (1 publicación/día), jitter, defer, foto real intercalada.

Variables de entorno:
  DRY=1     → preview sin publicar ni enviar email (no necesita credenciales)
  FORCE=1   → salta la guardia de "día de descanso" (publica hoy aunque toque descanso)
"""
import datetime, json, os, random, re, ssl, smtplib, subprocess, time
import urllib.request, urllib.parse, urllib.error
import base64, hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage

# Registro de identidad de imagen (regla de no-repeticion a 360 dias).
# WHY degradado y no fail-closed: si el registro no carga, NO publicar seria peor
# que publicar una repeticion. Se publica, pero el aviso sale en el log y en el
# email para que el watchdog diario lo cante.
try:
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import image_registry as REG
    REG_OK = True
except Exception as _e:                                   # pragma: no cover
    REG, REG_OK = None, False
    print(f"⚠️  REGISTRO DE IMAGEN NO DISPONIBLE ({_e}) — SIN control de repeticiones.")

# ──────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────
LOCAL    = os.path.expanduser("~/palacio-social")
SECRETS  = os.path.expanduser("~/Code/CyberSecurity/scripts/secrets.sh")
STATE    = os.path.join(LOCAL, ".daily_state.json")
CAPTIONS_FILE = os.path.join(LOCAL, "CAPTIONS.md")
RAW      = "https://raw.githubusercontent.com/victormanzanos/palacio-social/main"
BASE     = "https://graph.instagram.com/v23.0"
REPO     = "victormanzanos/palacio-social"
H        = "#PalacioDeManzanos"  # brand hashtag — siempre se mantiene

# Cadencia: 1 día sí, 1 día no (un día de cada 2).
# El motor publica cuando today.toordinal() % PALACIO_CYCLE_DIV == PALACIO_CYCLE_DAY.
# Con DIV=2, DAY=1 publica los días impares de calendario juliano (≈ alterno).
PALACIO_CYCLE_DIV = 2
PALACIO_CYCLE_DAY = 1

# ── DÍAS ESPECIALES DE ESPAÑA ─────────────────────────────────────────────
# En estos días se publica SIEMPRE (aunque toque descanso) un post + story
# especiales con recuadro dorado y logo en oro. Los assets están pregenerados
# con `make_palacio.py batch_special` → posts/sp-<slug>.jpg + stories/sp-<slug>-story.jpg
# (regenerar y push al repo si se añade un día nuevo aquí).
# El post especial NO consume la rotación normal (índices intactos).
SPECIAL_DAYS = {
    (1, 1): ("sp-ano-nuevo", "Año Nuevo",
        "Empezamos el año brindando en Haro. ¡Feliz Año Nuevo! 🥂✨\n"
        "Que este año te traiga salud, buenos vinos y mejores escapadas.\n\n"
        "#FelizAñoNuevo #AñoNuevo #PalacioDeManzanos #Haro #LaRioja #Brindis #Enoturismo"),
    (1, 6): ("sp-reyes", "Día de Reyes",
        "Noche de Reyes en el Palacio 👑✨\n"
        "Que los Reyes Magos te traigan salud, vino y muchos viajes.\n\n"
        "#Reyes #NocheDeReyes #DiaDeReyes #PalacioDeManzanos #Haro #LaRioja #Navidad"),
    (6, 29): ("sp-batalla-vino", "Batalla del Vino de Haro",
        "29 de junio: Haro se viste de blanco y se tiñe de vino. ¡Feliz Batalla del Vino! 🍷\n"
        "La fiesta más famosa de La Rioja se vive a las puertas del Palacio.\n\n"
        "#BatallaDelVino #Haro #SanPedro #PalacioDeManzanos #LaRioja #FiestasDeEspaña #Vino"),
    (7, 25): ("sp-santiago", "Santiago Apóstol",
        "25 de julio, día de Santiago Apóstol, patrón de España. 🇪🇸\n"
        "Feliz día desde Haro, La Rioja.\n\n"
        "#SantiagoApostol #DiaDeSantiago #España #PalacioDeManzanos #Haro #LaRioja"),
    (9, 8): ("sp-virgen-vega", "Virgen de la Vega (patrona de Haro)",
        "8 de septiembre: Haro celebra a su patrona, la Virgen de la Vega. 🎉\n"
        "¡Felices fiestas, jarreros!\n\n"
        "#VirgenDeLaVega #FiestasDeHaro #Haro #PalacioDeManzanos #LaRioja #Jarreros"),
    (10, 12): ("sp-hispanidad", "Fiesta Nacional de España",
        "12 de octubre, Fiesta Nacional de España. 🇪🇸\n"
        "Feliz día desde Haro, capital del Rioja.\n\n"
        "#FiestaNacional #DiaDeLaHispanidad #12DeOctubre #España #PalacioDeManzanos #Haro #LaRioja"),
    (12, 24): ("sp-nochebuena", "Nochebuena",
        "Feliz Nochebuena desde el Palacio de Manzanos. 🎄✨\n"
        "Que esta noche no falte una buena mesa, buena compañía y un buen Rioja.\n\n"
        "#Nochebuena #Navidad #FelizNavidad #PalacioDeManzanos #Haro #LaRioja"),
    (12, 25): ("sp-navidad", "Navidad",
        "¡Feliz Navidad! 🎄\n"
        "Desde Haro, La Rioja, os deseamos unas fiestas llenas de brindis y momentos en familia.\n\n"
        "#FelizNavidad #Navidad #MerryChristmas #PalacioDeManzanos #Haro #LaRioja"),
    (12, 31): ("sp-nochevieja", "Nochevieja",
        "Última noche del año: doce uvas, una copa de Rioja y los mejores deseos. 🥂🍇\n"
        "¡Feliz Nochevieja!\n\n"
        "#Nochevieja #FinDeAño #FelizAñoNuevo #PalacioDeManzanos #Haro #LaRioja #DoceUvas"),
}

# Foto real intercalada — 1 real cada N posts de marca (drop folder)
REAL_EVERY = 3
TDIR     = os.path.join(LOCAL, "tastings")
DONE_DIR = os.path.join(TDIR, "published")
IMG_EXT  = (".jpg", ".jpeg", ".png")

DEFAULT_REAL_CAPTION = (
    "Una postal del Palacio de Manzanos 🏰\n"
    "Reserva tu escapada en el link de la bio.\n\n"
    "#PalacioDeManzanos #PalacioPrivado #Haro #LaRioja #LuxuryRental #EscapadaDeLujo"
)

DRY = os.environ.get("DRY") == "1"

# Credenciales — lazy load para que DRY=1 funcione sin credenciales
TOK  = None
IGID = None
def _secret(n):
    return subprocess.check_output([SECRETS, "get", n]).decode().strip()
def ensure_creds():
    global TOK, IGID
    if TOK is None:
        TOK  = _secret("PALACIO_IG_ACCESS_TOKEN")
        IGID = _secret("PALACIO_IG_ACCOUNT_ID")


# ──────────────────────────────────────────────────────────────────────────
# PARSE CAPTIONS.md → POSTS, STORIES
# ──────────────────────────────────────────────────────────────────────────
def parse_captions(path):
    """Devuelve (palace_posts, surround_posts, stories) leyendo CAPTIONS.md.

    Estructura esperada:
        ## 36 POSTS                 ← posts del palacio
        ## 18 SURROUNDINGS POSTS    ← posts del entorno (intercalados 1 de cada 2)
        ## 12 STORIES               ← stories
    """
    text = open(path, encoding="utf-8").read()
    sections = re.split(r"^## ", text, flags=re.M)
    palace_posts, surround_posts, stories = [], [], []
    for sec in sections:
        head = sec.splitlines()[0].strip().upper() if sec.strip() else ""
        # WHY por patron y no por el numero exacto: las secciones crecen cada
        # semana con el refresh. Un `startswith("12 STORIES")` dejo de casar en
        # cuanto el pool paso de 12 y habria vaciado la rotacion de stories.
        if re.match(r"\d+\s+POSTS\b", head):
            target = palace_posts
        elif "SURROUNDINGS" in head:
            target = surround_posts
        elif re.match(r"\d+\s+STORIES\b", head):
            target = stories
        else:
            continue
        for entry in re.split(r"^### ", sec, flags=re.M)[1:]:
            lines = entry.splitlines()
            if not lines:
                continue
            header = lines[0]
            m = re.search(r"`([^`]+\.jpg)`", header)
            if not m:
                continue
            filename = m.group(1)
            body_lines = []
            for ln in lines[1:]:
                if ln.startswith("##") or ln.startswith("---"):
                    break
                body_lines.append(ln)
            caption = "\n".join(body_lines).strip()
            target.append((filename, caption))
    return palace_posts, surround_posts, stories

PALACE_POSTS, SURROUND_POSTS, STORIES = parse_captions(CAPTIONS_FILE)
STORY_FILES = [fn for fn, _ in STORIES]
assert PALACE_POSTS,    "No se parsearon posts del palacio de CAPTIONS.md"
assert SURROUND_POSTS,  "No se parsearon posts del entorno de CAPTIONS.md"
assert STORIES,         "No se parsearon stories de CAPTIONS.md"


# ──────────────────────────────────────────────────────────────────────────
# STATE
# ──────────────────────────────────────────────────────────────────────────
def state():
    if os.path.exists(STATE):
        s = json.load(open(STATE))
    else:
        s = {}
    # Defaults para campos nuevos
    s.setdefault("post", 0)         # contador total (alternancia palace/entorno)
    s.setdefault("palace_idx", 0)   # índice rotación palacio
    s.setdefault("surround_idx", 0) # índice rotación entorno
    s.setdefault("story", 0)
    s.setdefault("since_real", 0)
    return s
def save_state(s):
    json.dump(s, open(STATE, "w"))



# ──────────────────────────────────────────────────────────────────────────
# GUARD DE IDENTIDAD DE IMAGEN  (regla permanente de Victor, 2026-08-27)
# ──────────────────────────────────────────────────────────────────────────
# El 27-ago-2026 se publico `s19-coste-por-persona.jpg`: un salon con escalera
# de caracol que NO es el Palacio, bajo el sello "PALACIO · MANZANOS · HARO".
# La foto venia de la portada de un articulo del blog (banco de imagenes) y la
# rutina semanal la convirtio en tarjeta de "entorno" sin comprobar de que
# edificio era. La auditoria posterior encontro 16 tarjetas asi.
#
# REGLA: si la tarjeta ensena un espacio DEL ALOJAMIENTO (salon, habitacion,
# bano, cocina, comedor, spa...), la foto tiene que ser DEL PALACIO. De banco o
# del blog solo puede venir el ENTORNO: vinedos, bodegas, calados, Haro, la
# Ruta Norte, la vendimia, gastronomia y paisaje.
#
# Dos redes independientes, las dos FAIL-CLOSED (ante la duda no se publica):
#   1. Lista blanca `entorno_approved.json`: una tarjeta de entorno solo sale si
#      alguien ABRIO la imagen y la aprobo. Lo que no esta listado, no se publica.
#   2. Chequeo del GANCHO de la caption: si la primera linea de una tarjeta de
#      entorno promete un espacio interior del alojamiento, se bloquea aunque
#      este aprobada. Esta 2a red, por si sola, habria parado el post del 27-ago.
# Las 36 tarjetas del pool "palacio" son fotos verificadas del edificio: no
# pasan por la lista blanca y si pueden hablar de sus propios salones.
APPROVED_FILE = os.path.join(LOCAL, "entorno_approved.json")

def load_entorno_approved():
    try:
        return set(json.load(open(APPROVED_FILE, encoding="utf-8"))["approved"])
    except Exception as e:
        # WHY fail-closed: sin lista preferimos repetir palacio (fotos verificadas)
        # antes que publicar una imagen de dueno desconocido con nuestro sello.
        print(f"⚠️  No se pudo leer {APPROVED_FILE} ({e}) — pool de entorno BLOQUEADO.")
        return set()

ENTORNO_APPROVED = load_entorno_approved()

# Espacios propios del alojamiento. Si el GANCHO de una tarjeta de entorno los
# nombra, la imagen deberia ser del Palacio y, por definicion del pool, no lo es.
# El negative lookahead salva "la cocina del norte/riojana/vasca" (el estilo de
# cocina, no la habitacion) — es el unico falso positivo de las 95 captions.
PROPERTY_SPACE_RE = re.compile(
    r"\b(sal[oó]n(?:es)?|habitaci[oó]n(?:es)?|dormitorio(?:s)?|suite(?:s)?|"
    r"ba[nñ]o(?:s)?|aseo(?:s)?|cocina(?:s)?(?!\s+(?:del|de\s+la|riojana|vasca|"
    r"espa[nñ]ola|tradicional|de\s+autor|norte[nñ]a))|comedor(?:es)?|sauna|"
    r"jacuzzi|spa|gimnasio|vinoteca|billar|sala\s+de\s+cine|recibidor|"
    r"[aá]tico|piano\s+de\s+cola)\b", re.I)

def entorno_card_ok(filename, caption):
    """(ok, motivo) para una tarjeta del pool de ENTORNO. Fail-closed."""
    if filename not in ENTORNO_APPROVED:
        return False, "imagen no verificada como entorno (no esta en entorno_approved.json)"
    hook = caption.strip().splitlines()[0] if caption.strip() else ""
    m = PROPERTY_SPACE_RE.search(hook)
    if m:
        return False, (f"el gancho promete un espacio del alojamiento "
                       f"(\"{m.group(0)}\") sobre una imagen que no es del Palacio")
    return True, ""


# ──────────────────────────────────────────────────────────────────────────
# GUARD DE NO-REPETICION  (regla permanente de Victor, 2026-09-17)
# ──────────────────────────────────────────────────────────────────────────
# "No podemos repetir las mismas imagenes en diferentes post o stories durante
# 360 dias al menos."
#
# Hasta hoy el motor lo incumplia POR DISENO y nada lo delataba: la rotacion de
# stories tenia 18 tarjetas (ciclo de 36 dias), el pool de palacio 36 (ciclo de
# 144 dias), y ademas las 12 stories originales estaban hechas de las MISMAS
# fotos que los posts 01-36, asi que un post y una story podian enseñar la misma
# foto con dias de diferencia. Medido sobre el log: 77 publicaciones con solo
# 48 fotos distintas, 29 repeticiones en 87 dias.
#
# La identidad es la FOTO (phash de la fuente), nunca el nombre de la tarjeta.
def _blocked_today(today):
    """phashes vetados hoy por haberse publicado dentro de la ventana."""
    if not REG_OK:
        return []
    try:
        return REG.blocked_hashes(today)
    except Exception as e:
        print(f"⚠️  No se pudo leer el historial de imagenes ({e}) — sin control de repeticiones.")
        return []


def _fresh(card, blocked, idx, extra_ph=()):
    """(ok, motivo) — la foto de `card` no se ha publicado en la ventana."""
    if not REG_OK:
        return True, ""
    ph = (idx.get(REG.key(card)) or {}).get("phash")
    if not ph:
        print(f"⚠️  {card} no esta en el indice de imagenes — publicaria sin control de repeticion.")
        # Sin phash no se puede juzgar. Se deja pasar y se avisa: es preferible
        # publicar a bloquear la rotacion entera por una tarjeta sin indexar.
        return True, "(sin phash en el indice)"
    for x in extra_ph:
        if REG.same_photo(ph, x):
            return False, "misma foto que el post de hoy"
    bad, why = REG.is_blocked(ph, blocked)
    return (not bad), why


def entorno_story_ok(filename, caption):
    """Mismo guard de identidad que los posts, aplicado a una STORY.

    Una story `sNN-slug-story.jpg` es la version 9:16 del post `sNN-slug.jpg`:
    misma foto, mismo origen (blog/banco), asi que hereda su aprobacion. Las
    stories del palacio (`NN-st-*.jpg`) y las de Pexels (`px-st-*`) son fotos ya
    verificadas y no pasan por la lista blanca.
    """
    # Las stories del propio Palacio se llaman `NN-st-*.jpg` y salen de fotos
    # verificadas del edificio: no pasan por la lista blanca.
    if re.match(r"\d+-st-", filename):
        return True, ""
    # El resto viene de blog o banco de imagenes. Hereda la aprobacion de su post
    # gemelo si lo tiene, y si no, tiene que estar aprobada ella misma.
    # WHY: hasta el 17-sep el chequeo solo miraba `s\d+-.*-story.jpg`, asi que una
    # story de banco con otro nombre (px-*) entraba sin que nadie hubiera mirado
    # la imagen. La puerta de las stories era mas ancha que la de los posts.
    if filename.endswith("-story.jpg"):
        twin = filename[:-len("-story.jpg")] + ".jpg"
        if twin in ENTORNO_APPROVED:
            return entorno_card_ok(twin, caption)
    return entorno_card_ok(filename, caption)


def pick_next_post(s, blocked=(), idx=None):
    """Alterna: post par → palacio, post impar → entorno.

    Devuelve (filename, caption, pool_name, idx). `idx` es el indice REALMENTE
    usado dentro de su pool: al saltarse tarjetas bloqueadas por el guard de
    identidad o por el de no-repeticion, el indice avanza mas de uno, asi que
    quien publique debe guardar `idx + 1` — con `+= 1` se volveria a proponer la
    misma tarjeta cada dia.
    """
    idx = idx if idx is not None else (REG.load_index() if REG_OK else {})

    def walk(pool, start, name, check_entorno):
        n = len(pool)
        for step in range(n):
            i = (start + step) % n
            fn, cap = pool[i]
            if check_entorno:
                ok, why = entorno_card_ok(fn, cap)
                if not ok:
                    print(f"⛔ GUARD: salto {fn} — {why}")
                    continue
            ok, why = _fresh(f"posts/{fn}", blocked, idx)
            if not ok:
                print(f"🔁 NO-REPEAT: salto {fn} — {why}")
                continue
            return fn, cap, name, i
        return None

    if s["post"] % 2 == 0:
        r = walk(PALACE_POSTS, s["palace_idx"] % len(PALACE_POSTS), "palace", False)
        if r:
            return r
        r = walk(SURROUND_POSTS, s["surround_idx"] % len(SURROUND_POSTS), "surround", True)
        if r:
            print("⚠️  Sin fotos frescas de palacio — publico entorno.")
            return r
    else:
        r = walk(SURROUND_POSTS, s["surround_idx"] % len(SURROUND_POSTS), "surround", True)
        if r:
            return r
        r = walk(PALACE_POSTS, s["palace_idx"] % len(PALACE_POSTS), "palace", False)
        if r:
            print("⚠️  Ninguna tarjeta de entorno disponible — publico palacio.")
            return r

    # Nada fresco en ningun pool: se publica lo mas antiguo posible, pero se
    # canta. WHY no callar: quedarse sin baraja es la senal de que hay que traer
    # fotos nuevas, y si el motor lo resuelve en silencio nadie se entera.
    print("⚠️  BARAJA AGOTADA: todas las fotos se han publicado en los ultimos "
          f"{REG.NO_REPEAT_DAYS if REG_OK else '?'} dias. Hacen falta imagenes nuevas.")
    if s["post"] % 2 == 0:
        i = s["palace_idx"] % len(PALACE_POSTS)
        fn, cap = PALACE_POSTS[i]
        return fn, cap, "palace", i
    n = len(SURROUND_POSTS)
    start = s["surround_idx"] % n
    for step in range(n):
        i = (start + step) % n
        fn, cap = SURROUND_POSTS[i]
        if entorno_card_ok(fn, cap)[0]:
            return fn, cap, "surround", i
    i = s["palace_idx"] % len(PALACE_POSTS)
    fn, cap = PALACE_POSTS[i]
    return fn, cap, "palace", i


def pick_next_story(s, blocked=(), idx=None, post_card=None):
    """Story fresca. Excluye ademas la foto del POST de hoy.

    Devuelve (filename, idx_usado). Igual que en los posts, quien publique
    guarda `idx + 1`, nunca `s["story"] + 1`.
    """
    idx = idx if idx is not None else (REG.load_index() if REG_OK else {})
    extra = []
    if REG_OK and post_card:
        ph = (idx.get(REG.key(post_card)) or {}).get("phash")
        if ph:
            extra.append(ph)
    n = len(STORY_FILES)
    start = s["story"] % n
    caps = dict(STORIES)
    for step in range(n):
        i = (start + step) % n
        fn = STORY_FILES[i]
        # Las stories de entorno (`sNN-...-story.jpg`) salen de imagenes de banco
        # o del blog, igual que sus posts gemelos, asi que pasan por el MISMO
        # guard de identidad: lista blanca + chequeo del gancho. Sin esto, una
        # imagen bloqueada por no ser el Palacio se colaba por la puerta de las
        # stories (las 16 bloqueadas el 27-ago tienen su gemela en stories/).
        ok, why = entorno_story_ok(fn, caps.get(fn, ""))
        if not ok:
            print(f"⛔ GUARD story: salto {fn} — {why}")
            continue
        ok, why = _fresh(f"stories/{fn}", blocked, idx, extra)
        if ok:
            return fn, i
        print(f"🔁 NO-REPEAT story: salto {fn} — {why}")
    print("⚠️  BARAJA DE STORIES AGOTADA — hacen falta imagenes nuevas.")
    return STORY_FILES[start], start


# ──────────────────────────────────────────────────────────────────────────
# FOTO REAL intercalada (drop folder)
# ──────────────────────────────────────────────────────────────────────────
def real_collect():
    """Lista ordenada de (path, caption, is_story) para fotos reales en tastings/."""
    if not os.path.isdir(TDIR):
        return []
    out = []
    for name in sorted(os.listdir(TDIR)):
        path = os.path.join(TDIR, name)
        if not os.path.isfile(path):
            continue
        base, ext = os.path.splitext(name)
        if ext.lower() not in IMG_EXT:
            continue
        cap_file = os.path.join(TDIR, base + ".txt")
        cap = open(cap_file, encoding="utf-8").read().strip() if os.path.exists(cap_file) else DEFAULT_REAL_CAPTION
        out.append((path, cap, "-story" in base.lower()))
    return out

def gh_upload(local_path, remote_name):
    """PUT al repo público (vía gh CLI) y devuelve la URL raw."""
    with open(local_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()
    remote_path = f"tastings/{remote_name}"
    sha = None
    probe = subprocess.run(["gh", "api", f"/repos/{REPO}/contents/{remote_path}"],
                           capture_output=True, text=True)
    if probe.returncode == 0:
        try:    sha = json.loads(probe.stdout).get("sha")
        except: sha = None
        # WHY: el cuerpo va por STDIN (--input -), NUNCA como argumento -f content=<b64>.
    # Incidencia 2026-08-20 (@manzanosenterprises): una foto de 899 KB da un base64 de
    # ~1,20 MB y revienta el ARG_MAX de macOS (1.048.576 B) con "[Errno 7] Argument list
    # too long". Toda foto real de mas de ~780 KB fallaba SIEMPRE y caia al post de marca,
    # en silencio. Por stdin no hay limite de tamano.
    body = {"message": f"Add tasting photo {remote_name}", "content": content_b64}
    if sha: body["sha"] = sha
    args = ["gh", "api", "--method", "PUT", f"/repos/{REPO}/contents/{remote_path}",
            "--input", "-"]
    r = subprocess.run(args, input=json.dumps(body), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh upload failed: {r.stderr.strip()[:300]}")
    return f"{RAW}/{remote_path}"

def archive_real(path):
    os.makedirs(DONE_DIR, exist_ok=True)
    name = os.path.basename(path)
    os.rename(path, os.path.join(DONE_DIR, name))
    cap_file = os.path.join(TDIR, os.path.splitext(name)[0] + ".txt")
    if os.path.exists(cap_file):
        os.rename(cap_file, os.path.join(DONE_DIR, os.path.basename(cap_file)))


# ──────────────────────────────────────────────────────────────────────────
# INSTAGRAM GRAPH API
# ──────────────────────────────────────────────────────────────────────────
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
def api(path, params, method="POST"):
    data = urllib.parse.urlencode(params).encode()
    hdr  = {"User-Agent": UA}
    if method == "GET":
        req = urllib.request.Request(f"{BASE}/{path}?{data.decode()}", headers=hdr)
    else:
        req = urllib.request.Request(f"{BASE}/{path}", data=data, method="POST", headers=hdr)
    try:
        with urllib.request.urlopen(req) as r: return json.load(r)
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "body": e.read().decode()}

def wait_ready(cid):
    for _ in range(20):
        st = api(cid, {"fields": "status_code", "access_token": TOK}, "GET").get("status_code")
        if st in ("FINISHED", "ERROR", "EXPIRED"): return st
        time.sleep(4)
    return "TIMEOUT"

def publish_image(url, caption=None, story=False):
    ensure_creds()
    p = {"image_url": url, "access_token": TOK}
    if story:   p["media_type"] = "STORIES"
    if caption: p["caption"]    = caption
    c = api(f"{IGID}/media", p); cid = c.get("id")
    if not cid: return {"error": c}
    if wait_ready(cid) != "FINISHED": return {"error": "container not ready"}
    r = api(f"{IGID}/media_publish", {"creation_id": cid, "access_token": TOK})
    mid = r.get("id")
    if not mid: return {"error": r}
    return api(mid, {"fields": "permalink", "access_token": TOK}, "GET")


# ──────────────────────────────────────────────────────────────────────────
# EMAIL RESUMEN
# ──────────────────────────────────────────────────────────────────────────
def email_summary(html, post_path, story_path, subject):
    pw = _secret("VICTORIA_STERLING_EMAIL_PASSWORD")
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"]    = "victoriasterling@manzanos.eu"
    msg["To"]      = "victor@manzanos.com"
    msg.attach(MIMEText(html, "html", "utf-8"))
    for cid, path in (("postimg", post_path), ("storyimg", story_path)):
        try:
            with open(path, "rb") as f: img = MIMEImage(f.read())
            img.add_header("Content-ID", f"<{cid}>")
            img.add_header("Content-Disposition", "inline", filename=os.path.basename(path))
            msg.attach(img)
        except Exception as e: print("attach failed", path, e)
    with smtplib.SMTP_SSL("manzanos-eu.correoseguro.dinaserver.com", 465,
                          context=ssl.create_default_context()) as srv:
        srv.login("victoriasterling@manzanos.eu", pw)
        srv.send_message(msg)


# ──────────────────────────────────────────────────────────────────────────
# CAPTION ROTATION (anti-spam hashtags)
# ──────────────────────────────────────────────────────────────────────────
def rotate_caption(cap):
    """Mantiene cuerpo verbatim + brand tag, baraja el resto, cuenta variable.
    Evita que Meta detecte el mismo bloque de 8-10 hashtags fijos cada día."""
    body, tags = [], []
    for ln in cap.split("\n"):
        toks = ln.split()
        if toks and all(t.startswith("#") for t in toks):
            tags.extend(toks)
        else:
            body.append(ln)
    if not tags:
        return cap
    brand = [t for t in tags if t.lower() == H.lower()]
    rest  = [t for t in tags if t.lower() != H.lower()]
    random.shuffle(rest)
    k = min(len(rest), random.randint(4, 8))  # 5–9 totales — natural, nunca idéntico
    chosen = brand + rest[:k]
    random.shuffle(chosen)
    return "\n".join(body).rstrip() + "\n" + " ".join(chosen)


# ──────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────
def main():
    s = state()

    # ── ¿Hoy es día especial de España? (SPECIAL_TEST=MM-DD para probar) ──
    if os.environ.get("SPECIAL_TEST"):
        m, d = (int(x) for x in os.environ["SPECIAL_TEST"].split("-"))
        special = SPECIAL_DAYS.get((m, d))
    else:
        _t = datetime.date.today()
        special = SPECIAL_DAYS.get((_t.month, _t.day))

    if special:
        slug, sp_title, sp_cap = special
        do_real, real_path, real_cap = False, None, None
        pf, sf, pool = f"{slug}.jpg", f"{slug}-story.jpg", "special"
        pick_idx = story_idx = None
        cap = rotate_caption(sp_cap)
        post_url  = f"{RAW}/posts/{pf}"
        story_url = f"{RAW}/stories/{sf}"
        print(f"NEXT = DÍA ESPECIAL 🇪🇸 {sp_title}: {pf}\nSTORY: {sf}\n--- CAPTION ---\n{cap}\n---")
    else:
        real_items = real_collect()
        do_real    = bool(real_items) and s.get("since_real", 0) >= REAL_EVERY
        real_path  = real_items[0][0] if real_items else None
        real_cap   = real_items[0][1] if real_items else None

        _today = str(datetime.date.today())
        _idx = REG.load_index() if REG_OK else {}
        _blocked = _blocked_today(_today)
        pf, cap, pool, pick_idx = pick_next_post(s, _blocked, _idx)
        cap = rotate_caption(cap)
        sf, story_idx = pick_next_story(s, _blocked, _idx, post_card=f"posts/{pf}")
        post_url  = f"{RAW}/posts/{pf}"
        story_url = f"{RAW}/stories/{sf}"

        if do_real:
            print(f"NEXT = REAL PHOTO: {os.path.basename(real_path)}  (since_real={s.get('since_real',0)} ≥ {REAL_EVERY})")
            print(f"--- CAPTION ---\n{real_cap}\n---  (story: {sf})")
        else:
            print(f"NEXT = BRANDED POST [{pool}]: {pf}\nSTORY: {sf}\n--- CAPTION ---\n{cap}\n---  (real en {REAL_EVERY - s.get('since_real',0)} posts)")

    if DRY:
        print("DRY RUN — nada publicado.")
        return

    today = str(datetime.date.today())
    # Guardia "un día sí, un día no": publica cuando ordinal%DIV==DAY.
    # Los días ESPECIALES se publican SIEMPRE — se saltan la guardia de descanso.
    if not special and os.environ.get("FORCE") != "1" and datetime.date.today().toordinal() % PALACIO_CYCLE_DIV != PALACIO_CYCLE_DAY:
        print(f"Día de descanso ({today}) — Palacio publica cuando ordinal%{PALACIO_CYCLE_DIV}=={PALACIO_CYCLE_DAY}.")
        return
    if s.get("last_date") == today:
        print(f"Ya se publicó hoy ({today}) — nada que hacer.")
        return
    # Defer aleatorio si es temprano (rompe patrón horario).
    # WHY: en día especial NO se aplaza — la efeméride debe salir sí o sí.
    if not special and datetime.datetime.now().hour < 14 and random.random() < 0.40:
        print("Aplazo a una franja posterior hoy (rompe patrón horario).")
        return
    time.sleep(random.randint(30, 480))  # jitter

    # ── Publicar POST ─────────────────────────────────────────────────────
    is_real = False
    if do_real:
        try:
            h = hashlib.sha1(open(real_path, "rb").read()).hexdigest()[:8]
            base, ext = os.path.splitext(os.path.basename(real_path))
            url = gh_upload(real_path, f"{base}-{h}{ext.lower()}")
            time.sleep(5)  # CDN catch-up
            pr = publish_image(url, caption=real_cap)
            if pr.get("permalink"):
                is_real = True; cap = real_cap; post_url = url
            else:
                print("Foto real falló, fallback a marca:", json.dumps(pr)[:200])
                pr = publish_image(post_url, caption=cap)
        except Exception as e:
            print("EXCEPCIÓN foto real, fallback a marca:", e)
            pr = publish_image(post_url, caption=cap)
    else:
        pr = publish_image(post_url, caption=cap)

    time.sleep(random.randint(20, 120))  # gap humano antes del story
    sr = publish_image(story_url, story=True)

    post_ok  = bool(pr.get("permalink"))
    story_ok = bool(sr.get("permalink") or sr.get("id"))
    if post_ok:
        s["last_date"] = today
        if is_real:
            archive_real(real_path)
            s["since_real"] = 0
        elif pool == "special":
            pass  # WHY: el post especial no consume la rotación normal ni cuenta para la foto real
        else:
            # Avanzar al SIGUIENTE del indice realmente publicado (no += 1: el
            # guard de identidad puede haber saltado tarjetas por el camino).
            if pool == "palace":
                s["palace_idx"] = pick_idx + 1
            else:
                s["surround_idx"] = pick_idx + 1
            s["post"] += 1
            s["since_real"] = s.get("since_real", 0) + 1
    if story_ok and pool != "special":
        # Igual que en los posts: al saltar tarjetas repetidas el indice avanza
        # mas de uno, asi que se guarda el REALMENTE usado + 1.
        s["story"] = (story_idx + 1) if story_idx is not None else s["story"] + 1
    save_state(s)

    # Historial de imagenes — se anota JUSTO tras confirmar la publicacion, como
    # save_state: si algo posterior falla, la foto ya cuenta como usada.
    if REG_OK:
        try:
            if post_ok and not is_real:
                REG.record(today, "post", f"posts/{pf}")
            if story_ok:
                REG.record(today, "story", f"stories/{sf}")
        except Exception as e:
            print(f"⚠️  No se pudo anotar el historial de imagenes: {e}")

    plink = pr.get("permalink") or ("ERROR: " + json.dumps(pr)[:220])
    sok   = "publicada ✅" if story_ok else ("ERROR: " + json.dumps(sr)[:220])
    print("post:", plink, "(real)" if is_real else "(marca)")
    print("story:", sok)

    subj = ("📲 Instagram diario — Palacio de Manzanos"
            if post_ok else
            "⚠️ FALLO al publicar — Instagram Palacio (revisar)")
    post_path  = real_path if is_real else os.path.join(LOCAL, "posts", pf)
    story_path = os.path.join(LOCAL, "stories", sf)
    if is_real:
        kind = "Foto real (drop folder)"
    elif pool == "special":
        kind = f"🇪🇸 Día especial — {sp_title}"
    elif pool == "palace":
        kind = f"Post Palacio {s['palace_idx']}/{len(PALACE_POSTS)}"
    else:
        kind = f"Post Entorno {s['surround_idx']}/{len(SURROUND_POSTS)}"
    email_summary(
        f"<p>Publicado hoy en <b>@palaciodemanzanos</b> · <b>{kind}</b>:</p>"
        f"<p>📸 <b>Post:</b> <a href='{plink}'>{plink}</a><br>📱 <b>Story:</b> {sok}</p>"
        f"<table cellpadding='6'><tr>"
        f"<td valign='top' align='center'><div style='color:#888;font-size:11px;letter-spacing:1px'>POST</div>"
        f"<img src='cid:postimg' width='300' style='border-radius:10px;border:1px solid #ddd'></td>"
        f"<td valign='top' align='center'><div style='color:#888;font-size:11px;letter-spacing:1px'>STORY</div>"
        f"<img src='cid:storyimg' width='210' style='border-radius:10px;border:1px solid #ddd'></td>"
        f"</tr></table>"
        f"<p style='color:#888;font-size:12px'>Caption:</p>"
        f"<pre style='white-space:pre-wrap;color:#555;font-size:12px'>{cap}</pre>"
        f"<p style='color:#aaa;font-size:11px'>Rotación automática · 1 foto real cada {REAL_EVERY} posts de marca.</p>",
        post_path, story_path, subject=subj
    )



# ── ERP SOCIAL HUB (agolfcars.com/erp → vista Social) ─────────────────────
# El equipo puede BLOQUEAR tarjetas o CORREGIR captions desde el ERP; este motor
# consulta esos controles justo antes de publicar. Fail-open: sin red, sin
# secreto o con respuesta rara → la rotación sigue intacta. (2026-08-04)
def _hub_controls():
    import os as _os, json as _json, subprocess as _sp, urllib.request as _ur, urllib.parse as _up
    try:
        sec = _sp.check_output([_os.path.expanduser("~/Code/CyberSecurity/scripts/secrets.sh"),
                                "get", "AGC_SOCIAL_SYNC_SECRET"], timeout=15).decode().strip()
        if not sec:
            return set(), {}
        q = _up.urlencode({"handle": "palaciodemanzanos", "secret": sec})
        req = _ur.Request("https://agolfcars.com/api/social-sync.php?" + q,
                          headers={"User-Agent": "Mozilla/5.0 (social-engine)"})
        with _ur.urlopen(req, timeout=8) as r:
            d = _json.load(r)
        ov = d.get("overrides") or {}
        return set(d.get("blocked") or []), (ov if isinstance(ov, dict) else {})
    except Exception:
        return set(), {}

_HUB_BLOCKED, _HUB_OVERRIDES = (set(), {}) if os.environ.get("DRY") == "1" else _hub_controls()
if _HUB_BLOCKED or _HUB_OVERRIDES:
    def _hub_tuples(lst):
        kept = [(f, _HUB_OVERRIDES.get(f, c)) for f, c in lst if f not in _HUB_BLOCKED]
        return kept or lst  # nunca vaciar una baraja entera
    PALACE_POSTS[:] = _hub_tuples(PALACE_POSTS)
    SURROUND_POSTS[:] = _hub_tuples(SURROUND_POSTS)
    STORIES[:] = _hub_tuples(STORIES)
    STORY_FILES[:] = [fn for fn, _ in STORIES]

if __name__ == "__main__":
    main()
