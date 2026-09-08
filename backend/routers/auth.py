"""Routes d'authentification."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..auth import authentifier, membre_courant
from ..database import get_db
from ..models import Membre
from ..schemas import LoginPayload, MembreRead

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
