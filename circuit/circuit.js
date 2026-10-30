"use strict";
// Circuit administratif : communications structurées et accusés de prise de connaissance.
//
// Ce widget ne fait aucune cryptographie. Il parle à Element par l'API officielle des widgets
// (matrix-widget-api) : Element chiffre (Olm/Megolm) chaque événement que le widget envoie, et ne lui
// transmet, déchiffrés, que les événements du circuit de ce salon. Les clés ne quittent jamais Element.

const TYPE_COMMUNICATION = "bf.gouv.circuit.instruction";   // msgtype d'un m.room.message
const TYPE_ETAT = "bf.gouv.circuit.etat";                   // état déclaré par un destinataire
const NIVEAU_HABILITE = 50;   // niveau de pouvoir Matrix (appliqué par le serveur) requis pour émettre
const CLIENTS_AUTORISES = ["https://chat.localhost", "https://chat2.localhost"];

const TEXTES = {
  fr: {
    instruction: "Instruction de service", note: "Note administrative", convocation: "Convocation",
    demande_action: "Demande d'action", information: "Information institutionnelle",
    normale: "Priorité normale", haute: "Priorité haute", urgente: "Priorité urgente",
    recu: "Reçu", pris_connaissance: "Pris connaissance", en_cours: "En cours d'exécution",
    execute: "Exécuté", clarification: "Demande de clarification", sans_reponse: "Pas encore de réponse",
    chiffre: "🔒 Chiffré de bout en bout", non_chiffre: "Salon non chiffré",
    refus_non_chiffre: "Ce salon n'est pas chiffré : l'envoi est désactivé.",
    confidentiel: "Communication CONFIDENTIELLE : chaque affichage porte votre nom (filigrane). " +
      "Ne pas copier, transférer ni photographier. Expiration automatique.",
    restreint: "DIFFUSION RESTREINTE : ne pas transférer hors de ce salon. Expiration automatique.",
    envoi: "Envoi en cours… (pas encore transmis)", transmis: "Transmis.", echec: "Échec de l'envoi, réessayez : ",
    vide: "Aucune communication administrative dans ce salon.",
    non_habilite: "Message ignoré : son auteur n'est pas habilité à émettre dans ce salon.",
    emis_par: "Émis par", le: "le", echeance: "Date limite", accuse: "Accusé de prise de connaissance demandé",
    en_retard: "En retard", votre_etat: "Votre réponse", commentaire: "Commentaire (obligatoire pour une clarification)",
    suivi: "Suivi des destinataires", ont_pris: "ont pris connaissance", agent: "Destinataire", etat: "État",
    commentaire_court: "Commentaire",
  },
};
const t = (cle) => TEXTES.fr[cle] || cle;
const ORDRE = ["recu", "pris_connaissance", "en_cours", "execute"];

const parametres = new URLSearchParams(location.search);
const moi = parametres.get("user");
const origineClient = new URL(parametres.get("parentUrl") || "https://invalide.").origin;
if (!CLIENTS_AUTORISES.includes(origineClient)) throw new Error("Widget chargé hors de la messagerie");

// La version minifiée de matrix-widget-api expose une fonction qui renvoie le module.
const sdk = typeof mxwidgets === "function" ? mxwidgets() : mxwidgets;

const salon = { communications: new Map(), etats: new Map(), membres: new Map(), pouvoirs: {}, nom: "", chiffre: false };

const api = new sdk.WidgetApi(parametres.get("widgetId"), origineClient);
api.requestCapabilityToSendMessage(TYPE_COMMUNICATION);
api.requestCapabilityToReceiveMessage(TYPE_COMMUNICATION);
api.requestCapabilityToSendEvent(TYPE_ETAT);
api.requestCapabilityToReceiveEvent(TYPE_ETAT);
for (const type of ["m.room.member", "m.room.power_levels", "m.room.name", "m.room.encryption"]) {
  api.requestCapabilityToReceiveState(type);
}
api.on("ready", charger);
api.on(`action:${sdk.WidgetApiToWidgetAction.SendEvent}`, (ev) => {
  ev.preventDefault();
  api.transport.reply(ev.detail, {});
  recevoir(ev.detail.data);
  afficherBientot();
});
api.start();

async function charger() {
  const lots = await Promise.all([
    api.readStateEvents("m.room.member", 1000), api.readStateEvents("m.room.power_levels", 1),
    api.readStateEvents("m.room.name", 1), api.readStateEvents("m.room.encryption", 1),
    api.readRoomEvents("m.room.message", 500, TYPE_COMMUNICATION), api.readRoomEvents(TYPE_ETAT, 5000),
  ]);
  lots.flat().forEach(recevoir);
  afficher();
}

function recevoir(ev) {
  switch (ev.type) {
    case "m.room.member": salon.membres.set(ev.state_key, ev.content); break;
    case "m.room.power_levels": salon.pouvoirs = ev.content || {}; break;
    case "m.room.name": salon.nom = (ev.content && ev.content.name) || ""; break;
    case "m.room.encryption": salon.chiffre = ev.content.algorithm === "m.megolm.v1.aes-sha2"; break;
    case "m.room.message":
      if (ev.content.msgtype === TYPE_COMMUNICATION && ev.content["bf.gouv.circuit"]) salon.communications.set(ev.event_id, ev);
      break;
    case TYPE_ETAT: {
      const cible = ev.content.instruction;
      if (!cible || !ORDRE.concat("clarification").includes(ev.content.etat)) break;
      const parAgent = salon.etats.get(cible) || new Map();
      const precedent = parAgent.get(ev.sender);
      if (!precedent || precedent.origin_server_ts <= ev.origin_server_ts) parAgent.set(ev.sender, ev);
      salon.etats.set(cible, parAgent);
    }
  }
}

const niveauDe = (u) => {
  const p = salon.pouvoirs;
  return p.users && p.users[u] !== undefined ? p.users[u] : p.users_default || 0;
};
const nomDe = (u) => (salon.membres.get(u) && salon.membres.get(u).displayname) || u;
const nomCourt = (u) => nomDe(u).split(" · ")[0];   // « Prénom Nom », sans la fonction ni le service
const classification = () => {
  const nom = salon.nom.trim().toUpperCase();
  return nom.startsWith("[CONFIDENTIEL]") ? "CONFIDENTIEL" : nom.startsWith("[DIFFUSION RESTREINTE]") ? "DIFFUSION RESTREINTE" : "STANDARD";
};
const dateHeure = (ms) => new Date(ms).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });

function element(balise, classe, texte) {
  const e = document.createElement(balise);   // textContent uniquement : aucun contenu reçu n'est interprété comme du HTML
  if (classe) e.className = classe;
  if (texte !== undefined) e.textContent = texte;
  return e;
}

let afficherPrevu = false;
function afficherBientot() {
  if (afficherPrevu) return;
  afficherPrevu = true;
  requestAnimationFrame(() => { afficherPrevu = false; afficher(); });
}

function afficher() {
  const niveau = classification();
  document.getElementById("niveau").textContent = niveau;
  document.getElementById("niveau").className = "badge niveau-" + niveau.split(" ")[0].toLowerCase();
  const chiffrement = document.getElementById("chiffrement");
  chiffrement.textContent = salon.chiffre ? t("chiffre") : t("non_chiffre");
  chiffrement.className = "badge " + (salon.chiffre ? "ok" : "alerte");
  const avertissement = document.getElementById("avertissement");
  avertissement.hidden = niveau === "STANDARD" && salon.chiffre;
  avertissement.textContent = !salon.chiffre ? t("refus_non_chiffre") : niveau === "CONFIDENTIEL" ? t("confidentiel") : t("restreint");
  document.getElementById("emission").hidden = !(salon.chiffre && niveauDe(moi) >= NIVEAU_HABILITE);

  const liste = document.getElementById("liste");
  liste.replaceChildren();
  const communications = [...salon.communications.values()].sort((a, b) => b.origin_server_ts - a.origin_server_ts);
  if (!communications.length) liste.append(element("p", "vide", t("vide")));
  for (const ev of communications) liste.append(carte(ev, niveau));
}

function carte(ev, niveau) {
  if (niveauDe(ev.sender) < NIVEAU_HABILITE) return element("p", "ignore", t("non_habilite") + " (" + nomCourt(ev.sender) + ")");
  const d = ev.content["bf.gouv.circuit"];
  const c = element("article", "carte priorite-" + d.priorite);
  const entete = element("div", "entete");
  entete.append(element("span", "type", t(d.type)), element("span", "priorite", t(d.priorite)));
  const enRetard = d.echeance && new Date(d.echeance + "T23:59:59") < new Date();
  c.append(entete, element("h2", null, d.titre));
  const meta = [`${t("emis_par")} ${nomCourt(ev.sender)} ${t("le")} ${dateHeure(ev.origin_server_ts)}`];
  if (d.service) meta.push("→ " + d.service);
  if (d.echeance) meta.push(`${t("echeance")} : ${new Date(d.echeance).toLocaleDateString("fr-FR")}`);
  c.append(element("p", "meta", meta.join(" · ")));
  if (d.accuse) c.append(element("p", "accuse", t("accuse")));
  const contenu = element("p", "contenu", d.contenu);
  if (niveau === "CONFIDENTIEL") contenu.style.backgroundImage = filigrane();
  c.append(contenu);

  const reponses = salon.etats.get(ev.event_id) || new Map();
  const destinataires = [...salon.membres].filter(([u, m]) => m.membership === "join" && u !== ev.sender).map(([u]) => u);
  if (ev.sender !== moi) c.append(reponse(ev, reponses.get(moi), enRetard));
  if (ev.sender === moi || niveauDe(moi) >= NIVEAU_HABILITE) c.append(suivi(destinataires, reponses, enRetard));
  return c;
}

function reponse(ev, actuel, enRetard) {
  const bloc = element("div", "reponse");
  const etatActuel = actuel ? `${t(actuel.content.etat)} (${dateHeure(actuel.origin_server_ts)})` : t("sans_reponse");
  bloc.append(element("p", null, `${t("votre_etat")} : ${etatActuel}` + (enRetard && !(actuel && actuel.content.etat === "execute") ? ` · ${t("en_retard")}` : "")));
  const commentaire = element("input", "commentaire");
  commentaire.placeholder = t("commentaire");
  commentaire.maxLength = 500;
  const boutons = element("div", "boutons");
  for (const etat of ORDRE.concat("clarification")) {
    const b = element("button", etat === "clarification" ? "secondaire" : null, t(etat));
    b.type = "button";
    b.addEventListener("click", () => repondre(ev.event_id, etat, commentaire, b));
    boutons.append(b);
  }
  const statut = element("span", "statut");
  statut.setAttribute("role", "status");
  bloc.append(boutons, commentaire, statut);
  return bloc;
}

async function repondre(instruction, etat, champ, bouton) {
  const statut = bouton.closest(".reponse").querySelector(".statut");
  if (etat === "clarification" && !champ.value.trim()) { champ.focus(); return; }
  bouton.disabled = true;
  statut.textContent = t("envoi");
  try {
    await api.sendRoomEvent(TYPE_ETAT, { instruction, etat, commentaire: champ.value.trim() || undefined });
    statut.textContent = t("transmis");
  } catch (erreur) {
    statut.textContent = t("echec") + erreur.message;
  } finally {
    bouton.disabled = false;
  }
}

function suivi(destinataires, reponses, enRetard) {
  const bloc = element("div", "suivi");
  const avancees = destinataires.filter((u) => reponses.has(u) && ORDRE.indexOf(reponses.get(u).content.etat) >= 1).length;
  bloc.append(element("h3", null, `${t("suivi")} : ${avancees}/${destinataires.length} ${t("ont_pris")}`));
  const table = element("table");
  const tete = element("tr");
  tete.append(element("th", null, t("agent")), element("th", null, t("etat")), element("th", null, t("commentaire_court")));
  table.append(tete);
  for (const u of destinataires) {
    const r = reponses.get(u);
    const ligne = element("tr", r ? "etat-" + r.content.etat : "etat-aucun");
    const etat = r ? `${t(r.content.etat)} · ${dateHeure(r.origin_server_ts)}` : t("sans_reponse") + (enRetard ? ` · ${t("en_retard")}` : "");
    const nom = element("td", null, nomCourt(u));
    nom.title = nomDe(u);
    ligne.append(nom, element("td", null, etat), element("td", null, (r && r.content.commentaire) || ""));
    table.append(ligne);
  }
  bloc.append(table);
  return bloc;
}

function filigrane() {
  // Identifie la personne qui affiche le document en cas de capture d'écran (ne l'empêche pas).
  const texte = `CONFIDENTIEL · ${nomDe(moi)} · ${moi} · ${new Date().toLocaleString("fr-FR")}`
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="520" height="140"><text x="10" y="100" ` +
    `transform="rotate(-12 260 70)" fill="rgba(170,0,0,0.16)" font-family="sans-serif" font-size="15">${texte}</text></svg>`;
  return `url("data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}")`;
}

document.getElementById("formulaire").addEventListener("submit", async (evenement) => {
  evenement.preventDefault();
  const f = evenement.target;
  const statut = document.getElementById("statut-envoi");
  if (!salon.chiffre) { statut.textContent = t("refus_non_chiffre"); return; }
  const donnees = {
    version: 1, type: f.type.value, titre: f.titre.value.trim(), contenu: f.contenu.value.trim(),
    service: f.service.value.trim() || undefined, priorite: f.priorite.value,
    echeance: f.echeance.value || undefined, accuse: f.accuse.checked,
  };
  // Texte lisible dans Element, pour les membres qui n'ouvrent pas le circuit.
  const resume = [`📋 ${t(donnees.type).toUpperCase()} — ${donnees.titre}`, t(donnees.priorite)];
  if (donnees.echeance) resume.push(`${t("echeance")} : ${new Date(donnees.echeance).toLocaleDateString("fr-FR")}`);
  const corps = {
    msgtype: TYPE_COMMUNICATION, "bf.gouv.circuit": donnees,
    body: `${resume.join(" · ")}\n\n${donnees.contenu}\n\n(Répondre depuis le circuit administratif, en haut du salon.)`,
  };
  const bouton = f.querySelector("button[type=submit]");
  bouton.disabled = true;
  statut.textContent = t("envoi");
  try {
    await api.sendRoomEvent("m.room.message", corps);
    statut.textContent = t("transmis");
    f.reset();
  } catch (erreur) {
    statut.textContent = t("echec") + erreur.message;
  } finally {
    bouton.disabled = false;
  }
});
