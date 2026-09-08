// Bibliotheque : liste filtrable + actions (ouvrir, dupliquer, envoyer, supprimer).

let membreCourant = null;

async function demarrer() {
  membreCourant = await initialiserPage("bibliotheque");

  const [meta, membres] = await Promise.all([api.meta(), api.membres()]);
  remplirSelect("filtre-type", meta.types_contenu);
  remplirSelect("filtre-statut", meta.statuts);
  remplirSelect(
    "filtre-auteur",
    membres.map((membre) => ({ valeur: membre.id, libelle: membre.pseudo }))
  );

  const champs = [
    "filtre-type", "filtre-auteur", "filtre-statut",
    "filtre-debut", "filtre-fin", "filtre-recherche",
  ];
  champs.forEach((id) => {
    const element = document.getElementById(id);
    element.addEventListener(element.tagName === "INPUT" && element.type === "text" ? "input" : "change", rafraichir);
  });
  document.getElementById("filtre-recherche").addEventListener("input", debounce(rafraichir, 250));
  document.getElementById("bouton-reinitialiser").addEventListener("click", () => {
    champs.forEach((id) => { document.getElementById(id).value = ""; });
    rafraichir();
  });

  await rafraichir();
}

function debounce(fonction, delai) {
  let minuteur;
  return (...args) => {
    clearTimeout(minuteur);
    minuteur = setTimeout(() => fonction(...args), delai);
  };
}

function remplirSelect(id, valeurs) {
  const select = document.getElementById(id);
  valeurs.forEach((valeur) => {
    const option = document.createElement("option");
    option.value = typeof valeur === "object" ? valeur.valeur : valeur;
    option.textContent = typeof valeur === "object" ? valeur.libelle : valeur;
    select.appendChild(option);
  });
}

async function rafraichir() {
  const filtres = {
    type_contenu: document.getElementById("filtre-type").value,
    auteur_id: document.getElementById("filtre-auteur").value,
    statut: document.getElementById("filtre-statut").value,
    date_debut: document.getElementById("filtre-debut").value,
    date_fin: document.getElementById("filtre-fin").value,
    recherche: document.getElementById("filtre-recherche").value,
  };
  try {
    const compos = await api.compos(filtres);
    afficherCompos(compos);
  } catch (erreur) {
    afficherMessage("message", erreur.message, "erreur", erreur.erreurs);
  }
}

function afficherCompos(compos) {
  const corps = document.getElementById("corps-table");
  corps.innerHTML = "";
  document.getElementById("vide").hidden = compos.length > 0;

  compos.forEach((compo) => {
    const modifiable = membreCourant.role === "admin" || compo.auteur_id === membreCourant.id;
    const ligne = document.createElement("tr");
    ligne.innerHTML = `
      <td><a href="/compo?id=${compo.id}">${echapper(compo.nom)}</a></td>
      <td>${echapper(compo.type_contenu)}</td>
      <td>${compo.taille_groupe}</td>
      <td>${compo.nb_lignes}</td>
      <td>${echapper(compo.auteur_pseudo || "—")}</td>
      <td><span class="badge ${classeStatut(compo.statut)}">${echapper(compo.statut)}</span></td>
      <td>${formaterDate(compo.date_modification)}</td>
      <td>${formaterDate(compo.date_envoi)}</td>
      <td class="actions"></td>`;

    const cellule = ligne.querySelector("td.actions");
    cellule.appendChild(bouton("Dupliquer", "mini", () => dupliquer(compo.id)));
    cellule.appendChild(bouton("Discord", "mini discord", () => envoyer(compo)));
    if (modifiable) {
      cellule.appendChild(bouton("Supprimer", "mini danger", () => supprimer(compo)));
    }
    corps.appendChild(ligne);
  });
}

function bouton(libelle, classes, action) {
  const element = document.createElement("button");
  element.className = classes;
  element.textContent = libelle;
  element.addEventListener("click", action);
  return element;
}

function echapper(texte) {
  const noeud = document.createElement("span");
  noeud.textContent = texte ?? "";
  return noeud.innerHTML;
}

async function dupliquer(id) {
  try {
    const copie = await api.dupliquerCompo(id);
    afficherMessage("message", `Compo dupliquée : « ${copie.nom} ».`, "succes");
    await rafraichir();
  } catch (erreur) {
    afficherMessage("message", erreur.message, "erreur", erreur.erreurs);
  }
}

async function envoyer(compo) {
  if (!confirm(`Envoyer « ${compo.nom} » sur Discord ?`)) return;
  try {
    const resultat = await api.envoyerDiscord(compo.id);
    afficherMessage(
      "message",
      `« ${compo.nom} » envoyée sur Discord (${resultat.messages_envoyes} message(s)) le ${formaterDate(resultat.date_envoi)}.`,
      "succes"
    );
    await rafraichir();
  } catch (erreur) {
    afficherMessage("message", erreur.message, "erreur", erreur.erreurs);
  }
}

async function supprimer(compo) {
  if (!confirm(`Supprimer définitivement « ${compo.nom} » ?`)) return;
  try {
    await api.supprimerCompo(compo.id);
    afficherMessage("message", "Compo supprimée.", "succes");
    await rafraichir();
  } catch (erreur) {
    afficherMessage("message", erreur.message, "erreur", erreur.erreurs);
  }
}

demarrer();
