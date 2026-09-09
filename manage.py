#!/usr/bin/env python
"""Petites commandes d'administration en ligne de commande.

    python manage.py init                      # cree les tables + le compte admin
    python manage.py creer-membre <pseudo> <mdp> [admin|membre]
    python manage.py mot-de-passe <pseudo> <mdp>
    python manage.py importer-catalogue        # (re)charge le catalogue Albion en base
    python manage.py seed-demo                 # insere une compo d'exemple
    python manage.py images <compo_id> [dossier]  # exporte les images de build en PNG
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

from backend.auth import hacher_mot_de_passe
from backend.catalogue import REGLES, importer as importer_catalogue, index as index_catalogue
from backend.database import SessionLocal
from backend.images import DISPONIBLE as IMAGES_DISPONIBLES, images_des_lignes
from backend.main import initialiser_base
from backend.models import (
    CategorieAlbion,
    Compo,
    LigneCompo,
    Membre,
    ObjetAlbion,
    RoleMembre,
    StatutCompo,
    TypeContenu,
)
from backend.validation import defauts_pour_objet

# Compo d'exemple : on vise un objet par son nom, avec repli sur le premier objet
# de la categorie si le catalogue evolue. Les sorts sont ensuite choisis
# automatiquement (sort impose de l'objet, sort natif d'une armure, sinon premier
# sort autorise par la categorie).
LIGNES_DEMO = [
    {
        "role_ou_joueur": "Tank / Initiateur",
        "arme": ("mace", "Masse"),
        "offhand": ("shieldtype", "Bouclier"),
        "casque": ("plate_helmet", "Casque de soldat"),
        "torse": ("plate_armor", "Armure de gardetombe"),
        "bottes": ("plate_shoes", "Bottes de soldat"),
        "cape": ("accessoires_capes_martlock", "Cape de Martlock"),
        "monture": ("basemounts", "Cheval de guerre"),
        "potion": ("potions", "Potion de soin"),
        "nourriture": ("food", "Ragoût de bœuf"),
    },
    {
        # Un build peut rester a pourvoir : le nom du joueur est facultatif.
        "role_ou_joueur": "",
        "arme": ("holystaff", None),
        "casque": ("cloth_helmet", None),
        "torse": ("cloth_armor", "Robe d'ecclésiastique"),
        "bottes": ("cloth_shoes", None),
        "cape": ("accessoires_capes_lymhurst", None),
        "monture": ("basemounts", "Cheval de monte"),
        "potion": ("potions", "Potion d'énergie"),
        "nourriture": ("food", None),
    },
]


def _choisir_objet(db, code_categorie: str, nom: str | None):
    """Objet vise par son nom, ou premier objet de la categorie a defaut."""
    categorie = db.scalar(select(CategorieAlbion).where(CategorieAlbion.code == code_categorie))
    if categorie is None:
        return None
    requete = select(ObjetAlbion).where(ObjetAlbion.categorie_id == categorie.id)
    if nom:
        objet = db.scalar(requete.where(ObjetAlbion.nom == nom))
        if objet is not None:
            return objet
    return db.scalar(requete.order_by(ObjetAlbion.nom))


def _construire_ligne(db, index, modele: dict) -> LigneCompo | None:
    """Complete une ligne d'exemple : objets vises puis sorts valides."""
    valeurs: dict = {"role_ou_joueur": modele["role_ou_joueur"]}
    for slot, regle in REGLES.items():
        cible = modele.get(slot.value)
        if cible is None:
            continue
        objet = _choisir_objet(db, *cible)
        if objet is None:
            if regle.objet_obligatoire:
                return None
            continue
        valeurs[regle.champ_objet()] = objet.id
        valeurs.update(defauts_pour_objet(index, objet.id))
        for champ in regle.champs:
            nom_champ = regle.champ_sort(champ.nom)
            if valeurs.get(nom_champ) is not None:
                continue
            autorises = index.pool(objet.categorie_id, champ.emplacement)
            if autorises and champ.obligatoire:
                valeurs[nom_champ] = autorises[0]
    return LigneCompo(**valeurs)


def creer_membre(pseudo: str, mot_de_passe: str, role: str = "membre") -> None:
    with SessionLocal() as db:
        if db.scalar(select(Membre).where(Membre.pseudo == pseudo)):
            print(f"Le membre '{pseudo}' existe deja.")
            return
        db.add(
            Membre(
                pseudo=pseudo,
                mot_de_passe_hash=hacher_mot_de_passe(mot_de_passe),
                role=RoleMembre(role),
            )
        )
        db.commit()
        print(f"Membre '{pseudo}' cree ({role}).")


def changer_mot_de_passe(pseudo: str, mot_de_passe: str) -> None:
    with SessionLocal() as db:
        membre = db.scalar(select(Membre).where(Membre.pseudo == pseudo))
        if membre is None:
            print(f"Membre '{pseudo}' introuvable.")
            return
        membre.mot_de_passe_hash = hacher_mot_de_passe(mot_de_passe)
        db.commit()
        print(f"Mot de passe de '{pseudo}' mis a jour.")


def seed_demo() -> None:
    with SessionLocal() as db:
        auteur = db.scalar(select(Membre).order_by(Membre.id))
        if auteur is None:
            print("Aucun membre en base : lancez d'abord 'python manage.py init'.")
            return
        catalogue = index_catalogue(db)
        if catalogue.est_vide():
            print("Catalogue vide : lancez d'abord 'python manage.py importer-catalogue'.")
            return

        compo = Compo(
            nom="ZvZ - Groupe de test",
            type_contenu=TypeContenu.zvz,
            taille_groupe=len(LIGNES_DEMO),
            statut=StatutCompo.brouillon,
            notes="Compo d'exemple generee par manage.py seed-demo.",
            auteur_id=auteur.id,
        )
        for position, modele in enumerate(LIGNES_DEMO):
            ligne = _construire_ligne(db, catalogue, modele)
            if ligne is None:
                print(f"Ligne « {modele['role_ou_joueur'] or 'a pourvoir'} » ignoree : "
                      "objets introuvables.")
                continue
            ligne.ordre = position
            compo.lignes.append(ligne)
        db.add(compo)
        db.commit()
        print(f"Compo d'exemple creee (id={compo.id}, {len(compo.lignes)} lignes).")


def exporter_images(compo_id: int, dossier: str = ".") -> None:
    """Ecrit sur disque les images de build telles qu'elles partent sur Discord."""
    if not IMAGES_DISPONIBLES:
        print("Pillow n'est pas installe : pip install -r requirements.txt")
        return
    with SessionLocal() as db:
        compo = db.get(Compo, compo_id)
        if compo is None:
            print(f"Compo {compo_id} introuvable.")
            return
        images = asyncio.run(images_des_lignes(compo.lignes))
        cible = Path(dossier)
        cible.mkdir(parents=True, exist_ok=True)
        for ligne in compo.lignes:
            image = images.get(ligne.ordre)
            if image is None:
                continue
            fichier = cible / f"compo{compo.id}_build{ligne.ordre + 1}.png"
            fichier.write_bytes(image)
            print(f"{fichier} ({len(image) // 1024} Ko) — {ligne.libelle}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    commande = sys.argv[1]
    initialiser_base()

    if commande == "init":
        print("Base initialisee.")
    elif commande == "creer-membre" and len(sys.argv) >= 4:
        creer_membre(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "membre")
    elif commande == "mot-de-passe" and len(sys.argv) >= 4:
        changer_mot_de_passe(sys.argv[2], sys.argv[3])
    elif commande == "importer-catalogue":
        with SessionLocal() as db:
            compte = importer_catalogue(db)
        print(f"Catalogue importe : {compte['objets']} objets, "
              f"{compte['categories']} categories, {compte['sorts']} sorts.")
    elif commande == "seed-demo":
        seed_demo()
    elif commande == "images" and len(sys.argv) >= 3:
        exporter_images(int(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else ".")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
