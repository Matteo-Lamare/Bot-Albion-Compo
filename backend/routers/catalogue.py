"""Expose le catalogue Albion et les regles de slots au formulaire."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import membre_courant
from ..catalogue import REGLES, index as index_catalogue
from ..database import get_db
from ..models import Membre
from ..validation import LIBELLES_CHAMPS, LIBELLES_SLOTS

router = APIRouter(prefix="/api/catalogue", tags=["catalogue"])


def _champ(slot, nom: str) -> dict:
    return {
        "nom": nom,
        "champ": REGLES[slot].champ_sort(nom),
        "libelle": LIBELLES_CHAMPS.get(nom, nom).capitalize(),
    }


@router.get("")
def lire_catalogue(
    _: Membre = Depends(membre_courant), db: Session = Depends(get_db)
) -> dict:
    """Catalogue complet + regles : le formulaire se construit entierement a partir d'ici.

    La reponse fait quelques centaines de kilo-octets et ne change qu'a chaque
    mise a jour du jeu ; le frontend la charge une fois par page.
    """
    catalogue = index_catalogue(db)

    slots = []
    for slot, regle in REGLES.items():
        slots.append({
            "slot": slot.value,
            "libelle": LIBELLES_SLOTS[slot],
            "champ": regle.champ_objet(),
            "obligatoire": regle.objet_obligatoire,
            "champs": [
                {**_champ(slot, champ.nom),
                 "emplacement": champ.emplacement.value,
                 "obligatoire": champ.obligatoire}
                for champ in regle.champs
            ],
            "champ_impose": _champ(slot, regle.champ_impose) if regle.champ_impose else None,
        })

    categories = {}
    for identifiant, categorie in catalogue.categories.items():
        pools = {
            emplacement.value: identifiants
            for (categorie_id, emplacement), identifiants in catalogue.pools.items()
            if categorie_id == identifiant
        }
        categories[identifiant] = {
            "nom": categorie.nom,
            "slot": categorie.slot.value,
            "pools": pools,
        }

    return {
        "slots": slots,
        "categories": categories,
        "sorts": {
            identifiant: {"nom": sort.nom, "passif": sort.passif, "icone": sort.icone}
            for identifiant, sort in catalogue.sorts.items()
        },
        "objets": [
            {
                "id": objet.id,
                "nom": objet.nom,
                "slot": objet.slot.value,
                "categorie_id": objet.categorie_id,
                "icone": objet.icone,
                "deux_mains": objet.deux_mains,
                "sort_impose_id": objet.sort_impose_id,
                "sort_defaut_id": objet.sort_defaut_id,
            }
            for objet in sorted(catalogue.objets.values(), key=lambda o: (o.slot.value, o.nom))
        ],
    }
