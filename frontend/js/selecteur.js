// Menu déroulant avec recherche par nom et vignette de l'objet / du sort.
// Utilisé pour tous les slots du formulaire de compo.

const MAX_RESULTATS = 60;

function sansAccents(texte) {
  return (texte || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function creerVignette(url, taille = 26) {
  const image = document.createElement("img");
  image.className = "vignette";
  image.width = taille;
  image.height = taille;
  image.loading = "lazy";
  image.alt = "";
  if (url) image.src = `${url}?size=${taille * 2}`;
  return image;
}

/**
 * Crée un sélecteur.
 * options : [{ id, nom, icone, groupe }]
 * Renvoie un élément DOM enrichi de .valeur, .definirOptions(), .definirValeur().
 */
function creerSelecteur({ options = [], valeur = null, placeholder = "Choisir…", onChange = null,
                          verrouille = false } = {}) {
  const racine = document.createElement("div");
  racine.className = "selecteur";

  const bouton = document.createElement("button");
  bouton.type = "button";
  bouton.className = "selecteur-valeur";
  racine.appendChild(bouton);

  const panneau = document.createElement("div");
  panneau.className = "selecteur-panneau";
  panneau.hidden = true;
  const recherche = document.createElement("input");
  recherche.className = "selecteur-recherche";
  recherche.placeholder = "Rechercher par nom…";
  const liste = document.createElement("ul");
  liste.className = "selecteur-liste";
  panneau.appendChild(recherche);
  panneau.appendChild(liste);
  racine.appendChild(panneau);

  let toutes = options;
  let selection = valeur;
  let survol = -1;
  let visibles = [];

  function optionCourante() {
    return toutes.find((o) => o.id === selection) || null;
  }

  function dessinerBouton() {
    const option = optionCourante();
    bouton.innerHTML = "";
    if (option) {
      bouton.appendChild(creerVignette(option.icone));
      const nom = document.createElement("span");
      nom.textContent = option.nom;
      bouton.appendChild(nom);
    } else {
      const vide = document.createElement("span");
      vide.className = "selecteur-vide";
      vide.textContent = placeholder;
      bouton.appendChild(vide);
    }
    bouton.classList.toggle("verrouille", racine.verrouille);
    bouton.disabled = racine.verrouille || toutes.length === 0;
    if (toutes.length === 0 && !option) {
      bouton.firstChild.textContent = "—";
    }
  }

  function dessinerListe() {
    const terme = sansAccents(recherche.value.trim());
    visibles = toutes.filter((o) => !terme || sansAccents(o.nom).includes(terme));
    liste.innerHTML = "";

    if (!visibles.length) {
      const vide = document.createElement("li");
      vide.className = "selecteur-aucun";
      vide.textContent = "Aucun résultat";
      liste.appendChild(vide);
      return;
    }

    let groupeCourant = null;
    visibles.slice(0, MAX_RESULTATS).forEach((option, index) => {
      if (option.groupe && option.groupe !== groupeCourant) {
        groupeCourant = option.groupe;
        const titre = document.createElement("li");
        titre.className = "selecteur-groupe";
        titre.textContent = groupeCourant;
        liste.appendChild(titre);
      }
      const item = document.createElement("li");
      item.className = "selecteur-option";
      item.dataset.id = option.id;
      if (option.id === selection) item.classList.add("choisie");
      if (index === survol) item.classList.add("survolee");
      item.appendChild(creerVignette(option.icone));
      const nom = document.createElement("span");
      nom.textContent = option.nom;
      item.appendChild(nom);
      item.addEventListener("mousedown", (evenement) => {
        evenement.preventDefault();
        choisir(option.id);
      });
      liste.appendChild(item);
    });

    if (visibles.length > MAX_RESULTATS) {
      const reste = document.createElement("li");
      reste.className = "selecteur-aucun";
      reste.textContent = `… et ${visibles.length - MAX_RESULTATS} autres, affinez la recherche`;
      liste.appendChild(reste);
    }
  }

  function ouvrir() {
    if (racine.verrouille || !toutes.length) return;
    document.querySelectorAll(".selecteur-panneau:not([hidden])").forEach((autre) => {
      autre.hidden = true;
    });
    panneau.hidden = false;
    recherche.value = "";
    survol = Math.max(0, toutes.findIndex((o) => o.id === selection));
    dessinerListe();
    recherche.focus();
    const item = liste.querySelector(".selecteur-option.choisie");
    if (item) item.scrollIntoView({ block: "nearest" });
  }

  function fermer() {
    panneau.hidden = true;
  }

  function choisir(id) {
    const ancienne = selection;
    selection = id;
    dessinerBouton();
    fermer();
    if (ancienne !== id && onChange) onChange(id);
  }

  bouton.addEventListener("click", () => (panneau.hidden ? ouvrir() : fermer()));
  recherche.addEventListener("input", () => {
    survol = 0;
    dessinerListe();
  });
  recherche.addEventListener("keydown", (evenement) => {
    if (evenement.key === "Escape") {
      fermer();
      bouton.focus();
    } else if (evenement.key === "ArrowDown" || evenement.key === "ArrowUp") {
      evenement.preventDefault();
      const pas = evenement.key === "ArrowDown" ? 1 : -1;
      const limite = Math.min(visibles.length, MAX_RESULTATS);
      survol = (survol + pas + limite) % Math.max(limite, 1);
      dessinerListe();
      const item = liste.querySelector(".selecteur-option.survolee");
      if (item) item.scrollIntoView({ block: "nearest" });
    } else if (evenement.key === "Enter") {
      evenement.preventDefault();
      const option = visibles[survol];
      if (option) choisir(option.id);
    }
  });
  document.addEventListener("mousedown", (evenement) => {
    if (!racine.contains(evenement.target)) fermer();
  });

  racine.verrouille = verrouille;
  Object.defineProperty(racine, "valeur", {
    get: () => selection,
    set: (nouvelle) => {
      selection = nouvelle;
      dessinerBouton();
    },
  });
  racine.definirOptions = (nouvelles, nouvelleValeur = undefined) => {
    toutes = nouvelles;
    if (nouvelleValeur !== undefined) selection = nouvelleValeur;
    if (!toutes.some((o) => o.id === selection)) selection = null;
    dessinerBouton();
  };
  racine.definirVerrou = (etat) => {
    racine.verrouille = etat;
    dessinerBouton();
  };

  dessinerBouton();
  return racine;
}
