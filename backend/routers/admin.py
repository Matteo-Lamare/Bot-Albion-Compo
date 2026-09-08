"""Routes d'administration : membres et configuration du webhook."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import admin_courant, hacher_mot_de_passe, membre_courant
from ..config import settings
from ..database import get_db
from ..models import Membre, Setting
from ..schemas import MembreCreate, MembreRead, MembreUpdate, SettingsRead, SettingsUpdate

router = APIRouter(prefix="/api", tags=["admin"])

CLE_WEBHOOK = "discord_webhook_url"


def webhook_configure(db: Session) -> str:
    """URL du webhook : la valeur en base prime sur celle du .env."""
    enregistrement = db.get(Setting, CLE_WEBHOOK)
    if enregistrement and enregistrement.valeur.strip():
        return enregistrement.valeur.strip()
    return settings.discord_webhook_url.strip()


@router.get("/membres", response_model=list[MembreRead])
def lister_membres(
    _: Membre = Depends(membre_courant), db: Session = Depends(get_db)
) -> list[Membre]:
    """Accessible a tous les membres : sert aussi au filtre 'auteur'."""
    return list(db.scalars(select(Membre).order_by(Membre.pseudo)))


@router.post("/membres", response_model=MembreRead, status_code=status.HTTP_201_CREATED)
def creer_membre(
    payload: MembreCreate,
    _: Membre = Depends(admin_courant),
    db: Session = Depends(get_db),
) -> Membre:
    membre = Membre(
        pseudo=payload.pseudo,
        mot_de_passe_hash=hacher_mot_de_passe(payload.mot_de_passe),
        role=payload.role,
    )
    db.add(membre)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce pseudo existe deja.") from None
    db.refresh(membre)
    return membre


@router.put("/membres/{membre_id}", response_model=MembreRead)
def modifier_membre(
    membre_id: int,
    payload: MembreUpdate,
    admin: Membre = Depends(admin_courant),
    db: Session = Depends(get_db),
) -> Membre:
    membre = db.get(Membre, membre_id)
    if membre is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membre introuvable.")
    if membre.id == admin.id and payload.actif is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Impossible de se desactiver soi-meme.")
    if payload.mot_de_passe:
        membre.mot_de_passe_hash = hacher_mot_de_passe(payload.mot_de_passe)
    if payload.role is not None:
        membre.role = payload.role
    if payload.actif is not None:
        membre.actif = payload.actif
    db.commit()
    db.refresh(membre)
    return membre


@router.delete("/membres/{membre_id}", status_code=status.HTTP_204_NO_CONTENT)
def supprimer_membre(
    membre_id: int,
    admin: Membre = Depends(admin_courant),
    db: Session = Depends(get_db),
) -> None:
    membre = db.get(Membre, membre_id)
    if membre is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membre introuvable.")
    if membre.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Impossible de se supprimer soi-meme.")
    if membre.compos:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ce membre est auteur de compos : desactivez-le plutot que de le supprimer.",
        )
    db.delete(membre)
    db.commit()


def _lire_settings(db: Session) -> SettingsRead:
    enregistrement = db.get(Setting, CLE_WEBHOOK)
    if enregistrement and enregistrement.valeur.strip():
        return SettingsRead(discord_webhook_url=enregistrement.valeur.strip(), source="base")
    if settings.discord_webhook_url.strip():
        return SettingsRead(
            discord_webhook_url=settings.discord_webhook_url.strip(), source="env"
        )
    return SettingsRead(discord_webhook_url="", source="aucun")


@router.get("/settings", response_model=SettingsRead)
def lire_settings(
    _: Membre = Depends(admin_courant), db: Session = Depends(get_db)
) -> SettingsRead:
    return _lire_settings(db)


@router.put("/settings", response_model=SettingsRead)
def modifier_settings(
    payload: SettingsUpdate,
    _: Membre = Depends(admin_courant),
    db: Session = Depends(get_db),
) -> SettingsRead:
    enregistrement = db.get(Setting, CLE_WEBHOOK)
    if enregistrement is None:
        enregistrement = Setting(cle=CLE_WEBHOOK, valeur=payload.discord_webhook_url)
        db.add(enregistrement)
    else:
        enregistrement.valeur = payload.discord_webhook_url
    db.commit()
    return _lire_settings(db)
