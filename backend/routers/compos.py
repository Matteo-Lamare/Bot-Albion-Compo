"""CRUD des compos, duplication, apercu, images, import tableur et envoi Discord."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..auth import membre_courant
from ..catalogue import index as index_catalogue
from ..config import settings
from ..database import get_db
from ..discord import DiscordError, envoyer_webhook, texte_entete
from ..images import DISPONIBLE as IMAGES_DISPONIBLES, image_de_ligne
from ..models import (
    Compo,
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
    ImportLignes,
    LigneCompoBase,
)
from ..tableur import XLSX_DISPONIBLE, importer_lignes, modele_csv, modele_xlsx
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


def _lien_compo(compo: Compo) -> str:
    """Lien public vers la page de la compo, ou chaine vide si le site n'a pas d'adresse."""
    return f"{settings.app_base_url}/compo?id={compo.id}" if settings.app_base_url else ""


def _serialiser(compo: Compo) -> CompoRead:
    lecture = CompoRead.model_validate(compo)
    lecture.auteur_pseudo = compo.auteur.pseudo if compo.auteur else None
    return lecture


def _appliquer_lignes(db: Session, compo: Compo, lignes: list[LigneCompoBase]) -> None:
    """Valide les lignes contre le catalogue puis remplace celles de la compo.

    Les suppressions sont ecrites avant les insertions, sinon la contrainte
    d'unicite (compo_id, ordre) saute pendant le flush.
    """
    validees = valider_lignes(index_catalogue(db), [l.model_dump() for l in lignes])

    if compo.lignes:
        compo.lignes.clear()
        db.flush()
    for position, valeurs in enumerate(validees):
        valeurs["ordre"] = position
        compo.lignes.append(LigneCompo(**valeurs))


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


# --------------------------------------------------------------------------
# Import de builds depuis un tableur (Excel / CSV)
# --------------------------------------------------------------------------
# Ces deux routes sont declarees avant « /{compo_id} » : sinon FastAPI tenterait
# de lire « modele-tableur » comme un identifiant de compo.


@router.get(
    "/modele-tableur",
    response_class=Response,
    responses={200: {"content": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}},
)
def modele_tableur(
    _: Membre = Depends(membre_courant), db: Session = Depends(get_db)
) -> Response:
    """Fichier a remplir : une ligne par build, menus deroulants du catalogue."""
    catalogue = index_catalogue(db)
    if XLSX_DISPONIBLE:
        return Response(
            content=modele_xlsx(catalogue),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="modele_builds.xlsx"'},
        )
    return Response(
        content=modele_csv(catalogue),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="modele_builds.csv"'},
    )


@router.post("/importer-tableur", response_model=ImportLignes)
async def importer_tableur(
    fichier: UploadFile = File(..., description="Classeur .xlsx ou fichier .csv"),
    _: Membre = Depends(membre_courant),
    db: Session = Depends(get_db),
) -> ImportLignes:
    """Lit un fichier de builds et renvoie les lignes correspondantes.

    Rien n'est enregistre ici : les lignes remontent au formulaire, ou elles
    peuvent encore etre relues et corrigees avant d'etre sauvegardees.
    """
    contenu = await fichier.read()
    if len(contenu) > 2_000_000:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Fichier trop volumineux (2 Mo maximum)."
        )
    lignes, avertissements = importer_lignes(index_catalogue(db), contenu, fichier.filename or "")
    return ImportLignes(
        lignes=[LigneCompoBase(**valeurs) for valeurs in lignes],
        avertissements=avertissements,
    )


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
    """Rendu de ce qui sera poste, pour verification avant envoi.

    Le message se resume a un entete et aux images des builds : pas d'embed,
    pas de description textuelle.
    """
    compo = _lire_compo(db, compo_id)
    pseudo = compo.auteur.pseudo if compo.auteur else "?"
    return {
        "entete": texte_entete(compo, pseudo, _lien_compo(compo)),
        "images_disponibles": IMAGES_DISPONIBLES,
        "apercu": [
            {
                "ordre": ligne.ordre,
                "titre": f"#{ligne.ordre + 1} — {ligne.libelle}",
                "image": f"/api/compos/{compo.id}/lignes/{ligne.ordre}/image.png",
            }
            for ligne in compo.lignes
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
            _lien_compo(compo),
        )
    except DiscordError as erreur:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(erreur)) from erreur

    compo.statut = StatutCompo.envoyee
    compo.date_envoi = utcnow()
    # Trace de ce qui est parti sur le salon.
    compo.discord_messages = json.dumps(resultat["memoire"])
    db.commit()
    return EnvoiDiscordResultat(
        statut=compo.statut,
        date_envoi=compo.date_envoi.replace(tzinfo=timezone.utc),
        messages_envoyes=resultat["messages"],
        images_jointes=resultat["images"],
    )
