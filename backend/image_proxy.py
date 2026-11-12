"""Lecture des icones Albion exclusivement depuis le cache persistant en base."""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select

from .database import SessionLocal
from .models import ImageAlbion

router = APIRouter(tags=["images"])

_HOTE_AUTORISE = "render.albiononline.com"
_CHEMIN_AUTORISE = re.compile(r"^/v1/(?:item|spell)/[A-Za-z0-9_@.%-]+\.png$")
_TAILLE_STOCKEE = 128


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
    """Renvoie une image préchargée. Aucun appel réseau externe pendant l'affichage."""
    if not url_albion_autorisee(url):
        raise HTTPException(status_code=400, detail="URL d'icone Albion non autorisee")

    morceaux = urlsplit(url)
    url_source = f"https://{_HOTE_AUTORISE}{morceaux.path}?size={_TAILLE_STOCKEE}"
    cle = hashlib.sha256(url_source.encode("utf-8")).hexdigest()

    with SessionLocal() as db:
        image = db.scalar(select(ImageAlbion).where(ImageAlbion.cle == cle))
        if image is None:
            raise HTTPException(
                status_code=503,
                detail="Icone en cours de prechargement dans la base. Reessayez dans quelques instants.",
                headers={"Retry-After": "60"},
            )
        return Response(
            image.contenu,
            media_type=image.type_mime,
            headers={
                "Cache-Control": "public, max-age=604800, immutable",
                "X-Image-Cache": "DATABASE",
            },
        )
