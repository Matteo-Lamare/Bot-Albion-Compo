"""Modeles SQLAlchemy : Membre, Compo, LigneCompo, Inscription, Setting."""
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
    sort_id: Mapped[int] = mapped_column(
        ForeignKey("catalogue_sorts.id", ondelete="CASCADE"), nullable=False
    )
    emplacement: Mapped[Emplacement] = mapped_column(
        SAEnum(Emplacement, native_enum=False, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    categorie: Mapped["CategorieAlbion"] = relationship(back_populates="sorts")
    sort: Mapped["SortAlbion"] = relationship(lazy="selectin")


class ObjetAlbion(Base):
    """Objet du jeu, tous tiers confondus (le tier n'est plus manipule par l'outil)."""

    __tablename__ = "catalogue_objets"
    __table_args__ = (UniqueConstraint("slot", "code", name="uq_objet_slot_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    nom: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    slot: Mapped[SlotEquipement] = mapped_column(
        SAEnum(SlotEquipement, native_enum=False, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        index=True,
    )
    categorie_id: Mapped[int] = mapped_column(
        ForeignKey("catalogue_categories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Identifiant complet (avec tier) utilise uniquement pour afficher l'icone.
    code_rendu: Mapped[str] = mapped_column(String(120), nullable=False)
    deux_mains: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Sort impose par l'objet lui-meme : sort 3 d'une arme, passif d'une cape ou
    # d'une monture. Il est pose automatiquement et n'est jamais choisi.
    sort_impose_id: Mapped[int | None] = mapped_column(
        ForeignKey("catalogue_sorts.id", ondelete="SET NULL"), nullable=True
    )
    # Sort natif d'une piece d'armure : preselectionne, mais remplacable par un
    # autre sort de sa categorie.
    sort_defaut_id: Mapped[int | None] = mapped_column(
        ForeignKey("catalogue_sorts.id", ondelete="SET NULL"), nullable=True
    )

    categorie: Mapped["CategorieAlbion"] = relationship(back_populates="objets", lazy="selectin")
    sort_impose: Mapped["SortAlbion | None"] = relationship(
        foreign_keys=[sort_impose_id], lazy="selectin"
    )
    sort_defaut: Mapped["SortAlbion | None"] = relationship(
        foreign_keys=[sort_defaut_id], lazy="selectin"
    )

    @property
    def icone(self) -> str:
        return f"https://render.albiononline.com/v1/item/{self.code_rendu}.png"


class Membre(Base):
    __tablename__ = "membres"

    id: Mapped[int] = mapped_column(primary_key=True)
    pseudo: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    mot_de_passe_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[RoleMembre] = mapped_column(
        SAEnum(RoleMembre, native_enum=False, values_callable=lambda e: [m.value for m in e]),
        default=RoleMembre.membre,
        nullable=False,
    )
    actif: Mapped[bool] = mapped_column(default=True, nullable=False)
    date_creation: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    compos: Mapped[list["Compo"]] = relationship(back_populates="auteur")


class Compo(Base):
    __tablename__ = "compos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    type_contenu: Mapped[TypeContenu] = mapped_column(
        SAEnum(TypeContenu, native_enum=False, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        index=True,
    )
    taille_groupe: Mapped[int] = mapped_column(Integer, nullable=False)
    auteur_id: Mapped[int] = mapped_column(
        ForeignKey("membres.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    date_creation: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    date_modification: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
    date_envoi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    statut: Mapped[StatutCompo] = mapped_column(
        SAEnum(StatutCompo, native_enum=False, values_callable=lambda e: [m.value for m in e]),
        default=StatutCompo.brouillon,
        nullable=False,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Messages postes sur Discord, au format JSON : identifiant du message,
    # pieces jointes a conserver et lignes qu'il contient. C'est ce qui permet
    # de reediter le message quand quelqu'un s'inscrit sur un build.
    discord_messages: Mapped[str | None] = mapped_column(Text, nullable=True)

    auteur: Mapped["Membre"] = relationship(back_populates="compos")
    lignes: Mapped[list["LigneCompo"]] = relationship(
        back_populates="compo",
        cascade="all, delete-orphan",
        order_by="LigneCompo.ordre",
        lazy="selectin",
    )


class LigneCompo(Base):
    """Un joueur / role dans une compo, avec son equipement complet.

    Chaque piece d'equipement pointe vers le catalogue Albion : plus de saisie
    libre ni de tier. Les sorts choisis sont contraints par la categorie de
    l'objet (cf. backend/catalogue.py), et les sorts imposes par l'objet
    lui-meme (sort 3 d'une arme, passif d'une cape) sont poses automatiquement.
    """

    __tablename__ = "lignes_compo"
    __table_args__ = (UniqueConstraint("compo_id", "ordre", name="uq_ligne_ordre"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    compo_id: Mapped[int] = mapped_column(
        ForeignKey("compos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Facultatif : une ligne est d'abord un build. Vide, elle s'affiche
    # « Build #n » et attend que quelqu'un s'inscrive dessus.
    role_ou_joueur: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    def _objet(nullable: bool = False):
        return mapped_column(
            ForeignKey("catalogue_objets.id", ondelete="RESTRICT"), nullable=nullable
        )

    def _sort(nullable: bool = False):
        return mapped_column(
            ForeignKey("catalogue_sorts.id", ondelete="RESTRICT"), nullable=nullable
        )

    # Arme : sorts 1 et 2 et passif choisis dans la categorie, sort 3 impose par l'arme
    arme_id: Mapped[int] = _objet()
    arme_sort_1_id: Mapped[int] = _sort()
    arme_sort_2_id: Mapped[int] = _sort()
    arme_sort_3_id: Mapped[int] = _sort()
    arme_passif_id: Mapped[int] = _sort()

    # Off-hand : optionnel, ni sort ni passif
    offhand_id: Mapped[int | None] = _objet(nullable=True)

    # Casque : sort natif remplacable dans la categorie, passif de la categorie
    casque_id: Mapped[int] = _objet()
    casque_sort_id: Mapped[int] = _sort()
    casque_passif_id: Mapped[int] = _sort()

    # Torse : second passif seulement si l'armure en propose deux
    torse_id: Mapped[int] = _objet()
    torse_sort_id: Mapped[int] = _sort()
    torse_passif_1_id: Mapped[int] = _sort()
    torse_passif_2_id: Mapped[int | None] = _sort(nullable=True)

    # Bottes
    bottes_id: Mapped[int] = _objet()
    bottes_sort_id: Mapped[int] = _sort()
    bottes_passif_id: Mapped[int] = _sort()

    # Cape : passif impose par la cape, absent des capes de cite
    cape_id: Mapped[int] = _objet()
    cape_passif_id: Mapped[int | None] = _sort(nullable=True)

    # Monture : optionnelle, sort impose par la monture
    monture_id: Mapped[int | None] = _objet(nullable=True)
    monture_sort_id: Mapped[int | None] = _sort(nullable=True)

    # Consommables
    potion_id: Mapped[int | None] = _objet(nullable=True)
    nourriture_id: Mapped[int | None] = _objet(nullable=True)

    del _objet, _sort

    compo: Mapped["Compo"] = relationship(back_populates="lignes")
    inscriptions: Mapped[list["Inscription"]] = relationship(
        back_populates="ligne",
        cascade="all, delete-orphan",
        order_by="Inscription.date_creation",
        lazy="selectin",
    )

    @property
    def libelle(self) -> str:
        """Intitule affichable de la ligne, meme sans joueur assigne."""
        return self.role_ou_joueur.strip() or f"Build #{self.ordre + 1}"

    arme: Mapped["ObjetAlbion"] = relationship(foreign_keys=[arme_id], lazy="selectin")
    offhand: Mapped["ObjetAlbion | None"] = relationship(foreign_keys=[offhand_id], lazy="selectin")
    casque: Mapped["ObjetAlbion"] = relationship(foreign_keys=[casque_id], lazy="selectin")
    torse: Mapped["ObjetAlbion"] = relationship(foreign_keys=[torse_id], lazy="selectin")
    bottes: Mapped["ObjetAlbion"] = relationship(foreign_keys=[bottes_id], lazy="selectin")
    cape: Mapped["ObjetAlbion"] = relationship(foreign_keys=[cape_id], lazy="selectin")
    monture: Mapped["ObjetAlbion | None"] = relationship(foreign_keys=[monture_id], lazy="selectin")
    potion: Mapped["ObjetAlbion | None"] = relationship(foreign_keys=[potion_id], lazy="selectin")
    nourriture: Mapped["ObjetAlbion | None"] = relationship(
        foreign_keys=[nourriture_id], lazy="selectin"
    )

    arme_sort_1: Mapped["SortAlbion"] = relationship(foreign_keys=[arme_sort_1_id], lazy="selectin")
    arme_sort_2: Mapped["SortAlbion"] = relationship(foreign_keys=[arme_sort_2_id], lazy="selectin")
    arme_sort_3: Mapped["SortAlbion"] = relationship(foreign_keys=[arme_sort_3_id], lazy="selectin")
    arme_passif: Mapped["SortAlbion"] = relationship(foreign_keys=[arme_passif_id], lazy="selectin")
    casque_sort: Mapped["SortAlbion"] = relationship(foreign_keys=[casque_sort_id], lazy="selectin")
    casque_passif: Mapped["SortAlbion"] = relationship(
        foreign_keys=[casque_passif_id], lazy="selectin"
    )
    torse_sort: Mapped["SortAlbion"] = relationship(foreign_keys=[torse_sort_id], lazy="selectin")
    torse_passif_1: Mapped["SortAlbion"] = relationship(
        foreign_keys=[torse_passif_1_id], lazy="selectin"
    )
    torse_passif_2: Mapped["SortAlbion | None"] = relationship(
        foreign_keys=[torse_passif_2_id], lazy="selectin"
    )
    bottes_sort: Mapped["SortAlbion"] = relationship(foreign_keys=[bottes_sort_id], lazy="selectin")
    bottes_passif: Mapped["SortAlbion"] = relationship(
        foreign_keys=[bottes_passif_id], lazy="selectin"
    )
    cape_passif: Mapped["SortAlbion | None"] = relationship(
        foreign_keys=[cape_passif_id], lazy="selectin"
    )
    monture_sort: Mapped["SortAlbion | None"] = relationship(
        foreign_keys=[monture_sort_id], lazy="selectin"
    )


class Inscription(Base):
    """Un membre qui se declare volontaire pour jouer un build de la compo.

    Un membre ne tient qu'un seul build par compo (verifie par l'API), et un
    meme build peut accueillir plusieurs volontaires.
    """

    __tablename__ = "inscriptions"
    __table_args__ = (UniqueConstraint("ligne_id", "membre_id", name="uq_inscription"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ligne_id: Mapped[int] = mapped_column(
        ForeignKey("lignes_compo.id", ondelete="CASCADE"), nullable=False, index=True
    )
    membre_id: Mapped[int] = mapped_column(
        ForeignKey("membres.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date_creation: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    ligne: Mapped["LigneCompo"] = relationship(back_populates="inscriptions")
    membre: Mapped["Membre"] = relationship(lazy="selectin")

    @property
    def pseudo(self) -> str:
        return self.membre.pseudo if self.membre is not None else "?"


class Setting(Base):
    """Configuration modifiable par l'admin (ex: URL du webhook Discord)."""

    __tablename__ = "settings"

    cle: Mapped[str] = mapped_column(String(64), primary_key=True)
    valeur: Mapped[str] = mapped_column(Text, nullable=False, default="")
