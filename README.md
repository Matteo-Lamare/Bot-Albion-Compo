# ⚔️ Compos Albion Online

Site web interne + envoi Discord pour gérer les **compositions PvP** d'une guilde Albion Online.
Les compos sont créées et stockées sur le site, puis publiées dans un salon Discord en un clic :
chaque build part avec **son image** (la planche d'équipement, icônes officielles) et son bloc
d'inscription.

L'équipement se choisit dans le **vrai catalogue du jeu** : menus déroulants avec recherche par
nom et vignettes officielles, sorts et passifs limités à ceux que l'objet peut réellement porter.

Assigner un joueur est **facultatif** : une compo peut n'être qu'une liste de builds, sur lesquels
chacun **s'inscrit** ensuite. Le message Discord déjà posté se met alors à jour tout seul.

**Stack** : FastAPI (Python) · SQLite · HTML/CSS/JS sans framework · Webhook Discord.

---

## 1. Installation

Prérequis : **Python 3.11+**. Pillow (dans `requirements.txt`) sert à composer les images de
build ; sans lui, le message Discord part en texte seul, tout le reste fonctionne à l'identique.

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
| `APP_BASE_URL` | Adresse publique du site, insérée dans le message Discord pour que chacun clique et s'inscrive |
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
python manage.py images <compo_id> [dossier]       # exporte les images de build en PNG
```

## 4. Structure du projet

```
backend/
  config.py       Configuration (.env)
  database.py     Moteur SQLAlchemy + session SQLite
  models.py       Catalogue Albion + Membre, Compo, LigneCompo, Inscription, Setting
  catalogue.py    Import du catalogue, index en mémoire et règles par slot
  validation.py   Règles métier : sorts autorisés, sorts imposés (source de vérité)
  schemas.py      Schémas Pydantic (forme des données)
  auth.py         Hachage scrypt + session par cookie signé
  discord.py      Embeds, envoi au webhook et mise à jour des messages postés
  images.py       Rendu d'un build en PNG (icônes officielles, cache disque)
  routers/
    auth.py       Connexion / déconnexion / session courante
    catalogue.py  Catalogue et règles consommés par le formulaire
    compos.py     CRUD, duplication, aperçu, images, inscriptions et envoi Discord
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

Le bouton **Envoyer sur Discord** poste un embed d'en-tête (type, taille, notes, lien
d'inscription) puis **un embed par build**, chacun accompagné de son image en pièce jointe.
Le découpage respecte les limites de l'API Discord — 10 embeds, 10 pièces jointes et
6000 caractères par message — donc une compo ZvZ de 30 builds part en plusieurs messages, et les
`429` (rate limit) sont réessayés. En cas de succès, la compo passe au statut **envoyée**, la date
d'envoi est horodatée et les identifiants des messages sont mémorisés.

Le bouton **Aperçu Discord** affiche le rendu exact — images comprises — avant publication.

**L'image d'un build** reprend la disposition de l'écran d'équipement (3 × 3), chaque objet
surmontant ses sorts et passifs (liseré bleu pour un sort actif, doré pour un passif). Les icônes
viennent de `render.albiononline.com` et sont mises en cache dans `.cache/icones/` : seul le
premier rendu télécharge quelque chose. Le médaillon de tier gravé dans le cadre officiel est
effacé, l'outil ne manipulant plus les tiers.

Texte accompagnant un build (l'image porte les objets, le texte porte les sorts) :

```
#1 — Tank / Initiateur
⚔️ **Masse** — Frappe défensive · Charge piégée · Grande enjambée · Combat effroyable
🪖 **Casque de soldat** — Défense · Autorité
🥋 **Armure de gardetombe** — Chaîne d'âme · Autorité
🥾 **Bottes de soldat** — Envie d'ailleurs · Autorité
🧣 **Cape de Martlock** — Bouclier de protection
🛡️ Bouclier · 🐎 Cheval de guerre · 🧪 Potion de soin · 🍲 Ragoût de bœuf

🙋 Inscrits (1)
**Matteo**
```

Le torse affiche un second passif quand son armure en propose un (torses en plaques). Un build
sans volontaire s'affiche en gris avec « Personne pour l'instant ».

### Inscriptions : chacun choisit son build

Un build n'a pas besoin d'être attribué à l'avance. Sur la page de la compo, chaque build porte un
bouton **« Je joue ce build »** ; le lien mis dans le message Discord (`APP_BASE_URL`) y renvoie
directement. Un membre ne tient qu'**un seul build par compo** : s'inscrire ailleurs y déplace son
inscription. Les inscrits sont conservés lorsque la compo est modifiée (ils suivent le rang du
build).

À chaque inscription, les messages Discord déjà postés sont **ré-édités** : le compteur, la liste
des volontaires et la couleur de l'embed suivent, images comprises. Si Discord est injoignable,
l'inscription est quand même enregistrée et repartira au prochain envoi.

> Pourquoi pas des boutons directement dans Discord ? Un webhook ne peut que **poster** et
> **éditer** des messages : recevoir un clic exige une application Discord connectée en
> permanence, hors périmètre du MVP (cf. § 9). Le lien + la ré-édition du message donnent le même
> résultat visible dans le salon, sans bot à héberger.

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
| `GET` | `/api/compos/{id}/apercu-discord` | Aperçu des embeds, avec l'URL de l'image de chaque build |
| `GET` | `/api/compos/{id}/lignes/{ordre}/image.png` | Image du build (PNG), telle qu'elle part en pièce jointe |
| `POST` | `/api/compos/{id}/envoyer-discord` | Envoi + passage au statut « envoyée » |
| `GET` | `/api/compos/{id}/inscriptions` | Qui joue quel build |
| `POST` | `/api/compos/{id}/lignes/{ligne_id}/inscription` | S'inscrire sur un build (et re-éditer le message Discord) |
| `DELETE` | `/api/compos/{id}/lignes/{ligne_id}/inscription` | Se désinscrire (`?membre_id=` réservé aux admins) |
| `GET` | `/api/membres` | Liste des membres (sert au filtre « auteur ») |
| `POST`/`PUT`/`DELETE` | `/api/membres[/{id}]` | Gestion des membres (**admin**) |
| `GET`/`PUT` | `/api/settings` | URL du webhook Discord (**admin**) |

## 7. Tests

```bash
# Backend : auth, CRUD, validation par slot, images, inscriptions, découpage et envoi Discord
# (un faux webhook local reçoit les messages et les pièces jointes ; aucun accès réseau)
python tests/test_api.py

# Frontend (optionnel) : pilote les vraies pages dans jsdom (formulaire, enregistrement,
# inscriptions, aperçu, filtres, administration). Écrit dans la base visée : à réserver au dev.
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

- Vrai bot Discord avec commandes slash et **boutons d'inscription dans le salon**
  (aujourd'hui l'inscription se fait sur le site, via le lien du message, qui se met à jour)
- Validation automatique de cohérence des builds (arme à deux mains + off-hand, nombre de
  sorts actifs simultanés, etc. — le catalogue expose déjà l'indicateur `deux_mains`)
- Statistiques et historique de versions des compos
