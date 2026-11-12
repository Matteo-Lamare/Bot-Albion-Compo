"""Télécharge en lot les icones du catalogue et les stocke en base.

À lancer une fois après déploiement (puis après chaque mise à jour du catalogue) :
    python scripts/precharger_images.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database import SessionLocal  # noqa: E402
from backend.main import initialiser_base  # noqa: E402
from backend.models import ImageAlbion  # noqa: E402

CATALOGUE = ROOT / "database" / "catalogue_albion.json"
TAILLE = 128
CONCURRENCE = 8
TAILLE_MAX = 5 * 1024 * 1024
TYPES_IMAGE = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def urls_catalogue() -> list[str]:
    donnees = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    urls = {
        f"https://render.albiononline.com/v1/item/{objet['rendu']}.png"
        for objet in donnees["objets"]
    }
    urls.update(
        f"https://render.albiononline.com/v1/spell/{code}.png"
        for code in donnees["sorts"]
    )
    return sorted(urls)


async def telecharger(client: httpx.AsyncClient, semaphore: asyncio.Semaphore, url: str):
    cible = f"{url}?size={TAILLE}"
    async with semaphore:
        for tentative in range(3):
            try:
                reponse = await client.get(cible)
                mime = reponse.headers.get("content-type", "").split(";", 1)[0].lower()
                if reponse.status_code == 200 and mime in TYPES_IMAGE and 0 < len(reponse.content) <= TAILLE_MAX:
                    return url, cible, mime, reponse.content, None
                erreur = f"HTTP {reponse.status_code}, type={mime}, octets={len(reponse.content)}"
                if reponse.status_code == 404:
                    return url, None, None, None, erreur
            except httpx.HTTPError as exc:
                erreur = str(exc)
            if tentative < 2:
                await asyncio.sleep(1.5 * (tentative + 1))
        return url, None, None, None, erreur


async def main() -> int:
    initialiser_base()
    urls = urls_catalogue()
    semaphore = asyncio.Semaphore(CONCURRENCE)
    timeout = httpx.Timeout(20.0, connect=8.0)
    limites = httpx.Limits(max_connections=CONCURRENCE, max_keepalive_connections=CONCURRENCE)
    async with httpx.AsyncClient(timeout=timeout, limits=limites, follow_redirects=False) as client:
        resultats = await asyncio.gather(
            *(telecharger(client, semaphore, url) for url in urls)
        )

    reussites = [r for r in resultats if r[1] is not None]
    echecs = [r for r in resultats if r[1] is None]
    with SessionLocal() as db:
        deja = set(db.scalars(select(ImageAlbion.cle)))
        for _, cible, mime, contenu, _ in reussites:
            cle = hashlib.sha256(cible.encode("utf-8")).hexdigest()
            if cle not in deja:
                db.add(ImageAlbion(
                    cle=cle,
                    url_source=cible,
                    taille=TAILLE,
                    contenu=contenu,
                    type_mime=mime,
                ))
        db.commit()

    print(f"Images catalogue : {len(urls)}")
    print(f"Téléchargées/validées : {len(reussites)}")
    print(f"Échecs : {len(echecs)}")
    for url, _, _, _, erreur in echecs:
        print(f"ECHEC {url} : {erreur}")
    if echecs:
        print("Relancez le script après correction des erreurs : les images déjà enregistrées seront conservées.")
        return 1
    print("Préchargement terminé : toutes les images du catalogue sont en base.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
