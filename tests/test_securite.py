"""Tests de sécurité sur la messagerie en marche, par les mêmes adresses HTTPS qu'un navigateur.

Lancer (la pile doit tourner) : docker compose run --rm tests

Chaque test crée ses propres agents fictifs « essai-... » dans Keycloak (comme le ferait un
administrateur), se connecte comme un vrai navigateur (mot de passe + code TOTP), puis vérifie le
comportement réel du serveur. Les agents d'essai sont supprimés de Keycloak à la fin.
"""
import hashlib
import hmac
import http.cookiejar
import json
import os
import re
import secrets
import ssl
import struct
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

AUTORITE = "/caddy/caddy/pki/authorities/local/root.crt"   # autorité de certification interne (Caddy)
MATRIX = "https://matrix.localhost"
AUTH = "https://auth.localhost"
KEYCLOAK_INTERNE = "http://keycloak:8080"
REALM = "administration"
MOT_DE_PASSE = "Essai-Auto-2026!"
CONTEXTE_TLS = ssl.create_default_context(cafile=AUTORITE) if os.path.exists(AUTORITE) else None


def totp(secret, instant=None):
    """Code à 6 chiffres (RFC 6238, HMAC-SHA1, 30 s) : ce que calcule une application d'authentification."""
    compteur = struct.pack(">Q", int(instant or time.time()) // 30)
    empreinte = hmac.new(secret.encode(), compteur, hashlib.sha1).digest()
    decalage = empreinte[-1] & 0x0F
    return "%06d" % ((struct.unpack(">I", empreinte[decalage:decalage + 4])[0] & 0x7FFFFFFF) % 1000000)


class Formulaire(HTMLParser):
    """Récupère le premier formulaire de la page : adresse d'envoi et champs pré-remplis."""

    def __init__(self, page):
        super().__init__()
        self.action, self.champs = None, {}
        self.feed(page)

    def handle_starttag(self, balise, attributs):
        attributs = dict(attributs)
        if balise == "form" and self.action is None:
            self.action = attributs.get("action", "").replace("&amp;", "&")
        elif balise == "input" and self.action is not None and attributs.get("name"):
            self.champs.setdefault(attributs["name"], attributs.get("value") or "")


class Navigateur:
    """Un navigateur minimal : cookies, redirections, HTTPS vérifié avec l'autorité interne."""

    def __init__(self):
        self.ouvreur = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                                   urllib.request.HTTPSHandler(context=CONTEXTE_TLS))

    def ouvrir(self, url, champs=None):
        donnees = urllib.parse.urlencode(champs).encode() if champs is not None else None
        try:
            with self.ouvreur.open(url, donnees, timeout=20) as reponse:
                return reponse.status, reponse.geturl(), reponse.read().decode()
        except urllib.error.HTTPError as erreur:
            return erreur.code, erreur.geturl(), erreur.read().decode(errors="replace")


def connexion(identifiant, secret_totp=None, code=None, navigateur=None):
    """Connexion à la messagerie par Keycloak. Renvoie (jeton Matrix ou None, secret TOTP, dernière page)."""
    nav = navigateur or Navigateur()
    _, url, page = nav.ouvrir(f"{MATRIX}/_matrix/client/v3/login/sso/redirect/oidc-keycloak?"
                            + urllib.parse.urlencode({"redirectUrl": "https://chat.localhost/"}))
    for _ in range(4):
        jeton_connexion = re.search(r"loginToken=([\w.\-~]+)", url + page)
        if jeton_connexion:
            for _ in range(5):
                code, reponse = api("POST", "/login", corps={"type": "m.login.token", "token": jeton_connexion.group(1)})
                if code != 429:
                    break
                time.sleep(reponse.get("retry_after_ms", 2000) / 1000)   # limite de connexions du serveur
            return reponse.get("access_token"), secret_totp, page
        formulaire = Formulaire(page)
        if not formulaire.action:
            return None, secret_totp, page          # page d'erreur : connexion refusée
        champs = formulaire.champs
        if "username" in champs:
            champs.update(username=identifiant, password=MOT_DE_PASSE)
        elif "totpSecret" in champs:                # premier login : enregistrement de l'application TOTP
            secret_totp = champs["totpSecret"]
            champs.update(totp=code or totp(secret_totp), userLabel="essai")
        elif "otp" in champs:
            champs["otp"] = code or totp(secret_totp)
        else:
            return None, secret_totp, page
        _, url, page = nav.ouvrir(formulaire.action, champs)
    return None, secret_totp, page


def api(methode, chemin, jeton=None, corps=None):
    """Appel à l'API Matrix publique. Renvoie (code HTTP, réponse JSON)."""
    requete = urllib.request.Request(f"{MATRIX}/_matrix/client/v3{chemin}", method=methode,
                                     data=json.dumps(corps).encode() if corps is not None else None,
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {jeton}"} if jeton else {})})
    try:
        with urllib.request.urlopen(requete, timeout=20, context=CONTEXTE_TLS) as reponse:
            return reponse.status, json.loads(reponse.read() or b"{}")
    except urllib.error.HTTPError as erreur:
        contenu = erreur.read()
        try:
            return erreur.code, json.loads(contenu)
        except ValueError:
            return erreur.code, {}


class Keycloak:
    """Administration Keycloak par le réseau interne, comme l'outil d'administration."""

    def __init__(self):
        self.jeton, self.expiration = None, 0

    def _appel(self, methode, chemin, corps=None, formulaire=None):
        entetes, donnees = {}, None
        if formulaire is None:
            if time.time() > self.expiration:          # le jeton d'administration ne vit que 60 s
                self.jeton = self._appel("POST", "/realms/master/protocol/openid-connect/token", formulaire={
                    "grant_type": "password", "client_id": "admin-cli", "username": os.environ["KEYCLOAK_ADMIN"],
                    "password": os.environ["KEYCLOAK_ADMIN_PASSWORD"]})["access_token"]
                self.expiration = time.time() + 45
            entetes["Authorization"] = f"Bearer {self.jeton}"
        if corps is not None:
            donnees, entetes["Content-Type"] = json.dumps(corps).encode(), "application/json"
        elif formulaire is not None:
            donnees = urllib.parse.urlencode(formulaire).encode()
        requete = urllib.request.Request(KEYCLOAK_INTERNE + chemin, data=donnees, headers=entetes, method=methode)
        with urllib.request.urlopen(requete, timeout=20) as reponse:
            contenu = reponse.read()
        return json.loads(contenu) if contenu else None

    def creer_agent(self, roles, direction="Service des essais"):
        identifiant = "essai-" + secrets.token_hex(3)
        self._appel("POST", f"/admin/realms/{REALM}/users", corps={
            "username": identifiant, "firstName": "Essai", "lastName": identifiant.split("-")[1].upper(),
            "enabled": True, "attributes": {"ministere": ["Ministère des essais"], "direction": [direction],
                                            "fonction": ["Agent d'essai"]},
            "credentials": [{"type": "password", "value": MOT_DE_PASSE, "temporary": False}]})
        agent = self._appel("GET", f"/admin/realms/{REALM}/users?exact=true&username={identifiant}")[0]
        if roles:
            self._appel("POST", f"/admin/realms/{REALM}/users/{agent['id']}/role-mappings/realm",
                        corps=[self._appel("GET", f"/admin/realms/{REALM}/roles/{r}") for r in roles])
        return identifiant, agent["id"]

    def desactiver(self, agent_id):
        """Exactement ce que fait l'administrateur en décochant « Activé » dans la console."""
        self._appel("PUT", f"/admin/realms/{REALM}/users/{agent_id}", corps={"enabled": False})

    def supprimer(self, agent_id):
        self._appel("DELETE", f"/admin/realms/{REALM}/users/{agent_id}")


def attendre(condition, delai=20):
    """Attend qu'une condition devienne vraie ; renvoie le temps écoulé en secondes, ou None."""
    debut = time.time()
    while time.time() - debut < delai:
        if condition():
            return time.time() - debut
        time.sleep(0.5)
    return None


@unittest.skipUnless(CONTEXTE_TLS, "à lancer avec : docker compose run --rm tests")
class TestIntrus(unittest.TestCase):
    def test_inscription_libre_refusee(self):
        code, reponse = api("POST", "/register", corps={"username": "pirate", "password": "x" * 12})
        self.assertEqual(code, 403, reponse)

    def test_connexion_par_mot_de_passe_matrix_impossible(self):
        _, flux = api("GET", "/login")
        self.assertNotIn("m.login.password", [f["type"] for f in flux["flows"]])
        code, _ = api("POST", "/login", corps={"type": "m.login.password", "user": "awa.ouedraogo",
                                                "password": "Demo-Agent-2026!"})
        self.assertGreaterEqual(code, 400)

    def test_consoles_d_administration_non_exposees(self):
        nav = Navigateur()
        for url in (f"{MATRIX}/_synapse/admin/v1/server_version", f"{AUTH}/admin/master/console/",
                    f"{AUTH}/realms/master/protocol/openid-connect/token"):
            self.assertEqual(nav.ouvrir(url)[0], 403, url)

    def test_faux_jeton_refuse(self):
        code, reponse = api("GET", "/account/whoami", jeton="syt_" + secrets.token_urlsafe(30))
        self.assertEqual((code, reponse.get("errcode")), (401, "M_UNKNOWN_TOKEN"))

    def test_compte_non_enrole_refuse(self):
        kc = Keycloak()
        identifiant, agent_id = kc.creer_agent(roles=[])     # existe dans Keycloak, mais sans le rôle « agent »
        self.addCleanup(kc.supprimer, agent_id)
        jeton, secret, page = connexion(identifiant)
        self.assertIsNotNone(secret, "le 2FA a bien été exigé")
        self.assertIsNone(jeton, "un compte sans rôle agent ne doit pas entrer")
        self.assertIn("Accès refusé", page, "c'est la messagerie (Synapse) qui refuse, après Keycloak")

    def test_mauvais_code_2fa_refuse(self):
        kc = Keycloak()
        identifiant, agent_id = kc.creer_agent(roles=["agent"])
        self.addCleanup(kc.supprimer, agent_id)
        jeton, _, page = connexion(identifiant, code="000000")
        self.assertIsNone(jeton)
        self.assertIn("totpSecret", page, "on reste bloqué à l'étape du code")

    def test_pas_de_reconnexion_silencieuse_sur_un_poste_partage(self):
        # Après une session, le même navigateur doit redemander identifiant, mot de passe et code.
        kc = Keycloak()
        identifiant, agent_id = kc.creer_agent(roles=["agent"])
        self.addCleanup(kc.supprimer, agent_id)
        nav = Navigateur()
        self.assertIsNotNone(connexion(identifiant, navigateur=nav)[0])
        _, url, page = nav.ouvrir(f"{MATRIX}/_matrix/client/v3/login/sso/redirect/oidc-keycloak?"
                                  + urllib.parse.urlencode({"redirectUrl": "https://chat.localhost/"}))
        self.assertNotIn("loginToken=", url + page, "aucune connexion sans mot de passe ni code")
        self.assertIn("username", Formulaire(page).champs)


@unittest.skipUnless(CONTEXTE_TLS, "à lancer avec : docker compose run --rm tests")
class TestAgents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kc = Keycloak()
        cls.direction = "Service des essais " + secrets.token_hex(2)
        cls.responsable, cls.responsable_id = cls.kc.creer_agent(["agent", "responsable"], cls.direction)
        cls.agent, cls.agent_id = cls.kc.creer_agent(["agent"], cls.direction)
        cls.jeton_r = connexion(cls.responsable)[0]
        cls.jeton_a = connexion(cls.agent)[0]
        assert cls.jeton_r and cls.jeton_a, "connexion des agents d'essai impossible"
        cls.mxid_a = api("GET", "/account/whoami", cls.jeton_a)[1]["user_id"]
        # La liste des responsables est relue toutes les 5 s par le serveur.
        time.sleep(7)

    @classmethod
    def tearDownClass(cls):
        for agent_id in (cls.responsable_id, cls.agent_id):
            cls.kc.supprimer(agent_id)

    def creer_salon(self, jeton, **options):
        return api("POST", "/createRoom", jeton, {"preset": "private_chat", **options})

    def test_salons_chiffres_par_defaut(self):
        code, salon = self.creer_salon(self.jeton_a, name="Essai chiffrement")
        self.assertEqual(code, 200)
        code, etat = api("GET", f"/rooms/{salon['room_id']}/state/m.room.encryption/", self.jeton_a)
        self.assertEqual((code, etat.get("algorithm")), (200, "m.megolm.v1.aes-sha2"))

    def test_message_en_clair_refuse_par_le_serveur(self):
        salon = self.creer_salon(self.jeton_a, name="Essai clair")[1]["room_id"]
        code, _ = api("PUT", f"/rooms/{salon}/send/m.room.message/{secrets.token_hex(4)}", self.jeton_a,
                      {"msgtype": "m.text", "body": "texte en clair"})
        self.assertEqual(code, 403)

    def test_nom_affiche_vient_de_l_annuaire(self):
        attendu = f"Essai {self.agent.split('-')[1].upper()} · Agent d'essai · {self.direction} · Ministère des essais"
        self.assertIsNotNone(attendre(
            lambda: api("GET", f"/profile/{self.mxid_a}/displayname", self.jeton_a)[1].get("displayname") == attendu))
        code, _ = api("PUT", f"/profile/{self.mxid_a}/displayname", self.jeton_a, {"displayname": "Le Ministre"})
        self.assertGreaterEqual(code, 400, "un agent ne doit pas pouvoir changer son nom affiché")
        # Ni par un nom propre à un salon : le serveur remet le nom de l'annuaire.
        salon = self.creer_salon(self.jeton_a, name="Essai nom")[1]["room_id"]
        api("PUT", f"/rooms/{salon}/state/m.room.member/{self.mxid_a}", self.jeton_a,
            {"membership": "join", "displayname": "Le Ministre"})
        membre = api("GET", f"/rooms/{salon}/state/m.room.member/{self.mxid_a}", self.jeton_a)[1]
        self.assertEqual(membre.get("displayname"), attendu)

    def test_annuaire_recherche_par_service(self):
        trouve = lambda: any(r["user_id"] == self.mxid_a for r in api(
            "POST", "/user_directory/search", self.jeton_r, {"search_term": self.direction})[1].get("results", []))
        self.assertIsNotNone(attendre(trouve))
        self.assertEqual(api("POST", "/user_directory/search", None, {"search_term": self.direction})[0], 401)

    def test_seul_un_responsable_classifie_un_salon(self):
        code, _ = self.creer_salon(self.jeton_a, name="[CONFIDENTIEL] Essai agent")
        self.assertEqual(code, 403, "un agent simple ne peut pas créer de salon classifié")
        code, salon = self.creer_salon(self.jeton_r, name="[CONFIDENTIEL] Essai responsable")
        self.assertEqual(code, 200)
        salon = salon["room_id"]
        self.assertEqual(api("PUT", f"/rooms/{salon}/state/m.room.name/", self.jeton_r, {"name": "Déclassé"})[0], 403)
        self.assertEqual(api("PUT", f"/rooms/{salon}/state/m.room.join_rules/", self.jeton_r,
                             {"join_rule": "public"})[0], 403)

    def test_circuit_installe_dans_les_salons_classifies(self):
        salon = self.creer_salon(self.jeton_r, name="[DIFFUSION RESTREINTE] Essai circuit")[1]["room_id"]
        widget = lambda: api("GET", f"/rooms/{salon}/state/im.vector.modular.widgets/circuit", self.jeton_r)
        self.assertIsNotNone(attendre(lambda: widget()[0] == 200, 10))
        self.assertTrue(widget()[1]["url"].startswith("https://circuit.localhost/"))
        piege = {"type": "m.custom", "url": "https://site-externe.example/", "name": "Piège"}
        self.assertEqual(api("PUT", f"/rooms/{salon}/state/im.vector.modular.widgets/circuit", self.jeton_r, piege)[0], 403)
        self.assertEqual(api("PUT", f"/rooms/{salon}/state/im.vector.modular.widgets/autre", self.jeton_r, piege)[0], 403)
        self.assertEqual(api("PUT", f"/rooms/{salon}/state/m.widget/autre", self.jeton_r, piege)[0], 403)
        with urllib.request.urlopen("https://circuit.localhost/", timeout=20, context=CONTEXTE_TLS) as page:
            # La page du circuit ne peut être affichée que dans la messagerie (pas sur un site tiers).
            self.assertIn("frame-ancestors https://chat.localhost", page.headers["Content-Security-Policy"])

    def test_revocation_depuis_la_console_coupe_toutes_les_sessions(self):
        identifiant, agent_id = self.kc.creer_agent(["agent"], self.direction)
        self.addCleanup(self.kc.supprimer, agent_id)
        jeton_1, secret, _ = connexion(identifiant)
        time.sleep(30 - time.time() % 30 + 1)   # un code TOTP ne sert qu'une fois : on attend le suivant
        jeton_2 = connexion(identifiant, secret_totp=secret)[0]   # second appareil (autre navigateur)
        self.assertTrue(jeton_1 and jeton_2 and jeton_1 != jeton_2)
        mxid = api("GET", "/account/whoami", jeton_1)[1]["user_id"]
        salon = self.creer_salon(self.jeton_r, name="Essai groupe", invite=[mxid])[1]["room_id"]
        self.assertEqual(api("POST", f"/join/{salon}", jeton_1, {})[0], 200)

        self.kc.desactiver(agent_id)
        delai = attendre(lambda: api("GET", "/account/whoami", jeton_1)[0] == 401)
        self.assertIsNotNone(delai, "les sessions doivent être coupées en moins de 20 s")
        print(f"\n  révocation effective en {delai:.1f} s")
        self.assertEqual(api("GET", "/account/whoami", jeton_2)[0], 401, "second appareil")
        self.assertEqual(api("GET", "/sync?timeout=0", jeton_1)[0], 401, "plus aucune réception")
        # Synapse retire ensuite le compte de tous ses salons, en tâche de fond.
        adhesion = lambda: [m["content"]["membership"] for m in api("GET", f"/rooms/{salon}/members", self.jeton_r)[1]["chunk"]
                            if m["state_key"] == mxid]
        self.assertIsNotNone(attendre(lambda: adhesion() == ["leave"]), "l'agent doit quitter le groupe")
        self.assertIsNone(connexion(identifiant)[0], "reconnexion impossible sans nouvel enrôlement")


if __name__ == "__main__":
    unittest.main()
