"""Module Synapse : niveaux de classification des salons et expiration automatique.

Un salon est classifié par le début de son nom, par exemple « [CONFIDENTIEL] Cellule de crise ».
Pour chaque niveau, le serveur applique des règles sans jamais lire les messages (ils restent chiffrés) :
  - expiration : chaque message plus vieux que la durée du niveau est supprimé (rédaction Matrix),
    ce qui le fait disparaître sur tous les appareils et retire le contenu chiffré du serveur ;
  - pas de déclassement : on ne peut pas renommer le salon vers un niveau moins protégé ;
  - pas de salon public : un salon classifié ne peut pas être ouvert à tous.
"""
import logging
import time

logger = logging.getLogger(__name__)


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
        api.register_third_party_rules_callbacks(check_event_allowed=self.verifier_evenement)
        api.looping_background_call(self.faire_expirer, config.get("intervalle", 30) * 1000,
                                    desc="expiration_salons_classifies")

    @staticmethod
    def parse_config(config):
        return config

    async def verifier_evenement(self, evenement, etat):
        evenement_nom = etat.get(("m.room.name", ""))
        nom_actuel = evenement_nom.content.get("name") if evenement_nom else None

        if niveau_du_nom(nom_actuel, self.niveaux) is None:
            # Classifier un salon : seulement s'il est vide (sinon tout l'historique serait détruit
            # rétroactivement) et non public.
            if evenement.type == "m.room.name" and niveau_du_nom(evenement.content.get("name"), self.niveaux):
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
        # Supprimer l'événement qui porte le nom ferait revenir l'ancien nom : ce serait un déclassement.
        if evenement.type == "m.room.redaction" and evenement.redacts == evenement_nom.event_id:
            return False, None
        return True, None

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
