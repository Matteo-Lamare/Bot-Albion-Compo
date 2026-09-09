import { JSDOM, VirtualConsole, CookieJar } from "jsdom";

// Le serveur doit tourner (voir README) et la base contenir la compo de demonstration :
//   uvicorn backend.main:app --port 8123
//   python manage.py seed-demo
// Attention : ces tests ecrivent dans la base visee (edition de la compo 1, creation d'un membre).
const BASE = process.env.BASE_URL || "http://127.0.0.1:8123";
const PSEUDO = process.env.ADMIN_PSEUDO || "admin";
const MOT_DE_PASSE = process.env.ADMIN_PASSWORD || "changez-ce-mot-de-passe";
let echecs = 0;
const verifier = (condition, libelle) => {
  console.log(`${condition ? "✅" : "❌"} ${libelle}`);
  if (!condition) echecs++;
};
const attendre = (ms) => new Promise((r) => setTimeout(r, ms));

// Session admin partagee par jsdom et par les appels fetch injectes.
const connexion = await fetch(`${BASE}/api/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ pseudo: PSEUDO, mot_de_passe: MOT_DE_PASSE }),
});
if (connexion.status !== 200) {
  console.error(
    `❌ Connexion impossible (${connexion.status}). Renseignez ADMIN_PSEUDO / ADMIN_PASSWORD ` +
      "avec les identifiants de votre .env avant de lancer les tests."
  );
  process.exit(1);
}
const cookie = connexion.headers.getSetCookie()[0].split(";")[0];
verifier(connexion.status === 200, "Connexion admin depuis le navigateur simule");

async function ouvrir(chemin) {
  const virtualConsole = new VirtualConsole();
  const journal = [];
  virtualConsole.on("jsdomError", (e) => {
    if (!/Not implemented: navigation/.test(e.message)) journal.push(e.message);
  });
  virtualConsole.on("error", (m) => journal.push(String(m)));

  const jar = new CookieJar();
  jar.setCookieSync(`${cookie}; Path=/`, BASE);

  const dom = await JSDOM.fromURL(`${BASE}${chemin}`, {
    runScripts: "dangerously",
    resources: "usable",
    cookieJar: jar,
    virtualConsole,
    beforeParse(window) {
      window.fetch = (url, options = {}) =>
        fetch(new URL(url, BASE), {
          ...options,
          headers: { ...(options.headers || {}), cookie },
        });
      window.confirm = () => true;
      // jsdom n'implemente pas scrollIntoView : on le neutralise.
      window.Element.prototype.scrollIntoView = function () {};
      window.alert = () => {};
    },
  });
  await attendre(700);
  return { dom, window: dom.window, doc: dom.window.document, journal };
}

// ---------- Page bibliotheque ----------
{
  const { doc, journal, window } = await ouvrir("/bibliotheque");
  verifier(journal.length === 0, `Bibliothèque sans erreur JS ${journal.join(" | ")}`);
  verifier(doc.querySelectorAll("#corps-table tr").length >= 1, "La bibliothèque liste les compos");
  verifier(
    doc.querySelector("#filtre-type").options.length === 7,
    "Filtre type de contenu alimenté par /api/meta"
  );
  verifier(
    doc.querySelector("header.barre nav a[data-page='admin']") !== null,
    "Lien Administration visible pour un admin"
  );
  window.close();
}

// ---------- Page compo (edition) ----------
{
  const { doc, window, journal } = await ouvrir("/compo?id=1");
  verifier(journal.length === 0, `Éditeur sans erreur JS ${journal.join(" | ")}`);

  const cartes = doc.querySelectorAll(".ligne-compo");
  verifier(cartes.length === 2, "Les 2 lignes de la compo sont rendues");
  const carte = cartes[0];
  const slots = [...carte.querySelectorAll(".slot[data-slot]")].map((s) => s.dataset.slot);
  verifier(
    JSON.stringify(slots) ===
      JSON.stringify(["arme","offhand","casque","torse","bottes","cape","monture","potion","nourriture"]),
    "Les 9 slots sont rendus dans l'ordre"
  );

  const selecteur = (champ) => carte.selecteurs[champ];
  const visible = (champ) => !selecteur(champ).parentElement.hidden;
  const clic = (element) => element.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));

  // Les propositions ne sont rendues qu'à l'ouverture du menu : on l'ouvre pour lire.
  async function ouvrirMenu(champ) {
    clic(selecteur(champ).querySelector(".selecteur-valeur"));
    await attendre(90);
    return selecteur(champ).querySelector(".selecteur-panneau");
  }
  async function options(champ) {
    const panneau = await ouvrirMenu(champ);
    const noms = [...panneau.querySelectorAll(".selecteur-option")].map((o) => o.textContent.trim());
    clic(selecteur(champ).querySelector(".selecteur-valeur"));
    await attendre(30);
    return noms;
  }
  // Comme un utilisateur : on ouvre, on tape le nom, on clique le résultat.
  async function choisirDansMenu(champ, nom) {
    const panneau = await ouvrirMenu(champ);
    const recherche = panneau.querySelector(".selecteur-recherche");
    recherche.value = nom;
    recherche.dispatchEvent(new window.Event("input", { bubbles: true }));
    await attendre(90);
    const option = [...panneau.querySelectorAll(".selecteur-option")]
      .find((o) => o.textContent.trim() === nom);
    option.dispatchEvent(new window.MouseEvent("mousedown", { bubbles: true }));
    await attendre(150);
  }

  // Tous les choix passent par un menu déroulant, plus aucune saisie libre d'objet.
  verifier(
    carte.querySelectorAll(".selecteur").length >= 15,
    "Chaque slot et chaque sort est un menu déroulant"
  );
  const saisies = [...carte.querySelectorAll("input")].filter(
    (i) => !i.closest(".selecteur-panneau")   // les champs de recherche ne comptent pas
  );
  verifier(
    saisies.length === 1 && saisies[0].classList.contains("champ-role"),
    "Seul le rôle reste une saisie libre"
  );
  verifier(
    !doc.body.innerHTML.includes("T8.") && !doc.body.innerHTML.includes("Tier"),
    "Plus aucun champ de tier dans le formulaire"
  );

  // Les tests enregistrent leurs modifications : on repart d'un état connu pour
  // rester rejouable sur la même base.
  await choisirDansMenu("arme_id", "Masse");
  await choisirDansMenu("torse_id", "Armure de gardetombe");

  // Nommer le joueur n'est plus obligatoire : sans nom, le build s'annonce « Build #1 ».
  const nomInitial = carte.champRole.value;
  carte.champRole.value = "";
  carte.champRole.dispatchEvent(new window.Event("input", { bubbles: true }));
  verifier(
    !carte.champRole.dataset.requis && !carte.champRole.required,
    "Le champ joueur n'est plus marqué obligatoire"
  );
  verifier(
    carte.querySelector(".resume").textContent.startsWith("Build #1"),
    "Sans joueur assigné, le build s'affiche « Build #1 »"
  );

  // Images dans les menus
  const bouton = selecteur("arme_id").querySelector(".selecteur-valeur");
  const image = bouton.querySelector("img.vignette");
  verifier(
    image && image.src.startsWith("https://render.albiononline.com/v1/item/"),
    "L'objet choisi est accompagné de son image"
  );

  // Ouverture du menu + recherche par nom
  clic(bouton);
  await attendre(120);
  const panneau = selecteur("arme_id").querySelector(".selecteur-panneau");
  verifier(!panneau.hidden, "Le menu s'ouvre au clic");
  const total = panneau.querySelectorAll(".selecteur-option").length;
  const champRecherche = panneau.querySelector(".selecteur-recherche");
  champRecherche.value = "epee";
  champRecherche.dispatchEvent(new window.Event("input", { bubbles: true }));
  await attendre(120);
  const filtres = [...panneau.querySelectorAll(".selecteur-option")].map((o) => o.textContent.trim());
  verifier(
    filtres.length > 0 && filtres.length < total && filtres.every((n) => /épée|epee/i.test(n)),
    `Recherche « epee » : ${filtres.length} résultats accentués sur ${total} affichés`
  );
  verifier(
    panneau.querySelectorAll(".selecteur-option img.vignette").length === filtres.length,
    "Chaque proposition du menu porte son image"
  );
  verifier(
    panneau.querySelectorAll(".selecteur-groupe").length >= 1,
    "Les propositions sont regroupées par catégorie"
  );

  // Sélection d'une épée : les sorts suivent la nouvelle catégorie
  clic(bouton);
  await attendre(60);
  const passifsAvant = await options("arme_passif_id");
  await choisirDansMenu("arme_id", "Épée large");

  verifier(
    selecteur("arme_id").querySelector(".selecteur-valeur").textContent.includes("Épée large"),
    "Le choix se répercute sur le bouton"
  );
  const sort3 = selecteur("arme_sort_3_id");
  verifier(
    sort3.querySelector(".selecteur-valeur.verrouille") !== null,
    "Règle 1 : le sort 3 est verrouillé"
  );
  verifier(
    sort3.querySelector(".selecteur-valeur").textContent.includes("Coup puissant"),
    "Règle 1 : le sort 3 de l'épée est posé automatiquement"
  );
  const sorts1 = await options("arme_sort_1_id");
  const sorts2 = await options("arme_sort_2_id");
  const passifsApres = await options("arme_passif_id");
  verifier(
    sorts1.length === 2 && sorts1.includes("Frappe héroïque") && sorts1.includes("Fendoir héroïque"),
    `Règle 2 : les sorts 1 proposés sont ceux des épées (${sorts1.join(", ")})`
  );
  verifier(
    JSON.stringify(passifsApres) !== JSON.stringify(passifsAvant) && passifsApres.length === 4,
    "Règle 3 : changer d'arme change les passifs proposés"
  );
  verifier(
    sorts1.every((nom) => !sorts2.includes(nom)) && sorts2.length === 6,
    "Sorts 1 et 2 sont bien deux pools distincts"
  );
  // Après un changement d'arme, aucun champ obligatoire n'est laissé vide.
  verifier(
    ["arme_sort_1_id", "arme_sort_2_id", "arme_passif_id"].every((c) => selecteur(c).valeur),
    "Changer d'arme repose des sorts valides dans tous les champs obligatoires"
  );


  // Règle 4 : armure — sort natif présélectionné, échangeable dans la catégorie
  const natif = selecteur("casque_sort_id").querySelector(".selecteur-valeur").textContent.trim();
  const choixCasque = await options("casque_sort_id");
  verifier(
    natif !== "—" && natif !== "" && choixCasque.length > 1 && choixCasque.includes(natif),
    `Règle 4 : sort natif « ${natif} » présélectionné, échangeable parmi ${choixCasque.length}`
  );

  // Second passif du torse : présent en plaques, absent en tissu
  verifier(visible("torse_passif_2_id"), "Torse en plaques : le second passif est proposé");
  await choisirDansMenu("torse_id", "Robe d'ecclésiastique");
  verifier(!visible("torse_passif_2_id"), "Torse en tissu : le second passif disparaît");
  const passifsTissu = await options("torse_passif_1_id");
  verifier(passifsTissu.length === 3, "Les passifs proposés sont ceux du tissu");
  const passifTissu = selecteur("torse_passif_1_id").querySelector(".selecteur-valeur").textContent.trim();
  verifier(
    passifsTissu.includes(passifTissu),
    `Changer d'armure remplace le passif incompatible par un choix valide (« ${passifTissu} »)`
  );

  // Off-hand et cape : champs conformes aux règles
  verifier(
    !carte.selecteurs.offhand_sort_id && !carte.selecteurs.offhand_passif_id,
    "Off-hand : ni sort ni passif dans le formulaire"
  );
  verifier(!carte.selecteurs.cape_sort_id, "Cape : aucun champ sort");
  verifier(
    selecteur("cape_passif_id").querySelector(".selecteur-valeur.verrouille") !== null,
    "Cape : passif imposé par la cape, verrouillé"
  );

  // Validation : un choix obligatoire vidé bloque l'enregistrement
  selecteur("arme_sort_1_id").valeur = null;
  doc.getElementById("formulaire-compo").dispatchEvent(
    new window.Event("submit", { bubbles: true, cancelable: true })
  );
  await attendre(300);
  verifier(
    selecteur("arme_sort_1_id").classList.contains("erreur"),
    "Choix obligatoire manquant surligné en erreur"
  );
  verifier(
    doc.getElementById("message").className.includes("erreur"),
    "Message d'erreur affiché sans appel réseau"
  );
  verifier(
    !doc.getElementById("message").textContent.includes("Joueur"),
    "Le joueur laissé vide ne bloque pas l'enregistrement"
  );

  // Correction + enregistrement réel
  carte.champRole.value = nomInitial;
  await choisirDansMenu("arme_sort_1_id", "Frappe héroïque");
  doc.getElementById("nom").value = "ZvZ - Groupe de test (édité)";
  doc.getElementById("statut").value = "validée";
  doc.getElementById("formulaire-compo").dispatchEvent(
    new window.Event("submit", { bubbles: true, cancelable: true })
  );
  await attendre(900);
  verifier(
    doc.getElementById("message").className.includes("succes"),
    "Enregistrement confirmé dans l'interface"
  );

  const relue = await (await fetch(`${BASE}/api/compos/1`, { headers: { cookie } })).json();
  const catalogue = await (await fetch(`${BASE}/api/catalogue`, { headers: { cookie } })).json();
  const objets = Object.fromEntries(catalogue.objets.map((o) => [o.id, o]));
  const sorts = catalogue.sorts;
  verifier(relue.nom === "ZvZ - Groupe de test (édité)", "Modification persistée en base");
  verifier(relue.statut === "validée", "Statut persisté");
  verifier(
    objets[relue.lignes[0].arme_id].nom === "Épée large",
    "L'arme choisie dans le menu est bien enregistrée"
  );
  verifier(
    sorts[relue.lignes[0].arme_sort_3_id].nom === "Coup puissant",
    "Le sort 3 imposé est enregistré tel quel"
  );
  verifier(
    relue.lignes[0].torse_passif_2_id === null,
    "Le second passif du torse en tissu n'est pas enregistré"
  );

  // --- Arme à deux mains : l'off-hand se verrouille ---
  await choisirDansMenu("offhand_id", "Bouclier");
  verifier(
    selecteur("offhand_id").valeur !== null,
    "Off-hand choisie librement avec une arme à une main"
  );
  await choisirDansMenu("arme_id", "Masse lourde");
  verifier(
    selecteur("offhand_id").valeur === null &&
      selecteur("offhand_id").querySelector(".selecteur-valeur").disabled,
    "Arme à deux mains : l'off-hand est vidée et verrouillée"
  );
  verifier(
    !carte.querySelector(".note-offhand").hidden,
    "Le formulaire explique pourquoi l'off-hand est bloquée"
  );
  await choisirDansMenu("arme_id", "Épée large");
  verifier(
    !selecteur("offhand_id").querySelector(".selecteur-valeur").disabled,
    "Revenir à une arme à une main rouvre l'off-hand"
  );

  // --- Aperçu du message Discord : le build en image ---
  doc.getElementById("bouton-apercu").dispatchEvent(new window.Event("click", { bubbles: true }));
  await attendre(900);
  const images = doc.querySelectorAll("#contenu-apercu img.image-build");
  verifier(images.length === 2, "Aperçu : une image de build par ligne");
  verifier(
    images[0].src.endsWith("/api/compos/1/lignes/0/image.png"),
    "L'aperçu pointe vers l'image du build"
  );
  verifier(
    doc.querySelector("#contenu-apercu .entete-apercu").textContent.includes("📋"),
    "L'aperçu montre l'en-tête du message Discord"
  );
  verifier(
    !doc.getElementById("contenu-apercu").textContent.includes("Épée large"),
    "L'aperçu ne décrit plus les builds en texte : l'image suffit"
  );

  // Ajout d'une ligne
  doc.getElementById("ajouter-ligne").dispatchEvent(new window.Event("click", { bubbles: true }));
  await attendre(150);
  verifier(doc.querySelectorAll(".ligne-compo").length === 3, "Ajout d'un build");
  window.close();
}

// ---------- Page nouvelle compo ----------
{
  const { doc, window, journal } = await ouvrir("/compo");
  verifier(journal.length === 0, `Nouvelle compo sans erreur JS ${journal.join(" | ")}`);
  verifier(doc.querySelectorAll(".ligne-compo").length === 1, "Une ligne vierge par défaut");
  const vierge = doc.querySelector(".ligne-compo");
  verifier(
    vierge.selecteurs.arme_id.valeur === null,
    "Nouvelle ligne : aucun objet présélectionné"
  );
  verifier(
    doc.getElementById("bouton-discord").disabled,
    "Envoi Discord désactivé tant que la compo n'est pas enregistrée"
  );
  verifier(
    doc.getElementById("bouton-importer") !== null &&
      doc.getElementById("fichier-tableur") !== null &&
      doc.querySelector('a[href="/api/compos/modele-tableur"]') !== null,
    "Import Excel et modèle proposés sur le formulaire"
  );
  window.close();
}

// ---------- Page administration ----------
{
  const { doc, window, journal } = await ouvrir("/admin");
  verifier(journal.length === 0, `Administration sans erreur JS ${journal.join(" | ")}`);
  verifier(doc.querySelectorAll("#corps-membres tr").length >= 1, "Liste des membres affichée");
  verifier(
    doc.getElementById("source-webhook").textContent.length > 0,
    "Origine du webhook indiquée à l'admin"
  );

  // Pseudo unique : les tests doivent pouvoir etre relances sur la meme base.
  const pseudoTest = `recrue${Date.now().toString().slice(-8)}`;
  doc.getElementById("nouveau-pseudo").value = pseudoTest;
  doc.getElementById("nouveau-mdp").value = "motdepasse";
  doc.getElementById("nouveau-role").value = "membre";
  doc.getElementById("formulaire-membre").dispatchEvent(
    new window.Event("submit", { bubbles: true, cancelable: true })
  );
  await attendre(800);
  verifier(
    doc.getElementById("message").className.includes("succes"),
    "Création d'un membre depuis l'interface"
  );
  const membres = await (await fetch(`${BASE}/api/membres`, { headers: { cookie } })).json();
  const cree = membres.find((m) => m.pseudo === pseudoTest);
  verifier(cree !== undefined, "Nouveau membre persisté en base");
  if (cree) {
    await fetch(`${BASE}/api/membres/${cree.id}`, { method: "DELETE", headers: { cookie } });
  }
  window.close();
}

console.log(echecs === 0 ? "\n🎉 Frontend : tous les tests sont passés." : `\n${echecs} échec(s)`);
process.exit(echecs === 0 ? 0 : 1);
