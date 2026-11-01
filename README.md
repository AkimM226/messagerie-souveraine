# Messagerie souveraine de l'administration

Messagerie instantanée chiffrée de bout en bout pour les agents publics du Burkina Faso, hébergée sur
l'infrastructure de l'État, sans aucun service tiers. Sprint pré-hackathon — Hackathon 226, édition 2026.

## Fonctionnalités

- **Messages, groupes et fichiers chiffrés de bout en bout** (Matrix Olm/Megolm) : le serveur ne stocke que du chiffré
  et refuse tout message envoyé en clair dans un salon chiffré.
- **Enrôlement et 2FA** : pas d'inscription libre ; seuls les agents créés dans Keycloak avec le rôle `agent` entrent.
  Mot de passe **et** code TOTP à chaque connexion ; la déconnexion ferme aussi la session Keycloak (poste partagé).
- **Rôles vérifiés par le serveur** : `agent`, `responsable` (seul à créer un salon classifié), `admin-securite`
  (enrôle, révoque, consulte le journal dans la console Keycloak).
- **Révocation centralisée** : désactiver un agent coupe ses sessions sur tous ses appareils en moins de 5 s ;
  il quitte ses groupes, dont les membres changent de clé.
- **Innovation — circuit administratif chiffré** : instructions, notes, convocations, demandes d'action avec priorité,
  échéance et accusés (Reçu, Pris connaissance, En cours, Exécuté, Clarification) suivis par l'émetteur. Le serveur ne
  distingue même pas une instruction d'un message ordinaire.
- **Classification** : dans un salon `[DIFFUSION RESTREINTE] …` ou `[CONFIDENTIEL] …`, les messages expirent ; ni
  déclassement, ni salon public, ni réaction (non chiffrée) ; filigrane nominatif ; le circuit s'affiche en haut du salon.
- **Annuaire institutionnel** imposé par l'administration (« Prénom Nom · fonction · direction · ministère »),
  **journal** sans contenu, **sauvegarde**, identité visuelle commune (`design/jetons.css`).

## Architecture

```
Navigateur de l'agent : Element (chiffre / déchiffre) + widget « circuit administratif »
      │ HTTPS
      ▼
Caddy (point d'entrée, autorité de certification interne)
 ├─► Synapse (serveur Matrix, ne voit que du chiffré) ─► PostgreSQL
 │     modules/annuaire.py        : Keycloak fait foi (révocations, noms, responsables)
 │     modules/classification.py  : niveaux, expiration, refus du clair, installation du circuit
 └─► Keycloak (agents enrôlés, TOTP, rôles, journal) — console d'administration sur le poste serveur seulement
```

## Technologies et licences

| Composant | Rôle | Licence |
|---|---|---|
| [Element Web](https://github.com/element-hq/element-web) 1.11.85 | Client, chiffrement Olm/Megolm (vodozemac) | AGPL-3.0 / GPL-3.0 |
| [Synapse](https://github.com/element-hq/synapse) 1.120.0 | Serveur Matrix | AGPL-3.0 |
| [Keycloak](https://www.keycloak.org) 26.0.7 | Identité, TOTP, rôles, journal | Apache-2.0 |
| [PostgreSQL](https://www.postgresql.org) 16 | Base de données | PostgreSQL License |
| [Caddy](https://caddyserver.com) 2.8.4 | Proxy inverse, HTTPS | Apache-2.0 |
| [matrix-widget-api](https://github.com/matrix-org/matrix-widget-api) 1.10.0 | Widget ↔ Element (`circuit/vendor/`) | Apache-2.0 |
| [Inter](https://rsms.me/inter/) 4 | Police de l'interface (`design/polices/`) | OFL-1.1 |
| [Docker Compose](https://github.com/docker/compose) · [Python](https://www.python.org) 3.12 | Installation · modules, outils, tests | Apache-2.0 · PSF-2.0 |

**Aucune cryptographie écrite par l'équipe** : Olm/Megolm sont implémentés par Element. **Engagement open source :
« Étendre et adapter »** — briques éprouvées, configuration durcie, deux modules Synapse et un widget originaux,
sous licence MIT (`LICENSE`).

## Installation (une commande)

```bash
docker compose up -d
docker compose cp proxy:/data/caddy/pki/authorities/local/root.crt ./autorite-locale.crt   # une fois :
certutil -addstore -user Root autorite-locale.crt                                          # faire confiance au HTTPS local
```

Puis ouvrir https://chat.localhost (sous Linux : `update-ca-certificates`). En production : domaines de l'État et
secrets de `.env` changés (modèle `.env.example`). Les horloges doivent être à l'heure (TOTP).

## Comptes de démonstration (fictifs)

Mot de passe commun : `Demo-Agent-2026!` ; chaque agent enregistre une application TOTP à sa première connexion.

| Identifiant | Rôles | Fiche |
|---|---|---|
| admin.securite | agent, admin-securite | Administrateur sécurité · DSI · MTDPCE |
| awa.ouedraogo | agent, responsable | Cheffe de service · DRH · MTDPCE |
| ibrahim.sawadogo | agent | Gestionnaire du personnel · DRH · MTDPCE |
| fatimata.kabore | agent | Chargée de communication · DR du Centre · Ministère de la Santé |
| visiteur.intrus | aucun → refusé | — |

## Administration et tests

Console : http://localhost:8081/admin/administration/console/ (poste serveur, compte `admin.securite`). En commande :
`docker compose run --rm admin enroler <id> "<Prénom>" "<Nom>" "<Ministère>" "<Direction>" "<Fonction>" [responsable]`,
`… admin revoquer <id>`, `… admin journal` ; sauvegarde : `sh scripts/sauvegarde.sh`.

```bash
docker compose run --rm tests                   # 25 tests sur la pile : intrus, 2FA, chiffrement, révocation…
sh scripts/verifier.sh contenu "CHAINE-UNIQUE"  # le serveur ne lit rien (base, fichiers, journaux)
sh scripts/verifier.sh cles "Nom du salon"      # nouvelle clé Megolm après une révocation
```

Détails : [`docs/verification.md`](docs/verification.md) et [`docs/note-securite.pdf`](docs/note-securite.pdf).

## Limites connues et améliorations en cours

Nous continuons de travailler à réduire chacune de ces limites :

- Un appareil connecté **après** un message ne peut pas le lire → sauvegarde des clés chiffrée, protégée par une phrase
  de récupération. Ce qui était déjà déchiffré sur un appareil révoqué hors ligne y reste → effacement à distance.
- Une photo d'écran reste possible (le filigrane identifie l'agent) → application mobile bloquant les captures.
- Le serveur voit des métadonnées (membres et noms des salons, horodatages, tailles) → réduction continue, détaillée
  dans la note de sécurité.
- Keycloak en mode développement, un seul serveur → passage en production (base dédiée, haute disponibilité) ;
  `config/element/index.html` suit Element 1.11.85 et sera mis à jour avec Element.
