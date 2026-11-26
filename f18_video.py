#!/usr/bin/env python3
"""Reel de Coordenada 18 Farándula (1080x1920) hecho con las láminas del carrusel.

- Cada lámina sale en pantalla mientras la voz cuenta esa parte de la historia
  (el guion viene dividido en partes, una por lámina).
- Fondo: la portada desenfocada. Transición suave entre láminas y un acercamiento leve.
- Subtítulos de la narración debajo de la lámina.
- Voz: es-DO-RamonaNeural (Microsoft, dominicana). Si falla, voz de Gemini.
  Si fallan las dos, sale sin voz y con subtítulos a ritmo de lectura.

Las láminas quedan dentro de la zona segura de Reels (lejos de los botones de la derecha y
del texto de abajo).
"""
import asyncio
import base64
import os
import subprocess
import tempfile
import wave

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

import c18_render as R

W, H = 1080, 1920
FPS = 30
VOZ = os.getenv("VOZ", "").strip() or "es-DO-RamonaNeural"
VOZ_GEMINI = "Kore"
MODELOS_TTS = ["gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"]
MAX_SEG = 45.0
LAM_W, LAM_H = 900, 1125      # 4:5, como el carrusel
LAM_X, LAM_Y = 40, 215
TRANSICION = 0.30


def log(*a):
    print(*a, flush=True)


def duracion(ruta):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", ruta], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ----------------------------------------------------------------------------- voz

async def _edge(texto, ruta, velocidad):
    import edge_tts
    try:
        com = edge_tts.Communicate(texto, VOZ, rate=velocidad, boundary="WordBoundary")
    except TypeError:  # versiones viejas de edge-tts
        com = edge_tts.Communicate(texto, VOZ, rate=velocidad)
    palabras = []
    with open(ruta, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                ini = ch["offset"] / 1e7
                palabras.append((ch["text"], ini, ini + ch["duration"] / 1e7))
    return palabras


def voz_microsoft(texto, ruta):
    palabras = asyncio.run(_edge(texto, ruta, "+8%"))
    if duracion(ruta) > MAX_SEG:
        palabras = asyncio.run(_edge(texto, ruta, "+20%"))
    if os.path.getsize(ruta) < 2000:
        raise RuntimeError("la voz de Microsoft no devolvió audio")
    return palabras


def voz_gemini(texto, ruta_wav):
    clave = os.environ["GEMINI_API_KEY"]
    ultimo = ""
    for modelo in MODELOS_TTS:
        cuerpo = {
            "contents": [{"parts": [{"text": "Lee esto como una presentadora dominicana de farándula, "
                                             "con energía, picardía y ritmo ágil:\n\n" + texto}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOZ_GEMINI}}},
            },
        }
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                          json=cuerpo, timeout=(10, 120),
                          headers={"x-goog-api-key": clave, "Content-Type": "application/json"})
        if r.status_code != 200:
            ultimo = f"{modelo} HTTP {r.status_code}: {r.text[:150]}"
            continue
        try:
            datos = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        except (KeyError, IndexError, ValueError):
            ultimo = f"{modelo}: respuesta sin audio"
            continue
        with wave.open(ruta_wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(base64.b64decode(datos))
        return
    raise RuntimeError(f"voz de Gemini: {ultimo}")


def tiempos_aproximados(texto, total, inicio=0.15):
    palabras = texto.split()
    pesos = [len(p) + 2 for p in palabras]
    escala = (total - inicio - 0.2) / max(1, sum(pesos))
    t, out = inicio, []
    for p, w in zip(palabras, pesos):
        out.append((p, t, t + w * escala))
        t += w * escala
    return out


def preparar_voz(texto, carpeta):
    """Devuelve (ruta_audio o None, palabras con tiempos, duración del video)."""
    mp3 = os.path.join(carpeta, "voz.mp3")
    try:
        palabras = voz_microsoft(texto, mp3)
        dur = duracion(mp3)
        if not palabras:
            palabras = tiempos_aproximados(texto, dur)
        log(f"    voz: {VOZ} ({dur:.1f} s)")
        return mp3, palabras, dur + 0.9
    except Exception as e:  # noqa: BLE001
        log(f"    voz de Microsoft falló: {e}")
    wav = os.path.join(carpeta, "voz.wav")
    try:
        voz_gemini(texto, wav)
        dur = duracion(wav)
        log(f"    voz: Gemini ({dur:.1f} s)")
        return wav, tiempos_aproximados(texto, dur), dur + 0.9
    except Exception as e:  # noqa: BLE001
        log(f"    voz de Gemini falló: {e}")
    dur = min(40.0, max(15.0, len(texto.split()) / 2.6))
    log("    sin voz: subtítulos a ritmo de lectura")
    return None, tiempos_aproximados(texto, dur), dur


# ----------------------------------------------------------------------------- tiempos de cada lámina

def inicios_laminas(partes, palabras, dur):
    """Momento en que empieza cada lámina, según en qué palabra empieza su parte del guion."""
    n_total = sum(len(p.split()) for p in partes) or 1
    escala = len(palabras) / n_total if palabras else 0
    inicios, acum = [], 0
    for p in partes:
        if palabras:
            i = min(len(palabras) - 1, int(round(acum * escala)))
            inicios.append(max(0.0, palabras[i][1] - 0.15))
        else:
            inicios.append(dur * acum / n_total)
        acum += len(p.split())
    inicios[0] = 0.0
    # cada lámina al menos 1.6 s en pantalla
    for k in range(1, len(inicios)):
        inicios[k] = max(inicios[k], inicios[k - 1] + 1.6)
    return [min(t, dur - 1.0) for t in inicios]


# ----------------------------------------------------------------------------- subtítulos

def grupos_subtitulos(palabras, max_palabras=5, max_letras=28):
    grupos, act = [], []
    for p in palabras:
        texto_act = " ".join(x[0] for x in act + [p])
        if act and (len(act) >= max_palabras or len(texto_act) > max_letras):
            grupos.append(act)
            act = []
        act.append(p)
        if p[0].endswith((".", "?", "!", ":")):
            grupos.append(act)
            act = []
    if act:
        grupos.append(act)
    out = []
    for i, g in enumerate(grupos):
        ini = g[0][1]
        fin = grupos[i + 1][0][1] if i + 1 < len(grupos) else g[-1][2] + 0.4
        out.append((" ".join(x[0] for x in g), ini, max(fin, ini + 0.3)))
    return out


def capa_subtitulo(texto):
    f = R.fuente("Montserrat.ttf", 50, 800)
    ancho_max = LAM_W - 60
    palabras, lineas, act = texto.split(), [], ""
    for p in palabras:
        prueba = (act + " " + p).strip()
        if act and f.getlength(prueba) > ancho_max:
            lineas.append(act)
            act = p
        else:
            act = prueba
    if act:
        lineas.append(act)
    alto_l = 64
    w_txt = max(f.getlength(l) for l in lineas)
    cw, ch = int(w_txt + 56), int(alto_l * len(lineas) + 26)
    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, cw - 1, ch - 1], radius=20, fill=(232, 28, 120, 235))
    for i, l in enumerate(lineas):
        d.text(((cw - f.getlength(l)) / 2, 10 + i * alto_l), l, font=f, fill=(255, 255, 255, 255))
    return img


# ----------------------------------------------------------------------------- video

def ruta_portada(video):
    """Dónde queda la imagen de portada del reel."""
    return os.path.splitext(video)[0] + "_portada.jpg"


def render_reel(laminas, partes_guion, salida):
    """laminas: rutas de las láminas en orden. partes_guion: un texto por lámina.
    Devuelve (ruta, duración en segundos)."""
    R.asegurar_fuentes()
    imgs = [Image.open(p).convert("RGB") for p in laminas]
    partes = list(partes_guion)[:len(imgs)]
    while len(partes) < len(imgs):
        partes.append("")
    guion = " ".join(p.strip() for p in partes if p.strip())
    with tempfile.TemporaryDirectory() as tmp:
        audio, palabras, dur = preparar_voz(guion, tmp)
        n_frames = int(dur * FPS)
        inicios = inicios_laminas([p or "." for p in partes], palabras, dur)

        fondo = imgs[0].resize((W, int(W * imgs[0].height / imgs[0].width)), Image.LANCZOS)
        fondo = fondo.resize((int(fondo.width * H / fondo.height), H), Image.LANCZOS)
        x0 = (fondo.width - W) // 2
        fondo = fondo.crop((x0, 0, x0 + W, H)).filter(ImageFilter.GaussianBlur(40))
        fondo = ImageEnhance.Brightness(fondo).enhance(0.35)

        grandes = [im.resize((int(LAM_W * 1.04), int(LAM_H * 1.04)), Image.LANCZOS) for im in imgs]
        sombra = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sombra).rounded_rectangle([LAM_X + 4, LAM_Y + 10, LAM_X + LAM_W + 4, LAM_Y + LAM_H + 10],
                                                 radius=28, fill=(0, 0, 0, 170))
        fondo = Image.alpha_composite(fondo.convert("RGBA"), sombra.filter(ImageFilter.GaussianBlur(14))).convert("RGB")
        mascara = Image.new("L", (LAM_W, LAM_H), 0)
        ImageDraw.Draw(mascara).rounded_rectangle([0, 0, LAM_W - 1, LAM_H - 1], radius=28, fill=255)
        subs = [(capa_subtitulo(t), ini, fin) for t, ini, fin in grupos_subtitulos(palabras)]

        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
        if audio:
            cmd += ["-i", audio]
        else:
            cmd += ["-f", "lavfi", "-t", f"{dur:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-g", str(FPS * 2), "-keyint_min", str(FPS * 2), "-sc_threshold", "0",
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                "-t", f"{dur:.2f}", "-movflags", "+faststart", salida]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

        def cuadro_lamina(k, t):
            ini = inicios[k]
            fin = inicios[k + 1] if k + 1 < len(inicios) else dur
            avance = min(1.0, max(0.0, (t - ini) / max(0.5, fin - ini)))
            z = 1.0 + 0.04 * avance
            g = grandes[k]
            vw, vh = g.width / 1.04 / z * 1.0, g.height / 1.04 / z * 1.0
            bx = (g.width - vw) / 2
            by = (g.height - vh) / 2
            return g.resize((LAM_W, LAM_H), Image.BILINEAR, box=(bx, by, bx + vw, by + vh))

        # Portada limpia del reel (primer cuadro, sin subtítulo), para que Facebook no escoja un cuadro cualquiera
        portada = fondo.copy()
        portada.paste(cuadro_lamina(0, 0.0), (LAM_X, LAM_Y), mascara)
        portada.save(ruta_portada(salida), quality=92)

        for i in range(n_frames):
            t = i / FPS
            k = max(j for j, ini in enumerate(inicios) if ini <= t)
            frame = fondo.copy()
            actual = cuadro_lamina(k, t)
            if k > 0 and t - inicios[k] < TRANSICION:
                previa = cuadro_lamina(k - 1, t)
                actual = Image.blend(previa, actual, (t - inicios[k]) / TRANSICION)
            frame.paste(actual, (LAM_X, LAM_Y), mascara)
            for img, ini, fin in subs:
                if ini <= t < fin:
                    frame.paste(img, (LAM_X + (LAM_W - img.width) // 2, LAM_Y + LAM_H + 36), img)
                    break
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg no pudo armar el video")

    if os.path.getsize(salida) > 18_000_000:  # Telegram solo deja bajar hasta 20 MB
        tmp_out = salida + ".tmp.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", salida, "-c:v", "libx264", "-preset",
                        "veryfast", "-crf", "28", "-g", str(FPS * 2), "-c:a", "copy",
                        "-movflags", "+faststart", tmp_out], check=True)
        os.replace(tmp_out, salida)
    return salida, dur
