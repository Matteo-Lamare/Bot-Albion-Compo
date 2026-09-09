"""Message Discord d'une compo : embeds, images de build et inscriptions.

Un envoi produit un embed d'entete puis un embed par build, chacun accompagne
de son image (cf. backend/images.py) postee en piece jointe. Les identifiants
des messages sont memorises sur la compo : quand quelqu'un s'inscrit sur un
build depuis le site, le message deja poste est simplement re-edite.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Iterable

import httpx

from .images import images_des_lignes
from .models import Compo, LigneCompo

# Limites imposees par l'API Discord
MAX_EMBEDS_PAR_MESSAGE = 10
MAX_FICHIERS_PAR_MESSAGE = 10
MAX_CHARS_MESSAGE = 5800   # marge sous la limite de 6000 caracteres cumules
MAX_CHARS_DESCRIPTION = 4096
MAX_CHARS_FIELD_VALUE = 1024
COULEUR = 0x2B7FBF
COULEUR_LIBRE = 0x9AA3B2   # build sans volontaire


class DiscordError(RuntimeError):
    """Erreur remontee par le webhook Discord."""


def _tronquer(texte: str, limite: int) -> str:
    return texte if len(texte) <= limite else texte[: limite - 1] + "…"


def _nom(objet) -> str:
    return objet.nom if objet is not None else "—"


def nom_fichier_image(ligne: LigneCompo) -> str:
    return f"build_{ligne.ordre + 1}.png"


# --------------------------------------------------------------------------
# Rendu texte d'un build
# --------------------------------------------------------------------------


def formater_ligne(ligne: LigneCompo) -> tuple[str, str]:
    """Renvoie (titre, corps) pour un build.

    L'image porte les icones et les noms d'objets ; le texte porte ce qu'elle
    ne peut pas dire, c'est-a-dire le nom des sorts et des passifs.
    """
    def sorts(*valeurs) -> str:
        noms = [_nom(valeur) for valeur in valeurs if valeur is not None]
        return " · ".join(noms) if noms else "—"

    lignes: list[str] = [
        f"⚔️ **{_nom(ligne.arme)}** — "
        f"{sorts(ligne.arme_sort_1, ligne.arme_sort_2, ligne.arme_sort_3, ligne.arme_passif)}",
        f"🪖 **{_nom(ligne.casque)}** — {sorts(ligne.casque_sort, ligne.casque_passif)}",
        f"🥋 **{_nom(ligne.torse)}** — "
        f"{sorts(ligne.torse_sort, ligne.torse_passif_1, ligne.torse_passif_2)}",
        f"🥾 **{_nom(ligne.bottes)}** — {sorts(ligne.bottes_sort, ligne.bottes_passif)}",
        f"🧣 **{_nom(ligne.cape)}** — {sorts(ligne.cape_passif)}",
    ]

    annexes = [
        f"🛡️ {ligne.offhand.nom}" if ligne.offhand is not None else None,
        f"🐎 {ligne.monture.nom}" if ligne.monture is not None else None,
        f"🧪 {ligne.potion.nom}" if ligne.potion is not None else None,
        f"🍲 {ligne.nourriture.nom}" if ligne.nourriture is not None else None,
    ]
    annexes = [annexe for annexe in annexes if annexe]
    if annexes:
        lignes.append(" · ".join(annexes))

    titre = _tronquer(f"#{ligne.ordre + 1} — {ligne.libelle}", 256)
    return titre, _tronquer("\n".join(lignes), MAX_CHARS_DESCRIPTION)


def inscrits_de_ligne(ligne: LigneCompo) -> list[str]:
    return [inscription.pseudo for inscription in ligne.inscriptions]


# --------------------------------------------------------------------------
# Embeds
# --------------------------------------------------------------------------


def embed_entete(compo: Compo, auteur_pseudo: str, lien: str = "") -> dict[str, Any]:
    inscrits = sum(len(ligne.inscriptions) for ligne in compo.lignes)
    description = (
        f"**Type** : {compo.type_contenu.value}\n"
        f"**Taille de groupe** : {compo.taille_groupe}\n"
        f"**Builds proposes** : {len(compo.lignes)}\n"
        f"**Inscrits** : {inscrits}/{len(compo.lignes)}\n"
        f"**Auteur** : {auteur_pseudo}"
    )
    if compo.notes:
        description += f"\n\n**Notes**\n{_tronquer(compo.notes, 1200)}"
    if lien:
        description += (
            f"\n\n🙋 **Choisissez votre build** : {lien}\n"
            "Le message se met a jour tout seul apres chaque inscription."
        )

    entete: dict[str, Any] = {
        "title": _tronquer(f"📋 {compo.nom}", 256),
        "description": _tronquer(description, MAX_CHARS_DESCRIPTION),
        "color": COULEUR,
        "footer": {"text": f"Compo #{compo.id} · Compos Albion Online"},
    }
    if compo.lignes and compo.lignes[0].arme is not None:
        entete["thumbnail"] = {"url": compo.lignes[0].arme.icone}
    return entete


def embed_de_ligne(ligne: LigneCompo, avec_image: bool = False) -> dict[str, Any]:
    titre, corps = formater_ligne(ligne)
    inscrits = inscrits_de_ligne(ligne)
    embed: dict[str, Any] = {
        "title": titre,
        "description": corps,
        "color": COULEUR if inscrits else COULEUR_LIBRE,
        "fields": [{
            "name": f"🙋 Inscrits ({len(inscrits)})" if inscrits else "🙋 Personne pour l'instant",
            "value": _tronquer(
                " · ".join(f"**{pseudo}**" for pseudo in inscrits) if inscrits
                else "Ce build est libre — inscrivez-vous depuis le site.",
                MAX_CHARS_FIELD_VALUE,
            ),
            "inline": False,
        }],
    }
    if avec_image:
        embed["image"] = {"url": f"attachment://{nom_fichier_image(ligne)}"}
    return embed


def poids_embed(embed: dict[str, Any]) -> int:
    """Nombre de caracteres comptes par Discord pour un embed."""
    return (
        len(embed.get("title", ""))
        + len(embed.get("description", ""))
        + len(embed.get("footer", {}).get("text", ""))
        + sum(len(c["name"]) + len(c["value"]) for c in embed.get("fields", []))
    )


def repartir_lignes(compo: Compo) -> list[list[LigneCompo]]:
    """Groupe les builds par message, selon les limites de Discord.

    Un message porte au plus 10 embeds, 10 pieces jointes et 6000 caracteres ;
    l'entete occupe une place dans le premier message.
    """
    lots: list[list[LigneCompo]] = []
    courant: list[LigneCompo] = []
    poids = poids_embed(embed_entete(compo, "", ""))
    places = MAX_EMBEDS_PAR_MESSAGE - 1  # l'entete prend un embed

    for ligne in compo.lignes:
        cout = poids_embed(embed_de_ligne(ligne))
        if courant and (len(courant) >= min(places, MAX_FICHIERS_PAR_MESSAGE)
                        or poids + cout > MAX_CHARS_MESSAGE):
            lots.append(courant)
            courant = []
            poids = 0
            places = MAX_EMBEDS_PAR_MESSAGE
        courant.append(ligne)
        poids += cout
    if courant:
        lots.append(courant)
    return lots or [[]]


def construire_embeds(compo: Compo, auteur_pseudo: str, lien: str = "") -> list[dict[str, Any]]:
    """Tous les embeds de la compo, a plat (apercu et tests)."""
    return [embed_entete(compo, auteur_pseudo, lien)] + [
        embed_de_ligne(ligne) for ligne in compo.lignes
    ]


# --------------------------------------------------------------------------
# Envoi et mise a jour
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
    """Poste la compo. Renvoie le nombre de messages, d'images et de quoi les rouvrir.

    La cle « messages » est memorisee sur la compo : elle contient l'identifiant
    de chaque message poste, les pieces jointes a conserver et les builds qu'il
    presente, ce qu'il faut pour rejouer l'edition a chaque inscription.
    """
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
            embeds: list[dict[str, Any]] = []
            if index == 0:
                embeds.append(embed_entete(compo, auteur_pseudo, lien))

            fichiers: list[tuple[str, tuple[str, bytes, str]]] = []
            for ligne in lot:
                image = images.get(ligne.ordre)
                embeds.append(embed_de_ligne(ligne, avec_image=image is not None))
                if image is not None:
                    fichiers.append((
                        f"files[{len(fichiers)}]",
                        (nom_fichier_image(ligne), image, "image/png"),
                    ))

            charge: dict[str, Any] = {"embeds": embeds}
            if index == 0:
                charge["username"] = "Compos Albion"
            if fichiers:
                # Association explicite fichier -> piece jointe, comme le font les
                # bibliotheques Discord : les embeds y renvoient par attachment://.
                charge["attachments"] = [
                    {"id": position, "filename": contenu[0]}
                    for position, (_, contenu) in enumerate(fichiers)
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
                "pieces_jointes": [
                    piece.get("id") for piece in corps.get("attachments", []) or []
                ],
            })
            envoyes += 1

    return {
        "messages": envoyes,
        "images": sum(1 for ligne in compo.lignes if ligne.ordre in images),
        "memoire": memoire,
    }


async def mettre_a_jour_messages(
    url: str,
    compo: Compo,
    auteur_pseudo: str,
    memoire: Iterable[dict[str, Any]],
    lien: str = "",
) -> int:
    """Re-edite les messages deja postes (typiquement apres une inscription).

    Les images restent celles de l'envoi initial : seules les pieces jointes
    sont reconduites telles quelles, le texte et les inscrits sont recalcules.
    """
    if not url:
        return 0

    par_ordre = {ligne.ordre: ligne for ligne in compo.lignes}
    modifies = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        for message in memoire:
            identifiant = message.get("message_id")
            if not identifiant:
                continue
            lignes = [par_ordre[ordre] for ordre in message.get("ordres", []) if ordre in par_ordre]
            embeds: list[dict[str, Any]] = []
            if message.get("entete"):
                embeds.append(embed_entete(compo, auteur_pseudo, lien))
            pieces = message.get("pieces_jointes") or []
            for ligne in lignes:
                embeds.append(embed_de_ligne(ligne, avec_image=bool(pieces)))

            charge: dict[str, Any] = {"embeds": embeds}
            if pieces:
                # Sans cette liste, Discord retire les images du message edite.
                charge["attachments"] = [{"id": piece} for piece in pieces]
            await _appeler(client, "PATCH", f"{url}/messages/{identifiant}", json=charge)
            modifies += 1

    return modifies
