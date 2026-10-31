"""Outil d'administration de la messagerie souveraine (poste serveur).

Usage :
  docker compose run --rm admin enroler <identifiant> "<Prénom>" "<Nom>" "<Ministère>" "<Direction>" "<Fonction>" [responsable]
  docker compose run --rm admin revoquer <identifiant>
  docker compose run --rm admin journal [nombre]

La console Keycloak (http://localhost:8081/admin/administration/console/, compte admin.securite)
fait la même chose à la souris ; ces commandes servent aux démonstrations et aux scripts.

Révocation immédiate d'un agent :
  1. Keycloak : compte désactivé + toutes ses sessions fermées -> il ne peut plus se reconnecter.
  2. Synapse  : le module annuaire voit le compte désactivé (sous 5 s) et désactive le compte Matrix :
     tous ses appareils sont déconnectés, leurs clés supprimées, et il quitte tous ses salons. Les autres
     membres renouvellent alors la clé de groupe (Megolm) : il ne peut plus lire aucun nouveau message.
     Si SYNAPSE_ADMIN_TOKEN est renseigné, l'outil le fait lui-même, sans attendre.
"""
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

KEYCLOAK = "http://keycloak:8080"  # accès direct : l'API admin est bloquée sur le proxy public
SYNAPSE = "http://synapse:8008"   # accès direct, interne au réseau Docker (l'API admin n'est pas exposée)
REALM = "administration"
IDP_SYNAPSE = "oidc-keycloak"   # nom du fournisseur d'identité dans Synapse (idp_id préfixé "oidc-")
BASE = f"{KEYCLOAK}/admin/realms/{REALM}"


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


def trouver(jeton, identifiant):
    trouves = appel("GET", f"{BASE}/users?exact=true&username={urllib.parse.quote(identifiant)}", jeton)
    if not trouves:
        sys.exit(f"Agent inconnu : {identifiant}")
    return trouves[0]["id"]


def enroler(identifiant, prenom, nom, ministere, direction, fonction, *options):
    jeton = jeton_keycloak()
    provisoire = secrets.token_urlsafe(9)
    appel("POST", f"{BASE}/users", jeton, corps={
        "username": identifiant, "firstName": prenom, "lastName": nom, "enabled": True,
        "attributes": {"ministere": [ministere], "direction": [direction], "fonction": [fonction]},
        # Au premier login : nouveau mot de passe choisi par l'agent + enregistrement de son application TOTP.
        "requiredActions": ["UPDATE_PASSWORD", "CONFIGURE_TOTP"],
        "credentials": [{"type": "password", "value": provisoire, "temporary": True}],
    })
    roles = ["agent"] + (["responsable"] if "responsable" in options else [])
    appel("POST", f"{BASE}/users/{trouver(jeton, identifiant)}/role-mappings/realm", jeton,
          corps=[appel("GET", f"{BASE}/roles/{role}", jeton) for role in roles])
    print(f"Agent {identifiant} enrôlé (rôles : {', '.join(roles)}).")
    print(f"Mot de passe provisoire, à remettre en main propre : {provisoire}")


def revoquer(identifiant):
    jeton = jeton_keycloak()
    agent_id = trouver(jeton, identifiant)
    # Relancer la commande ne change rien : chaque étape est sans effet si elle est déjà faite.
    appel("PUT", f"{BASE}/users/{agent_id}", jeton, corps={"enabled": False})
    appel("POST", f"{BASE}/users/{agent_id}/logout", jeton)
    print(f"[Keycloak] {identifiant} désactivé, sessions fermées.")

    jeton_synapse = os.environ.get("SYNAPSE_ADMIN_TOKEN")
    if not jeton_synapse:
        print("[Synapse] Le serveur de messagerie coupe ses sessions et appareils sous 5 s (module annuaire).")
        return
    # On retrouve le compte Matrix par l'identifiant Keycloak (et non par le nom, qui peut
    # avoir été réattribué) : on est sûr de révoquer exactement le compte de cet agent.
    try:
        lien = appel("GET", f"{SYNAPSE}/_synapse/admin/v1/auth_providers/{IDP_SYNAPSE}/users/{agent_id}",
                     jeton_synapse)
    except urllib.error.HTTPError as erreur:
        if erreur.code == 404:
            print("[Synapse] Aucun compte : l'agent ne s'était jamais connecté à la messagerie.")
        else:   # jeton périmé ou sans droits d'administration : Keycloak est déjà fait, le module annuaire suit
            print(f"[Synapse] Jeton d'administration refusé ({erreur.code}) : le module annuaire coupe ses sessions sous 5 s.")
        return
    mxid = lien["user_id"]
    appel("POST", f"{SYNAPSE}/_synapse/admin/v1/deactivate/{urllib.parse.quote(mxid)}",
          jeton_synapse, corps={"erase": False})
    print(f"[Synapse] {mxid} désactivé : appareils déconnectés, salons quittés.")


def journal(nombre="30"):
    """Historique des enrôlements, modifications, révocations et connexions. Aucun contenu de conversation :
    Keycloak n'en a jamais eu connaissance."""
    jeton = jeton_keycloak()
    noms = {u["id"]: u["username"] for u in appel("GET", f"{BASE}/users?briefRepresentation=true&max=1000", jeton)}
    lignes = []
    for e in appel("GET", f"{BASE}/admin-events?max={int(nombre)}", jeton):
        fiche = json.loads(e.get("representation") or "{}") if e["resourceType"] == "USER" else {}
        cible_id = e["resourcePath"].split("/")[1] if e["resourcePath"].startswith("users/") else None
        cible = fiche.get("username") if isinstance(fiche, dict) and fiche.get("username") else noms.get(cible_id, e["resourcePath"])
        detail = " (compte désactivé)" if isinstance(fiche, dict) and fiche.get("enabled") is False else ""
        auteur = noms.get(e["authDetails"]["userId"], "administrateur technique")
        lignes.append((e["time"], f"ADMIN      {auteur} : {e['operationType']} {e['resourceType']} {cible}{detail}"))
    for e in appel("GET", f"{BASE}/events?max={int(nombre)}", jeton):
        erreur = f" ({e['error']})" if e.get("error") else ""
        qui = noms.get(e.get("userId"), e.get("details", {}).get("username", "?"))
        lignes.append((e["time"], f"CONNEXION  {qui} : {e['type']}{erreur} depuis {e.get('ipAddress', '?')}"))
    for instant, texte in sorted(lignes):
        print(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(instant / 1000)), "UTC ", texte)


COMMANDES = {"enroler": (enroler, 6, 7), "revoquer": (revoquer, 1, 1), "journal": (journal, 0, 1)}

if __name__ == "__main__":
    commande, arguments = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else (None, [])
    if commande not in COMMANDES or not COMMANDES[commande][1] <= len(arguments) <= COMMANDES[commande][2]:
        sys.exit(__doc__)
    COMMANDES[commande][0](*arguments)
