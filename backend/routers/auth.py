"""Routes d'authentification."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..auth import authentifier, hacher_mot_de_passe, membre_courant, verifier_mot_de_passe
from ..database import get_db
from ..models import Membre
from ..schemas import ChangePasswordPayload, LoginPayload, MembreRead

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=MembreRead)
def login(payload: LoginPayload, request: Request, db: Session = Depends(get_db)) -> Membre:
    membre = authentifier(db, payload.pseudo, payload.mot_de_passe)
    if membre is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Pseudo ou mot de passe incorrect.")
    request.session.clear()
    request.session["membre_id"] = membre.id
    return membre


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> None:
    request.session.clear()


@router.get("/me", response_model=MembreRead)
def me(membre: Membre = Depends(membre_courant)) -> Membre:
    return membre


@router.post("/changer-mot-de-passe", response_model=MembreRead)
def changer_mot_de_passe(
    payload: ChangePasswordPayload,
    membre: Membre = Depends(membre_courant),
    db: Session = Depends(get_db),
) -> Membre:
    """Permet au membre connecte de changer son propre mot de passe."""
    if not verifier_mot_de_passe(payload.ancien_mot_de_passe, membre.mot_de_passe_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "L'ancien mot de passe est incorrect.")
    if verifier_mot_de_passe(payload.nouveau_mot_de_passe, membre.mot_de_passe_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Le nouveau mot de passe doit etre different de l'ancien.")
    membre.mot_de_passe_hash = hacher_mot_de_passe(payload.nouveau_mot_de_passe)
    db.commit()
    db.refresh(membre)
    return membre
