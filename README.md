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

Puis ouvrir http://chat.localhost. Gestion des agents (poste serveur uniquement) : http://localhost:8081/admin.

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

Pour la démo, http://chat2.localhost ouvre un second accès : deux agents côte à côte dans le même navigateur.
