"""Tests de bout en bout : auth, catalogue, CRUD, regles de slots, envoi Discord."""
from __future__ import annotations

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

from backend.main import app  # noqa: E402
from backend.routers import compos as routeur_compos  # noqa: E402

RECUS: list[dict] = []


class FauxWebhook(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        taille = int(self.headers.get("Content-Length", 0))
        RECUS.append(json.loads(self.rfile.read(taille)))
        self.send_response(204)
        self.end_headers()

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

        # --- Apercu + envoi Discord ---
        apercu = client.get(f"/api/compos/{compo_id}/apercu-discord").json()
        verifier(apercu["embeds"][0]["title"].startswith("📋"), "Embed d'entete")
        premier = apercu["apercu"][0]["corps"]
        verifier("Sorts :" in premier and "Masse" in premier, "Les 3 sorts d'arme sont rendus")
        verifier(
            "T4." not in premier and "T8." not in premier and "`" not in premier,
            "Plus aucun tier dans le rendu Discord",
        )
        verifier(
            apercu["embeds"][0]["thumbnail"]["url"].startswith("https://render.albiononline.com"),
            "L'embed porte l'icone de l'arme",
        )

        reponse = client.post(f"/api/compos/{compo_id}/envoyer-discord")
        verifier(reponse.status_code == 200, "Envoi sur le webhook")
        verifier(reponse.json()["messages_envoyes"] == 1, "Un seul message pour 2 lignes")
        verifier(len(RECUS) == 1 and len(RECUS[0]["embeds"]) == 2, "Payload Discord bien forme")
        relue = client.get(f"/api/compos/{compo_id}").json()
        verifier(relue["statut"] == "envoyée", "Statut passe a 'envoyee'")
        verifier(relue["date_envoi"] is not None, "Horodatage d'envoi enregistre")

        # Grosse compo : decoupage en plusieurs embeds / messages
        grosse = compo_valide(cat, nom="ZvZ - 30", taille_groupe=30,
                              lignes=[ligne_valide(cat, role_ou_joueur=f"Joueur {i}") for i in range(30)])
        id_grosse = client.post("/api/compos", json=grosse).json()["id"]
        RECUS.clear()
        reponse = client.post(f"/api/compos/{id_grosse}/envoyer-discord")
        embeds = [embed for message in RECUS for embed in message["embeds"]]
        verifier(reponse.status_code == 200, "Envoi d'une compo de 30 joueurs")
        verifier(all(len(m["embeds"]) <= 10 for m in RECUS), "Max 10 embeds par message")
        verifier(
            all(len(embed.get("fields", [])) <= 25 for embed in embeds),
            "Max 25 champs par embed",
        )
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
            all(poids(embed) <= 6000 for embed in embeds),
            "Embeds sous la limite globale de 6000 caracteres",
        )
        noms = [champ["name"] for embed in embeds for champ in embed.get("fields", [])]
        verifier(len(noms) == 30, "Les 30 joueurs sont presents une seule fois")

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
