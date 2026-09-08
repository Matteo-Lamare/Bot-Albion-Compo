"""Construction de l'embed Discord et envoi via webhook."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .models import Compo, LigneCompo

# Limites imposees par l'API Discord
MAX_FIELDS_PAR_EMBED = 12
MAX_EMBEDS_PAR_MESSAGE = 10
MAX_CHARS_FIELD_VALUE = 1024
MAX_CHARS_EMBED = 5800  # marge sous la limite de 6000
COULEUR = 0x2B7FBF


class DiscordError(RuntimeError):
    """Erreur remontee par le webhook Discord."""


def _tronquer(texte: str, limite: int) -> str:
    return texte if len(texte) <= limite else texte[: limite - 1] + "…"


def _nom(objet) -> str:
    return objet.nom if objet is not None else "—"


def formater_ligne(ligne: LigneCompo) -> tuple[str, str]:
    """Renvoie (titre_du_champ, valeur_du_champ) pour un joueur."""
    lignes: list[str] = [
        f"⚔️ **Arme** — {_nom(ligne.arme)}",
        f"┗ Sorts : {_nom(ligne.arme_sort_1)} / {_nom(ligne.arme_sort_2)}"
        f" / {_nom(ligne.arme_sort_3)} · Passif : {_nom(ligne.arme_passif)}",
    ]

    if ligne.offhand is not None:
        lignes.append(f"🛡️ **Off-hand** — {_nom(ligne.offhand)}")

    lignes.append(f"🪖 **Casque** — {_nom(ligne.casque)}")
    lignes.append(f"┗ Sort : {_nom(ligne.casque_sort)} · Passif : {_nom(ligne.casque_passif)}")

    passifs_torse = _nom(ligne.torse_passif_1)
    if ligne.torse_passif_2 is not None:
        passifs_torse += f" + {ligne.torse_passif_2.nom}"
    lignes.append(f"🥋 **Torse** — {_nom(ligne.torse)}")
    lignes.append(f"┗ Sort : {_nom(ligne.torse_sort)} · Passifs : {passifs_torse}")

    lignes.append(f"🥾 **Bottes** — {_nom(ligne.bottes)}")
    lignes.append(f"┗ Sort : {_nom(ligne.bottes_sort)} · Passif : {_nom(ligne.bottes_passif)}")

    cape = f"🧣 **Cape** — {_nom(ligne.cape)}"
    if ligne.cape_passif is not None:
        cape += f"\n┗ Passif : {ligne.cape_passif.nom}"
    lignes.append(cape)

    if ligne.monture is not None:
        suffixe = f" · Sort : {ligne.monture_sort.nom}" if ligne.monture_sort else ""
        lignes.append(f"🐎 **Monture** — {ligne.monture.nom}{suffixe}")

    consommables = [
        f"🧪 {ligne.potion.nom}" if ligne.potion is not None else None,
        f"🍲 {ligne.nourriture.nom}" if ligne.nourriture is not None else None,
    ]
    consommables = [c for c in consommables if c]
    if consommables:
        lignes.append(" · ".join(consommables))

    titre = _tronquer(f"#{ligne.ordre + 1} — {ligne.role_ou_joueur}", 256)
    return titre, _tronquer("\n".join(lignes), MAX_CHARS_FIELD_VALUE)


def construire_embeds(compo: Compo, auteur_pseudo: str) -> list[dict[str, Any]]:
    """Un embed d'entete + N embeds de lignes, decoupes selon les limites Discord."""
    description = (
        f"**Type** : {compo.type_contenu.value}\n"
        f"**Taille de groupe** : {compo.taille_groupe}\n"
        f"**Joueurs listes** : {len(compo.lignes)}\n"
        f"**Auteur** : {auteur_pseudo}"
    )
    if compo.notes:
        description += f"\n\n**Notes**\n{_tronquer(compo.notes, 1500)}"

    entete: dict[str, Any] = {
        "title": _tronquer(f"📋 {compo.nom}", 256),
        "description": _tronquer(description, 4096),
        "color": COULEUR,
        "footer": {"text": f"Compo #{compo.id} · Compos Albion Online"},
    }
    if compo.lignes and compo.lignes[0].arme is not None:
        entete["thumbnail"] = {"url": compo.lignes[0].arme.icone}
    embeds: list[dict[str, Any]] = [entete]

    champs_courants: list[dict[str, Any]] = []
    taille_courante = 0

    def _cloturer() -> None:
        nonlocal champs_courants, taille_courante
        if champs_courants:
            embeds.append({"color": COULEUR, "fields": champs_courants})
            champs_courants = []
            taille_courante = 0

    for ligne in compo.lignes:
        titre, valeur = formater_ligne(ligne)
        poids = len(titre) + len(valeur)
        if champs_courants and (
            len(champs_courants) >= MAX_FIELDS_PAR_EMBED
            or taille_courante + poids > MAX_CHARS_EMBED
        ):
            _cloturer()
        champs_courants.append({"name": titre, "value": valeur, "inline": False})
        taille_courante += poids
    _cloturer()

    return embeds


def decouper_en_messages(embeds: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [
        embeds[i : i + MAX_EMBEDS_PAR_MESSAGE]
        for i in range(0, len(embeds), MAX_EMBEDS_PAR_MESSAGE)
    ]


async def envoyer_webhook(url: str, compo: Compo, auteur_pseudo: str) -> int:
    """Envoie la compo sur le webhook. Renvoie le nombre de messages postes."""
    if not url:
        raise DiscordError(
            "Aucune URL de webhook Discord configuree. "
            "Renseignez-la dans l'administration ou dans le fichier .env."
        )

    messages = decouper_en_messages(construire_embeds(compo, auteur_pseudo))
    envoyes = 0

    async with httpx.AsyncClient(timeout=20.0) as client:
        for index, lot in enumerate(messages):
            charge = {"embeds": lot}
            if index == 0:
                charge["username"] = "Compos Albion"
            for tentative in range(3):
                reponse = await client.post(url, json=charge)
                if reponse.status_code == 429:  # rate limit
                    attente = float(reponse.headers.get("Retry-After", "1"))
                    await asyncio.sleep(min(attente, 5.0))
                    continue
                if reponse.status_code >= 400:
                    raise DiscordError(
                        f"Discord a repondu {reponse.status_code} : "
                        f"{_tronquer(reponse.text, 300)}"
                    )
                break
            else:
                raise DiscordError("Discord limite les envois (429), reessayez dans un instant.")
            envoyes += 1

    return envoyes
