# ⚔️ Compos Albion Online

Site web interne + envoi Discord pour gérer les **compositions PvP** d'une guilde Albion Online.
Les compos sont créées et stockées sur le site, puis publiées dans un salon Discord en un clic
sous forme d'embed lisible.

L'équipement se choisit dans le **vrai catalogue du jeu** : menus déroulants avec recherche par
nom et vignettes officielles, sorts et passifs limités à ceux que l'objet peut réellement porter.

**Stack** : FastAPI (Python) · SQLite · HTML/CSS/JS sans framework · Webhook Discord.

---

## 1. Installation

Prérequis : **Python 3.11+**.

```bash
# 1. Environnement virtuel
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate

# 2. Dépendances
pip install -r requirements.txt

# 3. Configuration
cp .env.example .env
```

Éditez ensuite `.env` :

| Variable | Rôle |
| --- | --- |
| `SECRET_KEY` | Signe les cookies de session. **À changer** : `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DISCORD_WEBHOOK_URL` | Webhook du salon où poster les compos (modifiable aussi depuis `/admin`) |
| `ADMIN_PSEUDO` / `ADMIN_PASSWORD` | Compte admin créé au premier démarrage, si la base est vide |
| `DATABASE_URL` | Par défaut `sqlite:///./database/compos.db` |
| `COOKIE_SECURE` | `true` uniquement derrière HTTPS |
| `SESSION_MAX_AGE` | Durée d'une session en secondes (défaut : 7 jours) |

### Récupérer l'URL du webhook Discord

Salon Discord → *Modifier le salon* → *Intégrations* → *Webhooks* → *Nouveau webhook* → *Copier l'URL*.

## 2. Lancer le projet

```bash
uvicorn backend.main:app --reload
```

- Application : <http://127.0.0.1:8000>
- Documentation interactive de l'API : <http://127.0.0.1:8000/docs>

Au premier démarrage, les tables SQLite sont créées, le catalogue Albion est chargé en base
et le compte admin (`ADMIN_PSEUDO` / `ADMIN_PASSWORD`) est ajouté automatiquement.
Connectez-vous, puis créez les autres membres depuis **Administration**.

## 3. Commandes utiles

```bash
python manage.py init                              # crée les tables + le compte admin
python manage.py creer-membre <pseudo> <mdp> admin # ajoute un membre (admin | membre)
python manage.py mot-de-passe <pseudo> <mdp>       # réinitialise un mot de passe
python manage.py importer-catalogue                # recharge le catalogue Albion en base
python manage.py seed-demo                         # insère une compo d'exemple
```

## 4. Structure du projet

```
backend/
  config.py       Configuration (.env)
  database.py     Moteur SQLAlchemy + session SQLite
  models.py       Catalogue Albion + Membre, Compo, LigneCompo, Setting
  catalogue.py    Import du catalogue, index en mémoire et règles par slot
  validation.py   Règles métier : sorts autorisés, sorts imposés (source de vérité)
  schemas.py      Schémas Pydantic (forme des données)
  auth.py         Hachage scrypt + session par cookie signé
  discord.py      Construction de l'embed et envoi au webhook
  routers/
    auth.py       Connexion / déconnexion / session courante
    catalogue.py  Catalogue et règles consommés par le formulaire
    compos.py     CRUD, duplication, aperçu et envoi Discord
    admin.py      Membres et configuration du webhook
  main.py         Application FastAPI, init de la base, service du frontend
frontend/
  index.html          Connexion
  bibliotheque.html   Bibliothèque filtrable
  compo.html          Formulaire de création / édition
  admin.html          Membres + webhook
  css/style.css
  js/selecteur.js     Menu déroulant avec recherche et vignettes
  js/                 api.js (fetch partagé) + un script par page
scripts/
  importer_catalogue.py   Reconstruit le catalogue depuis les dumps officiels du jeu
database/
  catalogue_albion.json   Catalogue versionné avec le projet (aucun réseau requis)
  compos.db               Base SQLite (créée automatiquement)
tests/
  test_api.py         Tests de bout en bout du backend (aucune dépendance externe)
  test_frontend.mjs   Tests d'interface via jsdom (optionnel)
manage.py             Commandes d'administration
```

## 5. Fonctionnement

### Authentification

Accès fermé : **aucune inscription publique**. L'admin crée les comptes depuis `/admin`
(ou via `manage.py creer-membre`). Les mots de passe sont hachés en **scrypt** (sel aléatoire,
bibliothèque standard, aucune dépendance). La session est un cookie signé (`SameSite=Lax`).

Deux rôles :

- **membre** : consulte toutes les compos, crée les siennes, les modifie et les supprime,
  duplique et envoie n'importe quelle compo sur Discord ;
- **admin** : en plus, modifie/supprime les compos des autres et gère membres et webhook.

### Le catalogue Albion

L'équipement ne se saisit plus à la main : tout vient de `database/catalogue_albion.json`,
extrait des **dumps officiels du client** ([ao-data/ao-bin-dumps](https://github.com/ao-data/ao-bin-dumps))
et versionné avec le projet — il contient 396 objets, 49 catégories et 479 sorts et passifs,
en français. Les vignettes sont servies par `render.albiononline.com`.

Pour le rafraîchir après une mise à jour du jeu :

```bash
python scripts/importer_catalogue.py   # retélécharge les dumps et régénère le JSON
python manage.py importer-catalogue    # recharge le JSON en base
```

**Il n'y a plus aucune notion de tier** : un objet est choisi par son nom
(« Épée large »), le tier relevant du stuff de chaque joueur, pas de la compo.

### Règles de composition

Elles sont appliquées **côté serveur** (`backend/validation.py`, autorité) et reproduites dans
le formulaire pour le confort de saisie.

| Slot | Objet | Sorts | Passifs |
| --- | --- | --- | --- |
| **Arme** | obligatoire | sorts 1 et 2 au choix **dans sa catégorie** ; **sort 3 imposé par l'arme** | 1, au choix dans sa catégorie |
| **Off-hand** | facultatif | *aucun champ* | *aucun champ* |
| **Casque** | obligatoire | 1 sort : natif de la pièce, échangeable dans sa catégorie | 1, au choix dans sa catégorie |
| **Torse** | obligatoire | idem casque | passif 1 obligatoire ; passif 2 **uniquement si la catégorie en propose deux** (torses en plaques) |
| **Bottes** | obligatoire | idem casque | 1, au choix dans sa catégorie |
| **Cape** | obligatoire | *aucun champ* | **imposé par la cape** (absent des capes de cité) |
| **Monture** | facultative | **imposé par la monture** | *aucun champ* |
| **Potion** | facultative | — | — |
| **Nourriture** | facultative | — | — |

Concrètement, les quatre règles du modèle :

1. **une arme a un et un seul sort 3**, posé automatiquement dès qu'elle est choisie et
   verrouillé dans le formulaire (l'Épée large donne « Coup puissant », l'Adoube-roi
   « Frappe majestueuse ») ;
2. **une catégorie d'arme fournit les sorts 1, 2 et les passifs** proposés dans les menus ;
3. **un objet appartient à une seule catégorie**, qui définit donc entièrement ce qu'il peut
   choisir : deux épées partagent leurs sorts 1 et 2 ;
4. **une pièce d'armure a un sort natif**, présélectionné, mais échangeable contre n'importe
   quel autre sort de sa catégorie.

Autres garanties :

- un sort qui n'appartient pas à la catégorie de l'objet est refusé, avec un message nommant
  l'objet et sa catégorie ;
- changer d'objet réajuste les menus et remplace les sorts devenus incompatibles par des
  choix valides : un champ obligatoire n'est jamais laissé vide ;
- un slot facultatif est soit entièrement vide, soit renseigné ; un sort de monture sans
  monture est ignoré ;
- les deux passifs d'un torse doivent être différents ;
- une compo contient **au moins une ligne**, et l'ordre des lignes est normalisé à
  l'enregistrement.

Une erreur de validation renvoie un `422` avec un corps exploitable par le frontend :

```json
{ "detail": "Validation echouee",
  "erreurs": [{ "champ": "lignes.0.arme_sort_1_id",
                "message": "Arme : sort 1 : « Frappe héroïque » n'est pas disponible pour « Masse » (Masses)." }] }
```

### Envoi Discord

Le bouton **Envoyer sur Discord** poste un embed par lot de joueurs. Le découpage respecte les
limites de l'API Discord (25 champs par embed, 6000 caractères par embed, 10 embeds par message) :
une compo ZvZ de 30 joueurs part donc en plusieurs embeds, au besoin en plusieurs messages, et les
`429` (rate limit) sont réessayés. En cas de succès, la compo passe au statut **envoyée** et la
date d'envoi est horodatée.

Le bouton **Aperçu Discord** affiche le rendu exact avant publication.

Rendu d'une ligne :

```
#1 — Tank / Initiateur
⚔️ Arme — Masse
┗ Sorts : Frappe défensive / Charge piégée / Grande enjambée · Passif : Combat effroyable
🛡️ Off-hand — Bouclier
🪖 Casque — Casque de soldat
┗ Sort : Défense · Passif : Autorité
🥋 Torse — Armure de gardetombe
┗ Sort : Chaîne d'âme · Passifs : Autorité
🥾 Bottes — Bottes de soldat
┗ Sort : Envie d'ailleurs · Passif : Autorité
🧣 Cape — Cape de Martlock
┗ Passif : Bouclier de protection
🐎 Monture — Cheval de guerre
🧪 Potion de soin · 🍲 Ragoût de bœuf
```

Le torse affiche `Passifs : Autorité + Instinct protecteur` quand un second passif est
renseigné. L'embed d'en-tête porte en vignette l'icône de l'arme du premier joueur.

## 6. API

Toutes les routes exigent une session, sauf `POST /api/auth/login`.

| Méthode | Route | Description |
| --- | --- | --- |
| `POST` | `/api/auth/login` | Connexion (`{pseudo, mot_de_passe}`) |
| `POST` | `/api/auth/logout` | Déconnexion |
| `GET` | `/api/auth/me` | Membre connecté |
| `GET` | `/api/meta` | Énumérations (types de contenu, statuts, rôles) |
| `GET` | `/api/catalogue` | Catalogue Albion + règles de slots : le formulaire se construit à partir de cette seule réponse |
| `GET` | `/api/compos` | Liste filtrable : `type_contenu`, `auteur_id`, `statut`, `date_debut`, `date_fin`, `recherche` |
| `POST` | `/api/compos` | Création |
| `GET` | `/api/compos/{id}` | Détail avec toutes les lignes |
| `PUT` | `/api/compos/{id}` | Modification (auteur ou admin) |
| `DELETE` | `/api/compos/{id}` | Suppression (auteur ou admin) |
| `POST` | `/api/compos/{id}/dupliquer` | Duplication (la copie repart en brouillon, au nom du duplicateur) |
| `GET` | `/api/compos/{id}/apercu-discord` | Aperçu de l'embed |
| `POST` | `/api/compos/{id}/envoyer-discord` | Envoi + passage au statut « envoyée » |
| `GET` | `/api/membres` | Liste des membres (sert au filtre « auteur ») |
| `POST`/`PUT`/`DELETE` | `/api/membres[/{id}]` | Gestion des membres (**admin**) |
| `GET`/`PUT` | `/api/settings` | URL du webhook Discord (**admin**) |

## 7. Tests

```bash
# Backend : auth, CRUD, validation par slot, découpage et envoi Discord
# (un faux serveur webhook local est démarré par le test, aucun message n'est posté sur Discord)
python tests/test_api.py

# Frontend (optionnel) : pilote les vraies pages dans jsdom (validation du formulaire,
# enregistrement, filtres, administration). Écrit dans la base visée : à réserver au dev.
npm install jsdom
uvicorn backend.main:app --port 8123 &   # dans un autre terminal
python manage.py seed-demo               # la compo n°1 sert de support aux tests
ADMIN_PASSWORD="<le mot de passe de votre .env>" node tests/test_frontend.mjs
```

## 8. Mise en production (rapide)

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Derrière un reverse proxy HTTPS (nginx, Caddy), pensez à passer `COOKIE_SECURE=true` dans `.env`
et à sauvegarder régulièrement `database/compos.db`.

## 9. Prévu pour la V2 (hors périmètre du MVP)

- Vrai bot Discord avec commandes slash et interactions
- Validation automatique de cohérence des builds (arme à deux mains + off-hand, nombre de
  sorts actifs simultanés, etc. — le catalogue expose déjà l'indicateur `deux_mains`)
- Statistiques et historique de versions des compos
