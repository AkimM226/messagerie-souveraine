"""Outil d'administration de la messagerie souveraine.

Usage : docker compose run --rm admin revoquer <identifiant>

Révocation immédiate d'un agent, en deux temps :
  1. Keycloak : compte désactivé + toutes ses sessions fermées -> il ne peut plus se reconnecter.
  2. Synapse  : compte désactivé -> tous ses appareils sont déconnectés, leurs clés de
     chiffrement supprimées, et il quitte tous ses salons. Les autres membres renouvellent
     alors la clé de groupe (Megolm) : il ne peut plus lire aucun nouveau message.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

KEYCLOAK = "http://keycloak:8080"  # accès direct : l'API admin est bloquée sur le proxy public
SYNAPSE = "http://synapse:8008"   # accès direct, interne au réseau Docker (l'API admin n'est pas exposée)
REALM = "administration"
IDP_SYNAPSE = "oidc-keycloak"   # nom du fournisseur d'identité dans Synapse (idp_id préfixé "oidc-")


def appel(methode, url, jeton=None, corps=None, formulaire=None):
    """Envoie une requête HTTP et renvoie la réponse JSON (ou None si vide)."""
    entetes = {}
    donnees = None
    if jeton:
        entetes["Authorization"] = f"Bearer {jeton}"
    if corps is not None:
        donnees = json.dumps(corps).encode()
        entetes["Content-Type"] = "application/json"
    elif formulaire is not None:
        donnees = urllib.parse.urlencode(formulaire).encode()
    requete = urllib.request.Request(url, data=donnees, headers=entetes, method=methode)
    with urllib.request.urlopen(requete, timeout=15) as reponse:
        contenu = reponse.read()
    return json.loads(contenu) if contenu else None


def jeton_keycloak():
    """Connexion de l'administrateur Keycloak (compte technique défini dans .env)."""
    reponse = appel("POST", f"{KEYCLOAK}/realms/master/protocol/openid-connect/token", formulaire={
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": os.environ["KEYCLOAK_ADMIN"],
        "password": os.environ["KEYCLOAK_ADMIN_PASSWORD"],
    })
    return reponse["access_token"]


def revoquer(identifiant):
    jeton = jeton_keycloak()
    base = f"{KEYCLOAK}/admin/realms/{REALM}/users"
    trouves = appel("GET", f"{base}?exact=true&username={urllib.parse.quote(identifiant)}", jeton)
    if not trouves:
        sys.exit(f"Agent inconnu : {identifiant}")
    agent_id = trouves[0]["id"]

    appel("PUT", f"{base}/{agent_id}", jeton, corps={"enabled": False})
    appel("POST", f"{base}/{agent_id}/logout", jeton)
    print(f"[Keycloak] {identifiant} désactivé, sessions fermées.")

    jeton_synapse = os.environ.get("SYNAPSE_ADMIN_TOKEN")
    if not jeton_synapse:
        sys.exit("SYNAPSE_ADMIN_TOKEN manquant dans .env : révocation Synapse NON effectuée.")
    # On retrouve le compte Matrix par l'identifiant Keycloak (et non par le nom, qui peut
    # avoir été réattribué) : on est sûr de révoquer exactement le compte de cet agent.
    try:
        lien = appel("GET", f"{SYNAPSE}/_synapse/admin/v1/auth_providers/{IDP_SYNAPSE}/users/{agent_id}",
                     jeton_synapse)
    except urllib.error.HTTPError as erreur:
        if erreur.code != 404:
            raise
        print("[Synapse] Aucun compte : l'agent ne s'était jamais connecté à la messagerie.")
        return
    mxid = lien["user_id"]
    appel("POST", f"{SYNAPSE}/_synapse/admin/v1/deactivate/{urllib.parse.quote(mxid)}",
          jeton_synapse, corps={"erase": False})
    print(f"[Synapse] {mxid} désactivé : appareils déconnectés, salons quittés.")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "revoquer":
        sys.exit(__doc__)
    revoquer(sys.argv[2])
