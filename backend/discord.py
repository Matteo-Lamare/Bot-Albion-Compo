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
MAX_EMBEDS_PAR_MESSAGE = 10
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


async def _envoyer_message(
    client: httpx.AsyncClient,
    url: str,
    contenu: str,
    lignes: list[tuple[int, bytes]],
) -> dict:
    """Envoie jusqu'a 10 images de lignes dans un seul message Discord."""
    fichiers: list[tuple[str, tuple[str, bytes, str]]] = []
    embeds: list[dict[str, Any]] = []
    attachments: list[dict[str, Any]] = []

    for index, (_, donnees) in enumerate(lignes):
        nom_fichier = NOM_LIGNE.format(lignes[0][0] + index)
        fichiers.append(
            (f"files[{index}]", (nom_fichier, donnees, "image/png"))
        )
        embeds.append({"image": {"url": f"attachment://{nom_fichier}"}})
        attachments.append({"id": index, "filename": nom_fichier})

    charge: dict[str, Any] = {
        "username": "Compos Albion",
        "content": contenu,
        "embeds": embeds,
        "attachments": attachments,
    }
    reponse = await _appeler(
        client,
        "POST",
        url,
        params={"wait": "true"},
        data={"payload_json": json.dumps(charge, ensure_ascii=False)},
        files=fichiers,
    )
    return _corps_json(reponse)


async def envoyer_webhook(
    url: str,
    compo: Compo,
    auteur_pseudo: str,
    lien: str = "",
) -> dict[str, Any]:
    """Poste deux builds par image, avec jusqu'a 10 lignes dans chaque message."""
    if not url:
        raise DiscordError(
            "Aucune URL de webhook Discord configuree. "
            "Renseignez-la dans l'administration ou dans le fichier .env."
        )

    images = await images_des_lignes(compo.lignes)
    builds_valides = [
        (ligne.ordre, images[ligne.ordre])
        for ligne in compo.lignes
        if ligne.ordre in images
    ]

    lignes_images: list[tuple[int, bytes]] = []
    for index in range(0, len(builds_valides), 2):
        donnees = composer_ligne([donnees for _, donnees in builds_valides[index:index + 2]])
        if donnees:
            lignes_images.append((index // 2 + 1, donnees))

    legende = _legende_manquants(compo, images)
    entete = texte_entete(compo, auteur_pseudo, lien)
    if legende:
        entete = _tronquer(f"{entete}\n{legende}".strip(), MAX_CHARS_CONTENU)

    if not lignes_images:
        async with httpx.AsyncClient(timeout=60.0) as client:
            reponse = await _appeler(
                client,
                "POST",
                url,
                params={"wait": "true"},
                json={"username": "Compos Albion", "content": entete},
            )
        corps = _corps_json(reponse)
        return {
            "messages": 1,
            "images": len(images),
            "memoire": [{"message_id": corps.get("id"), "entete": True, "ordres": []}],
        }

    memoire = []
    total_messages = (len(lignes_images) + MAX_EMBEDS_PAR_MESSAGE - 1) // MAX_EMBEDS_PAR_MESSAGE

    async with httpx.AsyncClient(timeout=60.0) as client:
        for debut in range(0, len(lignes_images), MAX_EMBEDS_PAR_MESSAGE):
            lot = lignes_images[debut:debut + MAX_EMBEDS_PAR_MESSAGE]
            contenu = entete if debut == 0 else ""
            corps = await _envoyer_message(client, url, contenu, lot)

            premier_build = (debut * 2)
            derniers_builds = builds_valides[premier_build: premier_build + len(lot) * 2]
            memoire.append({
                "message_id": corps.get("id"),
                "entete": debut == 0,
                "ordres": [ordre for ordre, _ in derniers_builds],
            })

    return {
        "messages": total_messages,
        "images": len(images),
        "memoire": memoire,
    }
