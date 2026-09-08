"""Validation des lignes de compo contre le catalogue Albion.

Regles appliquees (elles font autorite ; le formulaire ne fait que les refleter) :

1. une arme a un et un seul sort 3, pose automatiquement par l'arme choisie ;
2. les sorts 1, 2 et le passif d'une arme sont ceux de sa categorie ;
3. un objet appartient a une seule categorie, qui definit ce qu'il peut choisir ;
4. une piece d'armure a un sort natif, remplacable par un autre sort de sa categorie.

Les slots facultatifs (off-hand, monture, potion, nourriture) sont soit vides,
soit renseignes ; le passif d'une cape et le sort d'une monture sont imposes par
l'objet, donc jamais choisis.
"""
from __future__ import annotations

from .catalogue import REGLES, IndexCatalogue
from .models import Emplacement, SlotEquipement

LIBELLES_SLOTS = {
    SlotEquipement.arme: "Arme",
    SlotEquipement.offhand: "Off-hand",
    SlotEquipement.casque: "Casque",
    SlotEquipement.torse: "Torse",
    SlotEquipement.bottes: "Bottes",
    SlotEquipement.cape: "Cape",
    SlotEquipement.monture: "Monture",
    SlotEquipement.potion: "Potion",
    SlotEquipement.nourriture: "Nourriture",
}

LIBELLES_CHAMPS = {
    "sort_1": "sort 1", "sort_2": "sort 2", "sort_3": "sort 3", "sort": "sort",
    "passif": "passif", "passif_1": "passif 1", "passif_2": "passif 2",
}


class ErreurLigne(Exception):
    """Erreurs de validation, au format attendu par le frontend."""

    def __init__(self, erreurs: list[dict[str, str]]) -> None:
        super().__init__("Validation echouee")
        self.erreurs = erreurs


def valider_lignes(index: IndexCatalogue, lignes: list[dict]) -> list[dict]:
    """Valide et normalise les lignes. Leve ErreurLigne en cas de probleme.

    Renvoie les lignes completees : sorts imposes poses, champs des slots vides
    remis a None.
    """
    if index.est_vide():
        raise ErreurLigne([{
            "champ": "catalogue",
            "message": "Le catalogue Albion n'est pas charge : "
                       "lancez `python manage.py importer-catalogue`.",
        }])

    erreurs: list[dict[str, str]] = []
    normalisees: list[dict] = []

    for numero, ligne in enumerate(lignes):
        donnees = dict(ligne)
        prefixe = f"lignes.{numero}"

        for slot, regle in REGLES.items():
            libelle = LIBELLES_SLOTS[slot]
            champ_objet = regle.champ_objet()
            objet_id = donnees.get(champ_objet)

            def signaler(champ: str, message: str) -> None:
                erreurs.append({"champ": f"{prefixe}.{champ}", "message": message})

            # --- Slot vide ---
            if objet_id is None:
                if regle.objet_obligatoire:
                    signaler(champ_objet, f"{libelle} : objet obligatoire.")
                for champ in _tous_les_champs(regle):
                    donnees[regle.champ_sort(champ)] = None
                continue

            objet = index.objets.get(objet_id)
            if objet is None:
                signaler(champ_objet, f"{libelle} : objet inconnu du catalogue.")
                continue
            if objet.slot != slot:
                signaler(
                    champ_objet,
                    f"{libelle} : « {objet.nom} » n'est pas un objet de ce slot.",
                )
                continue

            # --- Sort impose par l'objet (regle 1) ---
            if regle.champ_impose:
                donnees[regle.champ_sort(regle.champ_impose)] = objet.sort_impose_id

            # --- Sorts choisis dans le pool de la categorie (regles 2, 3 et 4) ---
            for champ in regle.champs:
                nom_champ = regle.champ_sort(champ.nom)
                valeur = donnees.get(nom_champ)
                autorises = index.pool(objet.categorie_id, champ.emplacement)
                intitule = f"{libelle} : {LIBELLES_CHAMPS.get(champ.nom, champ.nom)}"

                if not autorises:
                    # La categorie ne propose rien a cet emplacement (torse sans
                    # second passif, cape de cite sans passif...).
                    donnees[nom_champ] = None
                    continue
                if valeur is None:
                    if champ.obligatoire:
                        signaler(nom_champ, f"{intitule} obligatoire.")
                    continue
                if valeur not in autorises:
                    sort = index.sorts.get(valeur)
                    nom_sort = f"« {sort.nom} »" if sort else "ce sort"
                    signaler(
                        nom_champ,
                        f"{intitule} : {nom_sort} n'est pas disponible pour "
                        f"« {objet.nom} » ({index.categories[objet.categorie_id].nom}).",
                    )

            # --- Un meme passif ne peut pas etre pris deux fois ---
            if slot == SlotEquipement.torse:
                premier = donnees.get("torse_passif_1_id")
                second = donnees.get("torse_passif_2_id")
                if premier is not None and premier == second:
                    signaler(
                        "torse_passif_2_id",
                        "Torse : les deux passifs doivent être différents.",
                    )

        normalisees.append(donnees)

    if erreurs:
        raise ErreurLigne(erreurs)
    return normalisees


def _tous_les_champs(regle) -> list[str]:
    champs = [champ.nom for champ in regle.champs]
    if regle.champ_impose:
        champs.append(regle.champ_impose)
    return champs


def defauts_pour_objet(index: IndexCatalogue, objet_id: int) -> dict[str, int | None]:
    """Valeurs a preselectionner quand on choisit un objet (utilise par l'API)."""
    objet = index.objets.get(objet_id)
    if objet is None:
        return {}
    regle = REGLES[objet.slot]
    valeurs: dict[str, int | None] = {}
    if regle.champ_impose:
        valeurs[regle.champ_sort(regle.champ_impose)] = objet.sort_impose_id
    for champ in regle.champs:
        autorises = index.pool(objet.categorie_id, champ.emplacement)
        if not autorises:
            valeurs[regle.champ_sort(champ.nom)] = None
        elif champ.emplacement == Emplacement.sort and objet.sort_defaut_id in autorises:
            valeurs[regle.champ_sort(champ.nom)] = objet.sort_defaut_id
    return valeurs
