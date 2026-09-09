"""Rendu d'un build en image PNG (icones officielles Albion).

L'image est tout ce qui part sur Discord : une planche 3x3 reprenant la
disposition de l'ecran d'equipement du jeu, chaque objet accompagne de ses sorts
et passifs. La case en haut a gauche reste vide et la monture n'y figure pas.
Les icones viennent de render.albiononline.com et sont mises en cache sur
disque, donc un second envoi ne retelecharge rien.

Pillow est facultatif : sans lui, la fonction rend un dictionnaire vide et le
message Discord se contente de nommer les builds.
"""
from __future__ import annotations

import asyncio
import hashlib
import statistics
from io import BytesIO
from pathlib import Path
from typing import Iterable, Sequence

import httpx

from .config import settings
from .models import LigneCompo

try:
    from PIL import Image, ImageDraw, ImageFont
    DISPONIBLE = True
except ImportError:
    DISPONIBLE = False

CACHE_ICONES = settings.base_dir / ".cache" / "icones"

TAILLE_OBJET = 104
TAILLE_SORT = 36
LARGEUR_CASE = 172
HAUTEUR_CASE = 186
MARGE = 16
HAUTEUR_TITRE = 44

FOND = (30, 32, 39, 255)
FOND_CASE = (43, 46, 56, 255)
FOND_CASE_VIDE = (36, 38, 46, 255)
BORDURE = (58, 63, 76, 255)
TEXTE = (233, 235, 240, 255)
TEXTE_DISCRET = (150, 156, 170, 255)
CONTOUR_ACTIF = (74, 144, 217, 255)
CONTOUR_PASSIF = (201, 162, 39, 255)

CASES: tuple[tuple[int, int, str, str, tuple[str, ...]], ...] = (
    (1, 0, "casque", "Casque", ("casque_sort", "casque_passif")),
    (2, 0, "cape", "Cape", ("cape_passif",)),
    (0, 1, "arme", "Arme", ("arme_sort_1", "arme_sort_2", "arme_sort_3", "arme_passif")),
    (1, 1, "torse", "Armure", ("torse_sort", "torse_passif_1", "torse_passif_2")),
    (2, 1, "offhand", "Off-hand", ()),
    (0, 2, "potion", "Potion", ()),
    (1, 2, "bottes", "Bottes", ("bottes_sort", "bottes_passif")),
    (2, 2, "nourriture", "Nourriture", ()),
)

LARGEUR = MARGE * 2 + LARGEUR_CASE * 3
HAUTEUR = MARGE * 2 + HAUTEUR_TITRE + HAUTEUR_CASE * 3

POLICES = (
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
)


def _police(taille: int):
    for chemin in POLICES:
        if Path(chemin).exists():
            try:
                return ImageFont.truetype(chemin, taille)
            except OSError:
                continue
    return ImageFont.load_default(taille)


def _fichier_cache(url: str) -> Path:
    return CACHE_ICONES / f"{hashlib.sha1(url.encode()).hexdigest()}.png"


async def _telecharger(urls: Iterable[str]) -> dict[str, bytes]:
    icones: dict[str, bytes] = {}
    manquantes: list[str] = []
    for url in dict.fromkeys(urls):
        fichier = _fichier_cache(url)
        if fichier.exists():
            icones[url] = fichier.read_bytes()
        else:
            manquantes.append(url)

    if manquantes:
        CACHE_ICONES.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=15.0) as client:
            async def charger(url: str) -> None:
                try:
                    reponse = await client.get(url)
                    if reponse.status_code == 200 and reponse.content:
                        icones[url] = reponse.content
                        _fichier_cache(url).write_bytes(reponse.content)
                except httpx.HTTPError:
                    pass
            await asyncio.gather(*(charger(url) for url in manquantes))
    return icones


def _url_objet(objet, taille: int = 128) -> str:
    return f"{objet.icone}?size={taille}"


def _url_sort(sort, taille: int = 64) -> str:
    return f"{sort.icone}?size={taille}"


def _urls_de_ligne(ligne: LigneCompo) -> list[str]:
    urls: list[str] = []
    for _, _, slot, _, sorts in CASES:
        objet = getattr(ligne, slot, None)
        if objet is not None:
            urls.append(_url_objet(objet))
        for champ in sorts:
            sort = getattr(ligne, champ, None)
            if sort is not None:
                urls.append(_url_sort(sort))
    return urls


def _nom_ajuste(dessin, texte: str, largeur: int, tailles=(13, 12, 11, 10)):
    for taille in tailles:
        police = _police(taille)
        if dessin.textlength(texte, font=police) <= largeur:
            return texte, police
    police = _police(tailles[-1])
    return _tronquer_au_pixel(dessin, texte, police, largeur), police


def _tronquer_au_pixel(dessin, texte: str, police, largeur: int) -> str:
    if dessin.textlength(texte, font=police) <= largeur:
        return texte
    while texte and dessin.textlength(texte + "…", font=police) > largeur:
        texte = texte[:-1]
    return texte + "…"


def _effacer_tier(icone):
    echelle = icone.width / 128
    centre_x = centre_y = int(26 * echelle)
    rayon = int(15 * echelle)
    ecart = int(11 * echelle)
    points = ((-ecart, 0), (ecart, 0), (0, -ecart), (0, ecart))
    couleurs = [icone.getpixel((centre_x + dx, centre_y + dy)) for dx, dy in points]
    fond = tuple(int(statistics.median(c[canal] for c in couleurs)) for canal in range(4))
    marge = max(1, int(3 * echelle))
    ImageDraw.Draw(icone).ellipse(
        (centre_x - rayon + marge, centre_y - rayon + marge,
         centre_x + rayon - marge, centre_y + rayon - marge),
        fill=fond,
    )
    return icone


def _coller(planche, donnees: bytes, x: int, y: int, taille: int,
            contour=None, sans_tier: bool = False) -> None:
    with Image.open(BytesIO(donnees)) as source:
        icone = source.convert("RGBA")
        if sans_tier and icone.width >= 32:
            icone = _effacer_tier(icone)
        icone = icone.resize((taille, taille), Image.LANCZOS)
    planche.alpha_composite(icone, (x, y))
    if contour is not None:
        ImageDraw.Draw(planche).rounded_rectangle(
            (x, y, x + taille - 1, y + taille - 1), radius=6, outline=contour, width=2
        )


def _composer(ligne: LigneCompo, titre: str, icones: dict[str, bytes]) -> bytes:
    planche = Image.new("RGBA", (LARGEUR, HAUTEUR), FOND)
    dessin = ImageDraw.Draw(planche)
    police_titre = _police(21)
    police_nom = _police(13)
    dessin.text(
        (MARGE, MARGE - 2),
        _tronquer_au_pixel(dessin, titre, police_titre, LARGEUR - MARGE * 2),
        font=police_titre,
        fill=TEXTE,
    )

    for colonne, rangee, slot, libelle, champs_sorts in CASES:
        x = MARGE + colonne * LARGEUR_CASE
        y = MARGE + HAUTEUR_TITRE + rangee * HAUTEUR_CASE
        objet = getattr(ligne, slot, None)
        dessin.rounded_rectangle(
            (x + 3, y + 3, x + LARGEUR_CASE - 5, y + HAUTEUR_CASE - 5),
            radius=10,
            fill=FOND_CASE if objet is not None else FOND_CASE_VIDE,
            outline=BORDURE,
            width=1,
        )

        if objet is None:
            dessin.text(
                (x + LARGEUR_CASE // 2, y + HAUTEUR_CASE // 2),
                libelle,
                font=police_nom,
                fill=TEXTE_DISCRET,
                anchor="mm",
            )
            continue

        donnees = icones.get(_url_objet(objet))
        centre_x = x + (LARGEUR_CASE - TAILLE_OBJET) // 2
        if donnees:
            _coller(planche, donnees, centre_x, y + 8, TAILLE_OBJET, sans_tier=True)
        else:
            dessin.rounded_rectangle(
                (centre_x, y + 8, centre_x + TAILLE_OBJET, y + 8 + TAILLE_OBJET),
                radius=8, outline=BORDURE, width=1,
            )

        sorts = [
            (getattr(ligne, champ), champ)
            for champ in champs_sorts
            if getattr(ligne, champ, None) is not None
        ]
        if sorts:
            largeur_rangee = len(sorts) * TAILLE_SORT + (len(sorts) - 1) * 4
            depart = x + (LARGEUR_CASE - largeur_rangee) // 2
            haut = y + 8 + TAILLE_OBJET + 2
            for index, (sort, _) in enumerate(sorts):
                gauche = depart + index * (TAILLE_SORT + 4)
                contour = CONTOUR_PASSIF if sort.passif else CONTOUR_ACTIF
                donnees = icones.get(_url_sort(sort))
                if donnees:
                    _coller(planche, donnees, gauche, haut, TAILLE_SORT, contour)
                else:
                    dessin.rounded_rectangle(
                        (gauche, haut, gauche + TAILLE_SORT, haut + TAILLE_SORT),
                        radius=6, outline=contour, width=1,
                    )

        nom, police = _nom_ajuste(dessin, objet.nom, LARGEUR_CASE - 14)
        dessin.text(
            (x + LARGEUR_CASE // 2, y + HAUTEUR_CASE - 16),
            nom,
            font=police,
            fill=TEXTE,
            anchor="mm",
        )

    tampon = BytesIO()
    planche.convert("RGB").save(tampon, format="PNG", optimize=True)
    return tampon.getvalue()


async def images_des_lignes(lignes: Sequence[LigneCompo]) -> dict[int, bytes]:
    if not DISPONIBLE or not lignes:
        return {}
    urls = [url for ligne in lignes for url in _urls_de_ligne(ligne)]
    icones = await _telecharger(urls)
    def rendre() -> dict[int, bytes]:
        return {ligne.ordre: _composer(ligne, f"#{ligne.ordre + 1} — {ligne.libelle}", icones)
                for ligne in lignes}
    return await asyncio.to_thread(rendre)


async def image_de_ligne(ligne: LigneCompo) -> bytes | None:
    images = await images_des_lignes([ligne])
    return images.get(ligne.ordre)
