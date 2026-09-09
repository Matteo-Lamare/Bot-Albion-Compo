"""Message Discord d'une compo avec grille adaptative des builds."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from .grid import composer_grille
from .images import images_des_lignes
from .models import Compo, LigneCompo

MAX_CHARS_CONTENU = 2000
NOM_GRILLE = "compo_grille.png"


class DiscordError(RuntimeError):
    """Erreur remontee par le webhook Discord."""


def _tronquer(texte: str, limite: int) -> str:
    return texte if len(texte) <= limite else texte[: limite - 1] + "…"


def texte_entete(compo: Compo, auteur_pseudo: str, lien: str = "") -> str:
    """Texte de secours / contexte de la compo."""
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
    """Signale les builds dont le rendu d'image n'a pas pu etre produit."""
    manquants = [ligne for ligne in compo.lignes if ligne.ordre not in images]
    if not manquants:
        return ""
    return "\n".join(
        f"#{ligne.ordre + 1} — {ligne.libelle} (image indisponible)"
        for ligne in manquants
    )


async def _appeler(
    client: httpx.AsyncClient,
    methode: str,
    url: str,
    **options,
) -> httpx.Response:
    """Appel au webhook avec gestion du 429 (limitation de debit)."""
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


async def envoyer_webhook(
    url: str,
    compo: Compo,
    auteur_pseudo: str,
    lien: str = "",
) -> dict[str, Any]:
    """Poste toute la compo en un message avec une grille 1 a 40 builds."""
    if not url:
        raise DiscordError(
            "Aucune URL de webhook Discord configuree. "
            "Renseignez-la dans l'administration ou dans le fichier .env."
        )

    images = await images_des_lignes(compo.lignes)
    donnees_grille = composer_grille(
        [images[ligne.ordre] for ligne in compo.lignes if ligne.ordre in images]
    )
    legende = _legende_manquants(compo, images)
    contenu = texte_entete(compo, auteur_pseudo, lien)
    if legende:
        contenu = _tronquer(f"{contenu}\n{legende}".strip(), MAX_CHARS_CONTENU)

    charge: dict[str, Any] = {
        "username": "Compos Albion",
        "content": contenu,
    }

    fichiers: list[tuple[str, tuple[str, bytes, str]]] = []
    if donnees_grille:
        fichiers.append(
            ("files[0]", (NOM_GRILLE, donnees_grille, "image/png"))
        )
        charge["embeds"] = [
            {
                "title": compo.nom,
                "description": (
                    f"{len(compo.lignes)} builds — grille automatique sans déformation"
                ),
                "image": {"url": f"attachment://{NOM_GRILLE}"},
            }
        ]
        charge["attachments"] = [{"id": 0, "filename": NOM_GRILLE}]

    async with httpx.AsyncClient(timeout=60.0) as client:
        if fichiers:
            reponse = await _appeler(
                client,
                "POST",
                url,
                params={"wait": "true"},
                data={"payload_json": json.dumps(charge, ensure_ascii=False)},
                files=fichiers,
            )
        else:
            reponse = await _appeler(
                client,
                "POST",
                url,
                params={"wait": "true"},
                json=charge,
            )

    corps = _corps_json(reponse)
    return {
        "messages": 1,
        "images": len(images),
        "memoire": [
            {
                "message_id": corps.get("id"),
                "entete": True,
                "ordres": [ligne.ordre for ligne in compo.lignes],
            }
        ],
    }
