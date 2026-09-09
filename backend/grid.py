"""Composition des images de builds pour Discord, deux builds par ligne."""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

FOND = (30, 32, 39, 255)
ESPACEMENT = 8
BORDURE = (58, 63, 76, 255)
TAILLE_CASE = 520
MAX_COLONNES = 2


def _placer_sans_deformation(source: Image.Image, largeur: int, hauteur: int) -> Image.Image:
    """Redimensionne en conservant le ratio, puis centre dans la case."""
    image = source.convert("RGBA")
    image.thumbnail((largeur, hauteur), Image.Resampling.LANCZOS)
    case = Image.new("RGBA", (largeur, hauteur), FOND)
    x = (largeur - image.width) // 2
    y = (hauteur - image.height) // 2
    case.alpha_composite(image, (x, y))
    return case


def composer_ligne(images: list[bytes]) -> bytes | None:
    """Crée une image contenant au maximum deux builds côte à côte."""
    if not images:
        return None

    images = images[:MAX_COLONNES]
    largeur = len(images) * TAILLE_CASE + (len(images) + 1) * ESPACEMENT
    hauteur = TAILLE_CASE + 2 * ESPACEMENT
    planche = Image.new("RGBA", (largeur, hauteur), FOND)
    dessin = ImageDraw.Draw(planche)

    for index, donnees in enumerate(images):
        x = ESPACEMENT + index * (TAILLE_CASE + ESPACEMENT)
        y = ESPACEMENT
        dessin.rounded_rectangle(
            (x, y, x + TAILLE_CASE - 1, y + TAILLE_CASE - 1),
            radius=8,
            fill=FOND,
            outline=BORDURE,
            width=1,
        )
        try:
            with Image.open(BytesIO(donnees)) as source:
                case = _placer_sans_deformation(source, TAILLE_CASE - 4, TAILLE_CASE - 4)
            planche.alpha_composite(case, (x + 2, y + 2))
        except Exception:
            dessin.text((x + 12, y + 12), f"Build #{index + 1}", fill=(233, 235, 240, 255))

    tampon = BytesIO()
    planche.convert("RGB").save(tampon, format="PNG", optimize=True)
    return tampon.getvalue()
