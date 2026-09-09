"""Message Discord d'une compo, avec deux builds par image."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from .grid import composer_ligne
from .images import images_des_lignes
from .models import Compo

MAX_CHARS_CONTENU = 2000
NOM_LIGNE = "compo_ligne_{:02d}.png"


class DiscordError(RuntimeError):
    """Erreur remontee par le webhook Discord."""


def _tronquer(texte: str, limite: int) -> str:
    return texte if len(texte) <= limite else texte[: limite - 1] + "…"


def texte_entete(compo: Compo, auteur_pseudo: str, lien: str = "") -> str:
    lignes = [
        f"📋 **{compo.nom}** — {compo.type_contenu.value} · "
        f"{compo.taille_groupe} joueurs · {len(compo.lignes)} builds · par {auteur_pseudo}"
    ]
    if compo.notes:
        lignes.append(compo.notes)
    if lien:
        lignes.append(f"🔗 {lien}")
    return _tronquer("\n".join(lignes), MAX_CHARS_CONTENU)


def _legende_manquants(compo: Compo, images: dict[int, bytes]) -> str:
    manquants = [ligne for ligne in compo.lignes if ligne.ordre not in images]
    if not manquants:
        return ""
    return "\n".join(
        f"#{ligne.ordre + 1} — {ligne.libelle} (image indisponible)"
        for ligne in manquants
    )


async def _appeler(client: httpx.AsyncClient, methode: str, url: str, **options) -> httpx.Response:
    for _ in range(3):
        reponse = await client.request(methode, url, **options)
        if reponse.status_code == 429:
            attente = float(reponse.headers.get("Retry-After", "1"))
            await asyncio.sleep(min(attente, 5.0))
            continue
        if reponse.status_code >= 400:
            raise DiscordError(
                f"Discord a repondu {reponse.status_code} : {_tronquer(reponse.text, 300)}"
            )
        return reponse
    raise DiscordError("Discord limite les envois (429), reessayez dans un instant.")


def _corps_json(reponse: httpx.Response) -> dict:
    try:
        return reponse.json()
    except (json.JSONDecodeError, ValueError):
        return {}


async def _envoyer_ligne(
    client: httpx.AsyncClient,
    url: str,
    contenu: str,
    donnees: bytes,
    numero: int,
    total: int,
) -> dict:
    nom_fichier = NOM_LIGNE.format(numero)
    charge = {
        "username": "Compos Albion",
        "content": contenu,
        "embeds": [
            {
                "title": f"Ligne {numero}/{total}",
                "image": {"url": f"attachment://{nom_fichier}"},
            }
        ],
        "attachments": [{"id": 0, "filename": nom_fichier}],
    }
    reponse = await _appeler(
        client,
        "POST",
        url,
        params={"wait": "true"},
        data={"payload_json": json.dumps(charge, ensure_ascii=False)},
        files=[("files[0]", (nom_fichier, donnees, "image/png"))],
    )
    return _corps_json(reponse)


async def envoyer_webhook(
    url: str,
    compo: Compo,
    auteur_pseudo: str,
    lien: str = "",
) -> dict[str, Any]:
    """Poste chaque paire de builds comme une image distincte dans Discord."""
    if not url:
        raise DiscordError(
            "Aucune URL de webhook Discord configuree. "
            "Renseignez-la dans l'administration ou dans le fichier .env."
        )

    images = await images_des_lignes(compo.lignes)
    lignes_images: list[bytes] = []
    builds_valides = [
        images[ligne.ordre]
        for ligne in compo.lignes
        if ligne.ordre in images
    ]

    for debut in range(0, len(builds_valides), 2):
        donnees = composer_ligne(builds_valides[debut:debut + 2])
        if donnees:
            lignes_images.append(donnees)

    legende = _legende_manquants(compo, images)
    entete = texte_entete(compo, auteur_pseudo, lien)
    if legende:
        entete = _tronquer(f"{entete}\n{legende}".strip(), MAX_CHARS_CONTENU)

    if not lignes_images:
        async with httpx.AsyncClient(timeout=60.0) as client:
            reponse = await _appeler(
                client, "POST", url, params={"wait": "true"}, json={
                    "username": "Compos Albion",
                    "content": entete,
                }
            )
        corps = _corps_json(reponse)
        return {
            "messages": 1,
            "images": len(images),
            "memoire": [{"message_id": corps.get("id"), "entete": True, "ordres": []}],
        }

    memoire = []
    total = len(lignes_images)
    async with httpx.AsyncClient(timeout=60.0) as client:
        for index, donnees in enumerate(lignes_images, start=1):
            contenu = entete if index == 1 else ""
            corps = await _envoyer_ligne(client, url, contenu, donnees, index, total)
            memoire.append({
                "message_id": corps.get("id"),
                "entete": index == 1,
                "ordres": [
                    ligne.ordre
                    for ligne in compo.lignes[(index - 1) * 2:index * 2]
                ],
            })

    return {
        "messages": total,
        "images": len(images),
        "memoire": memoire,
    }
