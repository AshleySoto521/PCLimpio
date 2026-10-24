# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Genera el ícono y los logos oficiales de PCLimpio a partir de assets/logo-original.webp.

Ajustes respecto al original:
- Se recorta el margen vacío para que el emblema llene el ícono.
- Esquinas redondeadas con fondo transparente (se ve bien en la barra de tareas clara u oscura).
- En tamaños pequeños (16-32 px) se usa un recorte más cerrado y más nítido, porque los detalles se pierden.

Uso (necesita Pillow):  py -3 -m pip install pillow  y luego  py -3 tools/make_icon.py
Resultado: assets/icon.ico, assets/logo.png, ui/logo.png, ui/favicon.png
"""
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets", "logo-original.webp")

FULL_CROP = (100, 100, 924, 924)    # todo el emblema con un margen mínimo
TIGHT_CROP = (170, 170, 854, 854)   # para tamaños diminutos: casi solo el anillo y el cometa
RADIUS = 0.22                       # redondeo de esquinas (proporción del lado)


def _rounded(img, size, tight=False):
    """Recorta, escala con buena calidad y aplica esquinas redondeadas transparentes."""
    crop = img.crop(TIGHT_CROP if tight else FULL_CROP)
    work = crop.resize((size * 4, size * 4), Image.LANCZOS)  # se trabaja a 4x y se reduce: bordes suaves
    if tight:
        work = ImageEnhance.Contrast(work).enhance(1.25)
        work = ImageEnhance.Color(work).enhance(1.2)
    mask = Image.new("L", work.size, 0)
    r = int(work.size[0] * RADIUS)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, work.size[0] - 1, work.size[1] - 1), radius=r, fill=255)
    work = work.convert("RGBA")
    work.putalpha(mask)
    out = work.resize((size, size), Image.LANCZOS)
    if size <= 48:
        out = out.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=2))
    return out


def main():
    src = Image.open(SRC).convert("RGB")
    sizes = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
    frames = {s: _rounded(src, s, tight=s <= 32) for s in sizes}
    ico = os.path.join(ROOT, "assets", "icon.ico")
    frames[256].save(ico, format="ICO", sizes=[(s, s) for s in sizes], append_images=[frames[s] for s in sizes[:-1]])
    _rounded(src, 512).save(os.path.join(ROOT, "assets", "logo.png"))
    frames[96].save(os.path.join(ROOT, "ui", "logo.png"))
    frames[64].save(os.path.join(ROOT, "ui", "favicon.png"))
    preview = Image.new("RGBA", (sum(sizes) + 10 * len(sizes), 256), (240, 240, 240, 255))
    x = 0
    for s in sizes:
        preview.alpha_composite(frames[s], (x, 256 - s))
        x += s + 10
    preview.save(os.path.join(ROOT, "build", "icon_preview.png")) if os.path.isdir(os.path.join(ROOT, "build")) else None
    print("Listo: assets/icon.ico, assets/logo.png, ui/logo.png, ui/favicon.png")


if __name__ == "__main__":
    main()
