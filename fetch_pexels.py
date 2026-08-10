#!/usr/bin/env python3
"""Palacio de Manzanos — Pexels image fetcher for posts & stories.

Trae fotografía profesional de Pexels (viñedos, barricas, vino, uvas,
gastronomía, costa vasca…), le aplica el MISMO marco dorado del Palacio
(reutiliza make_palacio.make_post) y la guarda lista para publicar.

⚠️ REGLA DE PROVENANCE (Constitución Art. I): Pexels es SOLO para imágenes
   de ATMÓSFERA/ENTORNO genéricas y verdaderas (un viñedo ilustra La Rioja,
   una copa ilustra el vino). NUNCA se usa para representar el propio Palacio
   ni para afirmar que una foto de stock ES un lugar concreto real. Las fotos
   del palacio y sus habitaciones siguen siendo SIEMPRE reales.

Uso:
    python3 fetch_pexels.py post  px-vinedos-sierra "vineyard mountains sunset"
    python3 fetch_pexels.py story px-st-copa        "red wine glass"
    python3 fetch_pexels.py batch          # procesa THEME_BANK (posts + stories)
    python3 fetch_pexels.py batch --push   # además: git add/commit/push + verifica raw URLs

Requisitos: PEXELS_API_KEY en el Keychain vault (secrets.sh).
"""
import os, sys, json, subprocess, urllib.request, urllib.parse, urllib.error, time

LOCAL   = os.path.expanduser("~/palacio-social")
SECRETS = os.path.expanduser("~/Code/CyberSecurity/scripts/secrets.sh")
CACHE   = os.path.join(LOCAL, ".pexels_cache")          # descargas crudas (git-ignored)
USED    = os.path.join(LOCAL, ".pexels_used.json")      # IDs ya usados → sin repetición
CREDITS = os.path.join(LOCAL, "pexels_credits.json")    # cortesía: fotógrafo por slug
REPO    = "victormanzanos/palacio-social"
RAW     = "https://raw.githubusercontent.com/victormanzanos/palacio-social/main"

sys.path.insert(0, LOCAL)
import make_palacio  # reutiliza el pipeline de marco dorado (make_post)

# 200 req/hora en el plan free de Pexels; sobra de largo para un batch.
PER_PAGE = 30          # candidatos por búsqueda antes de elegir el mejor no usado
MIN_BYTES = 40_000     # una descarga válida pesa mucho más; menos = error/placeholder
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


# ──────────────────────────────────────────────────────────────────────────
# THEME BANK — atmósfera genérica y verdadera (sin afirmar lugares concretos)
# Cada entrada: (slug, query_pexels, caption). El slug es el nombre de archivo.
# Los posts se añaden al pool SURROUNDINGS; las stories al pool STORIES.
# ──────────────────────────────────────────────────────────────────────────
H = "#PalacioDeManzanos"

POST_THEMES = [
    ("px-vinedos-sierra", "vineyard mountains sunset",
     "Viñedos hasta donde alcanza la vista, con la Sierra de Cantabria al fondo. 🍇\n"
     "El paisaje que rodea tu escapada al Palacio, en pleno corazón de Rioja.\n"
     f"{H} #LaRioja #Rioja #Vinedos #WineCountry #EnoturismoLujo #VisitSpain #Paisaje"),
    ("px-barricas", "oak wine barrels cellar",
     "Barricas de roble envejeciendo en silencio. 🛢️\n"
     "La paciencia que hay detrás de cada Gran Reserva de Rioja.\n"
     f"{H} #Barricas #Rioja #BodegasDeRioja #RobleFrances #EnoturismoLujo #VinoDeRioja #WineLovers"),
    ("px-copa-tinto", "red wine glass close up",
     "Una copa de Rioja al final del día. 🍷\n"
     "El mejor final para una jornada de viñedos y calados.\n"
     f"{H} #VinoDeRioja #Rioja #WineLovers #CopaDeVino #EnoturismoLujo #TintoDeRioja #LaRioja"),
    ("px-uvas-vendimia", "wine grapes harvest hands",
     "Tempranillo recién cortado. 🍇\n"
     "Septiembre y octubre son vendimia en Rioja: te organizamos la experiencia desde el Palacio.\n"
     f"{H} #Vendimia #Tempranillo #Rioja #VendimiaRioja #Uvas #Otono #EnoturismoLujo"),
    ("px-atardecer-vinedo", "vineyard golden hour sunset rows",
     "La hora dorada sobre el viñedo. ✨\n"
     "Atardeceres que solo se entienden estando aquí.\n"
     f"{H} #LaRioja #Vinedos #GoldenHour #WineCountry #Rioja #Atardecer #EnoturismoLujo"),
    ("px-botellas-calado", "wine bottles aging cellar rows",
     "Añadas durmiendo en la penumbra del calado. 🍾\n"
     "Décadas de historia embotelladas, a pocos minutos del Palacio.\n"
     f"{H} #Calado #Rioja #GranReserva #BodegasDeRioja #VinoDeRioja #EnoturismoLujo #WineCellar"),
    ("px-brindis", "friends wine toast dinner table",
     "El brindis siempre es mejor en buena compañía. 🥂\n"
     "Reúne a los tuyos en un palacio para vosotros solos.\n"
     f"{H} #Brindis #Rioja #Celebracion #EscapadaDeLujo #PalacioPrivado #WineLovers #LaRioja"),
    ("px-gastronomia", "spanish tapas pintxos table",
     "La cocina del norte: producto, brasa y tradición. 🍤\n"
     "De la ruta de tapas de Haro a los pintxos de San Sebastián.\n"
     f"{H} #GastronomiaRioja #Tapas #Pintxos #FoodieSpain #NorteDeEspana #LaRioja #VisitSpain"),
    ("px-costa-vasca", "basque coast beach cliffs",
     "La costa vasca, a hora y media del Palacio. 🌊\n"
     "Playa por la mañana, pintxos al mediodía y de vuelta a Rioja para cenar.\n"
     f"{H} #PaisVasco #CostaVasca #SanSebastian #NorteDeEspana #VisitSpain #LuxuryTravel #Escapada"),
    ("px-mesa-vino", "rustic table wine bottle bread",
     "Mesa puesta, botella abierta, sin prisa. 🍷\n"
     "El plan perfecto en un palacio que es solo tuyo.\n"
     f"{H} #Rioja #VinoDeRioja #SobremesA #EscapadaDeLujo #PalacioPrivado #EnoturismoLujo #LaRioja"),
    ("px-vinedo-verano", "green vineyard summer rows",
     "Verano en el viñedo: hileras verdes hasta el horizonte. ☀️\n"
     "Reserva tu palacio antes de que se acabe la temporada.\n"
     f"{H} #Rioja #LaRioja #Vinedos #Verano #WineCountry #EnoturismoLujo #VisitRioja"),
    ("px-cata", "wine tasting swirl glass sommelier",
     "El arte de la cata. 🍷\n"
     "Catas privadas en bodegas centenarias, organizadas desde el Palacio.\n"
     f"{H} #CataDeVino #Rioja #EnoturismoLujo #WineTasting #VinoDeRioja #WineLovers #LaRioja"),
]

STORY_THEMES = [
    ("px-st-vinedo",    "vineyard mountains sunset",
     "Viñedos de Rioja 🍇\nTu paisaje esta semana.\n" + H),
    ("px-st-copa",      "red wine glass close up",
     "Una copa de Rioja 🍷\nReserva en la bio.\n" + H),
    ("px-st-barricas",  "oak wine barrels cellar",
     "Barricas de roble 🛢️\nCatas privadas desde el Palacio.\n" + H),
    ("px-st-uvas",      "wine grapes harvest hands",
     "Vendimia en Rioja 🍇\nTe organizamos la experiencia.\n" + H),
    ("px-st-atardecer", "vineyard golden hour sunset rows",
     "La hora dorada ✨\nAtardeceres de La Rioja.\n" + H),
    ("px-st-costa",     "basque coast beach cliffs",
     "Costa vasca 🌊\nA 1 h 40 del Palacio.\n" + H),
]


# ──────────────────────────────────────────────────────────────────────────
def _secret(n):
    return subprocess.check_output([SECRETS, "get", n]).decode().strip()

def _load_used():
    if os.path.exists(USED):
        try: return json.load(open(USED))
        except Exception: return {}
    return {}

def _save_used(u):
    json.dump(u, open(USED, "w"), indent=0)

def _load_credits():
    if os.path.exists(CREDITS):
        try: return json.load(open(CREDITS))
        except Exception: return {}
    return {}

def _save_credits(c):
    json.dump(c, open(CREDITS, "w"), indent=2, ensure_ascii=False)


def pexels_search(query, key, page=1):
    q = urllib.parse.urlencode({
        "query": query, "orientation": "portrait",
        "per_page": PER_PAGE, "size": "large", "page": page,
    })
    req = urllib.request.Request(
        f"https://api.pexels.com/v1/search?{q}",
        headers={"Authorization": key, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def pick_photo(query, key, used_ids):
    """Devuelve el mejor candidato (mayor resolución) aún NO usado, o None."""
    for page in (1, 2, 3):
        try:
            data = pexels_search(query, key, page=page)
        except urllib.error.HTTPError as e:
            print(f"    Pexels HTTP {e.code}: {e.read().decode()[:160]}")
            return None
        photos = [p for p in data.get("photos", []) if str(p["id"]) not in used_ids]
        # Preferimos verticales de alta resolución (mejor para 4:5 y 9:16)
        photos.sort(key=lambda p: p["width"] * p["height"], reverse=True)
        if photos:
            return photos[0]
        if len(data.get("photos", [])) < PER_PAGE:
            break  # no hay más páginas
    return None


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        blob = r.read()
    if len(blob) < MIN_BYTES:
        raise RuntimeError(f"descarga demasiado pequeña ({len(blob)} bytes) — posible error")
    with open(dest, "wb") as f:
        f.write(blob)
    return len(blob)


def fetch_one(slug, query, story, key, used, credits):
    if slug in used:
        # ya hay una foto asignada a este slug → no volver a gastar API
        print(f"  = {slug}: ya generado (id {used[slug]}), se conserva")
        return None
    photo = pick_photo(query, key, set(str(v) for v in used.values()))
    if not photo:
        print(f"  ⚠ {slug}: sin resultados nuevos para '{query}'")
        return None
    os.makedirs(CACHE, exist_ok=True)
    raw_path = os.path.join(CACHE, f"{slug}.jpg")
    n = download(photo["src"]["original"], raw_path)
    out_name = f"{slug}-story.jpg" if story else f"{slug}.jpg"
    make_palacio.make_post(f"{slug}.jpg", out_name, story=story, source_dir=CACHE)
    used[slug] = photo["id"]
    credits[slug] = {"id": photo["id"], "photographer": photo.get("photographer"),
                     "url": photo.get("url"), "query": query}
    print(f"  ✓ {slug}: Pexels#{photo['id']} {photo['width']}x{photo['height']} "
          f"({n//1024} KB) · foto de {photo.get('photographer')}")
    return out_name


def run_batch(push=False):
    key = _secret("PEXELS_API_KEY")
    used, credits = _load_used(), _load_credits()
    made = []
    print(f"Posts de atmósfera ({len(POST_THEMES)}):")
    for slug, query, _cap in POST_THEMES:
        try:
            r = fetch_one(slug, query, False, key, used, credits)
            if r: made.append(("posts", r))
        except Exception as e:
            print(f"  ⚠ {slug} → ERROR: {e}")
        time.sleep(1)  # cortesía con la API
    print(f"\nStories de atmósfera ({len(STORY_THEMES)}):")
    for slug, query, _cap in STORY_THEMES:
        try:
            r = fetch_one(slug, query, True, key, used, credits)
            if r: made.append(("stories", r))
        except Exception as e:
            print(f"  ⚠ {slug} → ERROR: {e}")
        time.sleep(1)
    _save_used(used); _save_credits(credits)
    print(f"\n✓ {len(made)} imágenes nuevas generadas.")

    if push and made:
        files = [os.path.join(d, n) for d, n in made]
        subprocess.run(["git", "-C", LOCAL, "add"] + files, check=True)
        subprocess.run(["git", "-C", LOCAL, "commit", "-m",
                        f"feat: {len(made)} tarjetas de atmósfera desde Pexels"], check=True)
        subprocess.run(["git", "-C", LOCAL, "push"], check=True)
        print("✓ push OK — verificando raw URLs…")
        time.sleep(4)
        ok = 0
        for d, n in made:
            url = f"{RAW}/{d}/{n}"
            try:
                req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=20) as r:
                    if r.status == 200: ok += 1
                    else: print(f"  ⚠ {url} → HTTP {r.status}")
            except Exception as e:
                print(f"  ⚠ {url} → {e}")
        print(f"✓ {ok}/{len(made)} raw URLs responden 200")
    return made


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    mode = sys.argv[1]
    if mode == "batch":
        run_batch(push=("--push" in sys.argv))
    elif mode in ("post", "story") and len(sys.argv) >= 4:
        key = _secret("PEXELS_API_KEY")
        used, credits = _load_used(), _load_credits()
        slug, query = sys.argv[2], sys.argv[3]
        fetch_one(slug, query, mode == "story", key, used, credits)
        _save_used(used); _save_credits(credits)
    else:
        print(__doc__); sys.exit(1)


if __name__ == "__main__":
    main()
