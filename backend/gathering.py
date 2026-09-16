"""Ajout des equipements de gathering et de leurs sorts/passifs au catalogue."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CategorieAlbion, CategorieSort, ObjetAlbion, SlotEquipement, SortAlbion, Emplacement


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

# Pools communs confirmés par les équipements gatherer actuels.
SORTS = {
    "BLOCK": "Défense",
    "SELF_CLEANSE": "Purification",
    "EMERGENCY_SHIELD": "Bouclier d'urgence",
    "MAGICMUSHROOM": "Pollen magique",
    "OUTOFCOMBATHEAL": "Guérison des blessures",
    "AMBUSH": "Embuscade",
    "WINDWALL": "Bourrasque",
    "SPRINTHOT": "Sprint de régénération",
    "WANDERLUST": "Nafse de voyage",
    "FLEE": "Fuite",
}

PASSIFS = {
    "FIBER": {
        "HEAD": "PASSIVE_HEAD_YIELD_FIBER_T8",
        "ARMOR": "PASSIVE_YIELD_FIBER_T8",
        "SHOES": "PASSIVE_SHOES_YIELD_FIBER_T8",
    },
    "HIDE": {
        "HEAD": "PASSIVE_HEAD_YIELD_HIDE_T8",
        "ARMOR": "PASSIVE_YIELD_HIDE_T8",
        "SHOES": "PASSIVE_SHOES_YIELD_HIDE_T8",
    },
    "ORE": {
        "HEAD": "PASSIVE_HEAD_YIELD_ORE_T8",
        "ARMOR": "PASSIVE_YIELD_ORE_T8",
        "SHOES": "PASSIVE_SHOES_YIELD_ORE_T8",
    },
    "ROCK": {
        "HEAD": "PASSIVE_HEAD_YIELD_ROCK_T8",
        "ARMOR": "PASSIVE_YIELD_ROCK_T8",
        "SHOES": "PASSIVE_SHOES_YIELD_ROCK_T8",
    },
    "WOOD": {
        "HEAD": "PASSIVE_HEAD_YIELD_WOOD_T8",
        "ARMOR": "PASSIVE_YIELD_WOOD_T8",
        "SHOES": "PASSIVE_SHOES_YIELD_WOOD_T8",
    },
    "FISH": {
        "HEAD": "PASSIVE_HEAD_YIELD_FISH_T8",
        "ARMOR": "PASSIVE_YIELD_FISH_T8",
        "SHOES": "PASSIVE_SHOES_YIELD_FISH_T8",
    },
}

PASSIF_NOMS = {
    "FIBER": "Compétences de récolte",
    "HIDE": "Compétences de dépeçage",
    "ORE": "Compétences de minage",
    "ROCK": "Compétences de carrier",
    "WOOD": "Compétences de bûcheron",
    "FISH": "Compétences de pêche",
}

SLOTS_SORTS = {
    "HEAD": (Emplacement.sort, ("BLOCK", "SELF_CLEANSE", "EMERGENCY_SHIELD", "MAGICMUSHROOM")),
    "ARMOR": (Emplacement.sort, ("OUTOFCOMBATHEAL", "AMBUSH", "WINDWALL")),
    "SHOES": (Emplacement.sort, ("FLEE", "SPRINTHOT", "WANDERLUST")),
}


def _get_or_create_sort(db: Session, code: str, nom: str, passif: bool = False) -> SortAlbion:
    sort = db.scalar(select(SortAlbion).where(SortAlbion.code == code))
    if sort is None:
        sort = SortAlbion(code=code, nom=nom, passif=passif)
        db.add(sort)
        db.flush()
    elif not sort.nom:
        sort.nom = nom
    return sort


def _ajouter_pool(db: Session, categorie_id: int, emplacement: Emplacement, sort: SortAlbion) -> None:
    deja = db.scalar(
        select(CategorieSort).where(
            CategorieSort.categorie_id == categorie_id,
            CategorieSort.emplacement == emplacement,
            CategorieSort.sort_id == sort.id,
        )
    )
    if deja is None:
        db.add(CategorieSort(categorie_id=categorie_id, emplacement=emplacement, sort_id=sort.id))


def installer_equipements_gathering(db: Session) -> int:
    """Installe les 18 pièces T8 représentatives avec leurs pools de sorts/passifs.

    Le formulaire travaille sur les catégories et leurs pools CategorieSort.
    Les anciennes versions créaient les catégories sans ces pools, ce qui
    expliquait les champs spell/passif vides.
    """
    existants = {o.code: o for o in db.scalars(select(ObjetAlbion)) if "GATHERER_" in o.code}
    categories = {c.code: c for c in db.scalars(select(CategorieAlbion))}
    ajoutes = 0

    for famille, (nom, _) in FAMILLES.items():
        for piece, slot, libelle in PIECES:
            code = f"{piece}_GATHERER_{famille}"
            categorie_code = f"gathering_{famille.lower()}_{slot.value}"
            categorie = categories.get(categorie_code)
            if categorie is None:
                categorie = CategorieAlbion(code=categorie_code, nom=f"{nom} — {libelle}", slot=slot)
                db.add(categorie)
                db.flush()
                categories[categorie_code] = categorie

            if code not in existants:
                objet = ObjetAlbion(
                    code=code,
                    nom=f"{nom} — {libelle}",
                    slot=slot,
                    categorie_id=categorie.id,
                    code_rendu=f"T8_{code}",
                    deux_mains=False,
                )
                db.add(objet)
                existants[code] = objet
                ajoutes += 1

            emplacement_sort, codes_sort = SLOTS_SORTS[piece]
            for sort_code in codes_sort:
                sort = _get_or_create_sort(db, sort_code, SORTS[sort_code])
                _ajouter_pool(db, categorie.id, emplacement_sort, sort)

            passif_code = PASSIFS[famille][piece]
            passif = _get_or_create_sort(db, passif_code, PASSIF_NOMS[famille], passif=True)
            _ajouter_pool(db, categorie.id, Emplacement.passif_1, passif)

            # Le torse utilise aussi ce passif comme valeur par défaut/imposée.
            if slot == SlotEquipement.torse:
                objet = existants[code]
                objet.sort_impose_id = passif.id
                objet.sort_defaut_id = passif.id

    db.commit()
    return ajoutes
