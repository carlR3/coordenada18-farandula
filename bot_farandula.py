#!/usr/bin/env python3
"""Bot de Coordenada 18 Farándula.

Cada ronda:
  1. Lee las secciones de farándula y entretenimiento de medios dominicanos e internacionales
     (RSS) y escoge con Gemini la historia de farándula más caliente que salga en al menos
     2 medios y que no se haya publicado ya.
  2. Lee los artículos y busca una foto limpia (sin logos ni marcas de agua, sin texto encima,
     sin menores, sin contenido gráfico).
  3. Escribe el carrusel (portada con gancho, 3 a 5 láminas con la historia, cierre con pregunta),
     el texto de la publicación y el guion del Reel, con tono picante pero sin inventar.
  4. Arma las láminas (1080x1350) y un Reel con las mismas láminas y la voz de Ramona.
  5. Publica el carrusel y el Reel en Instagram y en la página de Facebook, y te avisa en
     Telegram con las láminas, el Reel y los enlaces (o el motivo si algo falla).

Variables de entorno:
  GEMINI_API_KEY    (obligatoria)
  TELEGRAM_TOKEN    (obligatoria; puede ser el mismo bot de Coordenada 18)
  TELEGRAM_CHAT_ID  (recomendada; tu número de chat de Telegram)
  META_PAGE_TOKEN   (para publicar; token de la página de Facebook de Coordenada 18 Farándula)
  META_PAGE_ID / META_IG_ID (opcionales; si faltan, se sacan del token)
  GEMINI_MODEL      (opcional; modelo de Gemini a usar primero)
  VOZ               (opcional; por defecto es-DO-RamonaNeural; es-DO-EmilioNeural = Emilio)
  CANTIDAD          (opcional; carruseles por ronda, por defecto 1)
"""
import argparse
import base64
import datetime as dt
import html
import io
import json
import os
import re
import sys
import time
import traceback
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import feedparser
import requests
import trafilatura
from PIL import Image

import f18_render
import f18_video

AQUI = os.path.dirname(os.path.abspath(__file__))
ESTADO = os.path.join(AQUI, "estado")
HISTORIAL = os.path.join(ESTADO, "publicadas.json")
CHAT_FILE = os.path.join(ESTADO, "chat_id.txt")
SALIDA = os.path.join(AQUI, "salida")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
RD = dt.timezone(dt.timedelta(hours=-4))  # República Dominicana, sin horario de verano

# Medios que se leen. Cada uno tiene una o varias direcciones: se usa la primera que funcione.
# Si alguno falla, se sigue con los demás (el registro de cada ronda dice cuáles respondieron).
FUENTES = [
    # Secciones de farándula y entretenimiento
    ("Diario Libre", ["https://www.diariolibre.com/rss/revista.xml",
                      "https://www.diariolibre.com/rss/revista/farandula.xml"]),
    ("Listín Diario", ["https://listindiario.com/rss/entretenimiento",
                       "https://listindiario.com/rss/la-vida"]),
    ("CDN", ["https://cdn.com.do/temas/espectaculos/feed/",
             "https://cdn.com.do/category/entretenimiento/feed/"]),
    ("El Caribe", ["https://www.elcaribe.com.do/seccion/entretenimiento/feed/"]),
    ("Hoy", ["https://hoy.com.do/category/entretenimiento/feed/",
             "https://hoy.com.do/category/alegria/feed/"]),
    ("El Nuevo Diario", ["https://elnuevodiario.com.do/category/farandula/feed/",
                         "https://elnuevodiario.com.do/category/entretenimiento/feed/"]),
    ("El Día", ["https://eldia.com.do/category/entretenimiento/feed/"]),
    ("N Digital", ["https://n.com.do/category/entretenimiento/feed/"]),
    ("Infobae", ["https://www.infobae.com/arc/outboundfeeds/rss/category/teleshow/",
                 "https://www.infobae.com/arc/outboundfeeds/rss/category/entretenimiento/"]),
    ("TMZ", ["https://www.tmz.com/rss.xml"]),
    # Portadas generales (también traen farándula; Gemini escoge solo esa)
    ("Diario Libre", ["https://www.diariolibre.com/rss/portada.xml"]),
    ("Listín Diario", ["https://listindiario.com/rss/portada"]),
    ("El Nuevo Diario", ["https://elnuevodiario.com.do/feed/"]),
    ("Hoy", ["https://hoy.com.do/feed/"]),
    ("El Día", ["https://eldia.com.do/feed/"]),
    ("N Digital", ["https://n.com.do/feed/"]),
    ("El Nacional", ["https://elnacional.com.do/feed/"]),
    ("Noticias SIN", ["https://noticiassin.com/feed/"]),
    ("CDN", ["https://cdn.com.do/feed/"]),
]
# Google Noticias solo sirve para confirmar que otros medios también tienen la historia.
GOOGLE_NEWS = [
    "https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?hl=es-419&gl=DO&ceid=DO:es-419",
    "https://news.google.com/rss/search?q=far%C3%A1ndula+dominicana+when:2d&hl=es-419&gl=DO&ceid=DO:es-419",
    "https://news.google.com/rss/search?q=famosos+when:1d&hl=es-419&gl=US&ceid=US:es-419",
]

MODELOS_FLASH = ["gemini-flash-latest", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
MODELOS_LITE = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-latest", "gemini-3.6-flash"]

POR_MEDIO = 30
HORAS_VENTANA = 20       # historias de las últimas X horas (si el medio trae hora)
DIAS_HISTORIAL = 10
LIMITE_SEGUNDOS = 14 * 60  # después de esto no empieza otra historia (GitHub corta a los 25 min)
MARCA = "Coordenada 18 Farándula"
ETIQUETA = "#Coordenada18Farandula"
CIERRE = "Sigue a Coordenada 18 Farándula."
LIMITE_PIE = 1024  # Telegram no acepta más en el texto de una foto


def log(*a):
    print(*a, flush=True)


# ----------------------------------------------------------------------------- utilidades

def limpiar_html(t):
    t = re.sub(r"<[^>]+>", " ", t or "")
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def sin_tildes(t):
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def ahora_rd():
    return dt.datetime.now(RD)


def ahora_utc():
    return dt.datetime.now(dt.timezone.utc)


def _leer_json(ruta, defecto):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return defecto


def cargar_historial():
    limite = ahora_utc() - dt.timedelta(days=DIAS_HISTORIAL)
    return [d for d in _leer_json(HISTORIAL, []) if dt.datetime.fromisoformat(d["fecha"]) > limite]


def guardar_historial(datos):
    os.makedirs(ESTADO, exist_ok=True)
    with open(HISTORIAL, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)


# ----------------------------------------------------------------------------- Gemini

class ErrorGemini(RuntimeError):
    pass


def _extraer_json(texto):
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        m = re.search(r"[\{\[].*[\}\]]", texto, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def como_objeto(d):
    """Gemini a veces devuelve [ {...} ] en vez de {...}: se toma el primer objeto."""
    if isinstance(d, list):
        d = next((x for x in d if isinstance(x, dict)), {})
    return d if isinstance(d, dict) else {}


def _modelos(rapido):
    preferido = os.getenv("GEMINI_MODEL", "").strip()
    lista = MODELOS_LITE if rapido else MODELOS_FLASH
    return ([preferido] if preferido else []) + [m for m in lista if m != preferido]


def gemini(prompt, sistema=None, imagen_jpg=None, temperatura=0.4, rapido=False):
    """Llama a Gemini y devuelve el JSON. Si un modelo está saturado, pasa al siguiente."""
    clave = os.environ["GEMINI_API_KEY"]
    partes = [{"text": prompt}]
    if imagen_jpg:
        partes.append({"inlineData": {"mimeType": "image/jpeg",
                                      "data": base64.b64encode(imagen_jpg).decode()}})
    cuerpo = {"contents": [{"role": "user", "parts": partes}],
              "generationConfig": {"responseMimeType": "application/json", "temperature": temperatura}}
    if sistema:
        cuerpo["systemInstruction"] = {"parts": [{"text": sistema}]}
    ultimo, descartados = "", set()
    for vuelta in range(2):
        if vuelta:
            time.sleep(15)
        for modelo in _modelos(rapido):
            if modelo in descartados:
                continue
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
            try:
                r = requests.post(url, json=cuerpo, timeout=(10, 90),
                                  headers={"x-goog-api-key": clave, "Content-Type": "application/json"})
            except requests.RequestException as e:
                ultimo = f"{modelo}: {e}"
                log("  Gemini:", ultimo[:200])
                continue
            if r.status_code == 200:
                datos = r.json()
                try:
                    partes_r = datos["candidates"][0]["content"]["parts"]
                    texto = "".join(p.get("text", "") for p in partes_r if not p.get("thought"))
                    time.sleep(2)  # respeta el límite por minuto del plan gratis
                    return _extraer_json(texto)
                except (KeyError, IndexError, json.JSONDecodeError) as e:
                    ultimo = f"respuesta inesperada de {modelo}: {e} {str(datos)[:200]}"
                    log("  Gemini:", ultimo)
                    continue
            ultimo = f"{modelo} HTTP {r.status_code}: {r.text[:200]}"
            log("  Gemini:", " ".join(ultimo.split())[:200])
            if r.status_code not in (429, 500, 502, 503, 504):
                descartados.add(modelo)
    raise ErrorGemini(ultimo)


# ----------------------------------------------------------------------------- lectura de medios

def _imagenes_de_entrada(e):
    urls = []
    for m in e.get("media_content", []) or []:
        if m.get("url") and (m.get("medium") in (None, "image") or "image" in (m.get("type") or "")):
            urls.append(m["url"])
    for m in e.get("media_thumbnail", []) or []:
        if m.get("url"):
            urls.append(m["url"])
    for enc in e.get("enclosures", []) or []:
        if "image" in (enc.get("type") or "") and enc.get("href"):
            urls.append(enc["href"])
    for b in [c.get("value", "") for c in e.get("content", []) or []] + [e.get("summary", "")]:
        urls += re.findall(r'<img[^>]+src=["\']([^"\']+)', b or "")
    vistos, unicas = set(), []
    for u in urls:
        u = "https:" + u if u.startswith("//") else u
        if u.startswith("http") and u not in vistos:
            vistos.add(u)
            unicas.append(u)
    return unicas


def _fecha(e):
    t = e.get("published_parsed") or e.get("updated_parsed")
    return dt.datetime(*t[:6], tzinfo=dt.timezone.utc) if t else None


def _bajar(url):
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "es"}, timeout=(8, 15))
        r.raise_for_status()
        return r.content
    except Exception as e:  # noqa: BLE001
        return e


def leer_medios(urls_publicadas):
    ahora = ahora_utc()
    todas = list(dict.fromkeys([u for _, us in FUENTES for u in us] + GOOGLE_NEWS))
    with ThreadPoolExecutor(max_workers=16) as ex:
        bajados = dict(zip(todas, ex.map(_bajar, todas)))
    items, vistos = [], set()
    for medio, urls in FUENTES:
        entradas, fallo = None, ""
        for u in urls:
            c = bajados[u]
            if isinstance(c, Exception):
                fallo = str(c)[:100]
                continue
            ent = feedparser.parse(c).entries
            if ent:
                entradas = ent[:POR_MEDIO]
                break
            fallo = "sin titulares"
        if not entradas:
            log(f"  {medio} ({urls[0].split('/')[2]}): no se pudo leer ({fallo})")
            continue
        fechas = [_fecha(e) for e in entradas]
        horas_utiles = len({f for f in fechas if f}) > 2  # algunos medios ponen la misma hora a todo
        n = 0
        for e, f in zip(entradas, fechas):
            link, titulo = e.get("link", ""), limpiar_html(e.get("title", ""))
            if not link or not titulo or link in urls_publicadas or link in vistos:
                continue
            if horas_utiles and f and ahora - f > dt.timedelta(hours=HORAS_VENTANA):
                continue
            vistos.add(link)
            items.append({"medio": medio, "titulo": titulo, "link": link,
                          "fecha": f if horas_utiles else None,
                          "resumen": limpiar_html(e.get("summary", ""))[:300],
                          "imagenes": _imagenes_de_entrada(e), "directo": True})
            n += 1
        log(f"  {medio} ({urls[0].split('/')[2]}): {n} titulares")
    n = 0
    for u in GOOGLE_NEWS:
        c = bajados[u]
        if isinstance(c, Exception):
            continue
        for e in feedparser.parse(c).entries[:50]:
            t, medio = limpiar_html(e.get("title", "")), "Google Noticias"
            if " - " in t:
                t, medio = t.rsplit(" - ", 1)
            f = _fecha(e)
            if f and ahora - f > dt.timedelta(hours=HORAS_VENTANA * 2):
                continue
            items.append({"medio": medio.strip(), "titulo": t.strip(), "link": e.get("link", ""),
                          "fecha": f, "resumen": "", "imagenes": [], "directo": False})
            n += 1
    log(f"  Google Noticias: {n} titulares (solo para confirmar)")
    return items


# ----------------------------------------------------------------------------- selección

SISTEMA_EDITOR = (
    "Eres el editor de Coordenada 18 Farándula, una cuenta dominicana de Instagram y Facebook que "
    "publica carruseles de farándula: lo que pasa con los artistas, famosos, influencers, la "
    "televisión, la música y los realities, de República Dominicana y del mundo. Escoges la "
    "historia más comentada y compartible del momento, siempre que esté confirmada."
)


def seleccionar(items, historial, cantidad):
    temas = [h["tema"] for h in historial
             if dt.datetime.fromisoformat(h["fecha"]) > ahora_utc() - dt.timedelta(hours=72)]
    lineas = []
    for i, it in enumerate(items):
        hora = it["fecha"].astimezone(RD).strftime("%d/%m %I:%M %p") if it["fecha"] else "?"
        lineas.append(f"{i} | {it['medio']} | {hora} | {it['titulo']}")
    prompt = (
        f"Hora actual en RD: {ahora_rd().strftime('%d/%m/%Y %I:%M %p')}.\n\n"
        "Titulares recientes (id | medio | hora RD | titular):\n" + "\n".join(lineas) + "\n\n"
        "Historias ya publicadas en los últimos 3 días (no las repitas, ni con otro enfoque):\n"
        + ("\n".join(f"- {t}" for t in temas) if temas else "(ninguna)") + "\n\n"
        f"Escoge hasta {cantidad + 4} historias de FARÁNDULA, ordenadas de la más viral a la menos. Reglas:\n"
        "- Solo farándula y entretenimiento: artistas, cantantes, actores, presentadores, influencers, "
        "realities, premios, conciertos, lanzamientos, romances o rupturas confirmados, declaraciones "
        "polémicas, peleas públicas entre famosos, y la vida pública de deportistas famosos. "
        "Nada de política, economía, sucesos ni deportes en sí.\n"
        "- Cada historia tiene que aparecer en al menos 2 medios distintos (agrupa los titulares "
        "que hablan del mismo hecho y pon todos sus ids). Los rumores que nadie confirma no sirven.\n"
        "- Prioriza a famosos dominicanos y lo que más se comenta en RD; lo internacional, si es muy "
        "sonado (estrellas latinas o de Hollywood). Más o menos 2 de cada 3 historias deben ser de RD.\n"
        "- Prioriza lo que la gente le manda a sus amigos: sorpresas, confesiones, polémicas, "
        "reconciliaciones, anuncios, datos curiosos.\n"
        "- Descarta: crímenes, accidentes, violencia, abuso sexual, suicidio, enfermedades o salud de "
        "alguien que no lo haya contado él mismo, embarazos no confirmados por la persona, y cualquier "
        "historia centrada en menores de edad (incluidos los hijos de los famosos).\n"
        "- Las muertes de famosos solo si son muy relevantes; se tratarán con respeto.\n"
        "- No repitas historias ya publicadas.\n\n"
        'Responde solo con JSON: {"historias": [{"tema": "resumen corto del hecho", "ids": [ids], '
        '"categoria": "FARÁNDULA RD" o "FARÁNDULA INTERNACIONAL", '
        '"triste": true si es una muerte o algo doloroso (si no, false)}]}'
    )
    datos = gemini(prompt, sistema=SISTEMA_EDITOR, temperatura=0.3)
    lista = datos if isinstance(datos, list) else datos.get("historias", []) if isinstance(datos, dict) else []
    elegidas = []
    for n in lista:
        if not isinstance(n, dict):
            continue
        ids = list(dict.fromkeys(i for i in n.get("ids", []) if isinstance(i, int) and 0 <= i < len(items)))
        grupo = [items[i] for i in ids]
        medios = {g["medio"].lower() for g in grupo}
        directos = [g for g in grupo if g["directo"]]
        if len(medios) < 2 or not directos:
            continue
        cat = str(n.get("categoria", "FARÁNDULA RD")).upper()
        elegidas.append({"tema": n.get("tema", directos[0]["titulo"]), "grupo": grupo,
                         "categoria": "FARÁNDULA INTERNACIONAL" if "INTER" in cat else "FARÁNDULA RD",
                         "triste": bool(n.get("triste"))})
    return elegidas


# ----------------------------------------------------------------------------- artículos y fotos

def leer_articulo(url):
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "es"}, timeout=(8, 20))
        r.raise_for_status()
    except requests.RequestException as e:
        log(f"    no se pudo abrir {url[:80]} ({e})")
        return {"texto": "", "imagen": None}
    pagina = r.text
    texto = trafilatura.extract(pagina, url=url, include_comments=False, include_tables=False,
                                favor_precision=True) or ""
    m = re.search(r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)', pagina) \
        or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', pagina)
    return {"texto": texto[:6000], "imagen": html.unescape(m.group(1)) if m else None}


def descargar_imagen(url, referer):
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Referer": referer}, timeout=(8, 20))
        r.raise_for_status()
        if len(r.content) > 15_000_000:
            return None
        img = Image.open(io.BytesIO(r.content))
        img.load()
        return img.convert("RGB")
    except Exception:  # noqa: BLE001
        return None


def revisar_foto(img, titular):
    """Pide a Gemini que revise la foto. Devuelve (apta, foco_x, foco_y, motivo)."""
    vista = img.copy()
    vista.thumbnail((1024, 1024))
    buf = io.BytesIO()
    vista.save(buf, "JPEG", quality=85)
    prompt = (
        f'Esta foto se usaría en un carrusel de farándula con el titular: "{titular}".\n'
        "Analízala y responde solo con JSON:\n"
        '{"relacionada": true/false (¿muestra a la persona o el hecho de la historia?),\n'
        '"logo_o_marca_de_agua": true/false (¿tiene encima el logo, la marca de agua o el nombre de un '
        'medio, canal, agencia de fotos o fotógrafo?),\n'
        '"texto_encima": true/false (¿tiene títulos, franjas o texto agregado encima, como una portada, '
        'un afiche o un arte de redes? No cuentes letreros reales de la escena),\n'
        '"es_arte_o_montaje": true/false (¿es un collage, un arte gráfico, una captura de pantalla de '
        'redes o un montaje en vez de una foto?),\n'
        '"menor_identificable": true/false (¿se ve la cara de un niño o adolescente?),\n'
        '"desnudo_o_sugerente": true/false,\n'
        '"contenido_grafico": true/false (sangre, heridas o cadáveres),\n'
        '"foco_x": número de 0 a 1 (posición horizontal de la cara o sujeto principal),\n'
        '"foco_y": número de 0 a 1 (posición vertical de la cara o sujeto principal)}'
    )
    d = como_objeto(gemini(prompt, imagen_jpg=buf.getvalue(), temperatura=0.0, rapido=True))
    problemas = [k for k in ("logo_o_marca_de_agua", "texto_encima", "es_arte_o_montaje",
                             "menor_identificable", "desnudo_o_sugerente", "contenido_grafico") if d.get(k)]
    if not d.get("relacionada", True):
        problemas.append("no_relacionada")

    def num(v, defecto):
        try:
            return min(1.0, max(0.0, float(v)))
        except (TypeError, ValueError):
            return defecto
    return (not problemas, num(d.get("foco_x"), 0.5), num(d.get("foco_y"), 0.35), ",".join(problemas))


def huella(img):
    """Huella de 64 bits para reconocer la misma foto aunque venga con otro enlace o tamaño."""
    g = img.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(g.getdata())
    bits = "".join("1" if px[f * 9 + c] > px[f * 9 + c + 1] else "0" for f in range(8) for c in range(8))
    return f"{int(bits, 2):016x}"


def misma_foto(h1, h2):
    return bin(int(h1, 16) ^ int(h2, 16)).count("1") <= 8


def buscar_foto(candidatas, titular, destino, usadas):
    """candidatas: (url_imagen, medio, url_articulo). Devuelve (ruta, foco, medio, url, huella) o Nones."""
    vistas, revisadas = set(), 0
    for url, medio, referer in candidatas:
        if not url or url in vistas or revisadas >= 4:
            continue
        vistas.add(url)
        if url in usadas["urls"]:
            log(f"    foto descartada ({medio}): ya se usó")
            continue
        img = descargar_imagen(url, referer)
        if img is None or img.height < 500 or img.width < 500:
            continue
        h = huella(img)
        if any(misma_foto(h, u) for u in usadas["huellas"]):
            log(f"    foto descartada ({medio}): es la misma foto de otra publicación")
            continue
        revisadas += 1
        try:
            apta, fx, fy, motivo = revisar_foto(img, titular)
        except ErrorGemini:
            continue
        if not apta:
            log(f"    foto descartada ({medio}): {motivo}")
            continue
        img.save(destino, "JPEG", quality=95)
        return destino, (fx, fy), medio, url, h
    return None, None, None, None, None


# ----------------------------------------------------------------------------- redacción

SISTEMA_REDACCION = """Eres el equipo de redacción de Coordenada 18 Farándula, una cuenta dominicana de farándula en Instagram y Facebook. Escribes carruseles que la gente quiere leer hasta el final y mandarle a sus amigos.

Tono:
- Picante, divertido y con sabor dominicano ("se armó", "¡ay, mi madre!", "dejó a todos con la boca abierta"), pero sin vulgaridades, sin insultos y sin burlarte de nadie.
- Si la historia es triste (una muerte, algo doloroso), el tono es respetuoso y sin chistes.
- Nada de burlas por el físico, la edad, la raza, la orientación sexual, la religión o la clase social.

Lo que nunca se hace (reglas legales y éticas de República Dominicana):
- No inventes nada: usa solo hechos que estén en las fuentes que te paso. Ni cifras, ni frases, ni detalles nuevos.
- Atribuye todo: "según contó", "reveló en sus redes", "según reportes de prensa". No menciones a otros medios por su nombre.
- Un rumor solo se cuenta como rumor y atribuido ("según reportes de prensa"), nunca como hecho. No afirmes romances, rupturas, embarazos, enfermedades ni problemas legales que la persona o una fuente oficial no hayan confirmado.
- Presunción de inocencia: si hay un tema legal, usa "presunto", "acusado de", "según el Ministerio Público".
- Nunca nombres ni describas a menores de edad (tampoco a los hijos de los famosos).
- Nada de datos privados: direcciones, teléfonos, placas.
- No especules sobre la orientación sexual, la salud o la vida íntima de nadie.
- El titular tiene que estar sostenido por las láminas: nada engañoso.
- No menciones a Coordenada 18 salvo en el cierre del guion.

Carrusel:
- "portada": titular de 6 a 14 palabras que obligue a deslizar. Encierra entre <a> y </a> la parte más fuerte (el nombre del famoso o la frase clave); eso sale en amarillo. No uses otras etiquetas.
- "antetitulo": gancho corto de 2 a 5 palabras arriba del titular (por ejemplo "SE ARMÓ EL LÍO", "LO CONFIRMÓ", "NADIE LO ESPERABA"). Tiene que ser cierto según las fuentes.
- "laminas": de 3 a 5 láminas que cuentan la historia en orden. Cada una con "titulo" (2 a 5 palabras) y "texto" (de 18 a 34 palabras, frases cortas). La primera lámina es un segundo gancho: el dato más sorprendente. La última cuenta qué viene o qué se sabe hasta ahora.
- "pregunta": pregunta para que la gente comente, de máximo 12 palabras.
- "mandar": empieza con "Mándaselo a" y di a quién (máximo 9 palabras), por ejemplo "Mándaselo a tu amiga que no se pierde un chisme".

Texto de la publicación ("pie"): 2 párrafos cortos (máximo 500 caracteres en total) que resumen la historia con gancho, y al final la misma pregunta. Puedes usar de 2 a 4 emojis. Sin hashtags dentro del texto.
Hashtags: de 3 a 4 sobre el tema (nombres de los famosos, el programa o el tema), sin tildes ni espacios. No incluyas #Coordenada18Farandula; ese se agrega solo.

Guion del Reel ("guion"): una lista con un texto por cada lámina, en el mismo orden: primero la portada, luego una por cada lámina de la historia, y al final el cierre. Es lo que dirá en voz alta una presentadora dominicana de farándula mientras sale cada lámina.
- En total, entre 55 y 85 palabras. Frases cortas y con energía (respetuoso si la historia es triste).
- Mismas reglas: nada inventado, todo atribuido.
- Sin emojis ni símbolos. Escribe las cifras como se dicen en voz alta.
- El texto del cierre termina siempre con: "Sigue a Coordenada 18 Farándula."

Categoría: "FARÁNDULA RD" si el protagonista es dominicano o la historia pasó en RD; si no, "FARÁNDULA INTERNACIONAL".

Responde solo con JSON con esta forma:
{"categoria": "...", "antetitulo": "...", "portada": "...", "laminas": [{"titulo": "...", "texto": "..."}], "pregunta": "...", "mandar": "...", "pie": "párrafo 1\\n\\npárrafo 2\\n\\npregunta", "hashtags": ["#...", "#..."], "guion": ["portada", "lámina 1", "...", "cierre"]}"""


def _limpio(t, maximo=None):
    t = " ".join(str(t or "").replace("<a>", "").replace("</a>", "").split())
    return t[:maximo] if maximo else t


def ajustar_pie(cuerpo, etiquetas):
    """Une el texto y los hashtags sin pasar el límite de Telegram."""
    parrafos = [x.strip() for x in cuerpo.split("\n\n") if x.strip()]

    def unir(ps):
        return "\n\n".join(ps + [etiquetas])
    while len(parrafos) > 1 and len(unir(parrafos)) > LIMITE_PIE:
        parrafos.pop(-2 if len(parrafos) > 2 else -1)
    if len(unir(parrafos)) > LIMITE_PIE:
        parrafos = [parrafos[0][:LIMITE_PIE - len(etiquetas) - 5].rsplit(" ", 1)[0] + "…"]
    return unir(parrafos)


def limpiar_voz(t):
    t = re.sub(r"RD\$\s?", "", t)
    t = t.replace("%", " por ciento").replace("US$", "").replace("#", "").replace("@", "")
    t = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", t)
    return " ".join(t.split())


def redactar(historia, articulos):
    fuentes = [f"### {a['medio']}: {a['titulo']}\n{a['texto'] or a['resumen']}" for a in articulos]
    otros = [g for g in historia["grupo"] if g["link"] not in {a["link"] for a in articulos}]
    if otros:
        fuentes.append("### Otros titulares sobre el mismo hecho:\n" +
                       "\n".join(f"- {g['medio']}: {g['titulo']}" for g in otros))
    prompt = (f"Hora actual en RD: {ahora_rd().strftime('%d/%m/%Y %I:%M %p')}.\n"
              f"Categoría sugerida: {historia['categoria']}.\n"
              f"Historia triste: {'sí' if historia.get('triste') else 'no'}.\n\nFuentes:\n\n" + "\n\n".join(fuentes))
    d = como_objeto(gemini(prompt, sistema=SISTEMA_REDACCION, temperatura=0.7))

    laminas = []
    for l in d.get("laminas", [])[:5]:
        tit, tex = _limpio(l.get("titulo"), 60), _limpio(l.get("texto"), 260)
        if tit and len(tex.split()) >= 8:
            laminas.append({"titulo": tit, "texto": tex})
    if len(laminas) < 3:
        raise ErrorGemini("el carrusel salió con menos de 3 láminas")

    portada = re.sub(r"</?(?!a\b)[a-zA-Z][^>]*>", "", str(d.get("portada", ""))).strip()
    if not portada:
        raise ErrorGemini("el carrusel salió sin titular")
    if "<a>" not in portada.lower():
        p = portada.split()
        portada = "<a>" + " ".join(p[:2]) + "</a> " + " ".join(p[2:])
    categoria = str(d.get("categoria", historia["categoria"])).upper()
    categoria = "FARÁNDULA INTERNACIONAL" if "INTER" in categoria else "FARÁNDULA RD"
    pregunta = _limpio(d.get("pregunta"), 110) or "¿Y tú qué opinas?"
    mandar = _limpio(d.get("mandar"), 70)
    if not mandar.lower().startswith("mándaselo"):
        mandar = "Mándaselo a quien tiene que verlo"

    etiquetas = [ETIQUETA]
    for h in d.get("hashtags", []):
        h = "#" + re.sub(r"[^0-9A-Za-z]", "", sin_tildes(str(h)))
        if len(h) > 2 and h.lower() not in {e.lower() for e in etiquetas}:
            etiquetas.append(h)
    etiquetas = etiquetas[:5]  # Instagram permite 5
    pie = re.sub(r"#\w+", "", str(d.get("pie", ""))).strip()
    pie = re.sub(r"\n{3,}", "\n\n", pie)
    if pregunta.lower()[:20] not in pie.lower():
        pie = f"{pie}\n\n{pregunta}"

    total = len(laminas) + 2
    partes = d.get("guion") if isinstance(d.get("guion"), list) else []
    partes = [limpiar_voz(str(p)) for p in partes]
    if len(partes) != total or sum(len(p.split()) for p in partes) < 30:
        # sin guion útil: se arma con el texto de las láminas
        partes = ([limpiar_voz(_limpio(portada))] + [limpiar_voz(l["texto"]) for l in laminas]
                  + [limpiar_voz(pregunta)])
    if "coordenada 18" not in partes[-1].lower():
        partes[-1] = f"{partes[-1]} {CIERRE}".strip()

    return {
        "categoria": categoria,
        "antetitulo": _limpio(d.get("antetitulo"), 40),
        "portada": portada,
        "titulo_limpio": _limpio(portada),
        "laminas": laminas,
        "pregunta": pregunta,
        "mandar": mandar,
        "pie": ajustar_pie(pie, " ".join(etiquetas)),
        "guion": partes,
    }


# ----------------------------------------------------------------------------- Telegram

def tg(metodo, timeout=60, **kw):
    token = os.environ["TELEGRAM_TOKEN"]
    r = requests.post(f"https://api.telegram.org/bot{token}/{metodo}", timeout=timeout, **kw)
    datos = r.json()
    if not datos.get("ok"):
        raise RuntimeError(f"Telegram {metodo}: {datos.get('description')}")
    return datos["result"]


def chat_id():
    if os.getenv("TELEGRAM_CHAT_ID", "").strip():
        return os.environ["TELEGRAM_CHAT_ID"].strip()
    guardado = ""
    try:
        with open(CHAT_FILE, encoding="utf-8") as f:
            guardado = f.read().strip()
    except FileNotFoundError:
        pass
    if guardado:
        return guardado
    # Solo mira los mensajes, sin marcarlos como leídos (no le quita nada al bot de Coordenada 18)
    for upd in reversed(tg("getUpdates")):
        msg = upd.get("message") or upd.get("channel_post")
        if msg:
            cid = str(msg["chat"]["id"])
            os.makedirs(ESTADO, exist_ok=True)
            with open(CHAT_FILE, "w", encoding="utf-8") as f:
                f.write(cid)
            return cid
    raise RuntimeError("No encuentro tu chat de Telegram. Pon tu número de chat en el secreto TELEGRAM_CHAT_ID "
                       "(está en el archivo estado/chat_id.txt del repositorio de Coordenada 18).")


def enviar(cid, nota, laminas, video, dur):
    """Manda las láminas como álbum (con el texto en la primera) y el Reel. Devuelve el primer mensaje."""
    abiertos, media, archivos = [], [], {}
    try:
        for i, r in enumerate(laminas):
            f = open(r, "rb")
            abiertos.append(f)
            archivos[f"l{i}"] = (f"lamina{i + 1}.jpg", f, "image/jpeg")
            item = {"type": "photo", "media": f"attach://l{i}"}
            if i == 0:
                item["caption"] = nota["pie"]
            media.append(item)
        enviados = tg("sendMediaGroup", data={"chat_id": cid, "media": json.dumps(media)},
                      files=archivos, timeout=300)
    finally:
        for f in abiertos:
            f.close()
    if video:
        with open(video, "rb") as f:
            tg("sendVideo", data={"chat_id": cid, "caption": "🎬 Reel · " + nota["titulo_limpio"][:900],
                                  "supports_streaming": "true", "width": 1080, "height": 1920,
                                  "duration": int(dur)},
               files={"video": ("farandula.mp4", f, "video/mp4")}, timeout=300)
    return enviados[0]


def responder(cid, msg_id, texto):
    try:
        tg("sendMessage", data={"chat_id": cid, "text": texto, "reply_to_message_id": msg_id,
                                "disable_web_page_preview": True})
    except Exception as e:  # noqa: BLE001
        log(f"  no se pudo responder en Telegram: {e}")


# ----------------------------------------------------------------------------- Meta (Facebook e Instagram)

GRAPH = "https://graph.facebook.com/v27.0"
LIMITE_IG = 50
LIMITE_REELS_FB = 30
_IDS = {}


def meta_activo():
    return bool(os.getenv("META_PAGE_TOKEN", "").strip())


def graph(metodo, ruta, params=None, files=None):
    p = dict(params or {})
    p["access_token"] = os.environ["META_PAGE_TOKEN"].strip()
    if metodo == "GET":
        r = requests.get(f"{GRAPH}/{ruta}", params=p, timeout=60)
    else:
        r = requests.post(f"{GRAPH}/{ruta}", data=p, files=files, timeout=180)
    try:
        datos = r.json()
    except ValueError:
        raise RuntimeError(f"Meta respondió HTTP {r.status_code}") from None
    if isinstance(datos, dict) and "error" in datos:
        e = datos["error"]
        raise RuntimeError(f"Meta: {e.get('message')} (código {e.get('code')})")
    return datos


def ids_meta():
    """(id de la página de Facebook, id de la cuenta de Instagram). Si no están en las variables, se sacan del token."""
    if not _IDS:
        page = os.getenv("META_PAGE_ID", "").strip() or graph("GET", "me", {"fields": "id"})["id"]
        ig = os.getenv("META_IG_ID", "").strip()
        if not ig:
            ig = (graph("GET", page, {"fields": "instagram_business_account"})
                  .get("instagram_business_account") or {}).get("id", "")
        _IDS.update(page=page, ig=ig)
        log(f"  Meta: página {page}, Instagram {ig or '(no conectado)'}")
    return _IDS["page"], _IDS["ig"]


def subir_fotos_facebook(rutas):
    """Sube las láminas a la página sin publicarlas (para el álbum y para que Instagram las tome)."""
    page, _ = ids_meta()
    ids = []
    for r in rutas:
        with open(r, "rb") as f:
            ids.append(graph("POST", f"{page}/photos", params={"published": "false"},
                             files={"source": (os.path.basename(r), f.read(), "image/jpeg")})["id"])
    return ids


def url_foto_facebook(foto_id):
    imgs = graph("GET", foto_id, params={"fields": "images"}).get("images", [])
    if not imgs:
        raise RuntimeError("Facebook no devolvió el enlace de la imagen")
    return max(imgs, key=lambda i: i.get("width", 0))["source"]


def publicar_album_facebook(ids, texto):
    page, _ = ids_meta()
    params = {"message": texto}
    for i, fid in enumerate(ids):
        params[f"attached_media[{i}]"] = json.dumps({"media_fbid": fid})
    d = graph("POST", f"{page}/feed", params=params)
    return f"https://www.facebook.com/{d['id']}"


def _esperar(cont, intentos, pausa):
    for _ in range(intentos):
        estado = graph("GET", cont, params={"fields": "status_code"}).get("status_code")
        if estado == "FINISHED":
            return
        if estado in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram no aceptó el archivo ({estado})")
        time.sleep(pausa)
    raise RuntimeError("Instagram tardó demasiado procesando el archivo")


def _ig_publicar(cont, intentos, pausa):
    _, ig = ids_meta()
    _esperar(cont, intentos, pausa)
    media = graph("POST", f"{ig}/media_publish", params={"creation_id": cont})["id"]
    try:
        return graph("GET", media, params={"fields": "permalink"}).get("permalink") or "https://www.instagram.com/"
    except RuntimeError:
        return "https://www.instagram.com/"


def publicar_carrusel_instagram(urls, texto):
    _, ig = ids_meta()
    hijos = [graph("POST", f"{ig}/media", params={"image_url": u, "is_carousel_item": "true"})["id"]
             for u in urls[:10]]  # Instagram acepta hasta 10 por API
    for h in hijos:
        _esperar(h, 15, 2)
    cont = graph("POST", f"{ig}/media", params={"media_type": "CAROUSEL", "children": ",".join(hijos),
                                                 "caption": texto})["id"]
    return _ig_publicar(cont, 20, 3)


def _rupload(url, datos):
    token = os.environ["META_PAGE_TOKEN"].strip()
    r = requests.post(url, data=datos, timeout=600, headers={
        "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(datos)),
        "Content-Type": "application/octet-stream"})
    try:
        res = r.json()
    except ValueError:
        res = {}
    if r.status_code != 200 or (isinstance(res, dict) and "error" in res):
        detalle = res.get("error", {}).get("message") if isinstance(res, dict) and "error" in res else r.text[:200]
        raise RuntimeError(f"Meta no recibió el video: {detalle}")


def poner_portada_facebook(vid, portada, intentos=6, pausa=20):
    """Le pone al reel de Facebook la portada del carrusel. Si no, Facebook escoge un cuadro cualquiera."""
    ultimo = None
    for _ in range(intentos):
        try:
            with open(portada, "rb") as f:
                graph("POST", f"{vid}/thumbnails", params={"is_preferred": "true"},
                      files={"source": ("portada.jpg", f.read(), "image/jpeg")})
            log("  portada del reel de Facebook puesta")
            return True
        except (RuntimeError, OSError) as e:
            ultimo = e
            time.sleep(pausa)  # el video puede estar procesándose todavía
    log(f"  no se pudo poner la portada del reel de Facebook ({ultimo})")
    return False


def publicar_facebook_reel(video, texto, portada=None):
    page, _ = ids_meta()
    portada = portada if portada and os.path.exists(portada) else None
    try:
        ini = graph("POST", f"{page}/video_reels", params={"upload_phase": "start"})
        vid = ini["video_id"]
        _rupload(ini.get("upload_url") or f"https://rupload.facebook.com/video-upload/v27.0/{vid}", video)
        graph("POST", f"{page}/video_reels", params={
            "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED", "description": texto})
        if portada:
            poner_portada_facebook(vid, portada)
        return f"https://www.facebook.com/reel/{vid}"
    except RuntimeError as e:
        log(f"  reel de Facebook falló ({e}); se intenta como video normal")
        archivos = {"source": ("farandula.mp4", video, "video/mp4")}
        if portada:
            with open(portada, "rb") as f:
                archivos["thumb"] = ("portada.jpg", f.read(), "image/jpeg")
        d = graph("POST", f"{page}/videos", params={"description": texto}, files=archivos)
        return f"https://www.facebook.com/{page}/videos/{d['id']}"


def publicar_instagram_reel(video, texto):
    _, ig = ids_meta()
    c = graph("POST", f"{ig}/media", params={
        "media_type": "REELS", "upload_type": "resumable", "caption": texto, "share_to_feed": "true"})
    _rupload(c.get("uri") or f"https://rupload.facebook.com/ig-api-upload/v27.0/{c['id']}", video)
    return _ig_publicar(c["id"], 30, 10)


def cupo_instagram():
    _, ig = ids_meta()
    try:
        d = graph("GET", f"{ig}/content_publishing_limit", params={"fields": "quota_usage,config"})
        datos = (d.get("data") or [{}])[0]
        total = (datos.get("config") or {}).get("quota_total", LIMITE_IG)
        return max(0, int(total) - int(datos.get("quota_usage", 0)))
    except (RuntimeError, ValueError, TypeError, AttributeError, IndexError):
        return LIMITE_IG


def publicar(laminas, video, texto, historial):
    """Publica el carrusel y el Reel en Instagram y Facebook. Devuelve (líneas para Telegram, datos)."""
    lineas, info = [], {}
    try:
        page, ig = ids_meta()
    except Exception as e:  # noqa: BLE001
        return [f"⚠️ No pude entrar a Meta con el token: {str(e)[:250]}"], info
    hace24 = ahora_utc() - dt.timedelta(hours=24)
    reels_fb = sum(1 for h in historial if h.get("fb_reel") and dt.datetime.fromisoformat(h["fecha"]) > hace24)
    cupo = cupo_instagram() if ig else 0

    ids = []
    try:
        ids = subir_fotos_facebook(laminas)
    except Exception as e:  # noqa: BLE001
        log(f"  subir las láminas a Facebook falló: {e}")
        lineas.append(f"⚠️ No se pudieron subir las láminas a Facebook: {str(e)[:250]}")
    if ids and ig and cupo > (1 if video else 0):
        try:
            urls = [url_foto_facebook(i) for i in ids]
            lineas.append(f"🖼️ Carrusel en Instagram: {publicar_carrusel_instagram(urls, texto)}")
            cupo -= 1
            info["ig_carrusel"] = True
        except Exception as e:  # noqa: BLE001
            log(f"  carrusel en Instagram falló: {e}")
            lineas.append(f"⚠️ Carrusel en Instagram no salió: {str(e)[:250]}")
    elif ids and not ig:
        lineas.append("⚠️ La página de Facebook no tiene Instagram conectado.")
    elif ids:
        lineas.append("⏸️ Carrusel en Instagram: se llegó al límite de publicaciones del día.")
    if ids:
        try:
            lineas.append(f"🖼️ Álbum en Facebook: {publicar_album_facebook(ids, texto)}")
            info["fb_album"] = True
        except Exception as e:  # noqa: BLE001
            log(f"  álbum en Facebook falló: {e}")
            lineas.append(f"⚠️ Álbum en Facebook no salió: {str(e)[:250]}")

    if video:
        with open(video, "rb") as f:
            datos = f.read()
        if ig and cupo > 0:
            try:
                lineas.append(f"🎬 Reel en Instagram: {publicar_instagram_reel(datos, texto)}")
                info["ig_reel"] = True
            except Exception as e:  # noqa: BLE001
                log(f"  reel en Instagram falló: {e}")
                lineas.append(f"⚠️ Reel en Instagram no salió: {str(e)[:250]}")
        if reels_fb < LIMITE_REELS_FB - 1:
            try:
                portada = f18_video.ruta_portada(video)
                lineas.append(f"🎬 Reel en Facebook: {publicar_facebook_reel(datos, texto, portada)}")
                info["fb_reel"] = True
            except Exception as e:  # noqa: BLE001
                log(f"  reel en Facebook falló: {e}")
                lineas.append(f"⚠️ Reel en Facebook no salió: {str(e)[:250]}")
    return lineas, info


# ----------------------------------------------------------------------------- ronda

def ronda(cantidad, sin_enviar=False):
    os.makedirs(SALIDA, exist_ok=True)
    inicio = time.time()
    cid = None if sin_enviar else chat_id()  # primero: si no hay chat, no se gasta nada
    historial = cargar_historial()
    urls_publicadas = {u for h in historial for u in h.get("urls", [])}

    log("Leyendo medios…")
    items = leer_medios(urls_publicadas)
    if not any(i["directo"] for i in items):
        raise RuntimeError("No se pudo leer ningún medio.")

    log(f"Escogiendo historias entre {len(items)} titulares…")
    candidatas = seleccionar(items, historial, cantidad)
    log(f"  {len(candidatas)} candidatas ({time.time() - inicio:.0f} s)")

    hace4 = ahora_utc() - dt.timedelta(days=4)
    recientes = [h for h in historial if dt.datetime.fromisoformat(h["fecha"]) > hace4]
    usadas = {"urls": {h["foto"] for h in recientes if h.get("foto")},
              "huellas": {h["huella"] for h in recientes if h.get("huella")}}

    hechas = []
    for historia in candidatas:
        if len(hechas) >= cantidad:
            break
        if time.time() - inicio > LIMITE_SEGUNDOS:
            log("\nSe acabó el tiempo de esta ronda; lo demás queda para la próxima.")
            break
        log(f"\n→ {historia['tema']}")
        directos = [g for g in historia["grupo"] if g["directo"]][:3]
        with ThreadPoolExecutor(max_workers=3) as ex:
            leidos = list(ex.map(leer_articulo, [g["link"] for g in directos]))
        articulos = [{**g, **art} for g, art in zip(directos, leidos)]
        if not any(len(a["texto"]) >= 250 for a in articulos):
            log("    sin texto suficiente, se salta")
            continue

        n = len(hechas) + 1
        fotos = [(a["imagen"], a["medio"], a["link"]) for a in articulos if a.get("imagen")]
        fotos += [(u, a["medio"], a["link"]) for a in articulos for u in a.get("imagenes", [])]
        ruta_foto, foco, medio_foto, url_foto, huella_foto = buscar_foto(
            fotos, directos[0]["titulo"], os.path.join(SALIDA, f"foto{n}.jpg"), usadas)
        if not ruta_foto:
            log("    sin foto limpia (o solo fotos ya usadas), se salta")
            continue
        usadas["urls"].add(url_foto)
        usadas["huellas"].add(huella_foto)
        log(f"    foto de: {medio_foto}")

        try:
            nota = redactar(historia, articulos)
        except ErrorGemini as e:
            log(f"    no se pudo redactar: {e}")
            continue

        carpeta = os.path.join(SALIDA, f"carrusel{n}")
        laminas = f18_render.render_carrusel(ruta_foto, nota, carpeta, "lamina", foco)
        para_reel = f18_render.render_carrusel(ruta_foto, nota, carpeta, "reel", foco, desliza=False)
        video, dur = os.path.join(SALIDA, f"reel{n}.mp4"), 0
        try:
            video, dur = f18_video.render_reel(para_reel, nota["guion"], video)
        except Exception as e:  # noqa: BLE001
            log(f"    el Reel falló ({e}); sale solo el carrusel")
            video = None
        with open(os.path.join(SALIDA, f"carrusel{n}.txt"), "w", encoding="utf-8") as f:
            f.write(nota["titulo_limpio"] + "\n\n" + nota["pie"] + "\n\nGUION:\n" + "\n".join(nota["guion"]) + "\n")
        log(f"    ✔ {nota['titulo_limpio']} ({len(laminas)} láminas, {time.time() - inicio:.0f} s)")
        hechas.append((historia, nota, laminas, video))

        if sin_enviar:
            continue
        primero = enviar(cid, nota, laminas, video, dur)
        publicado = {}
        if meta_activo():
            log("    publicando en Instagram y Facebook…")
            lineas, publicado = publicar(laminas, video, nota["pie"], historial)
            responder(cid, primero["message_id"], "\n".join(lineas))
        historial.append({
            **publicado,
            "fecha": ahora_utc().isoformat(timespec="seconds"),
            "tema": historia["tema"], "titulo": nota["titulo_limpio"],
            "urls": [g["link"] for g in historia["grupo"] if g["directo"]],
            "foto": url_foto, "huella": huella_foto,
        })
        guardar_historial(historial)

    if not hechas and not sin_enviar:
        tg("sendMessage", data={"chat_id": cid, "text":
            f"{MARCA} · ronda de las {ahora_rd().strftime('%I:%M %p')}: no encontré una historia nueva "
            "confirmada en 2 medios y con foto limpia. Pruebo otra vez en la próxima ronda."})
    log(f"\nListo: {len(hechas)} carrusel(es) en {time.time() - inicio:.0f} s.")
    return hechas


def main():
    p = argparse.ArgumentParser(description="Ronda de Coordenada 18 Farándula")
    p.add_argument("--cantidad", type=int, default=int(os.getenv("CANTIDAD", "1") or 1))
    p.add_argument("--sin-enviar", action="store_true", help="prueba: guarda en salida/ y no manda nada")
    a = p.parse_args()
    try:
        ronda(a.cantidad, a.sin_enviar)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        if not a.sin_enviar and os.getenv("TELEGRAM_TOKEN"):
            try:
                tg("sendMessage", data={"chat_id": chat_id(),
                                        "text": f"⚠️ El bot de {MARCA} tuvo un error en esta ronda: {str(e)[:300]}"})
            except Exception:  # noqa: BLE001
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
