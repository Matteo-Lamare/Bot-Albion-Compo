// Éditeur de compo. Le formulaire est intégralement construit à partir de
// /api/catalogue : slots, champs et sorts disponibles viennent du serveur.

let membreCourant = null;
let meta = null;
let cat = null;
const compoId = new URLSearchParams(location.search).get("id");

const ICONES_SLOTS = { arme: "⚔️", offhand: "🛡️", casque: "🪖", torse: "🥋", bottes: "🥾", cape: "🧣", monture: "🐎", potion: "🧪", nourriture: "🍲" };

function indexerCatalogue(donnees) {
  const objetsParSlot = {};
  donnees.objets.forEach((objet) => { (objetsParSlot[objet.slot] ||= []).push({ ...objet, groupe: donnees.categories[objet.categorie_id].nom }); });
  Object.values(objetsParSlot).forEach((liste) => liste.sort((a, b) => a.groupe.localeCompare(b.groupe) || a.nom.localeCompare(b.nom)));
  return {
    slots: donnees.slots, categories: donnees.categories, sorts: donnees.sorts,
    objets: Object.fromEntries(donnees.objets.map((o) => [o.id, o])), objetsParSlot,
    optionsSorts(identifiants) { return (identifiants || []).map((id) => ({ id, ...donnees.sorts[id] })); },
    pool(objet, emplacement) { return donnees.categories[objet.categorie_id].pools[emplacement] || []; },
  };
}

async function demarrer() {
  membreCourant = await initialiserPage(compoId ? null : "compo");
  const [metaDonnees, catalogue] = await Promise.all([api.meta(), api.catalogue()]);
  meta = metaDonnees; cat = indexerCatalogue(catalogue);
  remplirOptions(document.getElementById("type_contenu"), meta.types_contenu);
  remplirOptions(document.getElementById("statut"), meta.statuts);
  document.getElementById("ajouter-ligne").addEventListener("click", () => { ajouterLigne(); majCompteur(); });
  document.getElementById("tout-replier").addEventListener("click", () => basculerTout(true));
  document.getElementById("tout-deplier").addEventListener("click", () => basculerTout(false));
  document.getElementById("formulaire-compo").addEventListener("submit", enregistrer);
  document.getElementById("bouton-apercu").addEventListener("click", apercu);
  document.getElementById("bouton-discord").addEventListener("click", envoyerDiscord);
  document.getElementById("bouton-dupliquer").addEventListener("click", dupliquer);
  document.getElementById("taille_groupe").addEventListener("input", majCompteur);
  const fichier = document.getElementById("fichier-tableur");
  document.getElementById("bouton-importer").addEventListener("click", () => fichier.click());
  fichier.addEventListener("change", importerTableur);
  if (compoId) await chargerCompo(compoId);
  else { ["bouton-discord", "bouton-apercu", "bouton-dupliquer"].forEach((id) => { document.getElementById(id).disabled = true; }); ajouterLigne(); majCompteur(); }
}

function remplirOptions(select, valeurs) { select.innerHTML = ""; valeurs.forEach((valeur) => select.appendChild(new Option(valeur, valeur))); }

async function chargerCompo(id) {
  try {
    const compo = await api.compo(id);
    document.getElementById("titre-page").textContent = `Modifier « ${compo.nom} »`;
    document.getElementById("info-compo").textContent = `Auteur : ${compo.auteur_pseudo} · créée le ${formaterDate(compo.date_creation)}` + ` · modifiée le ${formaterDate(compo.date_modification)}` + (compo.date_envoi ? ` · envoyée le ${formaterDate(compo.date_envoi)}` : "");
    document.getElementById("nom").value = compo.nom; document.getElementById("type_contenu").value = compo.type_contenu;
    document.getElementById("taille_groupe").value = compo.taille_groupe; document.getElementById("statut").value = compo.statut; document.getElementById("notes").value = compo.notes || "";
    document.getElementById("lignes").innerHTML = ""; compo.lignes.forEach((ligne) => ajouterLigne(ligne, true)); majCompteur();
  } catch (erreur) { afficherMessage("message", erreur.message, "erreur", erreur.erreurs); }
}

// Construction d'une ligne et gestion des slots.
function ajouterLigne(donnees = null, replie = false) {
  const conteneur = document.getElementById("lignes"), carte = document.createElement("div"); carte.className = `ligne-compo${replie ? " replie" : ""}`; carte.selecteurs = {};
  const entete = document.createElement("div"); entete.className = "ligne-entete"; entete.innerHTML = `<span class="numero"></span><span class="resume"></span><button type="button" class="mini" data-action="monter">↑</button><button type="button" class="mini" data-action="descendre">↓</button><button type="button" class="mini" data-action="copier">⧉</button><button type="button" class="mini danger" data-action="supprimer">✕</button>`;
  entete.addEventListener("click", (evenement) => { if (evenement.target.tagName !== "BUTTON") carte.classList.toggle("replie"); });
  const corps = document.createElement("div"); corps.className = "ligne-corps";
  const blocRole = document.createElement("div"); blocRole.className = "slot"; blocRole.innerHTML = '<h3>🎮 Rôle / joueur <span class="facultatif">(facultatif)</span></h3>';
  const champRole = document.createElement("input"); champRole.className = "champ-role"; champRole.maxLength = 120; champRole.placeholder = "Ex. Tank principal — laissez vide pour un build à pourvoir"; blocRole.appendChild(champRole); corps.appendChild(blocRole); carte.champRole = champRole;
  cat.slots.forEach((slot) => corps.appendChild(creerSlot(carte, slot)));
  carte.appendChild(entete); carte.appendChild(corps); conteneur.appendChild(carte);
  if (donnees) remplirLigne(carte, donnees);
  entete.querySelector('[data-action="supprimer"]').addEventListener("click", () => { if (document.querySelectorAll(".ligne-compo").length === 1) { afficherMessage("message", "Une compo doit contenir au moins une ligne.", "erreur"); return; } carte.remove(); majCompteur(); });
  entete.querySelector('[data-action="monter"]').addEventListener("click", () => { const precedent = carte.previousElementSibling; if (precedent) conteneur.insertBefore(carte, precedent); majCompteur(); });
  entete.querySelector('[data-action="descendre"]').addEventListener("click", () => { const suivant = carte.nextElementSibling; if (suivant) conteneur.insertBefore(suivant, carte); majCompteur(); });
  entete.querySelector('[data-action="copier"]').addEventListener("click", () => { const copie = lireLigne(carte); if (copie.role_ou_joueur) copie.role_ou_joueur = `${copie.role_ou_joueur} (copie)`.slice(0, 120); ajouterLigne(copie); majCompteur(); });
  champRole.addEventListener("input", () => majResume(carte)); majOffhand(carte); majResume(carte); return carte;
}

function creerSlot(carte, slot) {
  const bloc = document.createElement("div"); bloc.className = "slot"; bloc.dataset.slot = slot.slot;
  const titre = document.createElement("h3"); titre.innerHTML = `${ICONES_SLOTS[slot.slot] || ""} ${slot.libelle}` + (slot.obligatoire ? ' <span class="obligatoire">*</span>' : ' <span class="facultatif">(facultatif)</span>'); bloc.appendChild(titre);
  const grille = document.createElement("div"); grille.className = "grille col-3"; bloc.appendChild(grille);
  const objets = cat.objetsParSlot[slot.slot] || [];
  const selecteurObjet = creerSelecteur({ options: objets, placeholder: slot.obligatoire ? "Choisir un objet…" : "Aucun", onChange: () => { majChampsSlot(carte, slot); majOffhand(carte); majResume(carte); } });
  grille.appendChild(champ(slot.libelle, selecteurObjet, slot.obligatoire)); carte.selecteurs[slot.champ] = selecteurObjet;
  if (!slot.obligatoire && objets.length) { const effacer = document.createElement("button"); effacer.type = "button"; effacer.className = "mini effacer-slot"; effacer.textContent = "Vider"; effacer.addEventListener("click", () => { selecteurObjet.valeur = null; majChampsSlot(carte, slot); majOffhand(carte); majResume(carte); }); titre.appendChild(effacer); }
  if (slot.slot === "offhand") { const note = document.createElement("p"); note.className = "note-offhand facultatif"; note.textContent = "Arme à deux mains : elle occupe aussi cet emplacement."; note.hidden = true; bloc.appendChild(note); }
  slot.champs.forEach((definition) => { const selecteur = creerSelecteur({ options: [], placeholder: "—", onChange: () => majResume(carte) }); const bloc_champ = champ(definition.libelle, selecteur, definition.obligatoire); bloc_champ.dataset.champ = definition.champ; grille.appendChild(bloc_champ); carte.selecteurs[definition.champ] = selecteur; });
  if (slot.champ_impose) { const selecteur = creerSelecteur({ options: [], placeholder: "—", verrouille: true }); const bloc_champ = champ(`${slot.champ_impose.libelle} (imposé)`, selecteur, false); bloc_champ.dataset.champ = slot.champ_impose.champ; grille.appendChild(bloc_champ); carte.selecteurs[slot.champ_impose.champ] = selecteur; }
  return bloc;
}

function majOffhand(carte) { const selecteurOffhand = carte.selecteurs.offhand_id; if (!selecteurOffhand) return; const armeId = carte.selecteurs.arme_id?.valeur; const deuxMains = Boolean(armeId && cat.objets[armeId]?.deux_mains); if (deuxMains && selecteurOffhand.valeur) selecteurOffhand.valeur = null; selecteurOffhand.definirVerrou(deuxMains); const bloc = selecteurOffhand.closest(".slot"); bloc.classList.toggle("verrouille", deuxMains); bloc.querySelector(".note-offhand").hidden = !deuxMains; const effacer = bloc.querySelector(".effacer-slot"); if (effacer) effacer.hidden = deuxMains; }
function champ(libelle, selecteur, obligatoire) { const bloc = document.createElement("div"); bloc.innerHTML = `<label>${libelle}${obligatoire ? ' <span class="obligatoire">*</span>' : ""}</label>`; bloc.appendChild(selecteur); return bloc; }
function majChampsSlot(carte, slot, valeurs = null) { const objetId = carte.selecteurs[slot.champ].valeur, objet = objetId ? cat.objets[objetId] : null; slot.champs.forEach((definition) => { const selecteur = carte.selecteurs[definition.champ], bloc = selecteur.parentElement, autorises = objet ? cat.pool(objet, definition.emplacement) : []; bloc.hidden = autorises.length === 0; let valeur = valeurs ? valeurs[definition.champ] : undefined; if (valeur === undefined || !autorises.includes(valeur)) { if (definition.emplacement === "sort" && autorises.includes(objet?.sort_defaut_id)) valeur = objet.sort_defaut_id; else if (definition.obligatoire && autorises.length) valeur = autorises[0]; else valeur = null; } selecteur.definirOptions(cat.optionsSorts(autorises), valeur); }); if (slot.champ_impose) { const selecteur = carte.selecteurs[slot.champ_impose.champ], impose = objet?.sort_impose_id ?? null; selecteur.definirOptions(impose ? cat.optionsSorts([impose]) : [], impose); selecteur.parentElement.hidden = !impose; } }
function remplirLigne(carte, donnees) { carte.ligneId = donnees.id ?? null; carte.champRole.value = donnees.role_ou_joueur || ""; cat.slots.forEach((slot) => { carte.selecteurs[slot.champ].valeur = donnees[slot.champ] ?? null; majChampsSlot(carte, slot, donnees); }); majOffhand(carte); majResume(carte); }
