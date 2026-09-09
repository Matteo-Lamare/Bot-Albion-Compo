"""Message Discord d'une compo : entete court et images de build en pieces jointes.

Un envoi poste un premier message portant le titre de la compo, puis les images
des builds (cf. backend/images.py) en pieces jointes brutes : pas d'embed, pas
de description textuelle des builds, l'image porte deja tout l'equipement.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from .images import images_des_lignes
from .models import Compo, LigneCompo

# Limites imposees par l'API Discord
MAX_FICHIERS_PAR_MESSAGE = 10
MAX_CHARS_CONTENU = 2000


class DiscordError(RuntimeError):
    """Erreur remontee par le webhook Discord."""


def _tronquer(texte: str, limite: int) -> str:
    return texte if len(texte) <= limite else texte[: limite - 1] + "…"


def nom_fichier_image(ligne: LigneCompo) -> str:
    return f"build_{ligne.ordre + 1}.png"


# --------------------------------------------------------------------------
# Contenu des messages
# --------------------------------------------------------------------------


def texte_entete(compo: Compo, auteur_pseudo: str, lien: str = "") -> str:
    """Seul texte du message : de quoi identifier la compo, pas les builds."""
    lignes = [
        f"📋 **{compo.nom}** — {compo.type_contenu.value} · "
        f"{compo.taille_groupe} joueurs · {len(compo.lignes)} builds · par {auteur_pseudo}"
    ]
    if compo.notes:
        lignes.append(compo.notes)
    if lien:
        lignes.append(f"🔗 {lien}")
    return _tronquer("\n".join(lignes), MAX_CHARS_CONTENU)


def repartir_lignes(compo: Compo) -> list[list[LigneCompo]]:
    """Groupe les builds par message : Discord accepte 10 pieces jointes."""
    lignes = list(compo.lignes)
    lots = [
        lignes[depart:depart + MAX_FICHIERS_PAR_MESSAGE]
        for depart in range(0, len(lignes), MAX_FICHIERS_PAR_MESSAGE)
    ]
    return lots or [[]]


def _legende(lignes: list[LigneCompo], images: dict[int, bytes]) -> str:
    """Repli quand une image manque (Pillow absent) : au moins le nom du build."""
    manquants = [ligne for ligne in lignes if ligne.ordre not in images]
    if not manquants:
        return ""
    return "\n".join(
        f"#{ligne.ordre + 1} — {ligne.libelle} (image indisponible)" for ligne in manquants
    )


# --------------------------------------------------------------------------
# Envoi
# --------------------------------------------------------------------------


async def _appeler(client: httpx.AsyncClient, methode: str, url: str, **options) -> httpx.Response:
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
    """Poste la compo : un entete, puis les images des builds par paquets de 10."""
    if not url:
        raise DiscordError(
            "Aucune URL de webhook Discord configuree. "
            "Renseignez-la dans l'administration ou dans le fichier .env."
        )

    images = await images_des_lignes(compo.lignes)
    lots = repartir_lignes(compo)
    memoire: list[dict[str, Any]] = []
    envoyes = 0

    async with httpx.AsyncClient(timeout=60.0) as client:
        for index, lot in enumerate(lots):
            fichiers: list[tuple[str, tuple[str, bytes, str]]] = []
            for ligne in lot:
                image = images.get(ligne.ordre)
                if image is not None:
                    fichiers.append((
                        f"files[{len(fichiers)}]",
                        (nom_fichier_image(ligne), image, "image/png"),
                    ))

            contenu = texte_entete(compo, auteur_pseudo, lien) if index == 0 else ""
            legende = _legende(lot, images)
            if legende:
                contenu = _tronquer(f"{contenu}\n{legende}".strip(), MAX_CHARS_CONTENU)

            charge: dict[str, Any] = {"content": contenu}
            if index == 0:
                charge["username"] = "Compos Albion"
            if fichiers:
                # Association explicite fichier -> piece jointe, comme le font les
                # bibliotheques Discord.
                charge["attachments"] = [
                    {"id": position, "filename": contenu_fichier[0]}
                    for position, (_, contenu_fichier) in enumerate(fichiers)
                ]

            if fichiers:
                reponse = await _appeler(
                    client, "POST", url, params={"wait": "true"},
                    data={"payload_json": json.dumps(charge)}, files=fichiers,
                )
            else:
                reponse = await _appeler(
                    client, "POST", url, params={"wait": "true"}, json=charge
                )

            corps = _corps_json(reponse)
            memoire.append({
                "message_id": corps.get("id"),
                "entete": index == 0,
                "ordres": [ligne.ordre for ligne in lot],
            })
            envoyes += 1

    return {
        "messages": envoyes,
        "images": sum(1 for ligne in compo.lignes if ligne.ordre in images),
        "memoire": memoire,
    }
