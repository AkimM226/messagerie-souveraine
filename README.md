# Messagerie souveraine de l'administration

Messagerie instantanée chiffrée de bout en bout pour les agents publics du Burkina Faso, hébergée sur
l'infrastructure de l'État, sans aucun service tiers. Projet du sprint pré-hackathon — Hackathon 226, édition 2026.

## Fonctionnalités

- **Messages, groupes et fichiers chiffrés de bout en bout** (Matrix Olm/Megolm) : le serveur ne stocke que du chiffré
  et refuse tout message envoyé en clair dans un salon chiffré.
- **Enrôlement contrôlé** : pas d'inscription libre ; seuls les agents créés par un administrateur dans Keycloak,
  avec le rôle `agent`, entrent. **Second facteur TOTP obligatoire**, blocage après 5 échecs.
- **Rôles vérifiés par le serveur** : `agent`, `responsable` (seul habilité à créer un salon classifié), `admin-securite`
  (enrôle, révoque, consulte le journal dans la console Keycloak du domaine).
- **Révocation centralisée** : désactiver un agent dans la console (ou en une commande) coupe toutes ses sessions sur
  tous ses appareils en moins de 5 s ; il quitte ses groupes et les autres membres changent de clé de groupe.
- **Innovation — circuit administratif chiffré** : instructions de service, notes, convocations, demandes d'action,
  avec priorité, échéance et **accusés de prise de connaissance** (Reçu, Pris connaissance, En cours, Exécuté,
  Clarification) et un tableau de suivi pour l'émetteur. Tout reste chiffré : le serveur ne distingue même pas
  une instruction d'un message ordinaire.
- **Classification** : `[DIFFUSION RESTREINTE]` et `[CONFIDENTIEL]` en tête du nom d'un salon → expiration
  automatique des messages, pas de déclassement, pas de salon public, pas de réaction (transmise en clair par Matrix),
  filigrane nominatif sur les communications confidentielles. Sans préfixe : niveau standard.
- **Annuaire institutionnel** alimenté par les administrateurs : chaque agent apparaît sous la forme
  « Prénom Nom · fonction · direction · ministère », recherchable dans Element ; un agent ne peut pas changer son nom.
- **Journal administratif** (enrôlements, révocations, connexions ; aucun contenu), **sauvegarde et restauration**.
- **Identité visuelle institutionnelle** : un design system unique (`design/jetons.css` : navy, émeraude, or, police Inter
  hébergée localement) appliqué au thème d'Element, à la page de connexion (thème Keycloak `souverain`) et au circuit.

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
| Element Web 1.11.85 | Client, chiffrement Olm/Megolm (vodozemac) | AGPL-3.0 / GPL-3.0 |
| Synapse 1.120.0 | Serveur Matrix | AGPL-3.0 |
| Keycloak 26.0.7 | Identité, TOTP, rôles, journal | Apache-2.0 |
| PostgreSQL 16 | Base de données | PostgreSQL License |
| Caddy 2.8.4 | Proxy inverse, HTTPS | Apache-2.0 |
| matrix-widget-api 1.10.0 | Dialogue widget ↔ Element (fichier dans `circuit/vendor/`) | Apache-2.0 |
| Inter 4 (fontsource 5.1.0) | Police de l'interface (fichiers dans `design/polices/`) | OFL-1.1 |

**Chiffrement** : Matrix Olm (double ratchet entre appareils) et Megolm (groupes), implémentés par Element ;
le widget du circuit ne fait aucune cryptographie, Element chiffre ce qu'il envoie. **Aucune cryptographie écrite par l'équipe.**

**Engagement open source : « Étendre et adapter ».** Briques éprouvées, configuration durcie, deux modules
Synapse et un widget originaux. Notre code : licence MIT (`LICENSE`).

## Installation (une commande)

```bash
docker compose up -d
```

Puis ouvrir https://chat.localhost. Pour que le navigateur accepte l'autorité de certification interne (une fois) :

```bash
docker compose cp proxy:/data/caddy/pki/authorities/local/root.crt ./autorite-locale.crt
certutil -addstore -user Root autorite-locale.crt
```

(Sous Linux : copier dans `/usr/local/share/ca-certificates/` puis `update-ca-certificates`.) En production, remplacer
les noms `*.localhost` par les domaines de l'État et changer les secrets de `.env` (modèle : `.env.example`).
L'horloge du serveur et des téléphones doit être à l'heure : le code TOTP en dépend.

## Comptes de démonstration (fictifs)

Mot de passe commun : `Demo-Agent-2026!`. Au premier login, chaque agent enregistre une application TOTP.

| Identifiant | Rôles | Fiche |
|---|---|---|
| admin.securite | agent, admin-securite | Administrateur sécurité · DSI · MTDPCE |
| awa.ouedraogo | agent, responsable | Cheffe de service · DRH · MTDPCE |
| ibrahim.sawadogo | agent | Gestionnaire du personnel · DRH · MTDPCE |
| fatimata.kabore | agent | Chargée de communication · DR du Centre · Ministère de la Santé |
| visiteur.intrus | aucun → refusé | — |

## Administration (poste serveur)

- Console : http://localhost:8081/admin/administration/console/ (compte `admin.securite`, avec TOTP).
- `docker compose run --rm admin enroler <id> "<Prénom>" "<Nom>" "<Ministère>" "<Direction>" "<Fonction>" [responsable]`
- `docker compose run --rm admin revoquer <id>` · `docker compose run --rm admin journal`
- `sh scripts/sauvegarde.sh` · `sh scripts/sauvegarde.sh restaurer sauvegardes/<date>`

Circuit administratif : un responsable crée un salon `[CONFIDENTIEL] …` ou `[DIFFUSION RESTREINTE] …` ; le circuit
s'affiche en haut du salon (Element demande d'approuver ses permissions, une fois).

## Tests et preuves

```bash
python -m unittest discover tests      # règles (sans la pile)
docker compose run --rm tests          # 23 tests sur la pile en marche : intrus, 2FA, chiffrement, révocation…
sh scripts/verifier.sh contenu "CHAINE-UNIQUE"     # le serveur ne lit rien (base, fichiers, journaux)
sh scripts/verifier.sh cles "Nom du salon"         # nouvelle clé Megolm après une révocation
```

Détail des vérifications : [`docs/verification.md`](docs/verification.md). Menaces, métadonnées visibles et limites :
[`docs/note-securite.pdf`](docs/note-securite.pdf).

## Limites connues

- Un appareil connecté **après** l'envoi d'un message ne peut pas le déchiffrer (pas de sauvegarde de clés imposée).
- Après une révocation, ce qui était déjà déchiffré sur un appareil hors ligne y reste ; une photo de l'écran reste
  possible (le filigrane identifie la personne, il n'empêche rien).
- Après une déconnexion d'Element, la session Keycloak reste ouverte (24 h) : sur un poste partagé, la connexion
  suivante ne redemande ni mot de passe ni code. À régler côté Keycloak avant un usage réel.
- `config/element/index.html` est la page d'Element 1.11.85 complétée de notre feuille de style : à régénérer si
  l'on change de version d'Element.
- Le serveur voit des métadonnées : membres des salons, noms des salons, horodatages, tailles. Keycloak tourne en mode
  développement (base intégrée) et il n'y a qu'un serveur : à industrialiser pour la production.
