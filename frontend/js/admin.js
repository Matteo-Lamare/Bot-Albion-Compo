// Administration : gestion des membres.

let membreCourant = null;

async function demarrer() {
  membreCourant = await initialiserPage("admin");
  if (membreCourant.role !== "admin") { location.href = "/bibliotheque"; return; }
  const meta = await api.meta();
  const select = document.getElementById("nouveau-role");
  meta.roles.forEach((role) => select.appendChild(new Option(role, role)));
  select.value = "membre";
  document.getElementById("formulaire-membre").addEventListener("submit", creerMembre);
  await chargerMembres();
}

async function creerMembre(evenement) {
  evenement.preventDefault(); cacherMessage("message");
  try {
    await api.creerMembre({ pseudo: document.getElementById("nouveau-pseudo").value.trim(), mot_de_passe: document.getElementById("nouveau-mdp").value, role: document.getElementById("nouveau-role").value });
    evenement.target.reset(); document.getElementById("nouveau-role").value = "membre";
    afficherMessage("message", "Membre créé.", "succes"); await chargerMembres();
  } catch (erreur) { afficherMessage("message", erreur.message, "erreur", erreur.erreurs); }
}

async function chargerMembres() {
  const membres = await api.membres(), corps = document.getElementById("corps-membres"); corps.innerHTML = "";
  membres.forEach((membre) => {
    const ligne = document.createElement("tr");
    ligne.innerHTML = `<td>${echapper(membre.pseudo)}</td><td><span class="badge">${membre.role}</span></td><td>${membre.actif ? "✅" : "⛔"}</td><td>${formaterDate(membre.date_creation)}</td><td class="actions"></td>`;
    const cellule = ligne.querySelector("td.actions");
    if (membre.id !== membreCourant.id) {
      cellule.appendChild(bouton(membre.actif ? "Désactiver" : "Réactiver", "mini", () => modifier(membre.id, { actif: !membre.actif })));
      cellule.appendChild(bouton(membre.role === "admin" ? "→ membre" : "→ admin", "mini", () => modifier(membre.id, { role: membre.role === "admin" ? "membre" : "admin" })));
      cellule.appendChild(bouton("Supprimer", "mini danger", () => supprimer(membre)));
    }
    cellule.appendChild(bouton("Mot de passe", "mini", () => changerMotDePasse(membre)));
    corps.appendChild(ligne);
  });
}
function bouton(libelle, classes, action) { const element = document.createElement("button"); element.className = classes; element.textContent = libelle; element.addEventListener("click", action); return element; }
function echapper(texte) { const noeud = document.createElement("span"); noeud.textContent = texte ?? ""; return noeud.innerHTML; }
async function modifier(id, donnees) { cacherMessage("message"); try { await api.modifierMembre(id, donnees); await chargerMembres(); afficherMessage("message", "Membre mis à jour.", "succes"); } catch (erreur) { afficherMessage("message", erreur.message, "erreur", erreur.erreurs); } }
async function changerMotDePasse(membre) { const motDePasse = prompt(`Nouveau mot de passe pour ${membre.pseudo} (6 caractères minimum) :`); if (motDePasse) await modifier(membre.id, { mot_de_passe: motDePasse }); }
async function supprimer(membre) { if (!confirm(`Supprimer le membre ${membre.pseudo} ?`)) return; try { await api.supprimerMembre(membre.id); await chargerMembres(); afficherMessage("message", "Membre supprimé.", "succes"); } catch (erreur) { afficherMessage("message", erreur.message, "erreur", erreur.erreurs); } }

demarrer();
