"""Proxy securise et cache persistant en base des icones Albion Online."""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .database import SessionLocal
from .models import ImageAlbion

router = APIRouter(tags=["images"])

_HOTE_AUTORISE = "render.albiononline.com"
# Un seul antislash est necessaire dans une regex raw pour matcher le point.
_CHEMIN_AUTORISE = re.compile(r"^/v1/(?:item|spell)/[A-Za-z0-9_@.%-]+\.png$")
_TYPES_IMAGE = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_TAILLE_MAX = 5 * 1024 * 1024
_TIMEOUT = httpx.Timeout(8.0, connect=3.0)


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
    """Lit l'image en base ou la telecharge une seule fois depuis Albion."""
    if not url_albion_autorisee(url):
        raise HTTPException(status_code=400, detail="URL d'icone Albion non autorisee")

    morceaux = urlsplit(url)
    url_source = urlunsplit(
        (morceaux.scheme, morceaux.netloc, morceaux.path, urlencode({"size": size}), "")
    )
    cle = hashlib.sha256(url_source.encode("utf-8")).hexdigest()

    # Les octets sont conserves dans PostgreSQL/SQLite : aucun disque local
    # persistant n'est necessaire et le cache survit aux redeploiements Render.
    with SessionLocal() as db:
        image = db.scalar(select(ImageAlbion).where(ImageAlbion.cle == cle))
        if image is not None:
            return Response(
                image.contenu,
                media_type=image.type_mime,
                headers={"Cache-Control": "public, max-age=604800", "X-Image-Cache": "HIT"},
            )

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
    with SessionLocal() as db:
        db.add(
            ImageAlbion(
                cle=cle,
                url_source=url_source,
                taille=size,
                contenu=contenu,
                type_mime=media_type,
            )
        )
        try:
            db.commit()
        except IntegrityError:
            # Deux requetes simultanees peuvent avoir telecharge la meme image.
            # La contrainte unique garantit une seule ligne en base.
            db.rollback()

    return Response(
        contenu,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=604800", "X-Image-Cache": "MISS"},
    )
