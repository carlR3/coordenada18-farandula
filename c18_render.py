#!/usr/bin/env python3
"""Generador de imágenes de noticias — plantilla Coordenada 18 (1080x1350, 4:5).

Título: va en blanco; usa <a>palabras</a> para resaltar en amarillo.
Modo foto:    --foto foto.jpg
Modo tarjeta: sin --foto; usa --dato "RD$4.00" --dato-sub "MÁS POR GALÓN" (opcional)
"""
import argparse, os, re, subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1350
NAVY_L, NAVY_R = (18, 34, 92), (28, 45, 112)
ROJO, AMARILLO, BLANCO = (222, 38, 44), (245, 196, 48), (255, 255, 255)
AQUI = os.path.dirname(os.path.abspath(__file__))
FD = os.path.join(AQUI, "c18_fonts")
FUENTES = {
    "Montserrat.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
    "Cinzel.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/cinzel/Cinzel%5Bwght%5D.ttf",
    "sirena.png": "https://raw.githubusercontent.com/jdecked/twemoji/main/assets/72x72/1f6a8.png",
}


def asegurar_fuentes():
    os.makedirs(FD, exist_ok=True)
    for n, url in FUENTES.items():
        p = os.path.join(FD, n)
        if not os.path.exists(p) or os.path.getsize(p) < 1000:
            subprocess.run(["curl", "-sSL", "-o", p, url], check=True)


def fuente(nombre, tam, peso):
    f = ImageFont.truetype(os.path.join(FD, nombre), tam)
    try:
        f.set_variation_by_axes([peso])
    except Exception:
        pass
    return f


def ancho_txt(f, t, trk):
    return sum(f.getlength(c) for c in t) + trk * max(0, len(t) - 1)


def dibujar_txt(d, x, y, t, f, color, trk, sombra=False):
    for c in t:
        if sombra:
            d.text((x + 2, y + 3), c, font=f, fill=(0, 0, 0, 140))
        d.text((x, y), c, font=f, fill=color)
        x += f.getlength(c) + trk
    return x


def tokens(titulo):
    """Devuelve [(palabra, color)] respetando <r> y <a>."""
    out, color, prev = [], BLANCO, " "
    for parte in re.split(r"(</?[raRA]>)", titulo):
        p = parte.lower()
        if p in ("<r>", "<a>"):
            color = AMARILLO  # el título solo lleva blanco y amarillo
        elif p in ("</r>", "</a>"):
            color = BLANCO
        else:
            for k, w in enumerate(parte.split()):
                pegado = k == 0 and bool(out) and not parte[:1].isspace() and not prev[-1:].isspace()
                out.append((w.upper(), color, pegado))
            if parte:
                prev = parte
    return out


def maquetar(toks, f, trk, ancho, primero_extra):
    lineas, act, w_act = [], [], primero_extra
    esp = f.getlength(" ") + trk
    for w, c, pg in toks:
        ww = ancho_txt(f, w, trk)
        sep = 0 if pg else esp
        if act and not pg and w_act + sep + ww > ancho:
            lineas.append(act)
            act, w_act = [], 0
            sep = 0
        w_act += (sep if act else 0) + ww
        act.append((w, c, pg))
    if act:
        lineas.append(act)
    return lineas


def cubrir(img, w, h, foco=0.35):
    iw, ih = img.size
    e = max(w / iw, h / ih)
    img = img.resize((max(w, round(iw * e)), max(h, round(ih * e))), Image.LANCZOS)
    x = (img.width - w) // 2
    y = int((img.height - h) * foco)
    return img.crop((x, y, x + w, y + h))


def fondo_tarjeta(alto, dato, dato_sub):
    bg = Image.new("RGB", (W, alto))
    d = ImageDraw.Draw(bg)
    for y in range(alto):  # degradado vertical
        t = y / alto
        d.line([(0, y), (W, y)], fill=(int(8 + 14 * t), int(14 + 22 * t), int(40 + 60 * t)))
    # rejilla tipo coordenadas
    capa = Image.new("RGBA", (W, alto), (0, 0, 0, 0))
    dc = ImageDraw.Draw(capa)
    for x in range(0, W, 90):
        dc.line([(x, 0), (x, alto)], fill=(255, 255, 255, 14), width=1)
    for y in range(0, alto, 90):
        dc.line([(0, y), (W, y)], fill=(255, 255, 255, 14), width=1)
    dc.ellipse([W / 2 - 330, alto / 2 - 330, W / 2 + 330, alto / 2 + 330], outline=(255, 255, 255, 22), width=3)
    dc.ellipse([W / 2 - 230, alto / 2 - 230, W / 2 + 230, alto / 2 + 230], outline=(222, 38, 44, 40), width=3)
    bg = Image.alpha_composite(bg.convert("RGBA"), capa)
    d = ImageDraw.Draw(bg)
    if dato:
        tam = 230
        f = fuente("Montserrat.ttf", tam, 900)
        while ancho_txt(f, dato, 0) > W - 140 and tam > 80:
            tam -= 10
            f = fuente("Montserrat.ttf", tam, 900)
        x = (W - ancho_txt(f, dato, 0)) / 2
        cy = alto / 2 - (40 if dato_sub else 0)
        dibujar_txt(d, x, cy - tam * 0.62, dato, f, AMARILLO, 0, sombra=True)
        if dato_sub:
            t, ts = dato_sub.upper(), 52
            fs = fuente("Montserrat.ttf", ts, 800)
            while ancho_txt(fs, t, 6) > W - 160 and ts > 26:
                ts -= 2
                fs = fuente("Montserrat.ttf", ts, 800)
            dibujar_txt(d, (W - ancho_txt(fs, t, 6)) / 2, cy + tam * 0.45, t, fs, BLANCO, 6)
    return bg.convert("RGB")


def render(a):
    asegurar_fuentes()
    toks = tokens(a.titulo)
    margen_x, ancho = 66, W - 66 - 44
    sirena = Image.open(os.path.join(FD, "sirena.png")).convert("RGBA") if a.alerta else None

    # tamaño del título: lo más grande posible hasta 4 líneas
    for tam in range(52, 30, -2):
        f = fuente("Montserrat.ttf", tam, 720)
        trk = tam * 0.085
        em = int(tam * 1.05) if sirena else 0
        lineas = maquetar(toks, f, trk, ancho, em + (tam * 0.45 if sirena else 0))
        if len(lineas) <= (3 if tam > 44 else 4):
            break
    alto_linea = int(tam * 1.38)
    banda_alto = 48 + alto_linea * len(lineas) + 34
    banda_y = H - banda_alto

    # foto o tarjeta
    if a.foto:
        base = cubrir(Image.open(a.foto).convert("RGB"), W, banda_y + 20, a.foco)
    else:
        base = fondo_tarjeta(banda_y + 20, a.dato, a.dato_sub)
    lienzo = Image.new("RGB", (W, H), NAVY_L)
    lienzo.paste(base, (0, 0))
    lienzo = lienzo.convert("RGBA")
    d = ImageDraw.Draw(lienzo)

    # crédito de la foto
    nota = a.credito or ""
    if nota:
        fn = fuente("Montserrat.ttf", 20, 600)
        y_n = banda_y - (150 if a.urgente else 0) - 40
        dibujar_txt(d, W - 44 - ancho_txt(fn, nota.upper(), 1.5), y_n, nota.upper(), fn, (255, 255, 255, 230), 1.5, sombra=True)

    # ÚLTIMO MINUTO
    if a.urgente:
        fu = fuente("Cinzel.ttf", 64, 700)
        t = "ÚLTIMO MINUTO"
        wt = ancho_txt(fu, t, 5)
        bw, bh = wt + 120, 92
        bx, by = (W - bw) / 2, banda_y - 44 - bh
        sk = 22
        sombra = Image.new("RGBA", lienzo.size, (0, 0, 0, 0))
        ImageDraw.Draw(sombra).polygon([(bx + sk, by + 6), (bx + bw + sk, by + 6), (bx + bw - sk, by + bh + 6), (bx - sk, by + bh + 6)], fill=(0, 0, 0, 110))
        lienzo = Image.alpha_composite(lienzo, sombra.filter(ImageFilter.GaussianBlur(8)))
        d = ImageDraw.Draw(lienzo)
        d.polygon([(bx + sk, by), (bx + bw + sk, by), (bx + bw - sk, by + bh), (bx - sk, by + bh)], fill=(27, 45, 92))
        dibujar_txt(d, (W - wt) / 2, by + 6, t, fu, (232, 196, 106), 5)

    # banda azul con degradado + franja roja
    banda = Image.new("RGBA", (W, banda_alto))
    db = ImageDraw.Draw(banda)
    for x in range(W):
        t = x / W
        db.line([(x, 0), (x, banda_alto)], fill=tuple(int(NAVY_L[i] * (1 - t) + NAVY_R[i] * t) for i in range(3)) + (255,))
    db.rectangle([0, 0, 34, banda_alto], fill=ROJO + (255,))
    lienzo.alpha_composite(banda, (0, banda_y))
    d = ImageDraw.Draw(lienzo)

    # pestaña de categoría
    fc = fuente("Montserrat.ttf", 24, 800)
    cat = a.categoria.upper()
    wc = ancho_txt(fc, cat, 2.2)
    tx0, ty0, th, sk = 66, banda_y - 20, 40, 14
    tx1 = tx0 + wc + 70
    d.polygon([(tx0 + sk, ty0), (tx1 + sk, ty0), (tx1, ty0 + th), (tx0, ty0 + th)], fill=BLANCO)
    dibujar_txt(d, tx0 + 35 + sk / 2, ty0 + 6, cat, fc, ROJO, 2.2)

    # título
    y = banda_y + 44
    asc = f.getbbox("H")
    for i, linea in enumerate(lineas):
        x = margen_x
        if i == 0 and sirena:
            s = sirena.resize((em, em), Image.LANCZOS)
            lienzo.alpha_composite(s, (int(x), int(y + asc[1] + (asc[3] - asc[1]) / 2 - em / 2)))
            d = ImageDraw.Draw(lienzo)
            x += em + tam * 0.45
        for j, (w, c, pg) in enumerate(linea):
            if j > 0:
                x += trk if pg else f.getlength(" ") + 2 * trk
            x = dibujar_txt(d, x, y, w, f, c, trk) - trk
        y += alto_linea

    # logo (por defecto logo_c18.png junto al script o en la carpeta actual)
    ruta_logo = a.logo
    if not ruta_logo and not a.sin_logo:
        for cand in (os.path.join(AQUI, "logo_c18.png"), "logo_c18.png"):
            if os.path.exists(cand):
                ruta_logo = cand
                break
    if ruta_logo and not a.sin_logo and os.path.exists(ruta_logo):
        lg = Image.open(ruta_logo).convert("RGBA")
        lado = 200
        lg.thumbnail((lado, lado), Image.LANCZOS)
        marco = Image.new("RGBA", (lg.width + 16, lg.height + 16), (0, 0, 0, 0))
        marco.alpha_composite(lg, (8, 8))
        lg = marco
        pos = (W - 62 - lg.width, 67)
        alfa = lg.split()[3].filter(ImageFilter.MaxFilter(7))
        borde = Image.new("RGBA", lg.size, (255, 255, 255, 0))
        borde.putalpha(alfa)
        sombra = Image.new("RGBA", lienzo.size, (0, 0, 0, 0))
        sombra.paste(Image.new("RGBA", lg.size, (0, 0, 0, 150)), (pos[0] + 3, pos[1] + 5), alfa)
        lienzo = Image.alpha_composite(lienzo, sombra.filter(ImageFilter.GaussianBlur(6)))
        lienzo.alpha_composite(borde, pos)
        lienzo.alpha_composite(lg, pos)

    lienzo.convert("RGB").save(a.salida, quality=95)
    return a.salida


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--titulo", required=True)
    p.add_argument("--categoria", default="NACIONALES")
    p.add_argument("--foto")
    p.add_argument("--foco", type=float, default=0.35, help="0=arriba, 1=abajo")
    p.add_argument("--logo", help="por defecto usa logo_c18.png si existe")
    p.add_argument("--sin-logo", dest="sin_logo", action="store_true")
    p.add_argument("--alerta", action="store_true", help="pone 🚨 al inicio del título")
    p.add_argument("--urgente", action="store_true", help="banda ÚLTIMO MINUTO")
    p.add_argument("--credito", help='ej. "Foto: Presidencia RD"')
    p.add_argument("--dato")
    p.add_argument("--dato-sub", dest="dato_sub")
    p.add_argument("--salida", default="noticia.png")
    print(render(p.parse_args()))
