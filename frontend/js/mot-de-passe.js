initialiserPage("mot-de-passe").catch(() => {});

document.getElementById("formulaire-mot-de-passe").addEventListener("submit", async (evenement) => {
  evenement.preventDefault();
  cacherMessage("message");

  const ancien = document.getElementById("ancien-mot-de-passe").value;
  const nouveau = document.getElementById("nouveau-mot-de-passe").value;
  const confirmation = document.getElementById("confirmation-mot-de-passe").value;
  const bouton = evenement.target.querySelector("button");

  if (nouveau !== confirmation) {
    afficherMessage("message", "Les deux nouveaux mots de passe ne correspondent pas.", "erreur");
    return;
  }
  if (nouveau.length < 6) {
    afficherMessage("message", "Le nouveau mot de passe doit contenir au moins 6 caractères.", "erreur");
    return;
  }

  bouton.disabled = true;
  try {
    await api.changerMotDePasse(ancien, nouveau);
    evenement.target.reset();
    afficherMessage("message", "Votre mot de passe a été modifié avec succès.", "succes");
  } catch (erreur) {
    afficherMessage("message", erreur.message, "erreur", erreur.erreurs);
  } finally {
    bouton.disabled = false;
  }
});
