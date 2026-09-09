"""Tests de bout en bout : auth, catalogue, CRUD, regles, images, tableur, Discord."""
from __future__ import annotations

import email
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_TMP = Path(tempfile.mkdtemp())
os.environ["DATABASE_URL"] = f"sqlite:///{BASE_TMP / 'test.db'}"
os.environ["SECRET_KEY"] = "cle-de-test"
os.environ["ADMIN_PSEUDO"] = "admin"
os.environ["ADMIN_PASSWORD"] = "motdepasse"
os.environ["DISCORD_WEBHOOK_URL"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from backend import images as module_images  # noqa: E402
from backend.main import app  # noqa: E402
from backend.routers import compos as routeur_compos  # noqa: E402

RECUS: list[dict] = []  # messages postes sur le webhook


async def _icones_hors_ligne(_urls) -> dict:
    """Les tests ne sortent pas sur le reseau : les images se composent sans icones."""
    return {}


module_images._telecharger = _icones_hors_ligne


class FauxWebhook(BaseHTTPRequestHandler):
    """Webhook local : accepte le JSON simple comme le multipart avec images."""

    def _lire(self) -> tuple[dict, list[str]]:
        taille = int(self.headers.get("Content-Length", 0))
        brut = self.rfile.read(taille)
        type_contenu = self.headers.get("Content-Type", "")
        if not type_contenu.startswith("multipart/form-data"):
            return json.loads(brut or b"{}"), []
        message = email.message_from_bytes(
            b"Content-Type: " + type_contenu.encode() + b"\r\n\r\n" + brut
        )
        charge: dict = {}
        fichiers: list[str] = []
        for partie in message.get_payload():
            if partie.get_param("name", header="content-disposition") == "payload_json":
                charge = json.loads(partie.get_payload(decode=True))
            elif partie.get_filename():
                fichiers.append(partie.get_filename())
        return charge, fichiers

    def _repondre(self, corps: dict) -> None:
        donnees = json.dumps(corps).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(donnees)))
        self.end_headers()
        self.wfile.write(donnees)

    def do_POST(self) -> None:  # noqa: N802
        charge, fichiers = self._lire()
        charge["fichiers"] = fichiers
        RECUS.append(charge)
        self._repondre({
            "id": str(1000 + len(RECUS)),
            "attachments": [
                {"id": str(9000 + index), "filename": nom} for index, nom in enumerate(fichiers)
            ],
        })

    def log_message(self, *args) -> None:
        pass


def verifier(condition: bool, libelle: str) -> None:
    print(f"{'✅' if condition else '❌'} {libelle}")
    if not condition:
        raise AssertionError(libelle)


class Catalogue:
    """Petit assistant : reproduit ce que fait le formulaire a partir de /api/catalogue."""

    def __init__(self, donnees: dict) -> None:
        self.slots = {s["slot"]: s for s in donnees["slots"]}
        self.categories = {int(k): v for k, v in donnees["categories"].items()}
        self.sorts = {int(k): v for k, v in donnees["sorts"].items()}
        self.objets = donnees["objets"]

    def objet(self, slot: str, nom: str | None = None, categorie: str | None = None) -> dict:
        for objet in self.objets:
            if objet["slot"] != slot:
                continue
            if nom and objet["nom"] != nom:
                continue
            if categorie and self.categories[objet["categorie_id"]]["nom"] != categorie:
                continue
            return objet
        raise LookupError(f"objet introuvable : {slot} / {nom} / {categorie}")

    def pool(self, objet: dict, emplacement: str) -> list[int]:
        return self.categories[objet["categorie_id"]]["pools"].get(emplacement, [])

    def remplir(self, ligne: dict, slot: str, objet: dict) -> dict:
        """Pose l'objet, son sort impose et des sorts valides pour ses champs."""
        regle = self.slots[slot]
        ligne[regle["champ"]] = objet["id"]
        if regle["champ_impose"]:
            ligne[regle["champ_impose"]["champ"]] = objet["sort_impose_id"]
        for champ in regle["champs"]:
            autorises = self.pool(objet, champ["emplacement"])
            if not autorises:
                ligne[champ["champ"]] = None
            elif champ["emplacement"] == "sort" and objet["sort_defaut_id"] in autorises:
                ligne[champ["champ"]] = objet["sort_defaut_id"]
            elif champ["obligatoire"]:
                ligne[champ["champ"]] = autorises[0]
        return ligne


def ligne_valide(cat: Catalogue, **surcharges) -> dict:
    ligne: dict = {"role_ou_joueur": "Tank"}
    cat.remplir(ligne, "arme", cat.objet("arme", "Masse"))
    cat.remplir(ligne, "offhand", cat.objet("offhand", "Bouclier"))
    cat.remplir(ligne, "casque", cat.objet("casque", "Casque de soldat"))
    cat.remplir(ligne, "torse", cat.objet("torse", "Armure de gardetombe"))
    cat.remplir(ligne, "bottes", cat.objet("bottes", "Bottes de soldat"))
    cat.remplir(ligne, "cape", cat.objet("cape", "Cape de Martlock"))
    cat.remplir(ligne, "monture", cat.objet("monture", "Cheval de guerre"))
    cat.remplir(ligne, "potion", cat.objet("potion", "Potion de soin"))
    cat.remplir(ligne, "nourriture", cat.objet("nourriture", "Ragoût de bœuf"))
    ligne.update(surcharges)
    return ligne


def compo_valide(cat: Catalogue, **surcharges) -> dict:
    compo = {
        "nom": "ZvZ - Ligne de front",
        "type_contenu": "ZvZ",
        "taille_groupe": 2,
        "statut": "brouillon",
        "notes": "Tenir la ligne.",
        "lignes": [ligne_valide(cat), ligne_valide(cat, role_ou_joueur="Soigneur")],
    }
    compo.update(surcharges)
    return compo


def main() -> None:
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), FauxWebhook)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    url_webhook = f"http://127.0.0.1:{serveur.server_port}/webhook"
    routeur_compos.webhook_configure = lambda _db: url_webhook

    with TestClient(app) as client:
        # --- Authentification ---
        verifier(client.get("/api/compos").status_code == 401, "API protegee sans session")
        verifier(
            client.post("/api/auth/login", json={"pseudo": "admin", "mot_de_passe": "faux"}).status_code
            == 401,
            "Mauvais mot de passe refuse",
        )
        reponse = client.post("/api/auth/login", json={"pseudo": "admin", "mot_de_passe": "motdepasse"})
        verifier(reponse.status_code == 200 and reponse.json()["role"] == "admin", "Connexion admin")

        # --- Catalogue ---
        cat = Catalogue(client.get("/api/catalogue").json())
        verifier(len(cat.objets) > 300, f"Catalogue charge ({len(cat.objets)} objets)")
        verifier(len(cat.slots) == 9, "Les 9 slots sont decrits par l'API")
        verifier(
            all(o["icone"].startswith("https://render.albiononline.com/v1/item/") for o in cat.objets),
            "Chaque objet porte l'URL de son icone",
        )
        verifier(
            all(s["icone"].startswith("https://render.albiononline.com/v1/spell/")
                for s in cat.sorts.values()),
            "Chaque sort et passif porte l'URL de son icone",
        )
        verifier(
            not any("tier" in champ for champ in json.dumps(cat.slots)),
            "Plus aucune notion de tier dans les regles de slots",
        )

        # --- Regles du catalogue ---
        masse = cat.objet("arme", "Masse")
        epee = cat.objet("arme", "Épée large")
        verifier(
            masse["sort_impose_id"] != epee["sort_impose_id"],
            "Règle 1 : chaque arme a son propre sort 3",
        )
        verifier(
            cat.pool(masse, "sort_1") and cat.pool(masse, "sort_2") and cat.pool(masse, "passif"),
            "Règle 2 : la catégorie d'arme fournit sorts 1, 2 et passifs",
        )
        masse_lourde = cat.objet("arme", "Masse lourde")
        verifier(
            masse["categorie_id"] == masse_lourde["categorie_id"]
            and cat.pool(masse, "sort_1") == cat.pool(masse_lourde, "sort_1"),
            "Règle 3 : deux armes d'une même catégorie partagent leurs sorts 1 et 2",
        )
        casque_soldat = cat.objet("casque", "Casque de soldat")
        casque_garde = cat.objet("casque", "Casque de gardetombe")
        verifier(
            casque_soldat["sort_defaut_id"] != casque_garde["sort_defaut_id"]
            and casque_soldat["sort_defaut_id"] in cat.pool(casque_garde, "sort"),
            "Règle 4 : sort natif propre à chaque armure, échangeable dans sa catégorie",
        )
        torse_plaque = cat.objet("torse", "Armure de gardetombe")
        torse_tissu = cat.objet("torse", "Robe d'ecclésiastique")
        verifier(
            cat.pool(torse_plaque, "passif_2") and not cat.pool(torse_tissu, "passif_2"),
            "Second passif de torse : proposé pour les plaques, absent du tissu",
        )
        verifier(
            not cat.slots["offhand"]["champs"] and not cat.slots["offhand"]["champ_impose"],
            "Off-hand : ni sort ni passif",
        )
        verifier(
            not cat.slots["cape"]["champs"] and cat.slots["cape"]["champ_impose"]["nom"] == "passif",
            "Cape : aucun sort, passif imposé par la cape",
        )

        # --- Creation ---
        reponse = client.post("/api/compos", json=compo_valide(cat))
        verifier(reponse.status_code == 201, "Creation d'une compo valide")
        compo = reponse.json()
        verifier(len(compo["lignes"]) == 2, "Les deux lignes sont enregistrees")
        verifier([l["ordre"] for l in compo["lignes"]] == [0, 1], "Ordre des lignes normalise")
        compo_id = compo["id"]

        # --- Regle 1 : le sort 3 est impose, quoi qu'envoie le client ---
        triche = ligne_valide(cat, arme_sort_3_id=cat.pool(masse, "sort_1")[0])
        cree = client.post("/api/compos", json=compo_valide(cat, nom="Triche", lignes=[triche])).json()
        verifier(
            cree["lignes"][0]["arme_sort_3_id"] == masse["sort_impose_id"],
            "Règle 1 : le sort 3 envoyé par le client est remplacé par celui de l'arme",
        )
        verifier(
            client.post("/api/compos", json=compo_valide(
                cat, lignes=[ligne_valide(cat, arme_sort_3_id=None)])).json()["lignes"][0]
            ["arme_sort_3_id"] == masse["sort_impose_id"],
            "Règle 1 : le sort 3 est posé même s'il est omis",
        )

        # --- Refus attendus ---
        sort_epee = cat.pool(epee, "sort_1")[0]
        sort_tissu = cat.pool(torse_tissu, "sort")[0]
        masse_lourde = cat.objet("arme", "Masse lourde")
        verifier(masse_lourde["deux_mains"] and not masse["deux_mains"],
                 "Le catalogue distingue les armes a deux mains")
        avec_deux_mains = cat.remplir(ligne_valide(cat), "arme", masse_lourde)
        cas = [
            ("off-hand avec une arme a deux mains", dict(avec_deux_mains)),
            ("sort 1 d'une autre catégorie d'arme", ligne_valide(cat, arme_sort_1_id=sort_epee)),
            ("sort 2 pris dans le pool des sorts 1",
             ligne_valide(cat, arme_sort_2_id=cat.pool(masse, "sort_1")[0])),
            ("passif d'arme pris dans les sorts", ligne_valide(cat, arme_passif_id=cat.pool(masse, "sort_2")[0])),
            ("sort de torse d'une autre catégorie", ligne_valide(cat, torse_sort_id=sort_tissu)),
            ("passif de casque inconnu de sa catégorie",
             ligne_valide(cat, casque_passif_id=cat.pool(torse_plaque, "passif_2")[0])),
            ("arme absente", ligne_valide(cat, arme_id=None)),
            ("casque absent", ligne_valide(cat, casque_id=None)),
            ("cape absente", ligne_valide(cat, cape_id=None)),
            ("sort 1 d'arme absent", ligne_valide(cat, arme_sort_1_id=None)),
            ("sort de bottes absent", ligne_valide(cat, bottes_sort_id=None)),
            ("passif de torse absent", ligne_valide(cat, torse_passif_1_id=None)),
            ("objet inexistant", ligne_valide(cat, arme_id=999999)),
            ("objet du mauvais slot", ligne_valide(cat, casque_id=masse["id"])),
            ("deux fois le même passif de torse",
             ligne_valide(cat, torse_passif_2_id=cat.pool(torse_plaque, "passif_1")[0])),
        ]
        for libelle, ligne in cas:
            statut = client.post("/api/compos", json=compo_valide(cat, lignes=[ligne])).status_code
            verifier(statut == 422, f"Refus : {libelle}")

        verifier(
            client.post("/api/compos", json=compo_valide(cat, lignes=[])).status_code == 422,
            "Refus : compo sans aucune ligne",
        )
        corps = client.post(
            "/api/compos", json=compo_valide(cat, lignes=[ligne_valide(cat, arme_sort_1_id=sort_epee)])
        ).json()
        verifier(
            corps["erreurs"][0]["champ"] == "lignes.0.arme_sort_1_id"
            and "Masse" in corps["erreurs"][0]["message"],
            "Message d'erreur exploitable, nommant l'objet fautif",
        )

        verifier(
            client.post("/api/compos", json=compo_valide(
                cat, nom="Deux mains", lignes=[dict(avec_deux_mains, offhand_id=None)])
            ).status_code == 201,
            "La meme arme a deux mains passe sans off-hand",
        )

        # --- Champs optionnels et pools vides ---
        minimale = ligne_valide(cat, offhand_id=None, monture_id=None, monture_sort_id=None,
                                potion_id=None, nourriture_id=None, torse_passif_2_id=None)
        reponse = client.post("/api/compos", json=compo_valide(
            cat, nom="Ganking duo", type_contenu="Ganking", lignes=[minimale]))
        verifier(reponse.status_code == 201, "Slots facultatifs vides acceptes")
        id_ganking = reponse.json()["id"]

        # Torse en tissu : pas de second passif, meme si le client en envoie un.
        tissu = ligne_valide(cat)
        cat.remplir(tissu, "torse", torse_tissu)
        tissu["torse_passif_2_id"] = cat.pool(torse_plaque, "passif_2")[0]
        reponse = client.post("/api/compos", json=compo_valide(cat, nom="Tissu", lignes=[tissu]))
        verifier(
            reponse.status_code == 201 and reponse.json()["lignes"][0]["torse_passif_2_id"] is None,
            "Torse en tissu : le second passif est ignoré",
        )

        # Cape de cite : aucun passif disponible, le champ reste vide.
        cape_simple = ligne_valide(cat)
        cat.remplir(cape_simple, "cape", cat.objet("cape", "Cape"))
        reponse = client.post("/api/compos", json=compo_valide(cat, nom="Cape nue", lignes=[cape_simple]))
        verifier(
            reponse.status_code == 201 and reponse.json()["lignes"][0]["cape_passif_id"] is None,
            "Cape sans passif acceptée",
        )

        # Monture : son sort est celui de la monture.
        monture = cat.objet("monture", "Cheval de monte")
        avec_monture = ligne_valide(cat)
        cat.remplir(avec_monture, "monture", monture)
        reponse = client.post("/api/compos", json=compo_valide(cat, nom="Monture", lignes=[avec_monture]))
        verifier(
            reponse.json()["lignes"][0]["monture_sort_id"] == monture["sort_impose_id"],
            "Monture : sort imposé par la monture",
        )
        sans_monture = ligne_valide(cat, monture_id=None, monture_sort_id=99999)
        verifier(
            client.post("/api/compos", json=compo_valide(cat, nom="Sans monture", lignes=[sans_monture]))
            .json()["lignes"][0]["monture_sort_id"] is None,
            "Pas de monture : pas de sort de monture",
        )

        # --- Modification ---
        modifiee = compo_valide(cat, nom="ZvZ - Ligne de front v2", statut="validée")
        reponse = client.put(f"/api/compos/{compo_id}", json=modifiee)
        verifier(
            reponse.status_code == 200 and reponse.json()["statut"] == "validée",
            "Modification d'une compo",
        )

        # --- Filtres ---
        verifier(
            len(client.get("/api/compos", params={"type_contenu": "Ganking"}).json()) == 1,
            "Filtre par type de contenu",
        )
        verifier(
            len(client.get("/api/compos", params={"statut": "validée"}).json()) == 1,
            "Filtre par statut",
        )
        verifier(
            len(client.get("/api/compos", params={"recherche": "ganking"}).json()) == 1,
            "Filtre par nom (insensible a la casse)",
        )
        verifier(
            len(client.get("/api/compos", params={"date_debut": "2099-01-01"}).json()) == 0,
            "Filtre par date de creation",
        )
        resume = client.get("/api/compos", params={"recherche": "front"}).json()[0]
        verifier(resume["nb_lignes"] == 2 and resume["auteur_pseudo"] == "admin", "Resume enrichi")

        # --- Duplication ---
        reponse = client.post(f"/api/compos/{compo_id}/dupliquer")
        copie = reponse.json()
        verifier(reponse.status_code == 201, "Duplication")
        verifier(copie["nom"].endswith("(copie)"), "Nom de la copie suffixe")
        verifier(copie["statut"] == "brouillon", "La copie repart en brouillon")
        verifier(
            copie["lignes"][0]["arme_sort_3_id"] == masse["sort_impose_id"],
            "Lignes copiees avec leur equipement",
        )

        # --- Joueur facultatif ---
        anonyme = ligne_valide(cat, role_ou_joueur="")
        sans_nom = client.post(
            "/api/compos", json=compo_valide(cat, nom="Builds a pourvoir", lignes=[anonyme])
        )
        verifier(sans_nom.status_code == 201, "Build accepte sans joueur assigne")
        premiere_ligne = sans_nom.json()["lignes"][0]
        verifier(premiere_ligne["role_ou_joueur"] == "", "Le champ joueur reste vide")
        verifier(premiere_ligne["libelle"] == "Build #1", "Libelle de repli « Build #1 »")
        omis = ligne_valide(cat)
        del omis["role_ou_joueur"]
        verifier(
            client.post("/api/compos", json=compo_valide(cat, nom="Omis", lignes=[omis]))
            .status_code == 201,
            "Le champ joueur peut etre absent du corps de la requete",
        )
        verifier(
            client.post("/api/compos", json=compo_valide(
                cat, nom="Nul", lignes=[ligne_valide(cat, role_ou_joueur=None)])).status_code == 201,
            "Un joueur a null est accepte",
        )

        # --- Apercu + envoi Discord ---
        apercu = client.get(f"/api/compos/{compo_id}/apercu-discord").json()
        verifier(apercu["entete"].startswith("📋"), "Entete du message")
        verifier(
            "ZvZ - Ligne de front v2" in apercu["entete"] and "admin" in apercu["entete"],
            "L'entete nomme la compo et son auteur",
        )
        verifier("embeds" not in apercu, "Plus aucun embed dans le message Discord")
        verifier(len(apercu["apercu"]) == 2, "Un bloc d'apercu par build")
        verifier(
            all("corps" not in build for build in apercu["apercu"]),
            "Plus de description textuelle des builds : l'image suffit",
        )
        verifier(
            apercu["apercu"][0]["image"] == f"/api/compos/{compo_id}/lignes/0/image.png",
            "L'apercu expose l'URL de l'image de chaque build",
        )

        # --- Image du build ---
        verifier(module_images.DISPONIBLE, "Pillow disponible : les images sont rendues")
        reponse = client.get(f"/api/compos/{compo_id}/lignes/0/image.png")
        verifier(
            reponse.status_code == 200 and reponse.content[:8] == b"\x89PNG\r\n\x1a\n",
            "Image de build servie en PNG",
        )
        verifier(
            reponse.headers["content-type"] == "image/png" and len(reponse.content) > 1000,
            "Image non vide, servie avec le bon type MIME",
        )
        verifier(
            client.get(f"/api/compos/{compo_id}/lignes/42/image.png").status_code == 404,
            "Image d'un build inexistant : 404",
        )

        RECUS.clear()
        reponse = client.post(f"/api/compos/{compo_id}/envoyer-discord")
        verifier(reponse.status_code == 200, "Envoi sur le webhook")
        verifier(reponse.json()["messages_envoyes"] == 1, "Un seul message pour 2 builds")
        verifier(reponse.json()["images_jointes"] == 2, "Une image jointe par build")
        verifier(len(RECUS) == 1 and "embeds" not in RECUS[0], "Payload sans aucun embed")
        verifier(
            RECUS[0]["fichiers"] == ["build_1.png", "build_2.png"],
            "Les images partent en pieces jointes nommees par build",
        )
        verifier(
            RECUS[0]["content"].startswith("📋") and "Masse" not in RECUS[0]["content"],
            "Le seul texte est l'entete de la compo, pas le detail des builds",
        )
        verifier(
            RECUS[0]["attachments"] == [{"id": 0, "filename": "build_1.png"},
                                        {"id": 1, "filename": "build_2.png"}],
            "Les pieces jointes sont declarees dans le payload",
        )
        relue = client.get(f"/api/compos/{compo_id}").json()
        verifier(relue["statut"] == "envoyée", "Statut passe a 'envoyee'")
        verifier(relue["date_envoi"] is not None, "Horodatage d'envoi enregistre")

        # Grosse compo : decoupage en plusieurs messages
        grosse = compo_valide(cat, nom="ZvZ - 30", taille_groupe=30,
                              lignes=[ligne_valide(cat, role_ou_joueur=f"Joueur {i}") for i in range(30)])
        id_grosse = client.post("/api/compos", json=grosse).json()["id"]
        RECUS.clear()
        reponse = client.post(f"/api/compos/{id_grosse}/envoyer-discord")
        verifier(reponse.status_code == 200, "Envoi d'une compo de 30 builds")
        verifier(len(RECUS) == 3, "30 builds : trois messages de 10 images")
        verifier(all(len(m["fichiers"]) <= 10 for m in RECUS), "Max 10 images par message")
        verifier(
            all(len(m["content"]) <= 2000 for m in RECUS),
            "Chaque message reste sous la limite de 2000 caracteres",
        )
        verifier(
            [m["content"] != "" for m in RECUS] == [True, False, False],
            "Seul le premier message porte l'entete",
        )
        fichiers = [nom for message in RECUS for nom in message["fichiers"]]
        verifier(len(fichiers) == len(set(fichiers)) == 30, "Chaque build emporte son image, une fois")

        # --- Import de builds depuis un tableur ---
        XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        reponse = client.get("/api/compos/modele-tableur")
        verifier(
            reponse.status_code == 200 and reponse.content[:2] == b"PK",
            "Modele Excel telecharge",
        )
        verifier(
            "modele_builds.xlsx" in reponse.headers["content-disposition"],
            "Le modele est propose en telechargement",
        )
        reponse = client.post(
            "/api/compos/importer-tableur",
            files={"fichier": ("modele_builds.xlsx", reponse.content, XLSX)},
        )
        verifier(
            reponse.status_code == 200 and len(reponse.json()["lignes"]) == 1,
            "Le modele se relit tel quel : sa ligne d'exemple est un build valide",
        )

        nom_sort_1 = cat.sorts[cat.pool(masse, "sort_1")[0]]["nom"]
        entetes = ("joueur;arme;arme_sort_1;offhand;casque;torse;bottes;cape;potion\n")
        csv_valide = entetes + (
            f"Tank;masse;{nom_sort_1};Bouclier;casque de soldat;Armure de gardetombe;"
            "Bottes de soldat;Cape de Martlock;Potion de soin\n"
        )
        reponse = client.post(
            "/api/compos/importer-tableur",
            files={"fichier": ("builds.csv", csv_valide.encode("utf-8"), "text/csv")},
        )
        verifier(reponse.status_code == 200, "Import CSV accepte")
        importee = reponse.json()["lignes"][0]
        verifier(
            importee["arme_id"] == masse["id"] and importee["offhand_id"] is not None,
            "Les objets sont retrouves par leur nom, sans tenir compte de la casse",
        )
        verifier(
            importee["arme_sort_1_id"] == cat.pool(masse, "sort_1")[0],
            "Un sort nomme dans le fichier est retenu",
        )
        verifier(
            importee["arme_sort_3_id"] == masse["sort_impose_id"]
            and importee["casque_sort_id"] is not None
            and importee["torse_passif_1_id"] is not None,
            "Les sorts non precises sont completes comme dans le formulaire",
        )
        verifier(
            client.post("/api/compos", json=compo_valide(
                cat, nom="Depuis Excel", lignes=[importee])).status_code == 201,
            "Une ligne importee s'enregistre telle quelle",
        )

        refuses = [
            ("objet inconnu", entetes + "Tank;Marteau magique;;;;;;;\n"),
            ("arme manquante", entetes + "Tank;;;Bouclier;Casque de soldat;;;;\n"),
            ("off-hand avec une arme a deux mains",
             entetes + "Tank;Masse lourde;;Bouclier;Casque de soldat;"
                       "Armure de gardetombe;Bottes de soldat;Cape de Martlock;\n"),
            ("fichier sans colonne reconnue", "a;b;c\n1;2;3\n"),
        ]
        for libelle, contenu in refuses:
            reponse = client.post(
                "/api/compos/importer-tableur",
                files={"fichier": ("builds.csv", contenu.encode("utf-8"), "text/csv")},
            )
            verifier(reponse.status_code == 422, f"Import refuse : {libelle}")
            verifier(
                all("Fichier ligne" in erreur["champ"] or erreur["champ"] == "fichier"
                    for erreur in reponse.json()["erreurs"]),
                f"Erreur situee dans le fichier : {libelle}",
            )
        verifier(
            client.post("/api/compos/importer-tableur",
                        files={"fichier": ("builds.pdf", b"%PDF", "application/pdf")}
                        ).status_code == 422,
            "Import refuse : format de fichier inconnu",
        )

        # --- Droits ---
        client.post("/api/membres", json={"pseudo": "membre1", "mot_de_passe": "motdepasse",
                                          "role": "membre"})
        client.post("/api/auth/logout")
        client.post("/api/auth/login", json={"pseudo": "membre1", "mot_de_passe": "motdepasse"})
        verifier(client.get("/api/settings").status_code == 403, "Settings reserves a l'admin")
        verifier(
            client.post("/api/membres", json={"pseudo": "x2", "mot_de_passe": "motdepasse"}).status_code
            == 403,
            "Creation de membre reservee a l'admin",
        )
        verifier(
            client.put(f"/api/compos/{compo_id}", json=modifiee).status_code == 403,
            "Un membre ne modifie pas la compo d'un autre",
        )
        verifier(
            client.delete(f"/api/compos/{id_ganking}").status_code == 403,
            "Un membre ne supprime pas la compo d'un autre",
        )
        propre = client.post("/api/compos", json=compo_valide(cat, nom="Ma compo")).json()
        verifier(
            client.delete(f"/api/compos/{propre['id']}").status_code == 204,
            "Un membre supprime sa propre compo",
        )

        # --- Suppression en cascade des lignes ---
        client.post("/api/auth/logout")
        client.post("/api/auth/login", json={"pseudo": "admin", "mot_de_passe": "motdepasse"})
        verifier(client.delete(f"/api/compos/{id_grosse}").status_code == 204, "Suppression admin")
        verifier(client.get(f"/api/compos/{id_grosse}").status_code == 404, "Compo bien supprimee")

        # --- Webhook non configure ---
        routeur_compos.webhook_configure = lambda _db: ""
        verifier(
            client.post(f"/api/compos/{compo_id}/envoyer-discord").status_code == 502,
            "Erreur claire si aucun webhook configure",
        )

    print("\n🎉 Tous les tests sont passes.")


if __name__ == "__main__":
    main()
