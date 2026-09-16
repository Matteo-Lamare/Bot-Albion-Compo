"""Ajout des equipements de gathering absents des anciens catalogues.

Le catalogue principal est genere depuis les dumps Albion. Cette migration legere
permet aux installations existantes de recuperer les 6 familles de gatherer gear
sans devoir supprimer/recreer leur base.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CategorieAlbion, ObjetAlbion, SlotEquipement, SortAlbion


# code Albion -> libelle francais. Chaque famille possede casque, torse et bottes.
FAMILLES = {
    "FIBER": ("Récolteur", "Fibre"),
    "HIDE": ("Dépeceur", "Peau"),
    "ORE": ("Mineur", "Minerai"),
    "ROCK": ("Carrier", "Pierre"),
    "WOOD": ("Bûcheron", "Bois"),
    "FISH": ("Pêcheur", "Poisson"),
}

PIECES = (
    ("HEAD", SlotEquipement.casque, "Casque"),
    ("ARMOR", SlotEquipement.torse, "Armure"),
    ("SHOES", SlotEquipement.bottes, "Bottes"),
)


def _sort_par_code(db: Session, code: str) -> SortAlbion | None:
    return db.scalar(select(SortAlbion).where(SortAlbion.code == code))


def installer_equipements_gathering(db: Session) -> int:
    """Insere les 18 pieces gatherer si elles ne sont pas deja presentes.

    Les sorts restent ceux du catalogue principal. On ajoute volontairement les
    objets meme si une ancienne base ne connait pas encore les pools de sorts :
    cela rend les images et la selection des armures disponibles immediatement.
    """
    existants = {o.code: o for o in db.scalars(select(ObjetAlbion)) if "GATHERER_" in o.code}
    categories = {c.code: c for c in db.scalars(select(CategorieAlbion))}
    ajoutes = 0

    # Le catalogue importe deja les sorts globaux ; ces recherches sont utiles
    # pour associer le passif specifique quand le dump l'a deja fourni.
    passifs = {
        "FIBER": "PASSIVE_YIELD_FIBER_T8",
        "HIDE": "PASSIVE_YIELD_HIDE_T8",
        "ORE": "PASSIVE_YIELD_ORE_T8",
        "ROCK": "PASSIVE_YIELD_ROCK_T8",
        "WOOD": "PASSIVE_YIELD_WOOD_T8",
        "FISH": "PASSIVE_YIELD_FISH_T8",
    }

    for famille, (nom, ressource) in FAMILLES.items():
        for piece, slot, libelle in PIECES:
            code = f"{piece}_GATHERER_{famille}"
            categorie_code = f"gathering_{famille.lower()}_{slot.value}"
            categorie = categories.get(categorie_code)
            if categorie is None:
                categorie = CategorieAlbion(
                    code=categorie_code,
                    nom=f"{nom} — {libelle}",
                    slot=slot,
                )
                db.add(categorie)
                db.flush()
                categories[categorie_code] = categorie

            if code in existants:
                continue

            objet = ObjetAlbion(
                code=code,
                nom=f"{nom} — {libelle}",
                slot=slot,
                categorie_id=categorie.id,
                code_rendu=f"T8_{code}",
                deux_mains=False,
            )
            # Le passif du torse est le plus important pour le build gather.
            # On le lie si le code existe dans le catalogue de sorts.
            if slot == SlotEquipement.torse:
                passif = _sort_par_code(db, passifs[famille])
                if passif is not None:
                    objet.sort_impose_id = passif.id
            db.add(objet)
            existants[code] = objet
            ajoutes += 1

    db.commit()
    return ajoutes
