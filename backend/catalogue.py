"""Catalogue Albion : import du JSON, index en memoire et regles par slot.

Le fichier `database/catalogue_albion.json` est produit par
`scripts/importer_catalogue.py` a partir des dumps officiels du jeu. Il est
charge en base au demarrage, puis indexe en memoire : la validation des lignes
de compo et l'API du formulaire s'appuient toutes deux sur cet index.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    CategorieAlbion,
    CategorieSort,
    Emplacement,
    ObjetAlbion,
    SlotEquipement,
    SortAlbion,
)

CHEMIN_CATALOGUE = settings.base_dir / "database" / "catalogue_albion.json"


# --------------------------------------------------------------------------
# Regles de composition d'un slot
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ChampSort:
    """Un sort a choisir pour un slot, puise dans le pool de la categorie."""

    nom: str                    # suffixe du champ : "sort_1", "passif", "passif_2"...
    emplacement: Emplacement    # pool de la categorie ou puiser
    obligatoire: bool


@dataclass(frozen=True)
class RegleSlot:
    slot: SlotEquipement
    objet_obligatoire: bool
    champs: tuple[ChampSort, ...] = ()
    # Champ rempli automatiquement par le sort impose de l'objet :
    # sort 3 d'une arme, passif d'une cape, sort d'une monture.
    champ_impose: str | None = None

    def champ_objet(self) -> str:
        return f"{self.slot.value}_id"

    def champ_sort(self, nom: str) -> str:
        return f"{self.slot.value}_{nom}_id"


_S = SlotEquipement
_E = Emplacement

REGLES: dict[SlotEquipement, RegleSlot] = {
    # Arme : sorts 1 et 2 + passif choisis dans la categorie ; sort 3 impose par l'arme.
    _S.arme: RegleSlot(_S.arme, True, (
        ChampSort("sort_1", _E.sort_1, True),
        ChampSort("sort_2", _E.sort_2, True),
        ChampSort("passif", _E.passif, True),
    ), champ_impose="sort_3"),
    # Off-hand : ni sort ni passif.
    _S.offhand: RegleSlot(_S.offhand, False),
    # Armures : un sort actif (natif, remplacable dans la categorie) + passif(s).
    # Armures : le second emplacement de passif n'existe que pour les categories
    # qui le proposent (les torses en plaques) ; ailleurs son pool est vide et le
    # champ disparait du formulaire.
    _S.casque: RegleSlot(_S.casque, True, (
        ChampSort("sort", _E.sort, True),
        ChampSort("passif", _E.passif_1, True),
    )),
    _S.torse: RegleSlot(_S.torse, True, (
        ChampSort("sort", _E.sort, True),
        ChampSort("passif_1", _E.passif_1, True),
        ChampSort("passif_2", _E.passif_2, False),
    )),
    _S.bottes: RegleSlot(_S.bottes, True, (
        ChampSort("sort", _E.sort, True),
        ChampSort("passif", _E.passif_1, True),
    )),
    # Cape : pas de sort ; le passif est celui de la cape.
    _S.cape: RegleSlot(_S.cape, True, champ_impose="passif"),
    # Monture : facultative ; son sort est celui de la monture.
    _S.monture: RegleSlot(_S.monture, False, champ_impose="sort"),
    _S.potion: RegleSlot(_S.potion, False),
    _S.nourriture: RegleSlot(_S.nourriture, False),
}


# --------------------------------------------------------------------------
# Import du JSON en base
# --------------------------------------------------------------------------


def importer(db: Session, chemin: Path | None = None) -> dict[str, int]:
    """Charge (ou recharge) le catalogue en base. Idempotent."""
    chemin = chemin or CHEMIN_CATALOGUE
    if not chemin.exists():
        raise FileNotFoundError(
            f"Catalogue introuvable : {chemin}. "
            "Lancez `python scripts/importer_catalogue.py` pour le construire."
        )
    donnees = json.loads(chemin.read_text(encoding="utf-8"))

    sorts = {s.code: s for s in db.scalars(select(SortAlbion))}
    for code, brut in donnees["sorts"].items():
        sort = sorts.get(code)
        if sort is None:
            sort = SortAlbion(code=code)
            db.add(sort)
            sorts[code] = sort
        sort.nom = brut["nom"]
        sort.passif = brut["passif"]
    db.flush()

    categories = {c.code: c for c in db.scalars(select(CategorieAlbion))}
    for brut in donnees["categories"]:
        categorie = categories.get(brut["code"])
        if categorie is None:
            categorie = CategorieAlbion(code=brut["code"])
            db.add(categorie)
            categories[brut["code"]] = categorie
        categorie.nom = brut["nom"]
        categorie.slot = SlotEquipement(brut["slot"])
    db.flush()

    # Pools de sorts : on remplace integralement ceux de chaque categorie.
    existants = {
        (lien.categorie_id, lien.emplacement, lien.sort_id): lien
        for lien in db.scalars(select(CategorieSort))
    }
    attendus: set[tuple[int, Emplacement, int]] = set()
    for brut in donnees["categories"]:
        categorie = categories[brut["code"]]
        for emplacement, codes in brut.get("sorts", {}).items():
            for code in codes:
                if code not in sorts:
                    continue
                cle = (categorie.id, Emplacement(emplacement), sorts[code].id)
                attendus.add(cle)
                if cle not in existants:
                    db.add(CategorieSort(
                        categorie_id=cle[0], emplacement=cle[1], sort_id=cle[2]
                    ))
    for cle, lien in existants.items():
        if cle not in attendus:
            db.delete(lien)
    db.flush()

    objets = {(o.slot, o.code): o for o in db.scalars(select(ObjetAlbion))}
    for brut in donnees["objets"]:
        slot = SlotEquipement(brut["slot"])
        objet = objets.get((slot, brut["code"]))
        if objet is None:
            objet = ObjetAlbion(code=brut["code"], slot=slot)
            db.add(objet)
            objets[(slot, brut["code"])] = objet
        objet.nom = brut["nom"]
        objet.categorie_id = categories[brut["categorie"]].id
        objet.code_rendu = brut["rendu"]
        objet.deux_mains = brut["deux_mains"]
        impose = brut.get("sort_3") or brut.get("passif_defaut")
        objet.sort_impose_id = sorts[impose].id if impose in sorts else None
        defaut = brut.get("sort_defaut")
        objet.sort_defaut_id = sorts[defaut].id if defaut in sorts else None
    db.commit()

    vider_index()
    return {
        "sorts": len(donnees["sorts"]),
        "categories": len(donnees["categories"]),
        "objets": len(donnees["objets"]),
    }


# --------------------------------------------------------------------------
# Index en memoire
# --------------------------------------------------------------------------


@dataclass
class IndexCatalogue:
    objets: dict[int, ObjetAlbion]
    sorts: dict[int, SortAlbion]
    categories: dict[int, CategorieAlbion]
    # (categorie_id, emplacement) -> identifiants de sorts autorises
    pools: dict[tuple[int, Emplacement], list[int]]

    def pool(self, categorie_id: int, emplacement: Emplacement) -> list[int]:
        return self.pools.get((categorie_id, emplacement), [])

    def est_vide(self) -> bool:
        return not self.objets


_index: IndexCatalogue | None = None


def vider_index() -> None:
    global _index
    _index = None


def index(db: Session) -> IndexCatalogue:
    """Index du catalogue, construit une fois puis conserve en memoire."""
    global _index
    if _index is not None:
        return _index

    objets = {o.id: o for o in db.scalars(select(ObjetAlbion))}
    sorts = {s.id: s for s in db.scalars(select(SortAlbion))}
    categories = {c.id: c for c in db.scalars(select(CategorieAlbion))}
    pools: dict[tuple[int, Emplacement], list[int]] = {}
    for lien in db.scalars(select(CategorieSort)):
        pools.setdefault((lien.categorie_id, lien.emplacement), []).append(lien.sort_id)
    for identifiants in pools.values():
        identifiants.sort(key=lambda i: sorts[i].nom if i in sorts else "")

    _index = IndexCatalogue(objets=objets, sorts=sorts, categories=categories, pools=pools)
    return _index
