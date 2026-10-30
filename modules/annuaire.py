"""Module Synapse : l'annuaire des agents (Keycloak) fait foi pour la messagerie.

Toutes les quelques secondes, le serveur de messagerie lit l'annuaire, en lecture seule, et :
  - désactive le compte Matrix de tout agent désactivé, supprimé ou privé du rôle « agent » dans Keycloak :
    une révocation faite dans la console d'administration coupe donc aussi les sessions déjà ouvertes
    (jetons supprimés, appareils déconnectés, salons quittés) ;
  - affiche pour chaque agent « Prénom Nom · fonction · direction · ministère » : l'annuaire de la messagerie
    est alimenté uniquement par les administrateurs (les agents ne peuvent pas changer leur nom affiché) ;
  - tient à jour la liste des responsables (rôle « responsable »), lue par classification.py.
Si Keycloak ne répond pas, rien n'est modifié : on ne révoque jamais par erreur.
"""
import logging
import os

logger = logging.getLogger(__name__)

RESPONSABLES = set()   # identifiants Matrix des agents ayant le rôle « responsable »
PAGE = 200


def nom_affiche(agent):
    """« Prénom Nom · fonction · direction · ministère », en omettant ce qui n'est pas renseigné."""
    attributs = agent.get("attributes") or {}
    morceaux = [" ".join(filter(None, [agent.get("firstName"), agent.get("lastName")])) or agent["username"]]
    morceaux += [attributs[cle][0] for cle in ("fonction", "direction", "ministere") if attributs.get(cle)]
    return " · ".join(morceaux)


def comptes_a_revoquer(comptes_matrix, autorises):
    """Comptes Matrix actifs dont l'identifiant Keycloak n'est plus un agent actif.

    comptes_matrix : {identifiant Keycloak: identifiant Matrix} ; autorises : identifiants Keycloak autorisés.
    Une liste d'autorisés vide signale une erreur de lecture, pas un annuaire vide : on ne révoque alors personne.
    """
    if not autorises:
        return []
    return sorted(mxid for externe, mxid in comptes_matrix.items() if externe not in autorises)


class Annuaire:
    def __init__(self, config, api):
        self.api = api
        self.keycloak = config["keycloak"].rstrip("/")
        self.realm = config["realm"]
        self.client_id = config["client_id"]
        self.secret = os.environ["KEYCLOAK_ANNUAIRE_SECRET"]   # fourni par docker-compose (.env)
        self.fournisseur = config.get("fournisseur", "oidc-keycloak")
        api.looping_background_call(self.synchroniser, config.get("intervalle", 5) * 1000,
                                    desc="synchronisation_annuaire")

    @staticmethod
    def parse_config(config):
        return config

    async def _jeton(self):
        reponse = await self.api.http_client.post_urlencoded_get_json(
            f"{self.keycloak}/realms/{self.realm}/protocol/openid-connect/token",
            {"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.secret})
        return reponse["access_token"]

    async def _membres(self, jeton, role):
        membres, debut = [], 0
        while True:
            page = await self.api.http_client.get_json(
                f"{self.keycloak}/admin/realms/{self.realm}/roles/{role}/users",
                {"first": str(debut), "max": str(PAGE), "briefRepresentation": "false"},
                headers={"Authorization": [f"Bearer {jeton}"]})
            membres += page
            if len(page) < PAGE:
                return membres
            debut += PAGE

    async def synchroniser(self):
        from synapse.types import UserID, create_requester  # importé ici : les règles restent testables sans Synapse

        try:
            jeton = await self._jeton()
            agents = [a for a in await self._membres(jeton, "agent") if a.get("enabled")]
            responsables = {a["id"] for a in await self._membres(jeton, "responsable") if a.get("enabled")}
        except Exception as erreur:
            logger.warning("Annuaire Keycloak injoignable, aucune modification : %s", erreur)
            return

        comptes = dict(await self.api.run_db_interaction("comptes_lies", self._comptes_lies, self.fournisseur))
        autorises = {a["id"]: a for a in agents}

        for mxid in comptes_a_revoquer(comptes, autorises):
            logger.info("Révocation de %s : compte désactivé ou retiré dans l'annuaire", mxid)
            await self.api._hs.get_deactivate_account_handler().deactivate_account(
                mxid, erase_data=False, requester=create_requester(mxid), by_admin=True)

        RESPONSABLES.clear()
        RESPONSABLES.update(mxid for externe, mxid in comptes.items() if externe in responsables)

        for externe, mxid in comptes.items():
            if externe not in autorises:
                continue
            nom = nom_affiche(autorises[externe])
            profil = await self.api.get_profile_for_user(UserID.from_string(mxid).localpart)
            if profil.display_name != nom:
                await self.api.set_displayname(UserID.from_string(mxid), nom)

    @staticmethod
    def _comptes_lies(txn, fournisseur):
        txn.execute("SELECT x.external_id, x.user_id FROM user_external_ids x JOIN users u ON u.name = x.user_id"
                    " WHERE x.auth_provider = ? AND u.deactivated = 0", (fournisseur,))
        return txn.fetchall()
