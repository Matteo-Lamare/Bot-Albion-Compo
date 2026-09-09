"""Tests de bout en bout : auth, catalogue, CRUD, regles, images, inscriptions, Discord."""
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

RECUS: list[dict] = []     # messages postes sur le webhook
EDITIONS: list[dict] = []  # messages re-edites (PATCH), apres inscription


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

    def do_PATCH(self) -> None:  # noqa: N802
        charge, _ = self._lire()
        charge["chemin"] = self.path
        EDITIONS.append(charge)
        self._repondre({"id": self.path.rsplit("/", 1)[-1]})

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
        cas = [
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
        verifier(apercu["embeds"][0]["title"].startswith("📋"), "Embed d'entete")
        verifier(len(apercu["embeds"]) == 3, "Un embed d'entete + un embed par build")
        premier = apercu["apercu"][0]["corps"]
        verifier("Masse" in premier and "🪖" in premier, "Le texte nomme les objets et leurs sorts")
        verifier(
            "T4." not in premier and "T8." not in premier and "`" not in premier,
            "Plus aucun tier dans le rendu Discord",
        )
        verifier(
            apercu["embeds"][0]["thumbnail"]["url"].startswith("https://render.albiononline.com"),
            "L'embed porte l'icone de l'arme",
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
        verifier(len(RECUS) == 1 and len(RECUS[0]["embeds"]) == 3, "Payload Discord bien forme")
        verifier(
            RECUS[0]["fichiers"] == ["build_1.png", "build_2.png"],
            "Les images partent en pieces jointes nommees par build",
        )
        verifier(
            [e["image"]["url"] for e in RECUS[0]["embeds"][1:]]
            == ["attachment://build_1.png", "attachment://build_2.png"],
            "Chaque embed de build affiche son image",
        )
        verifier(
            RECUS[0]["attachments"] == [{"id": 0, "filename": "build_1.png"},
                                        {"id": 1, "filename": "build_2.png"}],
            "Les pieces jointes sont declarees dans le payload",
        )
        relue = client.get(f"/api/compos/{compo_id}").json()
        verifier(relue["statut"] == "envoyée", "Statut passe a 'envoyee'")
        verifier(relue["date_envoi"] is not None, "Horodatage d'envoi enregistre")

        # --- Inscriptions sur un build ---
        ligne_1, ligne_2 = relue["lignes"][0]["id"], relue["lignes"][1]["id"]
        verifier(
            client.get(f"/api/compos/{compo_id}/inscriptions").json()["lignes"][0]["inscrits"] == [],
            "Aucun inscrit au depart",
        )
        EDITIONS.clear()
        resultat = client.post(f"/api/compos/{compo_id}/lignes/{ligne_1}/inscription").json()
        verifier(
            [i["pseudo"] for i in resultat["lignes"][0]["inscrits"]] == ["admin"],
            "Inscription enregistree sur le build choisi",
        )
        verifier(resultat["discord_mis_a_jour"], "Le message Discord deja poste est re-edite")
        verifier(len(EDITIONS) == 1 and EDITIONS[0]["chemin"].endswith("/messages/1001"),
                 "L'edition vise le message realement poste")
        verifier(
            "Inscrits (1)" in json.dumps(EDITIONS[0]["embeds"], ensure_ascii=False),
            "Le message mis a jour annonce l'inscrit",
        )
        verifier(
            [p["id"] for p in EDITIONS[0]["attachments"]] == ["9000", "9001"],
            "Les images sont conservees lors de l'edition",
        )
        verifier(
            EDITIONS[0]["embeds"][1]["image"]["url"] == "attachment://build_1.png",
            "L'embed re-edite pointe toujours vers son image",
        )

        client.post(f"/api/compos/{compo_id}/lignes/{ligne_1}/inscription")
        verifier(
            len(client.get(f"/api/compos/{compo_id}/inscriptions").json()["lignes"][0]["inscrits"])
            == 1,
            "S'inscrire deux fois ne cree pas de doublon",
        )
        etat = client.post(f"/api/compos/{compo_id}/lignes/{ligne_2}/inscription").json()["lignes"]
        verifier(
            etat[0]["inscrits"] == [] and len(etat[1]["inscrits"]) == 1,
            "Un membre ne tient qu'un seul build : l'inscription se deplace",
        )
        verifier(
            client.post(f"/api/compos/{compo_id}/lignes/999999/inscription").status_code == 404,
            "Inscription sur un build inexistant refusee",
        )

        # Les inscrits survivent a une modification de la compo.
        client.put(f"/api/compos/{compo_id}", json=compo_valide(
            cat, nom="ZvZ - Ligne de front v3", statut="validée"))
        apres = client.get(f"/api/compos/{compo_id}").json()
        verifier(
            [i["pseudo"] for i in apres["lignes"][1]["inscriptions"]] == ["admin"],
            "Editer la compo ne perd pas les inscrits du build",
        )
        nouvelle_ligne_2 = apres["lignes"][1]["id"]
        etat = client.delete(
            f"/api/compos/{compo_id}/lignes/{nouvelle_ligne_2}/inscription"
        ).json()["lignes"]
        verifier(all(not ligne["inscrits"] for ligne in etat), "Desinscription effective")

        # Grosse compo : decoupage en plusieurs messages
        grosse = compo_valide(cat, nom="ZvZ - 30", taille_groupe=30,
                              lignes=[ligne_valide(cat, role_ou_joueur=f"Joueur {i}") for i in range(30)])
        id_grosse = client.post("/api/compos", json=grosse).json()["id"]
        RECUS.clear()
        reponse = client.post(f"/api/compos/{id_grosse}/envoyer-discord")
        embeds = [embed for message in RECUS for embed in message["embeds"]]
        verifier(reponse.status_code == 200, "Envoi d'une compo de 30 builds")
        verifier(all(len(m["embeds"]) <= 10 for m in RECUS), "Max 10 embeds par message")
        verifier(all(len(m["fichiers"]) <= 10 for m in RECUS), "Max 10 images par message")
        verifier(
            all(len(champ["value"]) <= 1024 for embed in embeds for champ in embed.get("fields", [])),
            "Champs sous la limite de 1024 caracteres",
        )

        def poids(embed: dict) -> int:
            """Compte les caracteres comme Discord : titre + description + champs."""
            return (
                len(embed.get("title", ""))
                + len(embed.get("description", ""))
                + len(embed.get("footer", {}).get("text", ""))
                + sum(len(c["name"]) + len(c["value"]) for c in embed.get("fields", []))
            )

        verifier(
            all(sum(poids(e) for e in message["embeds"]) <= 6000 for message in RECUS),
            "Chaque message reste sous la limite globale de 6000 caracteres",
        )
        titres = [embed["title"] for embed in embeds if embed["title"].startswith("#")]
        verifier(len(titres) == 30, "Les 30 builds sont presents une seule fois")
        verifier(
            sum(len(message["fichiers"]) for message in RECUS) == 30,
            "Chaque build emporte son image",
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
