"""Module Synapse : niveaux de classification des salons et expiration automatique.

Un salon est classifié par le début de son nom, par exemple « [CONFIDENTIEL] Cellule de crise ».
Pour chaque niveau, le serveur applique des règles sans jamais lire les messages (ils restent chiffrés) :
  - expiration : chaque message plus vieux que la durée du niveau est supprimé (rédaction Matrix),
    ce qui le fait disparaître sur tous les appareils et retire le contenu chiffré du serveur ;
  - pas de déclassement : on ne peut pas renommer le salon vers un niveau moins protégé ;
  - pas de salon public : un salon classifié ne peut pas être ouvert à tous ;
  - seuls les responsables (rôle Keycloak « responsable », voir annuaire.py) peuvent classifier un salon ;
  - pas de réaction (emoji) dans un salon classifié : Matrix les transmet en clair ;
  - le circuit administratif (widget) est ajouté et épinglé en haut du salon dès sa classification ;
    c'est le seul widget autorisé dans un salon classifié (aucune page tierce ne peut s'y greffer).
Dans tous les salons chiffrés, le serveur refuse aussi tout message envoyé en clair.
"""
import logging
import time

import annuaire

logger = logging.getLogger(__name__)
WIDGETS = ("im.vector.modular.widgets", "m.widget")   # les deux types d'état qu'Element affiche comme widgets


def niveau_du_nom(nom, niveaux):
    """Renvoie le préfixe de classification du nom de salon (ex. "[CONFIDENTIEL]"), ou None."""
    nom = (nom or "").strip().upper()
    for prefixe in niveaux:
        if nom.startswith(prefixe.upper()):
            return prefixe
    return None


def renommage_autorise(ancien_nom, nouveau_nom, niveaux):
    """Un salon classifié ne peut garder que son niveau ou passer à un niveau plus strict (durée plus courte)."""
    ancien = niveau_du_nom(ancien_nom, niveaux)
    if ancien is None:
        return True
    nouveau = niveau_du_nom(nouveau_nom, niveaux)
    return nouveau is not None and niveaux[nouveau] <= niveaux[ancien]


class Classification:
    def __init__(self, config, api):
        self.api = api
        self.niveaux = config["niveaux"]   # préfixe -> durée de vie des messages, en secondes
        self.circuit = config.get("circuit")   # adresse du widget du circuit administratif
        api.register_third_party_rules_callbacks(check_event_allowed=self.verifier_evenement,
                                                 on_new_event=self.installer_circuit)
        api.looping_background_call(self.faire_expirer, config.get("intervalle", 30) * 1000,
                                    desc="expiration_salons_classifies")

    @staticmethod
    def parse_config(config):
        return config

    async def verifier_evenement(self, evenement, etat):
        # Un client mal configuré ou malveillant ne peut pas glisser un message en clair dans un salon chiffré.
        if evenement.type == "m.room.message" and ("m.room.encryption", "") in etat:
            return False, None

        evenement_nom = etat.get(("m.room.name", ""))
        nom_actuel = evenement_nom.content.get("name") if evenement_nom else None

        if niveau_du_nom(nom_actuel, self.niveaux) is None:
            # Classifier un salon : seulement par un responsable, si le salon est vide (sinon tout
            # l'historique serait détruit rétroactivement) et non public.
            if evenement.type == "m.room.name" and niveau_du_nom(evenement.content.get("name"), self.niveaux):
                if evenement.sender not in annuaire.RESPONSABLES or self._widgets_etrangers(etat):
                    return False, None
                regles = etat.get(("m.room.join_rules", ""))
                if regles and regles.content.get("join_rule") == "public":
                    return False, None
                if await self.api.run_db_interaction("salon_a_des_messages", self._a_des_messages, evenement.room_id):
                    return False, None
            return True, None

        if evenement.type == "m.room.name" and not renommage_autorise(
                nom_actuel, evenement.content.get("name"), self.niveaux):
            return False, None
        if evenement.type == "m.room.join_rules" and evenement.content.get("join_rule") == "public":
            return False, None
        if evenement.type == "m.reaction":
            return False, None
        if evenement.type in WIDGETS and evenement.content.get("url") not in (None, self.circuit):
            return False, None
        # Supprimer l'événement qui porte le nom ferait revenir l'ancien nom : ce serait un déclassement.
        if evenement.type == "m.room.redaction" and evenement.redacts == evenement_nom.event_id:
            return False, None
        return True, None

    def _widgets_etrangers(self, etat):
        return any(cle[0] in WIDGETS and ev.content.get("url") not in (None, self.circuit)
                   for cle, ev in etat.items())

    async def installer_circuit(self, evenement, etat):
        if (evenement.type != "m.room.name" or not self.circuit
                or not niveau_du_nom(evenement.content.get("name"), self.niveaux)
                or ("im.vector.modular.widgets", "circuit") in etat):
            return
        widget = {"id": "circuit", "type": "m.custom", "name": "Circuit administratif", "url": self.circuit,
                  "data": {}, "waitForIframeLoad": True, "creatorUserId": evenement.sender}
        disposition = {"widgets": {"circuit": {"container": "top", "index": 0, "width": 100, "height": 45}}}
        for type_, cle, contenu in (("im.vector.modular.widgets", "circuit", widget),
                                    ("io.element.widgets.layout", "", disposition)):
            await self.api.create_and_send_event_into_room({
                "type": type_, "state_key": cle, "room_id": evenement.room_id,
                "sender": evenement.sender, "content": contenu})

    @staticmethod
    def _a_des_messages(txn, salon):
        txn.execute("SELECT 1 FROM events WHERE room_id = ? AND type IN ('m.room.encrypted', 'm.room.message') LIMIT 1",
                    (salon,))
        return txn.fetchone() is not None

    async def faire_expirer(self):
        for salon, nom, createur in await self.api.run_db_interaction("salons_classifies", self._salons):
            limite_ms = int((time.time() - self.niveaux[niveau_du_nom(nom, self.niveaux)]) * 1000)
            expires = await self.api.run_db_interaction("messages_expires", self._messages_expires, salon, limite_ms)
            for evenement_id, auteur in expires:
                # L'auteur peut toujours supprimer son propre message ; s'il a été révoqué, le créateur du salon le fait.
                for expediteur in (auteur, createur):
                    try:
                        await self.api.create_and_send_event_into_room({
                            "type": "m.room.redaction", "room_id": salon, "sender": expediteur,
                            "redacts": evenement_id,
                            "content": {"redacts": evenement_id, "reason": "Expiration automatique : " + nom.split("]")[0] + "]"},
                        })
                        break
                    except Exception as erreur:
                        logger.warning("Expiration de %s par %s impossible : %s", evenement_id, expediteur, erreur)

    def _salons(self, txn):
        txn.execute("SELECT s.room_id, s.name, r.creator FROM room_stats_state s JOIN rooms r USING (room_id)"
                    " WHERE s.name IS NOT NULL")
        return [ligne for ligne in txn.fetchall() if niveau_du_nom(ligne[1], self.niveaux)]

    @staticmethod
    def _messages_expires(txn, salon, limite_ms):
        txn.execute(
            "SELECT e.event_id, e.sender FROM events e"
            " LEFT JOIN redactions r ON r.redacts = e.event_id"
            " WHERE e.room_id = ? AND e.type IN ('m.room.encrypted', 'm.room.message')"
            " AND e.origin_server_ts < ? AND r.redacts IS NULL AND NOT e.outlier LIMIT 200",
            (salon, limite_ms))
        return txn.fetchall()
