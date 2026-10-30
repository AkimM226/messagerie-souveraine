# Messagerie souveraine de l'administration

Messagerie instantanée chiffrée de bout en bout pour les agents publics du Burkina Faso,
hébergée sur l'infrastructure de l'État, sans aucun service tiers.
Projet du sprint pré-hackathon — Hackathon 226, édition 2026.

> Brouillon : README en cours de rédaction.

## Architecture

```
Navigateur (Element : chiffre/déchiffre)  ──►  Caddy (point d'entrée)
                                              ├─► Synapse  (serveur Matrix : ne voit que du chiffré) ─► PostgreSQL
                                              └─► Keycloak (agents enrôlés, 2FA, rôles, révocation)
```

## Technologies et licences

| Composant | Rôle | Licence | Projet |
|---|---|---|---|
| Element Web | Client, chiffrement Olm/Megolm | AGPL-3.0 / GPL-3.0 | https://github.com/element-hq/element-web |
| Synapse | Serveur Matrix | AGPL-3.0 | https://github.com/element-hq/synapse |
| Keycloak | Identité, 2FA, rôles | Apache-2.0 | https://github.com/keycloak/keycloak |
| PostgreSQL | Base de données | PostgreSQL License | https://www.postgresql.org |
| Caddy | Proxy inverse | Apache-2.0 | https://github.com/caddyserver/caddy |

Niveau d'engagement : **Étendre et adapter**. Notre code : MIT (voir `LICENSE`).

## Installation (une commande)

```bash
docker compose up -d
```

Puis ouvrir https://chat.localhost. Gestion des agents (poste serveur uniquement) : http://localhost:8081/admin.

## Innovation : salons classifiés à expiration automatique

Un agent classe un salon en commençant son nom par un niveau de classification :

| Niveau | Durée de vie des messages |
|---|---|
| `[CONFIDENTIEL] ...` | 5 min en démo (24 h conseillé en production) |
| `[DIFFUSION RESTREINTE] ...` | 7 jours |

Le module serveur [`modules/classification.py`](modules/classification.py) applique, sans jamais lire les messages :
- **expiration automatique** : les messages trop anciens sont supprimés sur tous les appareils
  (« Message supprimé »), puis leur contenu chiffré est effacé du serveur ;
- **pas de déclassement** : impossible de retirer ou d'assouplir le niveau d'un salon ;
- **pas de salon public** pour un salon classifié.

Les durées se règlent dans `config/synapse/homeserver.yaml` (section `modules`).

### HTTPS : faire confiance à l'autorité de certification locale (une fois)

Caddy génère sa propre autorité de certification (aucun service tiers). Pour que le navigateur l'accepte :

```bash
docker compose cp proxy:/data/caddy/pki/authorities/local/root.crt ./autorite-locale.crt
certutil -addstore -user Root autorite-locale.crt
```

(Windows ; sous Linux : copier dans `/usr/local/share/ca-certificates/` puis `update-ca-certificates`.)
En production, on remplace les noms `*.localhost` par les domaines de l'État dans `config/caddy/Caddyfile`.

## Comptes de démonstration (fictifs)

Mot de passe commun : `Demo-Agent-2026!`. Au premier login, chaque agent enregistre une
application TOTP (FreeOTP, Aegis, Google Authenticator).

| Identifiant | Rôle |
|---|---|
| admin.securite | agent + admin-securite |
| awa.ouedraogo | agent |
| ibrahim.sawadogo | agent |
| fatimata.kabore | agent |
| visiteur.intrus | aucun rôle → refusé par la messagerie |

## Révoquer un agent

Préparation (une seule fois) : se connecter avec `admin.securite`, puis
1. lui donner les droits d'administration du serveur :
   `docker compose exec postgres psql -U synapse -c "UPDATE users SET admin = 1 WHERE name = '@admin.securite:matrix.localhost';"`
2. copier son jeton (Element > Paramètres > Aide et à propos > Jeton d'accès) dans `.env` (`SYNAPSE_ADMIN_TOKEN=...`).

Révocation (immédiate, sur tous les appareils) :

```bash
docker compose run --rm admin revoquer ibrahim.sawadogo
```

Pour la démo, https://chat2.localhost ouvre un second accès : deux agents côte à côte dans le même navigateur.

## Tests automatisés

```bash
python -m unittest discover tests
```
