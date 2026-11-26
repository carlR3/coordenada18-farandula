#!/usr/bin/env python3
"""Láminas del carrusel de Coordenada 18 Farándula (1080x1350, 4:5).

- Portada: foto completa, gancho corto en amarillo y titular grande (blanco + amarillo con <a>).
- Láminas de la historia: la foto arriba (con otro encuadre en cada lámina), número, título y texto.
- Cierre: pregunta para comentar y llamada a mandarlo, guardarlo y seguir la cuenta.

Todo el texto queda dentro del diseño; la foto nunca va sola.
"""
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

import c18_render as R

W, H = 1080, 1350
MAGENTA = (232, 28, 120)
AMARILLO = R.AMARILLO
BLANCO = R.BLANCO
NOCHE = (14, 12, 38)
MORADO = (52, 16, 78)
MARGEN = 64
NOMBRE = "COORDENADA 18 FARÁNDULA"


def _f(tam, peso=800):
    return R.fuente("Montserrat.ttf", tam, peso)


def cubrir(img, w, h, fx=0.5, fy=0.4, zoom=1.0):
    iw, ih = img.size
    e = max(w / iw, h / ih) * zoom
    img = img.resize((max(w, round(iw * e)), max(h, round(ih * e))), Image.LANCZOS)
    x = min(max(int(img.width * fx - w / 2), 0), img.width - w)
    y = min(max(int(img.height * fy - h / 2), 0), img.height - h)
    return img.crop((x, y, x + w, y + h))


def degradado_vertical(w, h, desde, hasta, a0, a1, inicio=0.0):
    """Capa RGBA que pasa de color/alfa a0 a a1 desde la fracción `inicio` hasta abajo."""
    capa = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(capa)
    y0 = int(h * inicio)
    for y in range(h):
        t = 0.0 if y < y0 else (y - y0) / max(1, h - y0)
        t = t * t * (3 - 2 * t)  # suave
        col = tuple(int(desde[i] * (1 - t) + hasta[i] * t) for i in range(3))
        d.line([(0, y), (w, y)], fill=col + (int(a0 * (1 - t) + a1 * t),))
    return capa


def emblema(alto):
    """Círculo del logo de Coordenada 18 (sin la palabra NOTICIAS) con borde blanco."""
    ruta = os.path.join(R.AQUI, "logo_c18.png")
    lg = Image.open(ruta).convert("RGBA").crop((0, 0, 230, 194))
    lg = lg.resize((int(lg.width * alto / lg.height), alto), Image.LANCZOS)
    marco = Image.new("RGBA", (lg.width + 14, lg.height + 14), (0, 0, 0, 0))
    marco.alpha_composite(lg, (7, 7))
    alfa = marco.split()[3].filter(ImageFilter.MaxFilter(7))
    borde = Image.new("RGBA", marco.size, (255, 255, 255, 0))
    borde.putalpha(alfa)
    out = Image.new("RGBA", marco.size, (0, 0, 0, 0))
    out.alpha_composite(borde)
    out.alpha_composite(marco)
    return out


def marca(alto=96):
    """Emblema + 'COORDENADA 18' y cinta magenta 'FARÁNDULA'."""
    em = emblema(alto)
    f1, f2 = _f(int(alto * 0.27), 900), _f(int(alto * 0.25), 900)
    t1, t2 = "COORDENADA 18", "FARÁNDULA"
    w1 = R.ancho_txt(f1, t1, 1.5)
    w2 = R.ancho_txt(f2, t2, 3)
    ancho = em.width + 14 + int(max(w1, w2 + 28))
    img = Image.new("RGBA", (ancho, em.height), (0, 0, 0, 0))
    img.alpha_composite(em, (0, 0))
    d = ImageDraw.Draw(img)
    x = em.width + 14
    y1 = em.height * 0.18
    R.dibujar_txt(d, x, y1, t1, f1, BLANCO, 1.5, sombra=True)
    cy = em.height * 0.56
    alto_cinta = int(alto * 0.36)
    d.rounded_rectangle([x, cy, x + w2 + 28, cy + alto_cinta], radius=8, fill=MAGENTA)
    R.dibujar_txt(d, x + 14, cy + (alto_cinta - f2.getbbox("H")[3]) / 2 - 1, t2, f2, BLANCO, 3)
    return img


def pegar_sombra(base, capa, pos, radio=8, alfa=150):
    sombra = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sombra.paste(Image.new("RGBA", capa.size, (0, 0, 0, alfa)), (pos[0] + 3, pos[1] + 5), capa.split()[3])
    base.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(radio)))
    base.alpha_composite(capa, pos)


def pastilla(d, x, y, texto, tam=30, fondo=MAGENTA, color=BLANCO, trk=2.5):
    f = _f(tam, 900)
    w = R.ancho_txt(f, texto, trk)
    alto = int(tam * 1.55)
    d.rounded_rectangle([x, y, x + w + tam * 1.1, y + alto], radius=alto // 2, fill=fondo)
    R.dibujar_txt(d, x + tam * 0.55, y + (alto - f.getbbox("H")[3]) / 2 - 1, texto, f, color, trk)
    return x + w + tam * 1.1, y + alto


def envolver(texto, f, ancho):
    lineas, act = [], ""
    for p in texto.split():
        prueba = (act + " " + p).strip()
        if act and f.getlength(prueba) > ancho:
            lineas.append(act)
            act = p
        else:
            act = prueba
    if act:
        lineas.append(act)
    return lineas


def titular(d, capa, titulo, x, y_base, ancho, max_lineas=5, tam_max=86, tam_min=50):
    """Titular en mayúsculas (blanco + amarillo) apoyado por abajo en y_base. Devuelve el y de arriba."""
    toks = R.tokens(titulo)
    for tam in range(tam_max, tam_min - 1, -2):
        f = _f(tam, 900)
        trk = tam * 0.02
        lineas = R.maquetar(toks, f, trk, ancho, 0)
        if len(lineas) <= max_lineas:
            break
    alto_l = int(tam * 1.12)
    y = y_base - alto_l * len(lineas)
    arriba = y
    for linea in lineas:
        xx = x
        for j, (w, c, pg) in enumerate(linea):
            if j > 0:
                xx += trk if pg else f.getlength(" ") + 2 * trk
            xx = R.dibujar_txt(d, xx, y, w, f, c, trk, sombra=True) - trk
        y += alto_l
    return arriba


def translucido(img, dibujar):
    """Dibuja con transparencia real (ImageDraw sobre RGBA reemplaza píxeles en vez de mezclarlos)."""
    capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dibujar(ImageDraw.Draw(capa))
    img.alpha_composite(capa)
    return ImageDraw.Draw(img)


def puntos(img, n, actual, y, x=MARGEN):
    def dib(d):
        xx = x
        for i in range(n):
            w = 46 if i == actual else 16
            col = AMARILLO + (255,) if i == actual else (255, 255, 255, 120)
            d.rounded_rectangle([xx, y, xx + w, y + 12], radius=6, fill=col)
            xx += w + 10
    return translucido(img, dib)


def flecha_desliza(d, x_der, y):
    f = _f(30, 900)
    t = "DESLIZA"
    w = R.ancho_txt(f, t, 3)
    x = x_der - w - 70
    R.dibujar_txt(d, x, y, t, f, BLANCO, 3, sombra=True)
    cx = x_der - 46
    for k in range(2):
        ox = cx + k * 20
        d.line([(ox, y + 6), (ox + 14, y + 19), (ox, y + 32)], fill=AMARILLO, width=6, joint="curve")


def fondo_oscuro(foto, fx, fy):
    """Fondo de las láminas: la foto desenfocada y oscurecida con un tinte morado."""
    base = cubrir(foto, W, H, fx, fy).filter(ImageFilter.GaussianBlur(28))
    base = ImageEnhance.Brightness(base).enhance(0.45).convert("RGBA")
    tinte = degradado_vertical(W, H, MORADO, NOCHE, 150, 235)
    return Image.alpha_composite(base, tinte)


# ----------------------------------------------------------------------------- láminas

def portada(foto, titulo, antetitulo, categoria, total, salida, foco=(0.5, 0.35), desliza=True):
    R.asegurar_fuentes()
    img = cubrir(foto, W, H, *foco).convert("RGBA")
    img.alpha_composite(degradado_vertical(W, H, (0, 0, 0), (8, 4, 20), 0, 245, inicio=0.30))
    img.alpha_composite(degradado_vertical(W, 260, (0, 0, 0), (0, 0, 0), 150, 0), (0, 0))
    d = ImageDraw.Draw(img)

    pastilla(d, MARGEN, 70, categoria.upper(), 28)
    m = marca(92)
    pegar_sombra(img, m, (W - MARGEN - m.width, 52))
    d = ImageDraw.Draw(img)

    arriba = titular(d, img, titulo, MARGEN, H - 150, W - 2 * MARGEN)
    if antetitulo:
        f = _f(40, 900)
        t = antetitulo.upper()
        w = R.ancho_txt(f, t, 2)
        y = arriba - 78
        d.rectangle([MARGEN, y + 4, MARGEN + 10, y + 50], fill=MAGENTA)
        R.dibujar_txt(d, MARGEN + 26, y + 4, t, f, AMARILLO, 2, sombra=True)
        _ = w
    d = puntos(img, total, 0, H - 78)
    if desliza:
        flecha_desliza(d, W - MARGEN, H - 92)
    img.convert("RGB").save(salida, "JPEG", quality=93)
    return salida


def lamina(foto, numero, total, titulo, texto, salida, foco=(0.5, 0.35), desliza=True):
    R.asegurar_fuentes()
    fx, fy = foco
    img = fondo_oscuro(foto, fx, fy)
    # foto arriba con otro encuadre en cada lámina (acercamientos distintos)
    alto_foto = 560
    zoom = [1.0, 1.25, 1.12, 1.4, 1.18][(numero - 1) % 5]
    desp = [0, -0.08, 0.08, 0, -0.05][(numero - 1) % 5]
    franja = cubrir(foto, W, alto_foto, min(1, max(0, fx + desp)), fy, zoom).convert("RGBA")
    mascara = Image.new("L", (W, alto_foto), 255)
    dm = ImageDraw.Draw(mascara)
    for y in range(alto_foto - 220, alto_foto):
        t = (y - (alto_foto - 220)) / 220
        dm.line([(0, y), (W, y)], fill=int(255 * (1 - t * t)))
    img.paste(franja, (0, 0), mascara)
    d = ImageDraw.Draw(img)
    m = marca(72)
    pegar_sombra(img, m, (W - MARGEN - m.width, 44))
    d = ImageDraw.Draw(img)

    # número grande + título
    y = alto_foto - 70
    fn = _f(120, 900)
    num = f"{numero:02d}"
    R.dibujar_txt(d, MARGEN - 4, y, num, fn, MAGENTA, 0, sombra=True)
    x_t = MARGEN + R.ancho_txt(fn, num, 0) + 26
    ft_tam = 50
    ancho_t = W - MARGEN - x_t
    t_may = titulo.upper()
    while ft_tam > 32:
        ft = _f(ft_tam, 900)
        lt = envolver(t_may, ft, ancho_t)
        if len(lt) <= 2:
            break
        ft_tam -= 2
    yt = y + 64 - (len(lt) * ft_tam * 1.08) / 2
    for l in lt:
        R.dibujar_txt(d, x_t, yt, l, ft, AMARILLO, 0.6, sombra=True)
        yt += ft_tam * 1.08

    # texto
    y_ini, y_fin = alto_foto + 100, H - 140
    for tam in range(60, 33, -2):
        fb = _f(tam, 600)
        lineas = envolver(texto, fb, W - 2 * MARGEN)
        if len(lineas) * tam * 1.38 <= y_fin - y_ini:
            break
    y = y_ini + max(0, (y_fin - y_ini - len(lineas) * tam * 1.38) * 0.35)
    for l in lineas:
        d.text((MARGEN + 2, y + 3), l, font=fb, fill=(0, 0, 0, 120))
        d.text((MARGEN, y), l, font=fb, fill=BLANCO)
        y += tam * 1.38

    d = puntos(img, total, numero, H - 78)
    if desliza and numero < total - 1:
        flecha_desliza(d, W - MARGEN, H - 92)
    img.convert("RGB").save(salida, "JPEG", quality=93)
    return salida


def _icono_avion(d, x, y, s, col):
    d.polygon([(x, y + s * 0.45), (x + s, y), (x + s * 0.62, y + s), (x + s * 0.45, y + s * 0.6)], fill=col)
    d.line([(x + s * 0.45, y + s * 0.6), (x + s, y)], fill=MAGENTA, width=3)


def _icono_guardar(d, x, y, s, col):
    d.polygon([(x + s * 0.15, y), (x + s * 0.85, y), (x + s * 0.85, y + s),
               (x + s * 0.5, y + s * 0.72), (x + s * 0.15, y + s)], fill=col)


def _icono_seguir(d, x, y, s, col):
    d.ellipse([x + s * 0.25, y, x + s * 0.75, y + s * 0.5], fill=col)
    d.pieslice([x, y + s * 0.5, x + s, y + s * 1.5], 180, 360, fill=col)


def cierre(foto, total, pregunta, mandar, salida, foco=(0.5, 0.35)):
    R.asegurar_fuentes()
    img = fondo_oscuro(foto, *foco)
    d = ImageDraw.Draw(img)
    m = marca(120)
    pegar_sombra(img, m, ((W - m.width) // 2, 90))
    d = ImageDraw.Draw(img)

    y = 330
    for linea in ("¿Y TÚ QUÉ", "OPINAS?"):
        f = _f(108, 900)
        R.dibujar_txt(d, (W - R.ancho_txt(f, linea, 1)) / 2, y, linea, f, AMARILLO, 1, sombra=True)
        y += 118
    y += 24
    for tam in range(50, 33, -2):
        fp = _f(tam, 700)
        lp = envolver(pregunta, fp, W - 2 * MARGEN - 40)
        if len(lp) <= 3:
            break
    for l in lp:
        d.text(((W - fp.getlength(l)) / 2, y), l, font=fp, fill=BLANCO)
        y += tam * 1.3
    y += 40

    filas = [(_icono_avion, mandar or "Mándaselo a quien tiene que verlo"),
             (_icono_guardar, "Guárdalo para que no se te pierda"),
             (_icono_seguir, "Síguenos para más farándula")]
    for icono, texto in filas:
        caja_alto = 104
        d = translucido(img, lambda dd, y=y: dd.rounded_rectangle(
            [MARGEN, y, W - MARGEN, y + caja_alto], radius=26,
            fill=(255, 255, 255, 30), outline=(255, 255, 255, 80), width=2))
        d.ellipse([MARGEN + 22, y + 17, MARGEN + 92, y + 87], fill=MAGENTA)
        icono(d, MARGEN + 38, y + 33, 38, BLANCO)
        for tam in range(38, 25, -1):
            ff = _f(tam, 800)
            if ff.getlength(texto) <= W - 2 * MARGEN - 140:
                break
        d.text((MARGEN + 116, y + (caja_alto - tam * 1.2) / 2), texto, font=ff, fill=BLANCO)
        y += caja_alto + 22

    d = puntos(img, total, total - 1, H - 78)
    f = _f(26, 700)
    t = "Noticias del país: @coordenada18"
    d.text((W - MARGEN - f.getlength(t), H - 90), t, font=f, fill=(225, 225, 235))
    img.convert("RGB").save(salida, "JPEG", quality=93)
    return salida


def render_carrusel(foto_path, nota, carpeta, prefijo="lamina", foco=(0.5, 0.35), desliza=True):
    """Arma todas las láminas. Devuelve la lista de rutas en orden.
    desliza=False: sin la flecha de «DESLIZA» (para las láminas que van en el Reel)."""
    os.makedirs(carpeta, exist_ok=True)
    foto = Image.open(foto_path).convert("RGB")
    laminas = nota["laminas"]
    total = len(laminas) + 2
    rutas = [portada(foto, nota["portada"], nota.get("antetitulo"), nota["categoria"], total,
                     os.path.join(carpeta, f"{prefijo}01.jpg"), foco, desliza)]
    for i, l in enumerate(laminas, start=1):
        rutas.append(lamina(foto, i, total, l["titulo"], l["texto"],
                            os.path.join(carpeta, f"{prefijo}{i + 1:02d}.jpg"), foco, desliza))
    rutas.append(cierre(foto, total, nota["pregunta"], nota.get("mandar"),
                        os.path.join(carpeta, f"{prefijo}{total:02d}.jpg"), foco))
    return rutas
