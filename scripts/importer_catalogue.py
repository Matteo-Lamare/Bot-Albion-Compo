#!/usr/bin/env python
"""Construit le catalogue Albion (objets, sorts, passifs) a partir des dumps officiels.

    python scripts/importer_catalogue.py [--cache DOSSIER] [--sortie FICHIER]

Le resultat, `database/catalogue_albion.json`, est versionne avec le projet : le site
n'a donc jamais besoin d'acceder au reseau. Relancez ce script apres une mise a jour du
jeu pour rafraichir le catalogue.

Source des donnees : https://github.com/ao-data/ao-bin-dumps (dumps officiels du client).
Icones : https://render.albiononline.com
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from pathlib import Path

BASE_DUMPS = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master"
FICHIERS = ("items.xml", "spells.xml", "localization.xml")
LANGUE = "FR-FR"

RACINE = Path(__file__).resolve().parent.parent

# slottype du dump -> slot de nos compos
SLOTS = {
    "mainhand": "arme",
    "offhand": "offhand",
    "head": "casque",
    "armor": "torse",
    "shoes": "bottes",
    "cape": "cape",
    "mount": "monture",
    "potion": "potion",
    "food": "nourriture",
}

# Seules ces familles de boutique nous interessent : on ecarte l'equipement de
# recolte, les outils et les objets de guilde.
CATEGORIES_RETENUES = {
    "weapons", "offhands", "head", "armors", "shoes", "capes", "mounts", "consumables",
}

# Les consommables changent reellement de nom d'un tier a l'autre (potion de soin /
# potion de soin majeure) : on garde une entree par tier. Ailleurs, le tier n'est
# qu'un qualificatif ("de l'adepte") et une seule entree suffit.
SLOTS_PAR_TIER = {"potion", "nourriture"}

# Pieces d'armure : leurs passifs sont numerotes par emplacement (1 ou 2).
SLOTS_ARMURE = {"casque", "torse", "bottes"}

# Mots de liaison a retirer en fin de nom quand on deduit le nom sans tier.
LIAISONS = {"de", "du", "des", "d'", "l'", "de l'", "la", "le", "en"}

NOMS_CATEGORIES = {
    # Armes
    "sword": "Épées", "axe": "Haches", "mace": "Masses", "hammer": "Marteaux",
    "quarterstaff": "Bâtons de combat", "spear": "Lances", "dagger": "Dagues",
    "knuckles": "Gantelets", "bow": "Arcs", "crossbow": "Arbalètes",
    "firestaff": "Bâtons de feu", "froststaff": "Bâtons de givre",
    "arcanestaff": "Bâtons arcaniques", "cursestaff": "Bâtons de malédiction",
    "holystaff": "Bâtons sacrés", "naturestaff": "Bâtons de la nature",
    "shapeshifterstaff": "Bâtons de métamorphe",
    # Off-hands
    "shieldtype": "Boucliers", "booktype": "Grimoires", "torchtype": "Torches",
    # Armures
    "cloth_helmet": "Chapeaux en tissu", "leather_helmet": "Casques en cuir",
    "plate_helmet": "Casques en plaques",
    "cloth_armor": "Robes en tissu", "leather_armor": "Vestes en cuir",
    "plate_armor": "Armures en plaques",
    "cloth_shoes": "Chaussures en tissu", "leather_shoes": "Bottes en cuir",
    "plate_shoes": "Sabatons en plaques",
    # Divers
    "basemounts": "Montures", "battle_mount": "Montures de combat",
    "raremounts": "Montures rares", "potions": "Potions", "food": "Nourriture",
}

# Les capes sont rangees par faction : "accessoires_capes_martlock" -> "Capes de Martlock".
FACTIONS_CAPES = {
    "capes": "Capes de cité", "avalon": "Avalon", "brecilien": "Brecilien",
    "bridgewatch": "Bridgewatch", "caerleon": "Caerleon", "demon": "Démon",
    "fortsterling": "Fort Sterling", "heretic": "Hérétiques", "keeper": "Gardiens",
    "lymhurst": "Lymhurst", "martlock": "Martlock", "morgana": "Morgane",
    "smuggler": "Contrebandiers", "thetford": "Thetford", "undead": "Morts-vivants",
}


def nom_categorie(code: str) -> str:
    if code.startswith("accessoires_capes_"):
        suffixe = code.removeprefix("accessoires_capes_")
        if suffixe == "capes":
            return "Capes de cité"
        return f"Capes — {FACTIONS_CAPES.get(suffixe, suffixe.capitalize())}"
    return NOMS_CATEGORIES.get(code, code.replace("_", " ").capitalize())


def telecharger(cache: Path) -> dict[str, Path]:
    cache.mkdir(parents=True, exist_ok=True)
    chemins = {}
    for fichier in FICHIERS:
        cible = cache / fichier
        if not cible.exists():
            print(f"  téléchargement de {fichier}…", flush=True)
            urllib.request.urlretrieve(f"{BASE_DUMPS}/{fichier}", cible)
        chemins[fichier] = cible
    return chemins


def charger_localisation(chemin: Path) -> dict[str, str]:
    """Lit le TMX et ne garde que les cles utiles, en francais."""
    prefixes = ("@ITEMS_", "@SPELLS_", "@COMBAT_")
    textes: dict[str, str] = {}
    cle = None
    langue_courante = None
    for evenement, element in ET.iterparse(chemin, events=("start", "end")):
        balise = element.tag.split("}")[-1]
        if evenement == "start":
            if balise == "tu":
                identifiant = element.get("tuid") or ""
                cle = identifiant if identifiant.startswith(prefixes) else None
            elif balise == "tuv" and cle:
                langue_courante = element.get(
                    "{http://www.w3.org/XML/1998/namespace}lang"
                ) or element.get("lang")
        else:
            if balise == "seg" and cle and langue_courante == LANGUE and element.text:
                textes[cle.lstrip("@")] = element.text.strip()
            elif balise == "tu":
                cle = None
                element.clear()
    return textes


def charger_sorts(chemin: Path, textes: dict[str, str]) -> dict[str, dict]:
    sorts: dict[str, dict] = {}
    for _, element in ET.iterparse(chemin, events=("end",)):
        balise = element.tag.split("}")[-1]
        if balise not in {"activespell", "passivespell", "togglespell"}:
            continue
        code = element.get("uniquename")
        if not code or code in sorts:
            continue
        etiquette = (element.get("namelocatag") or "").lstrip("@")
        sorts[code] = {
            "nom": (
                textes.get(etiquette)
                or textes.get(f"SPELLS_{code}")
                or code.replace("_", " ").title()
            ),
            "passif": balise == "passivespell" or code.startswith("PASSIVE_"),
        }
    return sorts


def nom_sans_tier(noms: list[str]) -> str:
    """Prefixe commun a plusieurs tiers, debarrasse du qualificatif final."""
    if len(noms) == 1:
        return noms[0]
    mots = [nom.split() for nom in noms]
    commun: list[str] = []
    for groupe in zip(*mots):
        if len(set(groupe)) != 1:
            break
        commun.append(groupe[0])
    while commun and commun[-1].lower() in LIAISONS:
        commun.pop()
    return " ".join(commun) if commun else noms[0]


def liste_sorts_objet(element: ET.Element, index: dict[str, ET.Element], profondeur: int = 0):
    """Resout <craftingspelllist reference="..."/> en remontant la chaine des tiers.

    Un objet peut a la fois referencer la liste de sa categorie *et* declarer ses
    propres sorts : c'est ainsi que les armes d'artefact heritent des sorts 1/2 et
    des passifs de leur categorie tout en ayant leur sort 3 bien a elles. Les sorts
    locaux completent donc la liste heritee, et l'emportent sur elle a emplacement egal.
    """
    liste = element.find("craftingspelllist")
    if liste is None:
        return []
    propres = [(s.get("uniquename"), s.get("slots")) for s in liste.findall("craftspell")]

    reference = liste.get("reference")
    if not reference or profondeur >= 12:
        return propres
    cible = index.get(reference)
    if cible is None:
        return propres

    herites = liste_sorts_objet(cible, index, profondeur + 1)
    emplacements_locaux = {slot for _, slot in propres if slot}
    return [(c, s) for c, s in herites if s not in emplacements_locaux] + propres


def construire(chemins: dict[str, Path]) -> dict:
    print("  lecture de la localisation…", flush=True)
    textes = charger_localisation(chemins["localization.xml"])
    print(f"    {len(textes)} libellés français", flush=True)

    print("  lecture des sorts…", flush=True)
    sorts_bruts = charger_sorts(chemins["spells.xml"], textes)
    print(f"    {len(sorts_bruts)} sorts", flush=True)

    print("  lecture des objets…", flush=True)
    racine = ET.parse(chemins["items.xml"]).getroot()
    index: dict[str, ET.Element] = {}
    for element in racine.iter():
        code = element.get("uniquename")
        if code:
            index.setdefault(code, element)

    # --- Regroupement des objets par famille (code sans le prefixe de tier) ---
    familles: dict[tuple[str, str], list[tuple[int, ET.Element]]] = defaultdict(list)
    for element in racine.iter():
        code = element.get("uniquename") or ""
        slot = SLOTS.get(element.get("slottype") or "")
        correspondance = re.match(r"^T(\d)_(.+)$", code)
        if not slot or not correspondance or "@" in code:
            continue
        if element.get("shopcategory") not in CATEGORIES_RETENUES:
            continue
        if (element.get("shopsubcategory1") or "other") == "other":
            continue
        tier, base = int(correspondance.group(1)), correspondance.group(2)
        cle = (slot, code if slot in SLOTS_PAR_TIER else base)
        familles[cle].append((tier, element))

    objets: list[dict] = []
    pools: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    actifs_par_objet: dict[str, tuple[str, list[str]]] = {}
    categories: dict[str, dict] = {}

    for (slot, base), variantes in sorted(familles.items()):
        variantes.sort(key=lambda v: v[0])
        tier_max, representatif = variantes[-1]
        categorie = representatif.get("shopsubcategory1")

        # Nom : le libelle de maitrise est deja sans tier ; sinon on le deduit.
        specialisation = representatif.get("combatspecachievement")
        nom = textes.get(f"COMBAT_{specialisation}_NAME") if specialisation else None
        if not nom:
            noms = [textes.get(f"ITEMS_{e.get('uniquename')}", "") for _, e in variantes]
            noms = [n for n in noms if n]
            if not noms:
                continue
            nom = nom_sans_tier(noms)
        if not nom:
            continue

        code_rendu = representatif.get("uniquename")
        sorts = liste_sorts_objet(representatif, index)

        # Sur une arme, `slots` numerote les sorts actifs (1, 2 et l'ultime 3) et les
        # passifs n'en portent pas. Sur une piece d'armure, c'est l'inverse : le sort
        # actif n'est pas numerote, et `slots` numerote les emplacements de passifs
        # (les torses en plaques en ont deux, les autres un seul).
        actifs, passifs_1, passifs_2, sorts_1, sorts_2, sorts_3 = [], [], [], [], [], []
        for code, emplacement in sorts:
            reference = sorts_bruts.get(code)
            if reference is None:
                continue
            if reference["passif"]:
                if slot in SLOTS_ARMURE:
                    (passifs_2 if emplacement == "2" else passifs_1).append(code)
                else:
                    passifs_1.append(code)
            elif emplacement == "1":
                sorts_1.append(code)
            elif emplacement == "2":
                sorts_2.append(code)
            elif emplacement == "3":
                sorts_3.append(code)
            else:
                actifs.append(code)

        categories.setdefault(categorie, {
            "code": categorie,
            "nom": nom_categorie(categorie),
            "slot": slot,
        })
        pool = pools[categorie]
        pool["sort_1"].update(sorts_1)
        pool["sort_2"].update(sorts_2)
        pool["sort"].update(actifs)
        # Les armes n'ont qu'un emplacement de passif : on le nomme "passif".
        pool["passif_1" if slot in SLOTS_ARMURE else "passif"].update(passifs_1)
        pool["passif_2"].update(passifs_2)

        code_objet = base if slot not in SLOTS_PAR_TIER else base
        objets.append({
            "code": code_objet,
            "nom": nom,
            "slot": slot,
            "categorie": categorie,
            "rendu": code_rendu,
            "deux_mains": representatif.get("twohanded") == "true",
            "sort_3": sorts_3[0] if sorts_3 else None,
            "sort_defaut": None,
            "passif_defaut": passifs_1[0] if slot in {"cape", "monture"} and passifs_1 else None,
        })
        actifs_par_objet[code_objet] = (categorie, actifs)

    # --- Sort natif d'une piece d'armure : celui qui la distingue de sa categorie ---
    partages: dict[str, set[str]] = {}
    for categorie, pool in pools.items():
        listes = [set(a) for c, (cat, a) in actifs_par_objet.items() if cat == categorie and a]
        partages[categorie] = set.intersection(*listes) if listes else set()
    for objet in objets:
        categorie, actifs = actifs_par_objet.get(objet["code"], (None, []))
        if not actifs:
            continue
        distinctifs = [a for a in actifs if a not in partages.get(categorie, set())]
        objet["sort_defaut"] = (distinctifs or actifs)[0]

    # --- On ne garde que les sorts reellement references ---
    utilises: set[str] = set()
    for pool in pools.values():
        for codes in pool.values():
            utilises.update(codes)
    for objet in objets:
        utilises.update(c for c in (objet["sort_3"], objet["sort_defaut"], objet["passif_defaut"]) if c)

    catalogue = {
        "genere_le": date.today().isoformat(),
        "source": "https://github.com/ao-data/ao-bin-dumps",
        "sorts": {code: sorts_bruts[code] for code in sorted(utilises) if code in sorts_bruts},
        "categories": [
            {**donnees, "sorts": {
                emplacement: sorted(codes)
                for emplacement, codes in sorted(pools[code].items()) if codes
            }}
            for code, donnees in sorted(categories.items())
        ],
        "objets": sorted(objets, key=lambda o: (o["slot"], o["nom"])),
    }
    return catalogue


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--cache", type=Path, default=RACINE / ".cache" / "albion")
    analyseur.add_argument("--sortie", type=Path, default=RACINE / "database" / "catalogue_albion.json")
    arguments = analyseur.parse_args()

    print("Construction du catalogue Albion")
    chemins = telecharger(arguments.cache)
    catalogue = construire(chemins)

    arguments.sortie.parent.mkdir(parents=True, exist_ok=True)
    arguments.sortie.write_text(
        json.dumps(catalogue, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    poids = arguments.sortie.stat().st_size / 1024
    print(
        f"\n✔ {arguments.sortie} écrit ({poids:.0f} Ko) : "
        f"{len(catalogue['objets'])} objets, {len(catalogue['categories'])} catégories, "
        f"{len(catalogue['sorts'])} sorts."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
