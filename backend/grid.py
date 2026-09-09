"""Composition d'une grille d'images de builds pour Discord."""
from __future__ import annotations

import math
from io import BytesIO

from PIL import Image, ImageDraw

FOND = (30, 32, 39, 255)
ESPACEMENT = 8
BORDURE = (58, 63, 76, 255)
TAILLE_CASE = 260
MAX_COLONNES = 7


def _dimensions(nombre: int) -> tuple[int, int]:
    if nombre <= 0:
        return 0, 0
    colonnes = min(MAX_COLONNES, max(1, math.ceil(math.sqrt(nombre))))
    lignes = math.ceil(nombre / colonnes)
    return colonnes, lignes


def _placer_sans_deformation(source: Image.Image, largeur: int, hauteur: int) -> Image.Image:
    """Redimensionne en conservant le ratio, puis centre dans la case."""
    image = source.convert("RGBA")
    image.thumbnail((largeur, hauteur), Image.Resampling.LANCZOS)
    case = Image.new("RGBA", (largeur, hauteur), FOND)
    x = (largeur - image.width) // 2
    y = (hauteur - image.height) // 2
    case.alpha_composite(image, (x, y))
    return case


def composer_grille(images: list[bytes]) -> bytes | None:
    """Crée une seule image contenant 1 à 40 builds sans les déformer."""
    if not images:
        return None

    images = images[:40]
    colonnes, lignes = _dimensions(len(images))
    largeur = colonnes * TAILLE_CASE + (colonnes + 1) * ESPACEMENT
    hauteur = lignes * TAILLE_CASE + (lignes + 1) * ESPACEMENT
    planche = Image.new("RGBA", (largeur, hauteur), FOND)
    dessin = ImageDraw.Draw(planche)

    for index, donnees in enumerate(images):
        colonne = index % colonnes
        ligne = index // colonnes
        x = ESPACEMENT + colonne * (TAILLE_CASE + ESPACEMENT)
        y = ESPACEMENT + ligne * (TAILLE_CASE + ESPACEMENT)
        dessin.rounded_rectangle(
            (x, y, x + TAILLE_CASE - 1, y + TAILLE_CASE - 1),
            radius=8,
            fill=FOND,
            outline=BORDURE,
            width=1,
        )
        try:
            with Image.open(BytesIO(donnees)) as source:
                case = _placer_sans_deformation(
                    source,
                    TAILLE_CASE - 4,
                    TAILLE_CASE - 4,
                )
            planche.alpha_composite(case, (x + 2, y + 2))
        except Exception:
            # Une image individuelle invalide ne doit pas empêcher toute la compo.
            dessin.text((x + 12, y + 12), f"Build #{index + 1}", fill=(233, 235, 240, 255))

    tampon = BytesIO()
    planche.convert("RGB").save(tampon, format="PNG", optimize=True)
    return tampon.getvalue()
