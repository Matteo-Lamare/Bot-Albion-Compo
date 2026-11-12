"""Proxy/cache local des icones publiques du client Albion Online.

Seul le domaine officiel render.albiononline.com et les chemins d'icones
item/spell sont acceptes afin d'eviter de transformer cette route en proxy SSRF.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from .config import settings

router = APIRouter(tags=["images"])

_HOTE_AUTORISE = "render.albiononline.com"
_CHEMIN_AUTORISE = re.compile(r"^/v1/(?:item|spell)/[A-Za-z0-9_@.%-]+\.png$")
_TYPES_IMAGE = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_TAILLE_MAX = 5 * 1024 * 1024
_TIMEOUT = httpx.Timeout(8.0, connect=3.0)


def _repertoire_cache() -> Path:
    """IMAGE_CACHE_DIR peut pointer vers un disque persistant Render."""
    return Path(os.getenv("IMAGE_CACHE_DIR", str(settings.base_dir / ".cache" / "albion-images")))


def url_albion_autorisee(url: str) -> bool:
    """N'autorise que les URL HTTPS d'icones Albion attendues."""
    try:
        morceaux = urlsplit(url)
        return (
            morceaux.scheme == "https"
            and morceaux.hostname == _HOTE_AUTORISE
            and morceaux.port in (None, 443)
            and morceaux.username is None
            and morceaux.password is None
            and _CHEMIN_AUTORISE.fullmatch(morceaux.path) is not None
            and not morceaux.fragment
        )
    except ValueError:
        return False


@router.get("/api/images")
def lire_icone(
    url: str = Query(..., min_length=20, max_length=500),
    size: int = Query(64, ge=16, le=512),
) -> Response:
    """Renvoie une icone Albion depuis le cache local ou la telecharge."""
    if not url_albion_autorisee(url):
        raise HTTPException(status_code=400, detail="URL d'icone Albion non autorisee")

    morceaux = urlsplit(url)
    url_source = urlunsplit((morceaux.scheme, morceaux.netloc, morceaux.path, urlencode({"size": size}), ""))
    cle = hashlib.sha256(url_source.encode("utf-8")).hexdigest()
    cache = _repertoire_cache()
    fichier = cache / f"{cle}.img"
    type_fichier = cache / f"{cle}.type"

    if fichier.is_file() and type_fichier.is_file():
        try:
            contenu = fichier.read_bytes()
            media_type = type_fichier.read_text(encoding="ascii")
            if contenu and media_type in _TYPES_IMAGE:
                return Response(contenu, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"})
        except OSError:
            pass

    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
            reponse = client.get(url_source)
    except httpx.HTTPError as erreur:
        raise HTTPException(status_code=502, detail="Serveur d'images Albion indisponible") from erreur

    media_type = reponse.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if reponse.status_code == 404:
        raise HTTPException(status_code=404, detail="Icone Albion introuvable")
    if reponse.status_code != 200:
        raise HTTPException(status_code=502, detail="Echec du chargement de l'icone Albion")
    if media_type not in _TYPES_IMAGE or not reponse.content or len(reponse.content) > _TAILLE_MAX:
        raise HTTPException(status_code=502, detail="Reponse image Albion invalide")

    contenu = reponse.content
    try:
        cache.mkdir(parents=True, exist_ok=True)
        temporaire = cache / f".{cle}.tmp"
        temporaire.write_bytes(contenu)
        temporaire.replace(fichier)
        type_temporaire = cache / f".{cle}.type.tmp"
        type_temporaire.write_text(media_type, encoding="ascii")
        type_temporaire.replace(type_fichier)
    except OSError:
        # Le cache est une optimisation : l'image reste servie si le disque
        # n'est pas inscriptible (filesystem ephemere ou permissions).
        pass

    return Response(contenu, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"})
