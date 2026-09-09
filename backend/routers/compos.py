"""CRUD des compos, duplication, apercu, images, inscriptions et envoi Discord."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..auth import membre_courant
from ..catalogue import index as index_catalogue
from ..config import settings
from ..database import get_db
from ..discord import (
    DiscordError,
    construire_embeds,
    envoyer_webhook,
    formater_ligne,
    inscrits_de_ligne,
    mettre_a_jour_messages,
)
from ..images import DISPONIBLE as IMAGES_DISPONIBLES, image_de_ligne
from ..models import (
    Compo,
    Inscription,
    LigneCompo,
    Membre,
    RoleMembre,
    StatutCompo,
    TypeContenu,
    utcnow,
)
from ..schemas import (
    CompoRead,
    CompoResume,
    CompoWrite,
    EnvoiDiscordResultat,
    InscriptionResultat,
    LigneCompoBase,
    LigneCompoInscriptions,
)
from ..validation import valider_lignes
from .admin import webhook_configure

router = APIRouter(prefix="/api/compos", tags=["compos"])

CHAMPS_LIGNE = tuple(LigneCompoBase.model_fields.keys())


def _lire_compo(db: Session, compo_id: int) -> Compo:
    compo = db.scalar(
        select(Compo).options(selectinload(Compo.lignes), selectinload(Compo.auteur)).where(
            Compo.id == compo_id
        )
    )
    if compo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compo introuvable.")
    return compo


def _verifier_droit_ecriture(compo: Compo, membre: Membre) -> None:
    if membre.role != RoleMembre.admin and compo.auteur_id != membre.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Seul l'auteur de la compo ou un administrateur peut la modifier.",
        )


def _lien_inscription(compo: Compo) -> str:
    """Lien public vers la page de la compo, ou chaine vide si le site n'a pas d'adresse."""
    return f"{settings.app_base_url}/compo?id={compo.id}" if settings.app_base_url else ""


def _memoire_discord(compo: Compo) -> list[dict]:
    try:
        return json.loads(compo.discord_messages) if compo.discord_messages else []
    except json.JSONDecodeError:
        return []


async def _resynchroniser_discord(db: Session, compo: Compo) -> bool:
    """Re-edite les messages Discord deja postes. Sans jamais bloquer l'appelant.

    Une inscription reste valable meme si Discord est injoignable : on se
    contente alors de ne pas rafraichir le message.
    """
    memoire = _memoire_discord(compo)
    if not memoire:
        return False
    try:
        modifies = await mettre_a_jour_messages(
            webhook_configure(db),
            compo,
            compo.auteur.pseudo if compo.auteur else "?",
            memoire,
            _lien_inscription(compo),
        )
    except (DiscordError, OSError):
        return False
    return modifies > 0


def _etat_inscriptions(compo: Compo) -> list[LigneCompoInscriptions]:
    return [
        LigneCompoInscriptions(
            ligne_id=ligne.id,
            ordre=ligne.ordre,
            libelle=ligne.libelle,
            inscrits=[
                {"membre_id": i.membre_id, "pseudo": i.pseudo, "date_creation": i.date_creation}
                for i in ligne.inscriptions
            ],
        )
        for ligne in compo.lignes
    ]


def _serialiser(compo: Compo) -> CompoRead:
    lecture = CompoRead.model_validate(compo)
    lecture.auteur_pseudo = compo.auteur.pseudo if compo.auteur else None
    return lecture


def _appliquer_lignes(db: Session, compo: Compo, lignes: list[LigneCompoBase]) -> None:
    """Valide les lignes contre le catalogue puis remplace celles de la compo.

    Les suppressions sont ecrites avant les insertions, sinon la contrainte
    d'unicite (compo_id, ordre) saute pendant le flush. Les inscrits sont
    rattaches au build de meme rang : editer une compo ne fait pas perdre les
    volontaires deja declares.
    """
    validees = valider_lignes(index_catalogue(db), [l.model_dump() for l in lignes])

    inscrits = {
        ligne.ordre: [inscription.membre_id for inscription in ligne.inscriptions]
        for ligne in compo.lignes
    }
    if compo.lignes:
        compo.lignes.clear()
        db.flush()
    for position, valeurs in enumerate(validees):
        valeurs["ordre"] = position
        nouvelle = LigneCompo(**valeurs)
        for membre_id in inscrits.get(position, []):
            nouvelle.inscriptions.append(Inscription(membre_id=membre_id))
        compo.lignes.append(nouvelle)


@router.get("", response_model=list[CompoResume])
def lister_compos(
    _: Membre = Depends(membre_courant),
    db: Session = Depends(get_db),
    type_contenu: TypeContenu | None = None,
    auteur_id: int | None = None,
    statut: StatutCompo | None = None,
    date_debut: date | None = Query(None, description="Filtre sur la date de creation (incluse)"),
    date_fin: date | None = Query(None, description="Filtre sur la date de creation (incluse)"),
    recherche: str | None = Query(None, description="Recherche sur le nom de la compo"),
) -> list[CompoResume]:
    nb_lignes = (
        select(LigneCompo.compo_id, func.count(LigneCompo.id).label("nb"))
        .group_by(LigneCompo.compo_id)
        .subquery()
    )
    requete = (
        select(Compo, Membre.pseudo, func.coalesce(nb_lignes.c.nb, 0))
        .join(Membre, Compo.auteur_id == Membre.id)
        .outerjoin(nb_lignes, nb_lignes.c.compo_id == Compo.id)
    )
    if type_contenu is not None:
        requete = requete.where(Compo.type_contenu == type_contenu)
    if auteur_id is not None:
        requete = requete.where(Compo.auteur_id == auteur_id)
    if statut is not None:
        requete = requete.where(Compo.statut == statut)
    if date_debut is not None:
        requete = requete.where(Compo.date_creation >= datetime.combine(date_debut, time.min))
    if date_fin is not None:
        requete = requete.where(Compo.date_creation <= datetime.combine(date_fin, time.max))
    if recherche:
        requete = requete.where(Compo.nom.ilike(f"%{recherche.strip()}%"))

    requete = requete.order_by(Compo.date_modification.desc())

    resultats: list[CompoResume] = []
    for compo, pseudo, compte in db.execute(requete).all():
        resume = CompoResume.model_validate(compo)
        resume.auteur_pseudo = pseudo
        resume.nb_lignes = compte
        resultats.append(resume)
    return resultats


@router.post("", response_model=CompoRead, status_code=status.HTTP_201_CREATED)
def creer_compo(
    payload: CompoWrite,
    membre: Membre = Depends(membre_courant),
    db: Session = Depends(get_db),
) -> CompoRead:
    compo = Compo(
        nom=payload.nom,
        type_contenu=payload.type_contenu,
        taille_groupe=payload.taille_groupe,
        statut=payload.statut,
        notes=payload.notes,
        auteur_id=membre.id,
    )
    db.add(compo)
    _appliquer_lignes(db, compo, payload.lignes)
    db.commit()
    return _serialiser(_lire_compo(db, compo.id))


@router.get("/{compo_id}", response_model=CompoRead)
def lire_compo(
    compo_id: int,
    _: Membre = Depends(membre_courant),
    db: Session = Depends(get_db),
) -> CompoRead:
    return _serialiser(_lire_compo(db, compo_id))


@router.put("/{compo_id}", response_model=CompoRead)
def modifier_compo(
    compo_id: int,
    payload: CompoWrite,
    membre: Membre = Depends(membre_courant),
    db: Session = Depends(get_db),
) -> CompoRead:
    compo = _lire_compo(db, compo_id)
    _verifier_droit_ecriture(compo, membre)

    compo.nom = payload.nom
    compo.type_contenu = payload.type_contenu
    compo.taille_groupe = payload.taille_groupe
    compo.statut = payload.statut
    compo.notes = payload.notes
    _appliquer_lignes(db, compo, payload.lignes)
    compo.date_modification = utcnow()
    db.commit()
    return _serialiser(_lire_compo(db, compo_id))


@router.post("/{compo_id}/dupliquer", response_model=CompoRead, status_code=status.HTTP_201_CREATED)
def dupliquer_compo(
    compo_id: int,
    membre: Membre = Depends(membre_courant),
    db: Session = Depends(get_db),
) -> CompoRead:
    source = _lire_compo(db, compo_id)
    copie = Compo(
        nom=f"{source.nom} (copie)"[:120],
        type_contenu=source.type_contenu,
        taille_groupe=source.taille_groupe,
        statut=StatutCompo.brouillon,
        notes=source.notes,
        auteur_id=membre.id,
    )
    for ligne in source.lignes:
        valeurs = {champ: getattr(ligne, champ) for champ in CHAMPS_LIGNE}
        copie.lignes.append(LigneCompo(**valeurs))
    db.add(copie)
    db.commit()
    return _serialiser(_lire_compo(db, copie.id))


@router.delete("/{compo_id}", status_code=status.HTTP_204_NO_CONTENT)
def supprimer_compo(
    compo_id: int,
    membre: Membre = Depends(membre_courant),
    db: Session = Depends(get_db),
) -> None:
    compo = _lire_compo(db, compo_id)
    _verifier_droit_ecriture(compo, membre)
    db.delete(compo)
    db.commit()


@router.get("/{compo_id}/apercu-discord")
def apercu_discord(
    compo_id: int,
    _: Membre = Depends(membre_courant),
    db: Session = Depends(get_db),
) -> dict:
    """Rendu de ce qui sera poste, pour verification avant envoi."""
    compo = _lire_compo(db, compo_id)
    pseudo = compo.auteur.pseudo if compo.auteur else "?"
    return {
        "embeds": construire_embeds(compo, pseudo, _lien_inscription(compo)),
        "images_disponibles": IMAGES_DISPONIBLES,
        "apercu": [
            {
                "ordre": ligne.ordre,
                "titre": titre,
                "corps": corps,
                "image": f"/api/compos/{compo.id}/lignes/{ligne.ordre}/image.png",
                "inscrits": inscrits_de_ligne(ligne),
            }
            for ligne, (titre, corps) in (
                (ligne, formater_ligne(ligne)) for ligne in compo.lignes
            )
        ],
    }


@router.get(
    "/{compo_id}/lignes/{ordre}/image.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def image_de_build(
    compo_id: int,
    ordre: int,
    _: Membre = Depends(membre_courant),
    db: Session = Depends(get_db),
) -> Response:
    """Image du build, telle qu'elle part en piece jointe sur Discord."""
    compo = _lire_compo(db, compo_id)
    ligne = next((l for l in compo.lignes if l.ordre == ordre), None)
    if ligne is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Build introuvable.")
    if not IMAGES_DISPONIBLES:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "Rendu d'image indisponible : installez Pillow (pip install -r requirements.txt).",
        )
    image = await image_de_ligne(ligne)
    if image is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Impossible de composer l'image du build.")
    return Response(content=image, media_type="image/png",
                    headers={"Cache-Control": "no-cache"})


@router.post("/{compo_id}/envoyer-discord", response_model=EnvoiDiscordResultat)
async def envoyer_sur_discord(
    compo_id: int,
    _: Membre = Depends(membre_courant),
    db: Session = Depends(get_db),
) -> EnvoiDiscordResultat:
    compo = _lire_compo(db, compo_id)
    url = webhook_configure(db)
    try:
        resultat = await envoyer_webhook(
            url,
            compo,
            compo.auteur.pseudo if compo.auteur else "?",
            _lien_inscription(compo),
        )
    except DiscordError as erreur:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(erreur)) from erreur

    compo.statut = StatutCompo.envoyee
    compo.date_envoi = utcnow()
    # Memorise les messages postes pour pouvoir les re-editer a chaque inscription.
    compo.discord_messages = json.dumps(resultat["memoire"])
    db.commit()
    return EnvoiDiscordResultat(
        statut=compo.statut,
        date_envoi=compo.date_envoi.replace(tzinfo=timezone.utc),
        messages_envoyes=resultat["messages"],
        images_jointes=resultat["images"],
    )


# --------------------------------------------------------------------------
# Inscriptions : chacun choisit le build qu'il veut jouer
# --------------------------------------------------------------------------


def _ligne_de_compo(compo: Compo, ligne_id: int) -> LigneCompo:
    ligne = next((l for l in compo.lignes if l.id == ligne_id), None)
    if ligne is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Build introuvable dans cette compo.")
    return ligne


@router.get("/{compo_id}/inscriptions", response_model=InscriptionResultat)
def lire_inscriptions(
    compo_id: int,
    _: Membre = Depends(membre_courant),
    db: Session = Depends(get_db),
) -> InscriptionResultat:
    return InscriptionResultat(lignes=_etat_inscriptions(_lire_compo(db, compo_id)))


@router.post("/{compo_id}/lignes/{ligne_id}/inscription", response_model=InscriptionResultat)
async def s_inscrire(
    compo_id: int,
    ligne_id: int,
    membre: Membre = Depends(membre_courant),
    db: Session = Depends(get_db),
) -> InscriptionResultat:
    """Declare le membre volontaire sur ce build.

    Un membre ne tient qu'un build par compo : s'inscrire ailleurs deplace
    simplement son inscription.
    """
    compo = _lire_compo(db, compo_id)
    ligne = _ligne_de_compo(compo, ligne_id)

    deja = False
    for autre in compo.lignes:
        for inscription in list(autre.inscriptions):
            if inscription.membre_id == membre.id:
                if autre.id == ligne.id:
                    deja = True
                else:
                    autre.inscriptions.remove(inscription)
    if not deja:
        ligne.inscriptions.append(Inscription(membre_id=membre.id))
    db.commit()
    db.refresh(compo)

    return InscriptionResultat(
        lignes=_etat_inscriptions(compo),
        discord_mis_a_jour=await _resynchroniser_discord(db, compo),
    )


@router.delete("/{compo_id}/lignes/{ligne_id}/inscription", response_model=InscriptionResultat)
async def se_desinscrire(
    compo_id: int,
    ligne_id: int,
    membre_id: int | None = Query(None, description="Reserve aux admins : liberer la place d'un autre"),
    membre: Membre = Depends(membre_courant),
    db: Session = Depends(get_db),
) -> InscriptionResultat:
    compo = _lire_compo(db, compo_id)
    ligne = _ligne_de_compo(compo, ligne_id)

    cible = membre.id
    if membre_id is not None and membre_id != membre.id:
        if membre.role != RoleMembre.admin:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Seul un administrateur peut desinscrire quelqu'un d'autre.",
            )
        cible = membre_id

    for inscription in list(ligne.inscriptions):
        if inscription.membre_id == cible:
            ligne.inscriptions.remove(inscription)
    db.commit()
    db.refresh(compo)

    return InscriptionResultat(
        lignes=_etat_inscriptions(compo),
        discord_mis_a_jour=await _resynchroniser_discord(db, compo),
    )
