#!/usr/bin/env python3
"""
Palacio de Manzanos — image processor for Instagram.

Toma fotos reales del palacio (carpeta SOURCE) y les aplica:
- crop/resize a 1080x1350 (post) o 1080x1920 (story)
- viñeta sutil en bordes (sin oscurecer demasiado, mantener calidad)
- marco DOBLE dorado (línea exterior + línea interior con gap)
- ACENTOS en las cuatro esquinas (líneas en L estilo art-deco)
- wordmark inferior sutil "PALACIO · MANZANOS · HARO"

Uso:
    python3 make_palacio.py post  Manzanos_interior-14.jpg    01-piano.jpg
    python3 make_palacio.py story Manzanos_lifestyle-50.jpg   01-piano-story.jpg
    python3 make_palacio.py batch                              # procesa BATCH_POSTS y BATCH_STORIES

El "batch" lee BATCH_POSTS / BATCH_STORIES (al final del archivo) y los procesa todos.
"""
import os, sys, math
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

# ============================================================
# CONFIG
# ============================================================
SOURCE       = "/Users/victor/Code/PalaciodeManzanosweb/fotospalacio"
# WHY: fuente VERIFICADA para posts/stories. La web (public/images/palacio) es la
# única fuente donde sabemos qué muestra cada foto (mapeo suite↔imagen en
# habitaciones.astro). fotospalacio usa nombres no descriptivos y provocó que
# BATCH_POSTS asignara imágenes a ciegas (texto≠imagen; corregido 2026-07-31).
SOURCE_WEB   = "/Users/victor/Code/PalaciodeManzanosweb/public/images/palacio"
SOURCE_BLOG  = "/Users/victor/Code/PalaciodeManzanosweb/public/images/blog"
OUT_POSTS    = os.path.expanduser("~/palacio-social/posts")
OUT_STORIES  = os.path.expanduser("~/palacio-social/stories")

# Paleta Palacio
GOLD       = (184, 153, 104)     # oro brand (#B89968)
GOLD_LT    = (217, 196, 154)     # oro claro (#D9C49A)
GOLD_DK    = (140, 115, 75)      # oro oscuro para sombra
INK        = (42, 24, 20)        # marrón oscuro brand (#2A1814)
WHITE_WARM = (247, 242, 232)     # crema brand (#F7F2E8)

# Fuentes (macOS system fonts)
FB = "/System/Library/Fonts/Supplemental/Georgia Bold.ttf"
FR = "/System/Library/Fonts/Supplemental/Georgia.ttf"
FI = "/System/Library/Fonts/Supplemental/Georgia Italic.ttf"

# Tamaños Instagram
POST_W,  POST_H  = 1080, 1350
STORY_W, STORY_H = 1080, 1920


# ============================================================
# HELPERS
# ============================================================
def cover(im, w, h):
    """Crop+resize para llenar w*h conservando proporciones (estilo CSS object-fit: cover)."""
    s = max(w / im.width, h / im.height)
    nw, nh = int(im.width * s + 1), int(im.height * s + 1)
    im = im.resize((nw, nh), Image.LANCZOS)
    x0 = (nw - w) // 2
    y0 = (nh - h) // 2
    return im.crop((x0, y0, x0 + w, y0 + h))


def add_vignette(im, strength=0.18):
    """Viñeta radial muy sutil — oscurece levemente los bordes sin matar la foto."""
    w, h = im.size
    mask = Image.new("L", (w, h), 0)
    px = mask.load()
    cx, cy = w / 2, h / 2
    max_d = math.hypot(cx, cy)
    for y in range(h):
        for x in range(w):
            d = math.hypot(x - cx, y - cy) / max_d
            # solo en el cuarto exterior
            v = max(0.0, d - 0.55) / 0.45
            px[x, y] = int(255 * v * strength)
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(dark, im, mask)


def spaced_text(draw, cx, y, text, font, fill, sp):
    """Texto con tracking (espaciado letra a letra) centrado en cx."""
    widths = [draw.textlength(c, font=font) for c in text]
    total = sum(widths) + sp * (len(text) - 1)
    x = cx - total / 2
    for c, w in zip(text, widths):
        draw.text((x, y), c, font=font, fill=fill)
        x += w + sp


def draw_double_frame(im, margin_outer=44, gap=16, line_outer=3, line_inner=1):
    """Marco dorado doble: línea exterior gruesa + línea interior fina con gap."""
    w, h = im.size
    canvas = im.convert("RGBA")
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # Exterior
    d.rectangle(
        [margin_outer, margin_outer, w - margin_outer - 1, h - margin_outer - 1],
        outline=GOLD, width=line_outer
    )
    # Interior
    mi = margin_outer + gap
    d.rectangle(
        [mi, mi, w - mi - 1, h - mi - 1],
        outline=GOLD_LT + (210,) if False else GOLD, width=line_inner
    )
    return Image.alpha_composite(canvas, overlay).convert("RGB")


def draw_corner_accents(im, margin=44, size=70, line=3):
    """4 acentos en L en las esquinas del marco — estilo art-decó sutil."""
    w, h = im.size
    canvas = im.convert("RGBA")
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # cada esquina: dos segmentos perpendiculares de longitud `size`
    # Top-left
    d.line([(margin, margin + size), (margin, margin)], fill=GOLD, width=line)
    d.line([(margin, margin), (margin + size, margin)], fill=GOLD, width=line)
    # Top-right
    d.line([(w - margin - size, margin), (w - margin - 1, margin)], fill=GOLD, width=line)
    d.line([(w - margin - 1, margin), (w - margin - 1, margin + size)], fill=GOLD, width=line)
    # Bottom-left
    d.line([(margin, h - margin - size), (margin, h - margin - 1)], fill=GOLD, width=line)
    d.line([(margin, h - margin - 1), (margin + size, h - margin - 1)], fill=GOLD, width=line)
    # Bottom-right
    d.line([(w - margin - size, h - margin - 1), (w - margin - 1, h - margin - 1)], fill=GOLD, width=line)
    d.line([(w - margin - 1, h - margin - size), (w - margin - 1, h - margin - 1)], fill=GOLD, width=line)

    return Image.alpha_composite(canvas, overlay).convert("RGB")


def draw_wordmark(im, line1="PALACIO · MANZANOS", line2="HARO · LA RIOJA", y_offset=130):
    """Wordmark inferior en oro sobre un panel ligeramente oscuro semi-transparente."""
    w, h = im.size
    canvas = im.convert("RGBA")
    panel_h = 96 if h > 1500 else 86  # panel un poco más alto en stories

    # Panel translúcido oscuro sólo bajo el wordmark
    panel = Image.new("RGBA", (w, panel_h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    pd.rectangle([0, 0, w, panel_h], fill=(20, 14, 10, 130))
    # Línea fina dorada arriba del panel
    pd.line([(w * 0.30, 0), (w * 0.70, 0)], fill=GOLD, width=1)

    panel_y = h - y_offset
    canvas.alpha_composite(panel, (0, panel_y))

    # Texto
    d = ImageDraw.Draw(canvas)
    font_big = ImageFont.truetype(FB, 28)
    font_sm  = ImageFont.truetype(FR, 14)
    spaced_text(d, w / 2, panel_y + 18, line1, font_big, GOLD_LT, sp=6)
    spaced_text(d, w / 2, panel_y + 56, line2, font_sm, (200, 180, 140), sp=4)

    return canvas.convert("RGB")


def draw_gold_band_frame(im, margin=34, band=12, gap=14, line_inner=2):
    """Recuadro DORADO destacado para días especiales: banda sólida dorada
    con degradado vertical claro→oscuro (efecto metal) + línea interior fina."""
    w, h = im.size
    canvas = im.convert("RGBA")
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # Banda sólida: anillos concéntricos interpolando GOLD_LT→GOLD_DK (brillo metálico)
    for i in range(band):
        t = i / max(band - 1, 1)
        c = tuple(int(GOLD_LT[j] * (1 - t) + GOLD_DK[j] * t) for j in range(3))
        m = margin + i
        d.rectangle([m, m, w - m - 1, h - m - 1], outline=c, width=1)
    # Línea interior fina separada por gap
    mi = margin + band + gap
    d.rectangle([mi, mi, w - mi - 1, h - mi - 1], outline=GOLD, width=line_inner)
    return Image.alpha_composite(canvas, overlay).convert("RGB")


def draw_special_banner(im, title, subtitle):
    """Cartela superior del día especial: título + subtítulo en oro con
    filetes dorados, sobre panel translúcido oscuro (legible en cualquier foto)."""
    w, h = im.size
    canvas = im.convert("RGBA")
    is_story = h > 1500
    panel_h = 150 if is_story else 132
    panel_y = 150 if is_story else 120

    panel = Image.new("RGBA", (w, panel_h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    pd.rectangle([0, 0, w, panel_h], fill=(20, 14, 10, 150))
    pd.line([(w * 0.22, 0), (w * 0.78, 0)], fill=GOLD, width=2)
    pd.line([(w * 0.22, panel_h - 1), (w * 0.78, panel_h - 1)], fill=GOLD, width=2)
    canvas.alpha_composite(panel, (0, panel_y))

    d = ImageDraw.Draw(canvas)
    f_title = ImageFont.truetype(FB, 40 if is_story else 36)
    f_sub   = ImageFont.truetype(FI, 22 if is_story else 20)
    spaced_text(d, w / 2, panel_y + 26, title, f_title, GOLD_LT, sp=5)
    spaced_text(d, w / 2, panel_y + (86 if is_story else 78), subtitle, f_sub, GOLD, sp=3)
    return canvas.convert("RGB")


def make_special(src_filename, out_filename, title, subtitle, story=False, source_dir=None):
    """Imagen de DÍA ESPECIAL (recuadro dorado destacado + cartela + logo en oro).
    Mismo pipeline que make_post pero con la banda dorada y la cartela del día."""
    src_dir = source_dir or SOURCE
    src_path = os.path.join(src_dir, src_filename)
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"No existe: {src_path}")

    w, h = (STORY_W, STORY_H) if story else (POST_W, POST_H)
    out_dir = OUT_STORIES if story else OUT_POSTS
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, out_filename)

    img = Image.open(src_path).convert("RGB")
    img = cover(img, w, h)
    img = add_vignette(img, strength=0.24)  # algo más de viñeta: resalta el oro

    if story:
        img = draw_gold_band_frame(img, margin=40, band=14, gap=16, line_inner=2)
        img = draw_corner_accents(img, margin=40, size=100, line=5)
        img = draw_special_banner(img, title, subtitle)
        img = draw_wordmark(img, y_offset=170)
    else:
        img = draw_gold_band_frame(img, margin=32, band=12, gap=14, line_inner=2)
        img = draw_corner_accents(img, margin=32, size=80, line=4)
        img = draw_special_banner(img, title, subtitle)
        img = draw_wordmark(img, y_offset=150)

    img.save(out_path, "JPEG", quality=92, optimize=True)
    print(f"  ✓ {('SP-STORY' if story else 'SP-POST '):<8} {src_filename:<38} → {out_filename}")
    return out_path


# ============================================================
# DÍAS ESPECIALES DE ESPAÑA — imágenes doradas pregeneradas
# (fuente de la lista: daily_engine.py SPECIAL_DAYS; aquí solo el batch de assets)
# ============================================================
BATCH_SPECIALS = [
    # (src, slug, título cartela, subtítulo cartela)
    ("Manzanos_lifestyle-58.jpg", "sp-ano-nuevo",    "1 DE ENERO",      "Feliz Año Nuevo"),
    ("Manzanos_interior-2.jpg",   "sp-reyes",        "6 DE ENERO",      "Noche de Reyes"),
    ("Manzanos_lifestyle-13.jpg", "sp-batalla-vino", "29 DE JUNIO",     "Batalla del Vino · Haro"),
    ("Manzanos_interior-1.jpg",   "sp-santiago",     "25 DE JULIO",     "Santiago Apóstol"),
    ("Manzanos_lifestyle-5.jpg",  "sp-virgen-vega",  "8 DE SEPTIEMBRE", "Virgen de la Vega · Haro"),
    ("Manzanos_interior-1.jpg",   "sp-hispanidad",   "12 DE OCTUBRE",   "Fiesta Nacional de España"),
    ("Manzanos_interior-10.jpg",  "sp-nochebuena",   "24 DE DICIEMBRE", "Nochebuena"),
    ("Manzanos_interior-14.jpg",  "sp-navidad",      "25 DE DICIEMBRE", "Feliz Navidad"),
    ("Manzanos_lifestyle-50.jpg", "sp-nochevieja",   "31 DE DICIEMBRE", "Nochevieja"),
]


# ============================================================
# MAIN PROCESSOR
# ============================================================
def make_post(src_filename, out_filename, story=False, source_dir=None):
    """Procesa una foto al formato post (1080x1350) o story (1080x1920).
    Por defecto lee de SOURCE (fotospalacio); pasar source_dir=SOURCE_BLOG para imágenes del blog."""
    src_dir = source_dir or SOURCE
    src_path = os.path.join(src_dir, src_filename)
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"No existe: {src_path}")

    w, h = (STORY_W, STORY_H) if story else (POST_W, POST_H)
    out_dir = OUT_STORIES if story else OUT_POSTS
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, out_filename)

    img = Image.open(src_path).convert("RGB")
    img = cover(img, w, h)
    img = add_vignette(img, strength=0.18)

    # En stories el margen es un pelín mayor + acentos más grandes
    if story:
        img = draw_double_frame(img, margin_outer=54, gap=20, line_outer=4, line_inner=1)
        img = draw_corner_accents(img, margin=54, size=90, line=4)
        img = draw_wordmark(img, y_offset=150)
    else:
        img = draw_double_frame(img, margin_outer=44, gap=16, line_outer=3, line_inner=1)
        img = draw_corner_accents(img, margin=44, size=70, line=3)
        img = draw_wordmark(img, y_offset=130)

    img.save(out_path, "JPEG", quality=92, optimize=True)
    print(f"  ✓ {('STORY' if story else 'POST '):<5} {src_filename:<40} → {out_filename}")
    return out_path


# ============================================================
# BATCH — selección curada de 36 posts + 12 stories
# ============================================================
# Lista ordenada de fotos a procesar. Mezcla intencional de interior + lifestyle.
# ⚠️ MAPEO VERIFICADO (2026-07-31). Cada fuente se comprobó VISUALMENTE contra la
# web antes de asignarla al slot (antes estaban a ciegas → texto≠imagen). Fuentes
# desde SOURCE_WEB (public/images/palacio). El nombre de slot es solo un ID estable;
# lo que importa es que la caption de CAPTIONS.md describa la foto real de aquí.
BATCH_POSTS = [
    # ====== Fachada + salón noble (slot 1-6) ======
    ("Manzanos_interior-1.jpg",          "01-fachada.jpg"),        # fachada 1733
    ("Manzanos_interior-14.jpg",         "02-salon-piano.jpg"),    # salón con piano
    ("Manzanos_interior-2.jpg",          "03-recibidor.jpg"),      # fachada barroca (exterior)
    ("Manzanos_interior-15.jpg",         "04-salon-noble.jpg"),    # salón noble
    ("Manzanos_lifestyle-5.jpg",         "05-vista-haro.jpg"),     # desayuno en familia
    ("Manzanos_interior-18.jpg",         "06-pasillo.jpg"),        # comedor + mural vendimia

    # ====== Suites reales (slot 7-13) — Ático/Chardonnay King, Viura/Tempranillo Queen ======
    ("Manzanos-16.jpg",                  "07-suite-atico.jpg"),    # Suite Ático (King, vigas)
    ("Manzanos-17.jpg",                  "08-suite-king.jpg"),     # camas King 200 (Ático)
    ("Manzanos-6.jpg",                   "09-suite-cama.jpg"),     # Suite Viura (Queen)
    ("Manzanos-2.jpg",                   "10-suite-chardonnay.jpg"),# Suite Chardonnay (King)
    ("Manzanos-5.jpg",                   "11-suite-viura.jpg"),    # Suite Viura (Queen)
    ("Manzanos-10.jpg",                  "12-suite-tempranillo.jpg"),# Suite Tempranillo (Queen)
    ("Manzanos-11.jpg",                  "13-suite-detalle.jpg"),  # detalle suite Tempranillo

    # ====== Wellness (slot 14-18) — sauna / gym / relax / baños ======
    ("Manzanos_interior-61.jpg",         "14-sauna.jpg"),          # sauna infrarrojos
    ("Manzanos_interior-62.jpg",         "15-jacuzzi.jpg"),        # gimnasio (NO hay foto de jacuzzi)
    ("Manzanos_interior-63.jpg",         "16-gimnasio.jpg"),       # zona relax / tumbonas
    ("Manzanos_interior-60.jpg",         "17-spa-detalle.jpg"),    # baño mosaico
    ("Manzanos_interior-59.jpg",         "18-relax.jpg"),          # bañera exenta

    # ====== Entretenimiento / baños (slot 19-22) ======
    ("Manzanos_interior-64.jpg",         "19-cine.jpg"),           # billar + proyector
    ("Manzanos_interior-46.jpg",         "20-billar.jpg"),         # ducha walk-in dorada
    ("Manzanos_interior-24.jpg",         "21-piano-cola.jpg"),     # piano de cola (detalle)
    ("Manzanos_interior-9.jpg",          "22-juegos.jpg"),         # rincón de desayuno (cocina)

    # ====== Cocina / comedor (slot 23-26) ======
    ("Manzanos_interior-7.jpg",          "23-cocina.jpg"),         # cocina equipada
    ("Manzanos_interior-8.jpg",          "24-vinoteca.jpg"),       # vinoteca en la cocina
    ("Manzanos_interior-21.jpg",         "25-comedor.jpg"),        # comedor (mesa)
    ("Manzanos_interior-19.jpg",         "26-mesa-noble.jpg"),     # mesa noble + mural

    # ====== Baños / dormitorio (slot 27-29) ======
    ("Manzanos_interior-47.jpg",         "27-bano-marmol.jpg"),    # baño Ático (bañera exenta)
    ("Manzanos_interior-48.jpg",         "28-bano-bañera.jpg"),    # baño mosaico artesanal
    ("Manzanos_interior-49_(2).jpg",     "29-bano-suite.jpg"),     # dormitorio bajo cubierta

    # ====== Lifestyle — gente disfrutando (slot 30-36) ======
    ("Manzanos_lifestyle-1.jpg",         "30-lifestyle-llegada.jpg"),# desayuno / cocina
    ("Manzanos_lifestyle-32.jpg",        "31-lifestyle-vino.jpg"), # brindis con Rioja
    ("Manzanos_lifestyle-25.jpg",        "32-lifestyle-cena.jpg"), # copa en el salón
    ("Manzanos_lifestyle-13.jpg",        "33-lifestyle-piano.jpg"),# niños al piano
    ("Manzanos_lifestyle-43.jpg",        "34-lifestyle-balcon.jpg"),# rincón de juego niños
    ("Manzanos_lifestyle-50.jpg",        "35-lifestyle-amigos.jpg"),# wellness / gym en uso
    ("Manzanos_lifestyle-58.jpg",        "36-lifestyle-noche.jpg"),# noche de billar
]

BATCH_STORIES = [
    ("Manzanos_interior-14.jpg",         "01-st-salon.jpg"),       # salón + piano
    ("Manzanos_interior-61.jpg",         "02-st-sauna.jpg"),       # sauna
    ("Manzanos_interior-64.jpg",         "03-st-cine.jpg"),        # billar + cine
    ("Manzanos-16.jpg",                  "04-st-suite-atico.jpg"), # Suite Ático real
    ("Manzanos_interior-24.jpg",         "05-st-piano.jpg"),       # piano de cola
    ("Manzanos_lifestyle-25.jpg",        "06-st-cena.jpg"),        # copa en el salón
    ("Manzanos_interior-1.jpg",          "07-st-fachada.jpg"),     # fachada
    ("Manzanos_interior-8.jpg",          "08-st-vinoteca.jpg"),    # vinoteca cocina
    ("Manzanos_lifestyle-32.jpg",        "09-st-cata.jpg"),        # brindis con Rioja
    ("Manzanos_lifestyle-58.jpg",        "10-st-billar.jpg"),      # billar en uso
    ("Manzanos_lifestyle-43.jpg",        "11-st-balcon.jpg"),      # rincón de juego niños
    ("Manzanos_lifestyle-5.jpg",         "12-st-grupo.jpg"),       # en familia
]

# ===== ENTORNO (basado en blog de la web) =====
# 18 posts intercalados (1 de cada 2) — Haro, bodegas, Rioja, Ruta Norte, vendimia.
# Origen: /public/images/blog/ de la web del Palacio.
BATCH_SURROUNDINGS = [
    ("bodegas-centenarias-haro-barricas-roble.jpg",                 "s01-bodegas-barricas.jpg"),
    ("enoturismo-lujo-rioja-cata-privada-copas.jpg",                "s02-cata-privada.jpg"),
    ("bodegas-centenarias-haro-dia-perfecto-calado.jpg",            "s03-calado-haro.jpg"),
    ("fin-de-semana-haro-plaza-historica.jpg",                      "s04-plaza-haro.jpg"),
    ("enoturismo-lujo-rioja-itinerario-tres-dias-vinedo.jpg",       "s05-3dias-rioja.jpg"),
    ("fin-de-semana-haro-gastronomia-tapas.jpg",                    "s06-tapas-haro.jpg"),
    ("enoturismo-rioja-cata-vertical-calado.jpg",                   "s07-cata-vertical.jpg"),
    ("ruta-norte-san-sebastian-la-concha.jpg",                      "s08-ss-concha.jpg"),
    ("vendimia-rioja-calendario-semanal-vinedo.jpg",                "s09-vendimia-vinedo.jpg"),
    ("ruta-norte-pintxos-gastronomia-vasca.jpg",                    "s10-pintxos-vasco.jpg"),
    ("junio-rioja-vinedo-montanas.jpg",                             "s11-junio-rioja.jpg"),
    ("ruta-norte-5-dias-bilbao-ria.jpg",                            "s12-bilbao-ria.jpg"),
    ("guia-bodegas-centenarias-haro-cuales-visitar-barricas.jpg",   "s13-guia-bodegas.jpg"),
    ("fin-de-semana-haro-cultura-casco-historico.jpg",              "s14-haro-casco.jpg"),
    ("julio-agosto-vinedo-verano-rioja.jpg",                        "s15-verano-rioja.jpg"),
    ("vendimia-otono-cesta-uvas-cosecha.jpg",                       "s16-cosecha-otono.jpg"),
    ("san-sebastian-bilbao-rioja-tres-mundos-costa-vasca.jpg",      "s17-tres-mundos.jpg"),
    ("vacaciones-familia-rioja-vinedo-familia.jpg",                 "s18-familia-rioja.jpg"),
]


# ============================================================
# CLI
# ============================================================
def usage():
    print(__doc__)
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        usage()
    mode = sys.argv[1]

    if mode == "batch":
        print(f"Procesando {len(BATCH_POSTS)} posts + {len(BATCH_STORIES)} stories...\n")
        for src, dst in BATCH_POSTS:
            try:
                make_post(src, dst, story=False, source_dir=SOURCE_WEB)
            except Exception as e:
                print(f"  ⚠ {src} → ERROR: {e}")
        print()
        for src, dst in BATCH_STORIES:
            try:
                make_post(src, dst, story=True, source_dir=SOURCE_WEB)
            except Exception as e:
                print(f"  ⚠ {src} → ERROR: {e}")
        print(f"\n✓ Listo. Posts en {OUT_POSTS}, stories en {OUT_STORIES}")
    elif mode == "batch_surr":
        print(f"Procesando {len(BATCH_SURROUNDINGS)} posts del entorno (blog)...\n")
        for src, dst in BATCH_SURROUNDINGS:
            try:
                make_post(src, dst, story=False, source_dir=SOURCE_BLOG)
            except Exception as e:
                print(f"  ⚠ {src} → ERROR: {e}")
        print(f"\n✓ Listo. Entorno en {OUT_POSTS}")
    elif mode == "batch_special":
        print(f"Procesando {len(BATCH_SPECIALS)} días especiales (post + story)...\n")
        for src, slug, title, subtitle in BATCH_SPECIALS:
            try:
                make_special(src, f"{slug}.jpg", title, subtitle, story=False)
                make_special(src, f"{slug}-story.jpg", title, subtitle, story=True)
            except Exception as e:
                print(f"  ⚠ {slug} → ERROR: {e}")
        print(f"\n✓ Listo. Especiales en {OUT_POSTS} y {OUT_STORIES}")
    elif mode in ("post", "story") and len(sys.argv) >= 4:
        src = sys.argv[2]
        dst = sys.argv[3]
        # Detección heurística: si el archivo no está en SOURCE pero sí en SOURCE_BLOG, usar éste
        source_dir = SOURCE_BLOG if (
            not os.path.exists(os.path.join(SOURCE, src)) and
            os.path.exists(os.path.join(SOURCE_BLOG, src))
        ) else SOURCE
        make_post(src, dst, story=(mode == "story"), source_dir=source_dir)
    else:
        usage()


if __name__ == "__main__":
    main()
