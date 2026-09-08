"""Authentification : hachage scrypt + session signee (cookie)."""
from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Membre, RoleMembre

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 32


def hacher_mot_de_passe(mot_de_passe: str) -> str:
    sel = os.urandom(16)
    cle = hashlib.scrypt(
        mot_de_passe.encode(), salt=sel, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DKLEN
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${sel.hex()}${cle.hex()}"


def verifier_mot_de_passe(mot_de_passe: str, encode: str) -> bool:
    try:
        algo, n, r, p, sel_hex, cle_hex = encode.split("$")
        if algo != "scrypt":
            return False
        cle = hashlib.scrypt(
            mot_de_passe.encode(),
            salt=bytes.fromhex(sel_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(cle_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(cle, bytes.fromhex(cle_hex))


def authentifier(db: Session, pseudo: str, mot_de_passe: str) -> Membre | None:
    membre = db.scalar(select(Membre).where(Membre.pseudo == pseudo))
    if membre is None or not membre.actif:
        return None
    if not verifier_mot_de_passe(mot_de_passe, membre.mot_de_passe_hash):
        return None
    return membre


def membre_courant(request: Request, db: Session = Depends(get_db)) -> Membre:
    """Dependance : renvoie le membre connecte ou leve une 401."""
    membre_id = request.session.get("membre_id")
    if not membre_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentification requise.")
    membre = db.get(Membre, membre_id)
    if membre is None or not membre.actif:
        request.session.clear()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session invalide.")
    return membre


def admin_courant(membre: Membre = Depends(membre_courant)) -> Membre:
    if membre.role != RoleMembre.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Reserve aux administrateurs.")
    return membre
