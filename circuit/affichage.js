"use strict";
// Circuit administratif — présentation : textes, rendu et formulaires.
// Aucune règle métier ici : l'état du salon, les règles et les envois viennent de circuit.js.

const TEXTES = {
  fr: {
    instruction: "Instruction de service", note: "Note administrative", convocation: "Convocation",
    demande_action: "Demande d'action", information: "Information institutionnelle",
    normale: "Priorité normale", haute: "Priorité haute", urgente: "Priorité urgente",
    recu: "Reçu", pris_connaissance: "Pris connaissance", en_cours: "En cours d'exécution",
    execute: "Exécuté", clarification: "Demande de clarification", sans_reponse: "Pas encore de réponse",
    chiffre: "Chiffré de bout en bout", non_chiffre: "Salon non chiffré",
    refus_non_chiffre: "Ce salon n'est pas chiffré : l'envoi est désactivé.",
    confidentiel: "Communication CONFIDENTIELLE : chaque affichage porte votre nom (filigrane). " +
      "Ne pas copier, transférer ni photographier. Expiration automatique.",
    restreint: "DIFFUSION RESTREINTE : ne pas transférer hors de ce salon. Expiration automatique.",
    explication_standard: "Niveau STANDARD : chiffré de bout en bout, conservation normale des messages.",
    explication_diffusion: "Niveau DIFFUSION RESTREINTE : chiffré, à ne pas transférer, messages supprimés automatiquement.",
    explication_confidentiel: "Niveau CONFIDENTIEL : chiffré, filigrane nominatif, messages supprimés automatiquement.",
    envoi: "Envoi en cours… (pas encore transmis)", transmis: "Transmis.", echec: "Échec de l'envoi, réessayez : ",
    vide: "Aucune communication administrative dans ce salon.",
    non_habilite: "Message ignoré : son auteur n'est pas habilité à émettre dans ce salon.",
    emis_par: "Émis par", le: "le", echeance: "Date limite", accuse: "Accusé de prise de connaissance demandé",
    en_retard: "En retard", votre_etat: "Votre réponse", commentaire: "Commentaire (obligatoire pour une clarification)",
    suivi: "Suivi", ont_pris: "ont pris connaissance", destinataire_etat: "Destinataire / État",
    commentaire_court: "Commentaire", a_traiter: "À traiter", terminee: "Terminées",
    court_recu: "Reçu", court_pris_connaissance: "Pris connaissance", court_en_cours: "En cours", court_execute: "Exécuté",
  },
};
const t = (cle) => TEXTES.fr[cle] || cle;

// Même thème que la messagerie : Element transmet le sien dans l'adresse (à défaut, celui du système).
document.documentElement.dataset.theme = new URLSearchParams(location.search).get("theme")
  || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
const dateHeure = (ms) => new Date(ms).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
const initiales = (u) => (nomCourt(u).match(/\p{L}+/gu) || ["?"]).slice(0, 2).map((mot) => mot[0]).join("").toUpperCase();

function element(balise, classe, texte) {
  const e = document.createElement(balise);   // textContent uniquement : aucun contenu reçu n'est interprété comme du HTML
  if (classe) e.className = classe;
  if (texte !== undefined) e.textContent = texte;
  return e;
}

// Le widget est redessiné à chaque événement reçu : on garde ce que l'agent a déplié ou commencé à écrire.
const suivisOuverts = new Set();
const brouillons = new Map();

let afficherPrevu = false;
function afficherBientot() {
  if (afficherPrevu) return;
  afficherPrevu = true;
  requestAnimationFrame(() => { afficherPrevu = false; afficher(); });
}

function afficher() {
  const niveau = classification();
  const badgeNiveau = document.getElementById("niveau");
  badgeNiveau.textContent = niveau;
  badgeNiveau.className = "badge niveau-" + niveau.split(" ")[0].toLowerCase();
  badgeNiveau.title = t("explication_" + niveau.split(" ")[0].toLowerCase());
  badgeNiveau.setAttribute("aria-label", badgeNiveau.title);
  const chiffrement = document.getElementById("chiffrement");
  chiffrement.textContent = salon.chiffre ? t("chiffre") : t("non_chiffre");
  chiffrement.className = "badge " + (salon.chiffre ? "ok" : "alerte");
  const avertissement = document.getElementById("avertissement");
  avertissement.hidden = niveau === "STANDARD" && salon.chiffre;
  avertissement.className = "avertissement " + (!salon.chiffre ? "alerte" : "niveau-" + niveau.split(" ")[0].toLowerCase());
  avertissement.textContent = !salon.chiffre ? t("refus_non_chiffre") : niveau === "CONFIDENTIEL" ? t("confidentiel") : t("restreint");
  document.getElementById("emission").hidden = !(salon.chiffre && habilite(moi));

  const communications = [...salon.communications.values()].sort((a, b) => b.origin_server_ts - a.origin_server_ts);
  const valides = communications.filter((ev) => habilite(ev.sender));
  const compte = { a_traiter: 0, en_retard: 0, terminee: 0 };
  for (const ev of valides) compte[situation(ev)]++;
  const synthese = document.getElementById("synthese");
  synthese.hidden = !valides.length;
  synthese.replaceChildren(...Object.entries(compte).map(([cle, nombre]) => {
    const tuile = element("div", "tuile tuile-" + cle + (cle === "en_retard" && nombre ? " alerte" : ""));
    tuile.append(element("strong", null, String(nombre)), element("span", null, t(cle)));
    return tuile;
  }));

  const liste = document.getElementById("liste");
  liste.replaceChildren();
  if (!communications.length) liste.append(element("p", "vide", t("vide")));
  for (const ev of communications) liste.append(carte(ev, niveau));
}

function carte(ev, niveau) {
  if (!habilite(ev.sender)) return element("p", "ignore", t("non_habilite") + " (" + nomCourt(ev.sender) + ")");
  const d = ev.content["bf.gouv.circuit"];
  const etatCarte = situation(ev);
  const c = element("article", "carte priorite-" + d.priorite);
  const entete = element("div", "entete");
  entete.append(element("span", "type", t(d.type)), element("span", "priorite", t(d.priorite)));
  c.append(entete);
  if (d.echeance) {
    const date = new Date(d.echeance).toLocaleDateString("fr-FR");
    const retard = etatCarte === "en_retard";
    const echeance = element("span", "echeance" + (retard ? " retard" : ""), retard ? `${t("en_retard")} · ${date}` : date);
    echeance.title = t("echeance");
    c.append(echeance);
  }
  c.append(element("h2", null, d.titre));
  const meta = element("p", "meta", `${t("emis_par")} ${nomCourt(ev.sender)} ${t("le")} ${dateHeure(ev.origin_server_ts)}`);
  if (d.service) meta.append(element("span", "service", "→ " + d.service));
  c.append(meta);
  if (d.accuse) c.append(element("p", "accuse", t("accuse")));
  const contenu = element("p", "contenu", d.contenu);
  if (niveau === "CONFIDENTIEL") contenu.style.backgroundImage = filigrane();
  c.append(contenu);

  const reponses = salon.etats.get(ev.event_id) || new Map();
  if (ev.sender !== moi) c.append(reponse(ev, reponses.get(moi), etatCarte === "en_retard"));
  if (ev.sender === moi || habilite(moi)) c.append(suivi(ev, destinatairesDe(ev), reponses, enRetard(d)));
  return c;
}

function reponse(ev, actuel, retard) {
  const bloc = element("div", "reponse");
  const ligne = element("div", "ligne-reponse");
  const etatActuel = (actuel ? `${t(actuel.content.etat)} · ${dateHeure(actuel.origin_server_ts)}` : t("sans_reponse"))
    + (retard ? ` · ${t("en_retard")}` : "");
  ligne.append(element("span", "titre-reponse", t("votre_etat")), element("span", "etat-actuel" + (retard ? " retard" : ""), etatActuel));

  const commentaire = element("input", "commentaire");
  commentaire.placeholder = t("commentaire");
  commentaire.maxLength = 500;
  commentaire.value = brouillons.get(ev.event_id) || "";
  commentaire.addEventListener("input", () => brouillons.set(ev.event_id, commentaire.value));
  const statut = element("span", "statut");
  statut.setAttribute("role", "status");
  const choisir = async (etat, bouton) => {
    if (etat === "clarification" && !commentaire.value.trim()) { commentaire.focus(); return; }
    if (await envoyer(bouton, statut, () => repondre(ev.event_id, etat, commentaire.value.trim()))) {
      brouillons.delete(ev.event_id);
      commentaire.value = "";
    }
  };

  // Étapes Reçu → Pris connaissance → En cours → Exécuté : un clic envoie l'étape choisie.
  const rang = actuel ? ORDRE.indexOf(actuel.content.etat) : -1;   // -1 : aucune étape (ou clarification)
  const etapes = element("ol", "etapes");
  ORDRE.forEach((etat, i) => {
    const b = element("button", "etape" + (i <= rang ? " faite" : ""));
    b.type = "button";
    b.title = t(etat);
    if (i === rang) b.setAttribute("aria-current", "step");
    b.append(element("span", "pastille"), element("span", "libelle", t("court_" + etat)));
    b.addEventListener("click", () => choisir(etat, b));
    const li = element("li");
    li.append(b);
    etapes.append(li);
  });
  const clarifier = element("button", "lien-clarification", t("clarification"));
  clarifier.type = "button";
  clarifier.addEventListener("click", () => choisir("clarification", clarifier));
  bloc.append(ligne, etapes, clarifier, commentaire, statut);
  return bloc;
}

function suivi(ev, destinataires, reponses, retard) {
  const bloc = element("details", "suivi");
  bloc.open = suivisOuverts.has(ev.event_id);
  bloc.addEventListener("toggle", () => (bloc.open ? suivisOuverts.add(ev.event_id) : suivisOuverts.delete(ev.event_id)));
  const avancees = destinataires.filter((u) => reponses.has(u) && ORDRE.indexOf(reponses.get(u).content.etat) >= 1).length;
  const resume = element("summary");
  resume.append(element("span", "titre-suivi", `${t("suivi")} : ${avancees}/${destinataires.length} ${t("ont_pris")}`));
  const avatars = element("span", "avatars");
  avatars.setAttribute("aria-hidden", "true");   // le détail lisible est dans le tableau
  for (const u of destinataires.slice(0, 5)) {
    avatars.append(element("span", "avatar etat-" + (reponses.has(u) ? reponses.get(u).content.etat : "aucun"), initiales(u)));
  }
  if (destinataires.length > 5) avatars.append(element("span", "avatar plus", "+" + (destinataires.length - 5)));
  resume.append(avatars);

  const table = element("table");
  const tete = element("tr");
  tete.append(element("th", null, t("destinataire_etat")), element("th", null, t("commentaire_court")));
  table.append(tete);
  for (const u of destinataires) {
    const r = reponses.get(u);
    const ligne = element("tr", r ? "etat-" + r.content.etat : "etat-aucun");
    const qui = element("td");
    const nom = element("div", "nom", nomCourt(u));
    nom.title = nomDe(u);
    const etat = r ? `${t(r.content.etat)} · ${dateHeure(r.origin_server_ts)}` : t("sans_reponse") + (retard ? ` · ${t("en_retard")}` : "");
    qui.append(nom, element("div", "etat-ligne", etat));
    ligne.append(qui, element("td", null, (r && r.content.commentaire) || ""));
    table.append(ligne);
  }
  bloc.append(resume, table);
  return bloc;
}

function filigrane() {
  // Identifie la personne qui affiche le document en cas de capture d'écran (ne l'empêche pas).
  const texte = `CONFIDENTIEL · ${nomDe(moi)} · ${moi} · ${new Date().toLocaleString("fr-FR")}`
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="520" height="140"><text x="10" y="100" ` +
    `transform="rotate(-12 260 70)" fill="rgba(139,30,45,0.14)" font-family="sans-serif" font-size="15">${texte}</text></svg>`;
  return `url("data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}")`;
}

// « Transmis » n'apparaît qu'une fois l'envoi confirmé par Element ; avant, c'est « Envoi en cours ».
async function envoyer(bouton, statut, action) {
  bouton.disabled = true;
  statut.textContent = t("envoi");
  try {
    await action();
    statut.textContent = t("transmis");
    return true;
  } catch (erreur) {
    statut.textContent = t("echec") + erreur.message;
    return false;
  } finally {
    bouton.disabled = false;
  }
}

document.getElementById("formulaire").addEventListener("submit", async (evenement) => {
  evenement.preventDefault();
  const f = evenement.target;
  const donnees = {
    type: f.type.value, titre: f.titre.value.trim(), contenu: f.contenu.value.trim(),
    service: f.service.value.trim() || undefined, priorite: f.priorite.value,
    echeance: f.echeance.value || undefined, accuse: f.accuse.checked,
  };
  if (await envoyer(f.querySelector("button[type=submit]"), document.getElementById("statut-envoi"), () => emettre(donnees))) f.reset();
});
