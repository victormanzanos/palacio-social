# Palacio de Manzanos — Instagram Automation

Sistema de publicación diaria a **@palaciodemanzanos** clonado del de `~/manzanos-social`. Mismo motor (anti-throttle, idempotencia, foto real intercalada, email diario) — solo cambia el contenido, las credenciales y el día del ciclo.

## Cómo funciona (en una frase)

Cada día a las 11/13/15/17 ET, `daily_engine.py` mira el ciclo (Palacio publica los días `ordinal%4==1`), elige el siguiente post + story de la rotación de 36+12, baraja hashtags, sube las fotos al repo público de GitHub para que Meta las pueda leer, y publica vía Instagram Graph API. Después manda un email a `victor@manzanos.com` con captura del post + story.

## Estructura

```
~/palacio-social/
├── make_palacio.py            # Genera imágenes 1080×1350 (posts) y 1080×1920 (stories) con marco dorado
├── CAPTIONS.md                # 36 captions de posts + 12 stories — fuente única de verdad
├── daily_engine.py            # Motor diario (parsea CAPTIONS, publica, manda email)
├── refresh_token.py           # Renueva token de IG (cada domingo)
├── run_daily.sh               # Wrapper bash para LaunchAgent
├── run_refresh.sh             # Wrapper bash para refresh
├── com.palacio.dailyig.plist  # LaunchAgent — 4 disparos/día (11/13/15/17 ET)
├── com.palacio.igtokenrefresh.plist  # LaunchAgent — domingos 10:15
├── posts/                     # 36 JPGs procesados (con marco dorado)
├── stories/                   # 12 JPGs procesados (con marco dorado)
├── raw/                       # (vacío — placeholder)
├── tastings/                  # DROP FOLDER: pones aquí fotos reales y se publican intercaladas
│   └── published/             # archivo de fotos reales ya publicadas
├── token-logs/                # logs del refresh
├── daily.log                  # log del motor diario
└── .daily_state.json          # estado de rotación (índices, last_date, since_real)
```

## Cadencia (un día sí, un día no)

El motor publica cuando `today.toordinal() % 2 == 1` (días impares de calendario juliano), descansa los pares. Resultado: 1 publicación cada 2 días, ~15 al mes.

Cada publicación alterna **palacio ↔ entorno**:
- Día 1 (publica): post de palacio + story
- Día 2 (descansa)
- Día 3 (publica): post de entorno + story
- Día 4 (descansa)
- Día 5 (publica): post de palacio + story
- … y así.

Para cambiar la cadencia, editar `daily_engine.py`:
```python
PALACIO_CYCLE_DIV = 2   # divisor (2 = cada 2 días)
PALACIO_CYCLE_DAY = 1   # día del ciclo donde publica
```
Ejemplos:
- Diario: `DIV=1, DAY=0` (publica siempre)
- Cada 3 días: `DIV=3, DAY=0`
- Cada 4 días (como Manzanos Wines): `DIV=4, DAY=1`

---

## SETUP — pasos exactos para activarlo

**ESTAS COSAS NO LAS PUEDE HACER CLAUDE — tienes que hacerlas tú una vez.**

### 1. Convertir la cuenta de Instagram a Profesional (Business)

En la app de Instagram, @palaciodemanzanos:
- Ajustes → Cuenta → Cambiar a cuenta profesional
- Categoría: **Hotel / Alquiler vacacional**
- Tipo: **Empresa** (no Creador)

### 2. Conectar @palaciodemanzanos a una página de Facebook

Instagram Business obliga a vincular con una página Facebook. Si no la tienes:
- Crea una página Facebook llamada "Palacio de Manzanos" (categoría: Hotel & Lodging).
- En el perfil de IG → Editar perfil → Página → conectar.

### 3. Crear la Meta App

- Ve a https://developers.facebook.com/apps/
- Create App → tipo: **Business** → nombre: `Palacio de Manzanos Social`
- Añade producto: **Instagram** (la opción "API setup with Instagram login")
- En Instagram → API setup → conecta @palaciodemanzanos como cuenta IG asociada
- **IMPORTANTE**: déjalo en modo **Development** (no Live). Cambiar a Live invalida los tokens — Manzanos Wines USA aprendió esto a las malas.

### 4. Generar token largo + obtener IG Account ID

En el panel de la app:
- Instagram → API setup → genera un token "User access token".
- Convierte a long-lived (60 días):
  ```bash
  curl -sG \
    'https://graph.instagram.com/access_token' \
    --data-urlencode 'grant_type=ig_exchange_token' \
    --data-urlencode 'client_secret=<APP_SECRET>' \
    --data-urlencode 'access_token=<SHORT_TOKEN>'
  ```
- Anota el `access_token` que devuelve (eso es el long-lived).
- Para obtener tu IG Account ID:
  ```bash
  curl -sG 'https://graph.instagram.com/me' \
    --data-urlencode 'fields=id,username' \
    --data-urlencode 'access_token=<LONG_TOKEN>'
  ```
  Devuelve `{"id":"178414XXXXXXXXXXX","username":"palaciodemanzanos"}`.

### 5. Guardar en Keychain

```bash
~/Code/CyberSecurity/scripts/secrets.sh set PALACIO_IG_ACCESS_TOKEN
# (te pide el valor; pega el long-lived token)

~/Code/CyberSecurity/scripts/secrets.sh set PALACIO_IG_ACCOUNT_ID
# (te pide el valor; pega el 178414XXXXXXXXXXX)
```

Si no tienes el helper `secrets.sh`, son las credenciales del Keychain de macOS — puedes guardarlas con:
```bash
security add-generic-password -a "$USER" -s "PALACIO_IG_ACCESS_TOKEN" -w "<TOKEN>"
security add-generic-password -a "$USER" -s "PALACIO_IG_ACCOUNT_ID"    -w "<IG_ID>"
```

### 6. Crear el repo público en GitHub

El motor necesita URLs públicas para que Meta lea las imágenes:

```bash
# En tu cuenta personal de GitHub (victormanzanos):
gh repo create victormanzanos/palacio-social --public --description "Image hosting for @palaciodemanzanos Instagram automation"

# Subir las imágenes generadas
cd ~/palacio-social
git init -b main
git add posts/ stories/ README.md
git commit -m "Initial: 36 posts + 12 stories with gold frames"
git remote add origin git@github.com:victormanzanos/palacio-social.git
git push -u origin main
```

Comprueba que las imágenes son accesibles:
```bash
curl -sI https://raw.githubusercontent.com/victormanzanos/palacio-social/main/posts/01-fachada.jpg | head -1
# debe devolver: HTTP/2 200
```

### 7. Test en DRY (sin publicar de verdad)

```bash
DRY=1 python3 ~/palacio-social/daily_engine.py
```

Debe mostrar:
```
NEXT = BRANDED POST: 01-fachada.jpg
STORY: 01-st-salon.jpg
--- CAPTION ---
...
DRY RUN — nada publicado.
```

### 8. Primer post manual (verificar credenciales)

```bash
FORCE=1 python3 ~/palacio-social/daily_engine.py
```

Esto publica AHORA (salta la guardia del ciclo de 4 días). Confirma:
- En @palaciodemanzanos sale el post y la story
- Recibes el email de resumen
- `cat ~/palacio-social/daily.log` muestra `permalink` válido

Si falla, revisa el log y el error (típicos: token expirado, cuenta no convertida a Business, IG ID erróneo).

### 9. Instalar LaunchAgents (programación automática)

```bash
cp ~/palacio-social/com.palacio.dailyig.plist        ~/Library/LaunchAgents/
cp ~/palacio-social/com.palacio.igtokenrefresh.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.palacio.dailyig.plist
launchctl load -w ~/Library/LaunchAgents/com.palacio.igtokenrefresh.plist

# Comprobar que están cargados
launchctl list | grep palacio
```

A partir de aquí, el sistema publica solo. Los días `ordinal%4==1` (uno cada cuatro) sale post + story. Los demás días el motor se ejecuta, ve "día de descanso" y no hace nada.

---

## OPERACIÓN DIARIA

### Subir una foto real (drop folder)

Coloca un JPG en `~/palacio-social/tastings/`. Opcionalmente con un `.txt` del mismo nombre con el caption personalizado:

```
~/palacio-social/tastings/
├── tasting-2026-07-15-iraide.jpg
└── tasting-2026-07-15-iraide.txt
```

El motor lo publica como foto real (no de la rotación de marca) la próxima vez que toque foto real (cada 3 posts de marca). Una vez publicada, se mueve a `tastings/published/` y nunca se repite.

### Forzar una publicación AHORA

```bash
FORCE=1 python3 ~/palacio-social/daily_engine.py
```

### Ver estado de rotación

```bash
cat ~/palacio-social/.daily_state.json
# { "post": 7, "story": 7, "last_date": "2026-06-20", "since_real": 2 }
```

### Cambiar caption / añadir nuevo post

1. Edita `~/palacio-social/CAPTIONS.md`
2. Si añades una foto nueva, genera la versión con marco:
   ```bash
   python3 ~/palacio-social/make_palacio.py post Manzanos_xxx.jpg 37-nuevo.jpg
   ```
3. Sube al repo:
   ```bash
   cd ~/palacio-social
   git add posts/ stories/ CAPTIONS.md
   git commit -m "Add post 37"
   git push
   ```
4. El motor el día siguiente recoge el nuevo POSTS automáticamente (parsea CAPTIONS.md en cada run).

### Comprobar logs

```bash
tail -f ~/palacio-social/daily.log               # publicaciones diarias
tail -f ~/palacio-social/token-refresh.log       # renovaciones de token
```

---

## TROUBLESHOOTING

| Síntoma | Causa probable | Fix |
|---|---|---|
| `urllib.error.HTTPError: 400` con `code: 190` | Token expirado o invalidado | Regenerar token en Meta app + `secrets.sh set PALACIO_IG_ACCESS_TOKEN` |
| `code: 200` ("API access blocked") | Meta detectó comportamiento automatizado / spam | NO reintentar. Pausa 24-48h. Confirma email/SMS de Meta si llegan. |
| `container not ready` | Meta no consigue descargar la imagen de GitHub | Verifica `curl -I` a la URL raw, espera 10 min (CDN), reintenta |
| `Día de descanso` cada día | El ciclo `ordinal%4==1` no toca | Es normal — solo publica 1 día de cada 4. Usa `FORCE=1` para forzar. |
| El email no llega | SMTP_PASSWORD caducó | `secrets.sh set MANZANOS_SMTP_PASSWORD` con la nueva clave dinaserver |

---

## SEGURIDAD

- Tokens **NUNCA** en código — todos vienen del Keychain via `secrets.sh`.
- El repo público `palacio-social` SOLO contiene imágenes (no .env, no secretos).
- `.daily_state.json` y `*.log` son locales — no se suben.

---

## REFERENCIA RÁPIDA

| Acción | Comando |
|---|---|
| Test sin publicar | `DRY=1 python3 ~/palacio-social/daily_engine.py` |
| Publicar AHORA | `FORCE=1 python3 ~/palacio-social/daily_engine.py` |
| Regenerar 1 imagen | `python3 ~/palacio-social/make_palacio.py post <src> <dst>` |
| Regenerar TODAS | `python3 ~/palacio-social/make_palacio.py batch` |
| Renovar token a mano | `python3 ~/palacio-social/refresh_token.py` |
| Ver siguiente post | `DRY=1 python3 ~/palacio-social/daily_engine.py \| head` |
| Pausar el agent | `launchctl unload ~/Library/LaunchAgents/com.palacio.dailyig.plist` |
| Reanudar | `launchctl load -w ~/Library/LaunchAgents/com.palacio.dailyig.plist` |
