"use strict";
// Circuit administratif — logique métier et données : communications structurées et accusés de prise de connaissance.
//
// Ce widget ne fait aucune cryptographie. Il parle à Element par l'API officielle des widgets
// (matrix-widget-api) : Element chiffre (Olm/Megolm) chaque événement que le widget envoie, et ne lui
// transmet, déchiffrés, que les événements du circuit de ce salon. Les clés ne quittent jamais Element.
// La présentation (textes, rendu, formulaires) est dans affichage.js.

const TYPE_COMMUNICATION = "bf.gouv.circuit.instruction";   // msgtype d'un m.room.message
const TYPE_ETAT = "bf.gouv.circuit.etat";                   // état déclaré par un destinataire
const NIVEAU_HABILITE = 50;   // niveau de pouvoir Matrix (appliqué par le serveur) requis pour émettre
const CLIENTS_AUTORISES = ["https://chat.localhost", "https://chat2.localhost"];
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
const habilite = (u) => niveauDe(u) >= NIVEAU_HABILITE;
const nomDe = (u) => (salon.membres.get(u) && salon.membres.get(u).displayname) || u;
const nomCourt = (u) => nomDe(u).split(" · ")[0];   // « Prénom Nom », sans la fonction ni le service
const classification = () => {
  const nom = salon.nom.trim().toUpperCase();
  return nom.startsWith("[CONFIDENTIEL]") ? "CONFIDENTIEL" : nom.startsWith("[DIFFUSION RESTREINTE]") ? "DIFFUSION RESTREINTE" : "STANDARD";
};
const enRetard = (d) => Boolean(d.echeance) && new Date(d.echeance + "T23:59:59") < new Date();
const destinatairesDe = (ev) => [...salon.membres].filter(([u, m]) => m.membership === "join" && u !== ev.sender).map(([u]) => u);

// Ce qui reste à faire pour la personne connectée : sa propre réponse si elle est destinataire,
// celle de tous les destinataires si elle est l'émettrice.
function situation(ev) {
  const reponses = salon.etats.get(ev.event_id) || new Map();
  const concernes = ev.sender === moi ? destinatairesDe(ev) : [moi];
  if (concernes.length && concernes.every((u) => reponses.has(u) && reponses.get(u).content.etat === "execute")) return "terminee";
  return enRetard(ev.content["bf.gouv.circuit"]) ? "en_retard" : "a_traiter";
}

// Aucun envoi dans un salon non chiffré : ni instruction ni accusé ne doit partir en clair.
function verifierChiffrement() {
  if (!salon.chiffre) throw new Error(t("refus_non_chiffre"));
}

async function repondre(instruction, etat, commentaire) {
  verifierChiffrement();
  await api.sendRoomEvent(TYPE_ETAT, { instruction, etat, commentaire: commentaire || undefined });
}

async function emettre(donnees) {
  verifierChiffrement();
  // Texte lisible dans Element, pour les membres qui n'ouvrent pas le circuit.
  const resume = [`📋 ${t(donnees.type).toUpperCase()} — ${donnees.titre}`, t(donnees.priorite)];
  if (donnees.echeance) resume.push(`${t("echeance")} : ${new Date(donnees.echeance).toLocaleDateString("fr-FR")}`);
  await api.sendRoomEvent("m.room.message", {
    msgtype: TYPE_COMMUNICATION, "bf.gouv.circuit": { version: 1, ...donnees },
    body: `${resume.join(" · ")}\n\n${donnees.contenu}\n\n(Répondre depuis le circuit administratif, en haut du salon.)`,
  });
}
