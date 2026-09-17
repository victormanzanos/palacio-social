#!/usr/bin/env python3
"""Herramienta de imagenes de @palaciodemanzanos (regla de 360 dias).

    /usr/bin/python3 images_tool.py check       auditoria del indice y la baraja
    /usr/bin/python3 images_tool.py plan [N]    simula las proximas N publicaciones
    /usr/bin/python3 images_tool.py add post|story <foto-fuente> <tarjeta.jpg>

`add` es la UNICA via de alta: rechaza (exit 2) cualquier foto que ya este en la
baraja, por md5 o por hash perceptual. Llamar a make_palacio.py directamente se
salta el dedup y es como se colaron las fotos repetidas.

⚠️ Usar SIEMPRE /usr/bin/python3: bajo launchd el PATH es /usr/bin:/bin:... y ese
es el interprete que publica de verdad. Ver [[agolfcars-ig-engine]].
"""
import os
import sys
import json
import hashlib
import datetime
import importlib.util

LOCAL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LOCAL)
import image_registry as REG  # noqa: E402


def engine():
    os.environ.setdefault("DRY", "1")
    spec = importlib.util.spec_from_file_location("de", os.path.join(LOCAL, "daily_engine.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["de"] = m
    spec.loader.exec_module(m)
    return m


# ──────────────────────────────────────────────────────────────────────────
def cmd_check():
    idx = REG.load_index()
    led = REG.load_ledger()
    m = engine()

    photos = {}
    for card, e in idx.items():
        photos.setdefault(e["photo"], []).append(card)
    print(f"INDICE   · {len(idx)} tarjetas · {len(photos)} fotos distintas")

    # Fotos que dan de comer a mas de un SLOT (no solo post + su story gemela)
    def slot(c):
        b = c.split("/")[-1]
        return b[:-len("-story.jpg")] if b.endswith("-story.jpg") else b[:-4]
    cross = {p: v for p, v in photos.items() if len(set(slot(c) for c in v)) > 1}
    print(f"           {len(cross)} fotos usadas por MAS DE UN slot distinto")
    for p, v in sorted(cross.items(), key=lambda x: -len(x[1]))[:12]:
        print(f"             {p[:46]:46s} → {', '.join(sorted(slot(c) for c in set(v)))}")

    print(f"\nHISTORIAL · {len(led)} publicaciones"
          + (f" ({led[0]['date']} → {led[-1]['date']})" if led else ""))
    seen = {}
    for r in led:
        if r.get("phash"):
            seen.setdefault(r["photo"], []).append(r["date"])
    reps = {p: d for p, d in seen.items() if len(d) > 1}
    print(f"           {len(seen)} fotos distintas publicadas · "
          f"{len(reps)} repetidas · {sum(len(d) - 1 for d in reps.values())} publicaciones repetidas")

    # Baraja: fotos distintas disponibles en cada pool
    def pool_photos(cards):
        return {(idx.get(c) or {}).get("photo") for c in cards} - {None}
    palace = pool_photos(f"posts/{f}" for f, _ in m.PALACE_POSTS)
    surr = pool_photos(f"posts/{f}" for f, _ in m.SURROUND_POSTS
                       if m.entorno_card_ok(f, dict(m.SURROUND_POSTS)[f])[0])
    stor = pool_photos(f"stories/{f}" for f in m.STORY_FILES
                       if m.entorno_story_ok(f, dict(m.STORIES).get(f, ""))[0])
    print(f"\nBARAJA    · posts palacio {len(palace):3d} fotos · posts entorno {len(surr):3d} "
          f"· stories {len(stor):3d}")
    allp = palace | surr | stor
    print(f"           {len(allp)} fotos distintas en total")
    need = 366  # 183 publicaciones/ano x 2 fotos (post + story)
    print(f"\nNECESIDAD · 1 publicacion de cada 2 dias = 183/ano x 2 fotos = {need} fotos/360 dias")
    print(f"           faltan {max(0, need - len(allp))} fotos para cubrir el ano")
    return 0


# ──────────────────────────────────────────────────────────────────────────
def cmd_plan(n=60):
    """Simula las proximas N publicaciones SIN publicar ni tocar estado."""
    m = engine()
    idx = REG.load_index()
    led = list(REG.load_ledger())
    s = dict(json.load(open(os.path.join(LOCAL, ".daily_state.json"))))

    d = datetime.date.today()
    used, rows, exhausted = {}, [], None
    for r in led:
        if r.get("phash"):
            used.setdefault(r["photo"], []).append(r["date"])

    for k in range(n):
        while d.toordinal() % m.PALACIO_CYCLE_DIV != m.PALACIO_CYCLE_DAY:
            d += datetime.timedelta(days=1)
        today = str(d)
        blocked = REG.blocked_hashes(today, rows=led)
        pf, cap, pool, pi = m.pick_next_post(s, blocked, idx)
        sf, si = m.pick_next_story(s, blocked, idx, post_card=f"posts/{pf}")
        pph = (idx.get(f"posts/{pf}") or {}).get("photo", "?")
        sph = (idx.get(f"stories/{sf}") or {}).get("photo", "?")
        # WHY la ventana y no "visto alguna vez": la regla es no repetir en 360
        # dias. Contar cualquier reaparicion posterior marca como violacion algo
        # que es correcto, y hace creer que la baraja se agota antes de tiempo.
        def within(photo):
            for d0 in used.get(photo, []):
                if (d - datetime.date.fromisoformat(d0)).days < REG.NO_REPEAT_DAYS:
                    return d0
            return None
        rep = []
        prev = within(pph)
        if prev:
            rep.append(f"POST repite {pph} de {prev}")
        prev = within(sph)
        if prev:
            rep.append(f"STORY repite {sph} de {prev}")
        if pph == sph:
            rep.append("post y story MISMA foto")
        if rep and exhausted is None:
            exhausted = today
        rows.append((today, pool, pf, sf, pph, sph, rep))
        used.setdefault(pph, []).append(today)
        used.setdefault(sph, []).append(today)
        for kind, card in (("post", f"posts/{pf}"), ("story", f"stories/{sf}")):
            e = idx.get(card) or {}
            led.append({"date": today, "kind": kind, "card": card,
                        "photo": e.get("photo"), "phash": e.get("phash")})
        if pool == "palace":
            s["palace_idx"] = pi + 1
        elif pool == "surround":
            s["surround_idx"] = pi + 1
        s["post"] += 1
        s["story"] = si + 1
        d += datetime.timedelta(days=1)

    bad = [r for r in rows if r[6]]
    print(f"\nSIMULACION de {n} publicaciones ({rows[0][0]} → {rows[-1][0]})")
    print(f"  repeticiones: {len(bad)}")
    for r in bad[:25]:
        print(f"   ⚠️  {r[0]}  {r[2]} / {r[4]}  +  {r[3]} / {r[5]}  →  {'; '.join(r[6])}")
    if exhausted:
        dias = (datetime.date.fromisoformat(exhausted) - datetime.date.today()).days
        print(f"  BARAJA AGOTADA el {exhausted} (dentro de {dias} dias)")
    else:
        print("  ✅ ninguna foto repetida en toda la simulacion")
    return 1 if bad else 0


# ──────────────────────────────────────────────────────────────────────────
def cmd_add(kind, src_name, card_name):
    """Genera una tarjeta nueva rechazando cualquier foto ya presente."""
    src = REG.find_source(src_name)
    if not src:
        print(f"ERROR: no encuentro la foto fuente {src_name} en {REG.SRC_DIRS}")
        return 2
    idx = REG.load_index()
    md5 = hashlib.md5(open(src, "rb").read()).hexdigest()
    ph = REG.phash(src)
    for card, e in idx.items():
        if e.get("phash") and REG.same_photo(ph, e["phash"]):
            print(f"RECHAZADA: {src_name} es la misma foto que {card} ({e['photo']}).")
            return 2
        p = e.get("src")
        if p and os.path.exists(p) and hashlib.md5(open(p, "rb").read()).hexdigest() == md5:
            print(f"RECHAZADA: {src_name} es byte a byte {card}.")
            return 2

    sys.path.insert(0, LOCAL)
    import make_palacio as MK
    src_dir = os.path.dirname(src)
    MK.make_post(os.path.basename(src), card_name, story=(kind == "story"), source_dir=src_dir)
    sub = "stories" if kind == "story" else "posts"
    idx[f"{sub}/{card_name}"] = {"photo": os.path.basename(src), "phash": ph,
                                 "src": src, "how": "add"}
    REG.save_index(idx)
    print(f"OK: {sub}/{card_name} ← {os.path.basename(src)}")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "check":
        sys.exit(cmd_check())
    if a[0] == "plan":
        sys.exit(cmd_plan(int(a[1]) if len(a) > 1 else 60))
    if a[0] == "add" and len(a) == 4:
        sys.exit(cmd_add(a[1], a[2], a[3]))
    print(__doc__)
    sys.exit(2)
