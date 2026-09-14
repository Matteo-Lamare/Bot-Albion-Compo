"""Schemas Pydantic + regles de validation par slot d'equipement.

Ces regles sont la source de verite : le frontend les reproduit pour le confort
de l'utilisateur, mais rien n'est accepte sans etre revalide ici.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from .models import RoleMembre, StatutCompo, TypeContenu

Requis = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Libelle = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
Identifiant = Annotated[int, Field(gt=0)]


def _vide_en_none(valeur: Any) -> Any:
    if isinstance(valeur, str) and not valeur.strip():
        return None
    return valeur


class LigneCompoBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ordre: int = Field(default=0, ge=0)
    role_ou_joueur: Libelle = ""
    arme_id: Identifiant
    arme_sort_1_id: Identifiant
    arme_sort_2_id: Identifiant
    arme_sort_3_id: Identifiant | None = None
    arme_passif_id: Identifiant
    offhand_id: Identifiant | None = None
    casque_id: Identifiant
    casque_sort_id: Identifiant
    casque_passif_id: Identifiant
    torse_id: Identifiant
    torse_sort_id: Identifiant
    torse_passif_1_id: Identifiant
    torse_passif_2_id: Identifiant | None = None
    bottes_id: Identifiant
    bottes_sort_id: Identifiant
    bottes_passif_id: Identifiant
    cape_id: Identifiant
    cape_passif_id: Identifiant | None = None
    monture_id: Identifiant | None = None
    monture_sort_id: Identifiant | None = None
    potion_id: Identifiant | None = None
    nourriture_id: Identifiant | None = None

    @field_validator("role_ou_joueur", mode="before")
    @classmethod
    def _role_absent(cls, valeur: Any) -> Any:
        return "" if valeur is None else valeur


class LigneCompoRead(LigneCompoBase):
    id: int
    libelle: str = ""


class CompoBase(BaseModel):
    nom: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    type_contenu: TypeContenu
    taille_groupe: int = Field(ge=1, le=200)
    statut: StatutCompo = StatutCompo.brouillon
    notes: str | None = None

    @field_validator("notes", mode="before")
    @classmethod
    def _notes_vides(cls, valeur: Any) -> Any:
        return _vide_en_none(valeur)


class CompoWrite(CompoBase):
    lignes: list[LigneCompoBase] = Field(min_length=1)

    @model_validator(mode="after")
    def _reordonner_les_lignes(self) -> "CompoWrite":
        for index, ligne in enumerate(self.lignes):
            ligne.ordre = index
        return self


class CompoRead(CompoBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    auteur_id: int
    auteur_pseudo: str | None = None
    date_creation: datetime
    date_modification: datetime
    date_envoi: datetime | None = None
    lignes: list[LigneCompoRead] = []


class CompoResume(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nom: str
    type_contenu: TypeContenu
    taille_groupe: int
    statut: StatutCompo
    auteur_id: int
    auteur_pseudo: str | None = None
    nb_lignes: int = 0
    date_creation: datetime
    date_modification: datetime
    date_envoi: datetime | None = None


class LoginPayload(BaseModel):
    pseudo: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    mot_de_passe: Annotated[str, StringConstraints(min_length=1)]


class MembreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    pseudo: str
    role: RoleMembre
    actif: bool
    date_creation: datetime


class MembreCreate(BaseModel):
    pseudo: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=64)]
    mot_de_passe: Annotated[str, StringConstraints(min_length=6, max_length=128)]
    role: RoleMembre = RoleMembre.membre


class MembreUpdate(BaseModel):
    mot_de_passe: Annotated[str, StringConstraints(min_length=6, max_length=128)] | None = None
    role: RoleMembre | None = None
    actif: bool | None = None


class ChangePasswordPayload(BaseModel):
    ancien_mot_de_passe: Annotated[str, StringConstraints(min_length=1)]
    nouveau_mot_de_passe: Annotated[str, StringConstraints(min_length=6, max_length=128)]


class EnvoiDiscordPayload(BaseModel):
    """Webhook fourni uniquement pour cet envoi, jamais persiste en base."""
    webhook_url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    type_salon: str = "forum"

    @field_validator("webhook_url")
    @classmethod
    def _valider_webhook(cls, valeur: str) -> str:
        if not (valeur.startswith("https://discord.com/api/webhooks/") or valeur.startswith("https://discordapp.com/api/webhooks/")):
            raise ValueError("L'URL doit commencer par https://discord.com/api/webhooks/")
        return valeur

    @field_validator("type_salon")
    @classmethod
    def _valider_type_salon(cls, valeur: str) -> str:
        valeur = valeur.strip().lower()
        if valeur not in {"text", "forum"}:
            raise ValueError("Le type de salon doit etre 'text' ou 'forum'.")
        return valeur


class EnvoiDiscordResultat(BaseModel):
    statut: StatutCompo
    date_envoi: datetime
    messages_envoyes: int
    images_jointes: int = 0


class ImportLignes(BaseModel):
    lignes: list[LigneCompoBase]
    avertissements: list[str] = []
