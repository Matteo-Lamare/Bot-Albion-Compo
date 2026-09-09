// Helpers reseau partages par toutes les pages.

async function appelApi(chemin, options = {}) {
  const reponse = await fetch(chemin, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (reponse.status === 401) {
    if (!location.pathname.endsWith("/")) location.href = "/";
    throw new ErreurApi("Session expiree, reconnectez-vous.", 401, []);
  }

  if (reponse.status === 204) return null;

  const type = reponse.headers.get("content-type") || "";
  const corps = type.includes("application/json") ? await reponse.json() : await reponse.text();

  if (!reponse.ok) {
    const detail = typeof corps === "string" ? corps : corps.detail;
    const erreurs = (typeof corps === "object" && corps.erreurs) || [];
    throw new ErreurApi(
      typeof detail === "string" ? detail : "Une erreur est survenue.",
      reponse.status,
      erreurs
    );
  }
  return corps;
}

class ErreurApi extends Error {
  constructor(message, statut, erreurs) {
    super(message);
    this.statut = statut;
    this.erreurs = erreurs || [];
  }
}

const api = {
  me: () => appelApi("/api/auth/me"),
  login: (pseudo, motDePasse) =>
    appelApi("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ pseudo, mot_de_passe: motDePasse }),
    }),
  logout: () => appelApi("/api/auth/logout", { method: "POST" }),
  meta: () => appelApi("/api/meta"),
  catalogue: () => appelApi("/api/catalogue"),
  membres: () => appelApi("/api/membres"),
  creerMembre: (donnees) =>
    appelApi("/api/membres", { method: "POST", body: JSON.stringify(donnees) }),
  modifierMembre: (id, donnees) =>
    appelApi(`/api/membres/${id}`, { method: "PUT", body: JSON.stringify(donnees) }),
  supprimerMembre: (id) => appelApi(`/api/membres/${id}`, { method: "DELETE" }),
  settings: () => appelApi("/api/settings"),
  majSettings: (url) =>
    appelApi("/api/settings", {
      method: "PUT",
      body: JSON.stringify({ discord_webhook_url: url }),
    }),
  compos: (filtres = {}) => {
    const params = new URLSearchParams();
    Object.entries(filtres).forEach(([cle, valeur]) => {
      if (valeur !== "" && valeur !== null && valeur !== undefined) params.append(cle, valeur);
    });
    const suffixe = params.toString() ? `?${params}` : "";
    return appelApi(`/api/compos${suffixe}`);
  },
  compo: (id) => appelApi(`/api/compos/${id}`),
  creerCompo: (donnees) =>
    appelApi("/api/compos", { method: "POST", body: JSON.stringify(donnees) }),
  modifierCompo: (id, donnees) =>
    appelApi(`/api/compos/${id}`, { method: "PUT", body: JSON.stringify(donnees) }),
  dupliquerCompo: (id) => appelApi(`/api/compos/${id}/dupliquer`, { method: "POST" }),
  supprimerCompo: (id) => appelApi(`/api/compos/${id}`, { method: "DELETE" }),
  apercuDiscord: (id) => appelApi(`/api/compos/${id}/apercu-discord`),
  envoyerDiscord: (id) => appelApi(`/api/compos/${id}/envoyer-discord`, { method: "POST" }),
  // Le navigateur pose lui-meme le Content-Type multipart (avec sa frontiere) :
  // on lui laisse la main en vidant les en-tetes par defaut.
  importerTableur: (fichier) => {
    const corps = new FormData();
    corps.append("fichier", fichier);
    return appelApi("/api/compos/importer-tableur", { method: "POST", body: corps, headers: {} });
  },
};

// --- Utilitaires d'interface ---

function afficherMessage(id, texte, categorie = "info", erreurs = []) {
  const bloc = document.getElementById(id);
  if (!bloc) return;
  bloc.className = `message visible ${categorie}`;
  bloc.innerHTML = "";
  bloc.appendChild(document.createTextNode(texte));
  if (erreurs.length) {
    const liste = document.createElement("ul");
    erreurs.forEach((erreur) => {
      const item = document.createElement("li");
      item.textContent = erreur.champ ? `${erreur.champ} : ${erreur.message}` : erreur.message;
      liste.appendChild(item);
    });
    bloc.appendChild(liste);
  }
  bloc.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function cacherMessage(id) {
  const bloc = document.getElementById(id);
  if (bloc) bloc.className = "message";
}

function formaterDate(valeur) {
  if (!valeur) return "—";
  const date = new Date(valeur.endsWith("Z") || valeur.includes("+") ? valeur : `${valeur}Z`);
  return date.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

function classeStatut(statut) {
  return { brouillon: "brouillon", "validée": "validee", "envoyée": "envoyee" }[statut] || "";
}

// Injecte l'en-tete commun et verifie la session.
async function initialiserPage(pageActive) {
  let membre;
  try {
    membre = await api.me();
  } catch (erreur) {
    location.href = "/";
    throw erreur;
  }
  const barre = document.querySelector("header.barre");
  if (barre) {
    barre.innerHTML = `
      <span class="marque">⚔️ Compos Albion</span>
      <nav>
        <a href="/bibliotheque" data-page="bibliotheque">Bibliothèque</a>
        <a href="/compo" data-page="compo">Nouvelle compo</a>
        ${membre.role === "admin" ? '<a href="/admin" data-page="admin">Administration</a>' : ""}
      </nav>
      <span class="utilisateur">${membre.pseudo} · ${membre.role}</span>
      <button class="mini" id="bouton-deconnexion">Déconnexion</button>`;
    const lien = barre.querySelector(`[data-page="${pageActive}"]`);
    if (lien) lien.classList.add("actif");
    document.getElementById("bouton-deconnexion").addEventListener("click", async () => {
      await api.logout();
      location.href = "/";
    });
  }
  return membre;
}
