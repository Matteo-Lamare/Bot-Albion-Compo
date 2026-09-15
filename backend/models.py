"""Modeles SQLAlchemy : Membre, Compo, LigneCompo, Setting."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RoleMembre(str, enum.Enum):
    admin = "admin"
    membre = "membre"


class TypeContenu(str, enum.Enum):
    ganking = "Ganking"
    small_scale = "Small-scale"
    zvz = "ZvZ"
    hce = "HCE"
    avalonian_roads = "Avalonian Roads"
    corrupted_dungeon = "Corrupted Dungeon"
    group_dungeon = "Donjon de groupe"
    hellgate = "Hellgate"
    solo = "Solo"
    terre_ancestrale = "Terre ancestrale"


class StatutCompo(str, enum.Enum):
    brouillon = "brouillon"
    validee = "validée"
    envoyee = "envoyée"


class SlotEquipement(str, enum.Enum):
    """Emplacements d'equipement d'une ligne de compo."""

    arme = "arme"
    offhand = "offhand"
    casque = "casque"
    torse = "torse"
    bottes = "bottes"
    cape = "cape"
    monture = "monture"
    potion = "potion"
    nourriture = "nourriture"


class Emplacement(str, enum.Enum):
    """Nature d'un sort dans le pool d'une categorie."""

    sort_1 = "sort_1"      # armes : premier sort actif
    sort_2 = "sort_2"      # armes : deuxieme sort actif
    sort = "sort"          # armures : unique sort actif
    passif = "passif"      # armes, capes, montures
    passif_1 = "passif_1"  # armures : premier emplacement de passif
    passif_2 = "passif_2"  # armures : second emplacement (torses en plaques)


class SortAlbion(Base):
    """Sort actif ou passif du jeu (icone servie par render.albiononline.com)."""

    __tablename__ = "catalogue_sorts"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    nom: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    passif: Mapped[bool] = mapped_column(default=False, nullable=False)

    @property
    def icone(self) -> str:
        return f"https://render.albiononline.com/v1/spell/{self.code}.png"


class CategorieAlbion(Base):
    """Categorie d'objets (epees, casques en plaques, capes de Martlock...).

    C'est elle qui definit les sorts et passifs parmi lesquels un objet peut choisir.
    """

    __tablename__ = "catalogue_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    nom: Mapped[str] = mapped_column(String(120), nullable=False)
    slot: Mapped[SlotEquipement] = mapped_column(
        SAEnum(SlotEquipement, native_enum=False, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        index=True,
    )

    sorts: Mapped[list["CategorieSort"]] = relationship(
        back_populates="categorie", cascade="all, delete-orphan", lazy="selectin"
    )
    objets: Mapped[list["ObjetAlbion"]] = relationship(back_populates="categorie")


class CategorieSort(Base):
    """Sort disponible pour une categorie, a un emplacement donne."""

    __tablename__ = "catalogue_categorie_sorts"
    __table_args__ = (
        UniqueConstraint("categorie_id", "emplacement", "sort_id", name="uq_pool_categorie"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    categorie_id: Mapped[int] = mapped_column(
        ForeignKey("catalogue_categories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sort_id: Mapped[int] = mapped_column("sort_id", ForeignKey("catalogue_sorts.id", ondelete="CASCADE"), nullable=False, index=True)
    emplacement: Mapped[Emplacement] = mapped_column(
        SAEnum(Emplacement, native_enum=False, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    categorie: Mapped[CategorieAlbion] = relationship(back_populates="sorts")
    sort: Mapped[SortAlbion] = relationship()


class ObjetAlbion(Base):
    """Objet du catalogue, rattache a une categorie."""

    __tablename__ = "catalogue_objets"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    nom: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    slot: Mapped[SlotEquipement] = mapped_column(
        SAEnum(SlotEquipement, native_enum=False, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        index=True,
    )
    categorie_id: Mapped[int] = mapped_column(ForeignKey("catalogue_categories.id"), nullable=False, index=True)
    code_rendu: Mapped[str] = mapped_column(String(160), nullable=False)
    deux_mains: Mapped[bool] = mapped_column(default=False, nullable=False)
    sort_impose_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_sorts.id"), nullable=True)
    sort_defaut_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_sorts.id"), nullable=True)
    categorie: Mapped[CategorieAlbion] = relationship(back_populates="objets")
    sort_impose: Mapped[SortAlbion | None] = relationship(foreign_keys=[sort_impose_id])
    sort_defaut: Mapped[SortAlbion | None] = relationship(foreign_keys=[sort_defaut_id])


class Compo(Base):
    """Composition de groupe partageable."""

    __tablename__ = "compos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(120), nullable=False)
    type_contenu: Mapped[TypeContenu] = mapped_column(
        SAEnum(TypeContenu, native_enum=False, values_callable=lambda e: [m.value for m in e]), nullable=False
    )
    taille_groupe: Mapped[int] = mapped_column(Integer, nullable=False)
    statut: Mapped[StatutCompo] = mapped_column(
        SAEnum(StatutCompo, native_enum=False, values_callable=lambda e: [m.value for m in e]), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    auteur_id: Mapped[int] = mapped_column(ForeignKey("membres.id"), nullable=False, index=True)
    date_creation: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    date_modification: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    date_envoi: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discord_messages: Mapped[str | None] = mapped_column(Text, nullable=True)
    auteur: Mapped["Membre"] = relationship(back_populates="compos")
    lignes: Mapped[list["LigneCompo"]] = relationship(
        back_populates="compo", cascade="all, delete-orphan", order_by="LigneCompo.ordre", lazy="selectin"
    )


class LigneCompo(Base):
    """Une ligne/build dans une composition."""

    __tablename__ = "lignes_compo"

    id: Mapped[int] = mapped_column(primary_key=True)
    compo_id: Mapped[int] = mapped_column(ForeignKey("compos.id", ondelete="CASCADE"), nullable=False, index=True)
    ordre: Mapped[int] = mapped_column(Integer, nullable=False)
    role_ou_joueur: Mapped[str | None] = mapped_column(String(120), nullable=True)
    arme_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_objets.id"), nullable=True)
    arme_sort_1_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_sorts.id"), nullable=True)
    arme_sort_2_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_sorts.id"), nullable=True)
    arme_passif_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_sorts.id"), nullable=True)
    arme_sort_3_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_sorts.id"), nullable=True)
    offhand_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_objets.id"), nullable=True)
    casque_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_objets.id"), nullable=True)
    casque_sort_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_sorts.id"), nullable=True)
    casque_passif_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_sorts.id"), nullable=True)
    torse_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_objets.id"), nullable=True)
    torse_sort_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_sorts.id"), nullable=True)
    torse_passif_1_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_sorts.id"), nullable=True)
    torse_passif_2_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_sorts.id"), nullable=True)
    bottes_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_objets.id"), nullable=True)
    bottes_sort_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_sorts.id"), nullable=True)
    bottes_passif_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_sorts.id"), nullable=True)
    cape_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_objets.id"), nullable=True)
    cape_passif_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_sorts.id"), nullable=True)
    monture_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_objets.id"), nullable=True)
    monture_sort_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_sorts.id"), nullable=True)
    potion_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_objets.id"), nullable=True)
    nourriture_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_objets.id"), nullable=True)
    compo: Mapped[Compo] = relationship(back_populates="lignes")


class Membre(Base):
    """Compte utilisateur du site."""

    __tablename__ = "membres"

    id: Mapped[int] = mapped_column(primary_key=True)
    pseudo: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    mot_de_passe_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[RoleMembre] = mapped_column(
        SAEnum(RoleMembre, native_enum=False, values_callable=lambda e: [m.value for m in e]), nullable=False
    )
    actif: Mapped[bool] = mapped_column(default=True, nullable=False)
    date_creation: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    dernier_acces: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    compos: Mapped[list[Compo]] = relationship(back_populates="auteur")
