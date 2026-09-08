// Page de connexion : si une session est deja active, on file a la bibliotheque.
api.me().then(() => { location.href = "/bibliotheque"; }).catch(() => {});

document.getElementById("formulaire-connexion").addEventListener("submit", async (evenement) => {
  evenement.preventDefault();
  cacherMessage("message");
  const bouton = evenement.target.querySelector("button");
  bouton.disabled = true;
  try {
    await api.login(
      document.getElementById("pseudo").value,
      document.getElementById("mot_de_passe").value
    );
    location.href = "/bibliotheque";
  } catch (erreur) {
    afficherMessage("message", erreur.message, "erreur");
    bouton.disabled = false;
  }
});
