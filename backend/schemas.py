"""Schemas Pydantic + regles de validation par slot d'equipement.

Ces regles sont la source de verite : le frontend les reproduit pour le confort
de l'utilisateur, mais rien n'est accepte sans etre revalide ici.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .models import RoleMembre, StatutCompo, TypeContenu

# Les identifiants renvoient au catalogue Albion (cf. backend/catalogue.py).
# La coherence (objet du bon slot, sort autorise par la categorie) est verifiee
# par backend/validation.py, qui a acces au catalogue.

Requis = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Identifiant = Annotated[int, Field(gt=0)]


def _vide_en_none(valeur: Any) -> Any:
    if isinstance(valeur, str) and not valeur.strip():
        return None
    return valeur


class LigneCompoBase(BaseModel):
    """Un joueur / role : chaque piece d'equipement pointe vers le catalogue.

    Les slots arme, casque, torse, bottes et cape sont obligatoires ; off-hand,
    monture, potion et nourriture sont facultatifs. Les sorts imposes par un objet
    (sort 3 d'une arme, passif d'une cape, sort d'une monture) sont ignores a
    l'entree et reposes par le serveur.
    """

    model_config = ConfigDict(from_attributes=True)

    ordre: int = Field(default=0, ge=0)
    role_ou_joueur: Requis

    # --- Arme ---
    arme_id: Identifiant
    arme_sort_1_id: Identifiant
    arme_sort_2_id: Identifiant
    arme_sort_3_id: Identifiant | None = None   # impose par l'arme
    arme_passif_id: Identifiant

    # --- Off-hand : facultatif, ni sort ni passif ---
    offhand_id: Identifiant | None = None

    # --- Casque ---
    casque_id: Identifiant
    casque_sort_id: Identifiant
    casque_passif_id: Identifiant

    # --- Torse : second passif seulement si la categorie en propose ---
    torse_id: Identifiant
    torse_sort_id: Identifiant
    torse_passif_1_id: Identifiant
    torse_passif_2_id: Identifiant | None = None

    # --- Bottes ---
    bottes_id: Identifiant
    bottes_sort_id: Identifiant
    bottes_passif_id: Identifiant

    # --- Cape : pas de sort, passif impose par la cape ---
    cape_id: Identifiant
    cape_passif_id: Identifiant | None = None

    # --- Monture : facultative, sort impose par la monture ---
    monture_id: Identifiant | None = None
    monture_sort_id: Identifiant | None = None

    # --- Consommables ---
    potion_id: Identifiant | None = None
    nourriture_id: Identifiant | None = None


class LigneCompoRead(LigneCompoBase):
    id: int


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
    """Version allegee (sans les lignes) pour la bibliotheque."""

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


# --- Membres / auth ---


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


class SettingsRead(BaseModel):
    discord_webhook_url: str
    source: str  # "base" ou "env" ou "aucun"


class SettingsUpdate(BaseModel):
    discord_webhook_url: Annotated[str, StringConstraints(strip_whitespace=True)] = ""

    @field_validator("discord_webhook_url")
    @classmethod
    def _valider_url(cls, valeur: str) -> str:
        if valeur and not valeur.startswith("https://discord.com/api/webhooks/"):
            if not valeur.startswith("https://discordapp.com/api/webhooks/"):
                raise ValueError(
                    "L'URL doit commencer par https://discord.com/api/webhooks/"
                )
        return valeur


class EnvoiDiscordResultat(BaseModel):
    statut: StatutCompo
    date_envoi: datetime
    messages_envoyes: int
