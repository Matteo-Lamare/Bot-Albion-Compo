// Éditeur de compo. Le formulaire est intégralement construit à partir de
// /api/catalogue : slots, champs et sorts disponibles viennent du serveur, qui
// reste seul juge de la validité (cf. backend/validation.py).

let membreCourant = null;
let meta = null;
let cat = null; // catalogue indexé
const compoId = new URLSearchParams(location.search).get("id");

const ICONES_SLOTS = {
  arme: "⚔️", offhand: "🛡️", casque: "🪖", torse: "🥋", bottes: "🥾",
  cape: "🧣", monture: "🐎", potion: "🧪", nourriture: "🍲",
};

// --- Indexation du catalogue ------------------------------------------------

function indexerCatalogue(donnees) {
  const objetsParSlot = {};
  donnees.objets.forEach((objet) => {
    (objetsParSlot[objet.slot] ||= []).push({
      ...objet,
      groupe: donnees.categories[objet.categorie_id].nom,
    });
  });
  // Regroupement par catégorie dans la liste déroulante.
  Object.values(objetsParSlot).forEach((liste) =>
    liste.sort((a, b) => a.groupe.localeCompare(b.groupe) || a.nom.localeCompare(b.nom))
  );
  return {
    slots: donnees.slots,
    categories: donnees.categories,
    sorts: donnees.sorts,
    objets: Object.fromEntries(donnees.objets.map((o) => [o.id, o])),
    objetsParSlot,
    optionsSorts(identifiants) {
      return (identifiants || []).map((id) => ({ id, ...donnees.sorts[id] }));
    },
    pool(objet, emplacement) {
      return donnees.categories[objet.categorie_id].pools[emplacement] || [];
    },
  };
}

// --- Initialisation ---------------------------------------------------------

async function demarrer() {
  membreCourant = await initialiserPage(compoId ? null : "compo");
  const [metaDonnees, catalogue] = await Promise.all([api.meta(), api.catalogue()]);
  meta = metaDonnees;
  cat = indexerCatalogue(catalogue);

  remplirOptions(document.getElementById("type_contenu"), meta.types_contenu);
  remplirOptions(document.getElementById("statut"), meta.statuts);

  document.getElementById("ajouter-ligne").addEventListener("click", () => {
    ajouterLigne();
    majCompteur();
  });
  document.getElementById("tout-replier").addEventListener("click", () => basculerTout(true));
  document.getElementById("tout-deplier").addEventListener("click", () => basculerTout(false));
  document.getElementById("formulaire-compo").addEventListener("submit", enregistrer);
  document.getElementById("bouton-apercu").addEventListener("click", apercu);
  document.getElementById("bouton-discord").addEventListener("click", envoyerDiscord);
  document.getElementById("bouton-dupliquer").addEventListener("click", dupliquer);
  document.getElementById("taille_groupe").addEventListener("input", majCompteur);

  if (compoId) {
    await chargerCompo(compoId);
  } else {
    ["bouton-discord", "bouton-apercu", "bouton-dupliquer"].forEach((id) => {
      document.getElementById(id).disabled = true;
    });
    ajouterLigne();
    majCompteur();
  }
}

function remplirOptions(select, valeurs) {
  select.innerHTML = "";
  valeurs.forEach((valeur) => select.appendChild(new Option(valeur, valeur)));
}

async function chargerCompo(id) {
  try {
    const compo = await api.compo(id);
    document.getElementById("titre-page").textContent = `Modifier « ${compo.nom} »`;
    document.getElementById("info-compo").textContent =
      `Auteur : ${compo.auteur_pseudo} · créée le ${formaterDate(compo.date_creation)}` +
      ` · modifiée le ${formaterDate(compo.date_modification)}` +
      (compo.date_envoi ? ` · envoyée le ${formaterDate(compo.date_envoi)}` : "");
    document.getElementById("nom").value = compo.nom;
    document.getElementById("type_contenu").value = compo.type_contenu;
    document.getElementById("taille_groupe").value = compo.taille_groupe;
    document.getElementById("statut").value = compo.statut;
    document.getElementById("notes").value = compo.notes || "";

    document.getElementById("lignes").innerHTML = "";
    compo.lignes.forEach((ligne) => ajouterLigne(ligne, true));
    majCompteur();

    if (membreCourant.role !== "admin" && compo.auteur_id !== membreCourant.id) {
      afficherMessage(
        "message",
        "Vous n'êtes pas l'auteur de cette compo : vous pouvez la consulter, la dupliquer et l'envoyer, mais pas l'enregistrer.",
        "info"
      );
      document.querySelector("button[type=submit]").disabled = true;
    }
  } catch (erreur) {
    afficherMessage("message", erreur.message, "erreur", erreur.erreurs);
  }
}

// --- Construction d'une ligne ----------------------------------------------

function ajouterLigne(donnees = null, replie = false) {
  const conteneur = document.getElementById("lignes");
  const carte = document.createElement("div");
  carte.className = `ligne-compo${replie ? " replie" : ""}`;
  carte.selecteurs = {};   // champ de LigneCompo -> sélecteur

  const entete = document.createElement("div");
  entete.className = "ligne-entete";
  entete.innerHTML = `
    <span class="numero"></span>
    <span class="resume"></span>
    <button type="button" class="mini" data-action="monter" title="Monter">↑</button>
    <button type="button" class="mini" data-action="descendre" title="Descendre">↓</button>
    <button type="button" class="mini" data-action="copier" title="Dupliquer la ligne">⧉</button>
    <button type="button" class="mini danger" data-action="supprimer" title="Supprimer">✕</button>`;
  entete.addEventListener("click", (evenement) => {
    if (evenement.target.tagName !== "BUTTON") carte.classList.toggle("replie");
  });

  const corps = document.createElement("div");
  corps.className = "ligne-corps";

  // Nommer le build est facultatif : sans nom, il s'affiche « Build #n » et
  // attend qu'un joueur s'inscrive dessus.
  const blocRole = document.createElement("div");
  blocRole.className = "slot";
  blocRole.innerHTML =
    '<h3>🎮 Rôle / joueur <span class="facultatif">(facultatif)</span></h3>';
  const champRole = document.createElement("input");
  champRole.className = "champ-role";
  champRole.maxLength = 120;
  champRole.placeholder = "Ex. Tank principal — laissez vide pour un build à pourvoir";
  blocRole.appendChild(champRole);
  corps.appendChild(blocRole);
  carte.champRole = champRole;

  corps.appendChild(creerBlocInscription(carte));

  cat.slots.forEach((slot) => corps.appendChild(creerSlot(carte, slot)));

  carte.appendChild(entete);
  carte.appendChild(corps);
  conteneur.appendChild(carte);

  if (donnees) remplirLigne(carte, donnees);

  entete.querySelector('[data-action="supprimer"]').addEventListener("click", () => {
    if (document.querySelectorAll(".ligne-compo").length === 1) {
      afficherMessage("message", "Une compo doit contenir au moins une ligne.", "erreur");
      return;
    }
    carte.remove();
    majCompteur();
  });
  entete.querySelector('[data-action="monter"]').addEventListener("click", () => {
    const precedent = carte.previousElementSibling;
    if (precedent) conteneur.insertBefore(carte, precedent);
    majCompteur();
  });
  entete.querySelector('[data-action="descendre"]').addEventListener("click", () => {
    const suivant = carte.nextElementSibling;
    if (suivant) conteneur.insertBefore(suivant, carte);
    majCompteur();
  });
  entete.querySelector('[data-action="copier"]').addEventListener("click", () => {
    const copie = lireLigne(carte);
    if (copie.role_ou_joueur) {
      copie.role_ou_joueur = `${copie.role_ou_joueur} (copie)`.slice(0, 120);
    }
    ajouterLigne(copie);
    majCompteur();
  });

  champRole.addEventListener("input", () => majResume(carte));
  majResume(carte);
  return carte;
}

// --- Inscriptions : qui joue quel build ------------------------------------

function creerBlocInscription(carte) {
  const bloc = document.createElement("div");
  bloc.className = "slot inscriptions";
  // Tant que le build n'est pas enregistré, il n'y a rien sur quoi s'inscrire :
  // majInscriptions() révèle le bloc dès que la ligne a un identifiant.
  bloc.hidden = true;
  bloc.innerHTML = '<h3>🙋 Inscrits <span class="badge compte">0</span></h3>';

  const liste = document.createElement("div");
  liste.className = "liste-inscrits";
  bloc.appendChild(liste);

  const bouton = document.createElement("button");
  bouton.type = "button";
  bouton.className = "mini";
  bouton.addEventListener("click", () => basculerInscription(carte));
  bloc.appendChild(bouton);

  carte.blocInscription = bloc;
  carte.listeInscrits = liste;
  carte.boutonInscription = bouton;
  carte.inscrits = [];
  return bloc;
}

function estInscrit(carte) {
  return carte.inscrits.some((inscrit) => inscrit.membre_id === membreCourant.id);
}

function majInscriptions(carte, inscrits) {
  carte.inscrits = inscrits || [];
  carte.blocInscription.hidden = !compoId || !carte.ligneId;
  carte.querySelector(".compte").textContent = carte.inscrits.length;
  carte.listeInscrits.innerHTML = "";
  if (!carte.inscrits.length) {
    const vide = document.createElement("span");
    vide.className = "facultatif";
    vide.textContent = "Personne pour l'instant — ce build est à pourvoir.";
    carte.listeInscrits.appendChild(vide);
  }
  carte.inscrits.forEach((inscrit) => {
    const pastille = document.createElement("span");
    pastille.className = "badge inscrit";
    pastille.textContent = inscrit.pseudo;
    carte.listeInscrits.appendChild(pastille);
  });
  carte.boutonInscription.textContent = estInscrit(carte)
    ? "Me retirer de ce build"
    : "Je joue ce build";
  carte.boutonInscription.classList.toggle("principal", !estInscrit(carte));
  majResume(carte);
}

async function basculerInscription(carte) {
  cacherMessage("message");
  carte.boutonInscription.disabled = true;
  try {
    const retrait = estInscrit(carte);
    const resultat = retrait
      ? await api.desinscrire(compoId, carte.ligneId)
      : await api.inscrire(compoId, carte.ligneId);
    appliquerInscriptions(resultat, retrait);
  } catch (erreur) {
    afficherMessage("message", erreur.message, "erreur", erreur.erreurs);
  } finally {
    carte.boutonInscription.disabled = false;
  }
}

/** Un membre ne tient qu'un build par compo : toutes les cartes sont rafraîchies. */
function appliquerInscriptions(resultat, retrait) {
  const parLigne = new Map(resultat.lignes.map((ligne) => [ligne.ligne_id, ligne.inscrits]));
  document.querySelectorAll(".ligne-compo").forEach((carte) => {
    majInscriptions(carte, parLigne.get(carte.ligneId) || []);
  });
  afficherMessage(
    "message",
    (retrait ? "Inscription retirée." : "Inscription enregistrée.") +
      (resultat.discord_mis_a_jour
        ? " Le message Discord a été mis à jour."
        : " (Le message Discord sera à jour au prochain envoi.)"),
    "succes"
  );
}

function creerSlot(carte, slot) {
  const bloc = document.createElement("div");
  bloc.className = "slot";
  bloc.dataset.slot = slot.slot;

  const titre = document.createElement("h3");
  titre.innerHTML =
    `${ICONES_SLOTS[slot.slot] || ""} ${slot.libelle}` +
    (slot.obligatoire ? ' <span class="obligatoire">*</span>' : ' <span class="facultatif">(facultatif)</span>');
  bloc.appendChild(titre);

  const grille = document.createElement("div");
  grille.className = "grille col-3";
  bloc.appendChild(grille);

  // Sélecteur d'objet
  const objets = cat.objetsParSlot[slot.slot] || [];
  const selecteurObjet = creerSelecteur({
    options: objets,
    placeholder: slot.obligatoire ? "Choisir un objet…" : "Aucun",
    onChange: () => {
      majChampsSlot(carte, slot);
      majResume(carte);
    },
  });
  grille.appendChild(champ(slot.libelle, selecteurObjet, slot.obligatoire));
  carte.selecteurs[slot.champ] = selecteurObjet;

  if (!slot.obligatoire && objets.length) {
    const effacer = document.createElement("button");
    effacer.type = "button";
    effacer.className = "mini effacer-slot";
    effacer.textContent = "Vider";
    effacer.addEventListener("click", () => {
      selecteurObjet.valeur = null;
      majChampsSlot(carte, slot);
      majResume(carte);
    });
    titre.appendChild(effacer);
  }

  // Sorts choisis dans le pool de la catégorie
  slot.champs.forEach((definition) => {
    const selecteur = creerSelecteur({
      options: [],
      placeholder: "—",
      onChange: () => majResume(carte),
    });
    const bloc_champ = champ(definition.libelle, selecteur, definition.obligatoire);
    bloc_champ.dataset.champ = definition.champ;
    grille.appendChild(bloc_champ);
    carte.selecteurs[definition.champ] = selecteur;
  });

  // Sort imposé par l'objet : affiché, verrouillé
  if (slot.champ_impose) {
    const selecteur = creerSelecteur({ options: [], placeholder: "—", verrouille: true });
    const bloc_champ = champ(`${slot.champ_impose.libelle} (imposé)`, selecteur, false);
    bloc_champ.dataset.champ = slot.champ_impose.champ;
    grille.appendChild(bloc_champ);
    carte.selecteurs[slot.champ_impose.champ] = selecteur;
  }

  return bloc;
}

function champ(libelle, selecteur, obligatoire) {
  const bloc = document.createElement("div");
  const etoile = obligatoire ? ' <span class="obligatoire">*</span>' : "";
  bloc.innerHTML = `<label>${libelle}${etoile}</label>`;
  bloc.appendChild(selecteur);
  return bloc;
}

/** Met à jour les sorts proposés pour un slot après changement d'objet. */
function majChampsSlot(carte, slot, valeurs = null) {
  const objetId = carte.selecteurs[slot.champ].valeur;
  const objet = objetId ? cat.objets[objetId] : null;

  slot.champs.forEach((definition) => {
    const selecteur = carte.selecteurs[definition.champ];
    const bloc = selecteur.parentElement;
    const autorises = objet ? cat.pool(objet, definition.emplacement) : [];
    // Un pool vide signifie que la catégorie ne propose rien ici (torse sans
    // second passif, par exemple) : le champ disparaît.
    bloc.hidden = autorises.length === 0;

    // Un champ obligatoire n'est jamais laissé vide : on retombe sur le sort natif
    // de l'armure, sinon sur le premier choix de la catégorie. L'utilisateur voit
    // toujours ce qui est retenu et peut en changer.
    let valeur = valeurs ? valeurs[definition.champ] : undefined;
    if (valeur === undefined || !autorises.includes(valeur)) {
      if (definition.emplacement === "sort" && autorises.includes(objet?.sort_defaut_id)) {
        valeur = objet.sort_defaut_id;
      } else if (definition.obligatoire && autorises.length) {
        valeur = autorises[0];
      } else {
        valeur = null;
      }
    }
    selecteur.definirOptions(cat.optionsSorts(autorises), valeur);
  });

  if (slot.champ_impose) {
    const selecteur = carte.selecteurs[slot.champ_impose.champ];
    const impose = objet?.sort_impose_id ?? null;
    selecteur.definirOptions(impose ? cat.optionsSorts([impose]) : [], impose);
    selecteur.parentElement.hidden = !impose;
  }
}

function remplirLigne(carte, donnees) {
  carte.ligneId = donnees.id ?? null;
  carte.champRole.value = donnees.role_ou_joueur || "";
  majInscriptions(carte, donnees.inscriptions || []);
  cat.slots.forEach((slot) => {
    carte.selecteurs[slot.champ].valeur = donnees[slot.champ] ?? null;
    majChampsSlot(carte, slot, donnees);
  });
  majResume(carte);
}

function lireLigne(carte) {
  const donnees = { role_ou_joueur: carte.champRole.value.trim() };
  Object.entries(carte.selecteurs).forEach(([champ, selecteur]) => {
    donnees[champ] = selecteur.valeur ?? null;
  });
  return donnees;
}

function majResume(carte) {
  const donnees = lireLigne(carte);
  const nom = (identifiant) => (identifiant ? cat.objets[identifiant]?.nom : null);
  const morceaux = [donnees.arme_id, donnees.casque_id, donnees.torse_id, donnees.bottes_id]
    .map(nom)
    .filter(Boolean)
    .join(" · ");
  carte.querySelector(".resume").textContent =
    `${donnees.role_ou_joueur || libelleParDefaut(carte)}${morceaux ? " — " + morceaux : ""}`;
}

/** « Build #3 » : ce que le serveur affichera aussi pour une ligne sans joueur. */
function libelleParDefaut(carte) {
  const rang = [...document.querySelectorAll(".ligne-compo")].indexOf(carte);
  return `Build #${rang + 1}`;
}

function majCompteur() {
  const cartes = document.querySelectorAll(".ligne-compo");
  cartes.forEach((carte, index) => {
    carte.querySelector(".numero").textContent = `#${index + 1}`;
  });
  const taille = parseInt(document.getElementById("taille_groupe").value, 10);
  const compteur = document.getElementById("compteur-lignes");
  compteur.textContent = `${cartes.length} ligne(s)`;
  compteur.title = cartes.length === taille ? "" : "Différent de la taille de groupe annoncée";
  compteur.style.color = cartes.length === taille ? "" : "var(--or)";
}

function basculerTout(replie) {
  document.querySelectorAll(".ligne-compo").forEach((carte) => {
    carte.classList.toggle("replie", replie);
  });
}

// --- Validation côté client (doublon de celle du serveur) -------------------

function validerFormulaire() {
  const erreurs = [];
  document.querySelectorAll(".erreur").forEach((champ) => champ.classList.remove("erreur"));

  document.querySelectorAll(".ligne-compo").forEach((carte, index) => {
    const numero = index + 1;
    const signaler = (element, libelle, message) => {
      element.classList.add("erreur");
      erreurs.push({ champ: `Ligne ${numero} · ${libelle}`, message });
      carte.classList.remove("replie");
    };

    cat.slots.forEach((slot) => {
      const selecteurObjet = carte.selecteurs[slot.champ];
      if (!selecteurObjet.valeur) {
        if (slot.obligatoire) signaler(selecteurObjet, slot.libelle, "objet obligatoire");
        return;
      }
      slot.champs.forEach((definition) => {
        const selecteur = carte.selecteurs[definition.champ];
        if (definition.obligatoire && !selecteur.parentElement.hidden && !selecteur.valeur) {
          signaler(selecteur, `${slot.libelle} · ${definition.libelle}`, "choix obligatoire");
        }
      });
    });

    const donnees = lireLigne(carte);
    if (donnees.torse_passif_1_id && donnees.torse_passif_1_id === donnees.torse_passif_2_id) {
      signaler(carte.selecteurs.torse_passif_2_id, "Torse · Passif 2",
        "les deux passifs doivent être différents");
    }
  });

  return erreurs;
}

function lireFormulaire() {
  return {
    nom: document.getElementById("nom").value.trim(),
    type_contenu: document.getElementById("type_contenu").value,
    taille_groupe: parseInt(document.getElementById("taille_groupe").value, 10),
    statut: document.getElementById("statut").value,
    notes: document.getElementById("notes").value.trim() || null,
    lignes: [...document.querySelectorAll(".ligne-compo")].map((carte, index) => ({
      ...lireLigne(carte),
      ordre: index,
    })),
  };
}

// --- Actions ----------------------------------------------------------------

async function enregistrer(evenement) {
  evenement.preventDefault();
  cacherMessage("message");

  const erreurs = validerFormulaire();
  if (erreurs.length) {
    afficherMessage("message", "Corrigez les champs suivants :", "erreur", erreurs);
    return;
  }

  const donnees = lireFormulaire();
  const bouton = evenement.target.querySelector("button[type=submit]");
  bouton.disabled = true;
  try {
    const compo = compoId
      ? await api.modifierCompo(compoId, donnees)
      : await api.creerCompo(donnees);
    if (!compoId) {
      location.href = `/compo?id=${compo.id}`;
      return;
    }
    // Les lignes sont réécrites en base : on récupère leurs nouveaux
    // identifiants (les inscrits, eux, suivent le rang du build).
    const cartes = [...document.querySelectorAll(".ligne-compo")];
    compo.lignes.forEach((ligne, index) => {
      if (!cartes[index]) return;
      cartes[index].ligneId = ligne.id;
      majInscriptions(cartes[index], ligne.inscriptions || []);
    });
    afficherMessage("message", "Compo enregistrée.", "succes");
    document.getElementById("info-compo").textContent =
      `Auteur : ${compo.auteur_pseudo} · modifiée le ${formaterDate(compo.date_modification)}`;
  } catch (erreur) {
    afficherMessage("message", erreur.message, "erreur", traduireErreurs(erreur.erreurs));
  } finally {
    bouton.disabled = false;
  }
}

function traduireErreurs(erreurs) {
  // "lignes.3.arme_sort_1_id" -> "Ligne 4 · arme_sort_1"
  return (erreurs || []).map((erreur) => {
    const morceaux = (erreur.champ || "").split(".");
    if (morceaux[0] === "lignes" && morceaux.length >= 2) {
      const champ = (morceaux.slice(2).join(".") || "ligne").replace(/_id$/, "");
      return { champ: `Ligne ${parseInt(morceaux[1], 10) + 1} · ${champ}`, message: erreur.message };
    }
    return erreur;
  });
}

async function apercu() {
  cacherMessage("message");
  try {
    const resultat = await api.apercuDiscord(compoId);
    const zone = document.getElementById("zone-apercu");
    const contenu = document.getElementById("contenu-apercu");
    contenu.innerHTML = "";
    resultat.apercu.forEach((champApercu) => {
      const bloc = document.createElement("div");
      bloc.className = "apercu";
      const titre = document.createElement("div");
      titre.className = "titre-champ";
      titre.textContent = champApercu.titre;
      bloc.appendChild(titre);

      // L'image est celle qui partira en pièce jointe sur Discord.
      if (resultat.images_disponibles) {
        const image = document.createElement("img");
        image.className = "image-build";
        image.loading = "lazy";
        image.alt = `Build ${champApercu.titre}`;
        image.src = champApercu.image;
        bloc.appendChild(image);
      }

      const corps = document.createElement("div");
      corps.textContent = champApercu.corps;
      bloc.appendChild(corps);

      const inscrits = document.createElement("div");
      inscrits.className = "titre-champ";
      inscrits.textContent = champApercu.inscrits.length
        ? `🙋 Inscrits (${champApercu.inscrits.length}) : ${champApercu.inscrits.join(", ")}`
        : "🙋 Personne pour l'instant";
      bloc.appendChild(inscrits);

      contenu.appendChild(bloc);
    });
    zone.hidden = false;
    zone.scrollIntoView({ behavior: "smooth" });
  } catch (erreur) {
    afficherMessage("message", erreur.message, "erreur", erreur.erreurs);
  }
}

async function envoyerDiscord() {
  if (!confirm("Envoyer cette compo sur le salon Discord ?")) return;
  cacherMessage("message");
  const bouton = document.getElementById("bouton-discord");
  bouton.disabled = true;
  try {
    const resultat = await api.envoyerDiscord(compoId);
    afficherMessage(
      "message",
      `Compo envoyée sur Discord : ${resultat.messages_envoyes} message(s), ` +
        `${resultat.images_jointes} image(s) de build. Statut : ${resultat.statut}, ` +
        `le ${formaterDate(resultat.date_envoi)}.`,
      "succes"
    );
    document.getElementById("statut").value = resultat.statut;
  } catch (erreur) {
    afficherMessage("message", erreur.message, "erreur", erreur.erreurs);
  } finally {
    bouton.disabled = false;
  }
}

async function dupliquer() {
  try {
    const copie = await api.dupliquerCompo(compoId);
    location.href = `/compo?id=${copie.id}`;
  } catch (erreur) {
    afficherMessage("message", erreur.message, "erreur", erreur.erreurs);
  }
}

demarrer();
