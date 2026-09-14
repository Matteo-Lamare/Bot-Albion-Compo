"""Routes d'administration : gestion des membres."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import admin_courant, hacher_mot_de_passe, membre_courant
from ..database import get_db
from ..models import Membre
from ..schemas import MembreCreate, MembreRead, MembreUpdate

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/membres", response_model=list[MembreRead])
def lister_membres(_: Membre = Depends(membre_courant), db: Session = Depends(get_db)) -> list[Membre]:
    return list(db.scalars(select(Membre).order_by(Membre.pseudo)))


@router.post("/membres", response_model=MembreRead, status_code=status.HTTP_201_CREATED)
def creer_membre(payload: MembreCreate, _: Membre = Depends(admin_courant), db: Session = Depends(get_db)) -> Membre:
    membre = Membre(pseudo=payload.pseudo, mot_de_passe_hash=hacher_mot_de_passe(payload.mot_de_passe), role=payload.role)
    db.add(membre)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce pseudo existe deja.") from None
    db.refresh(membre)
    return membre


@router.put("/membres/{membre_id}", response_model=MembreRead)
def modifier_membre(membre_id: int, payload: MembreUpdate, admin: Membre = Depends(admin_courant), db: Session = Depends(get_db)) -> Membre:
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
def supprimer_membre(membre_id: int, admin: Membre = Depends(admin_courant), db: Session = Depends(get_db)) -> None:
    membre = db.get(Membre, membre_id)
    if membre is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membre introuvable.")
    if membre.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Impossible de se supprimer soi-meme.")
    if membre.compos:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce membre est auteur de compos : desactivez-le plutot que de le supprimer.")
    db.delete(membre)
    db.commit()
