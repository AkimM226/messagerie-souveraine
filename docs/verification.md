# Vérifier soi-même

Chaque vérification se rejoue sur la pile en marche (`docker compose up -d`), depuis la racine du dépôt.
Sous Windows, lancer les scripts `sh` depuis Git Bash.

## 1. Le serveur ne lit rien

1. Dans Element, envoyer un message contenant une chaîne unique (ex. `TEST-JURY-4821`) et un fichier texte la contenant.
2. `sh scripts/verifier.sh contenu "TEST-JURY-4821"`

Résultat attendu : 0 occurrence dans la copie complète de la base, 0 fichier, 0 ligne de journal ; les messages sont
enregistrés en `m.room.encrypted` / `m.megolm.v1.aes-sha2`. Les pièces jointes sont stockées comme des blocs
`application/octet-stream`, sans leur nom. Le serveur refuse aussi un message en clair envoyé par un client modifié
(test `test_message_en_clair_refuse_par_le_serveur`). HTTPS protège en plus le transport, mais n'est pas la preuve :
c'est le chiffrement de bout en bout qui empêche le serveur de lire.

## 2. Révocation dans un groupe

1. Un groupe avec au moins trois agents, dont l'agent à révoquer connecté sur deux navigateurs (`chat.localhost`, `chat2.localhost`).
2. Révoquer : décocher « Activé » dans la console Keycloak, ou `docker compose run --rm admin revoquer <id>`.
3. En moins de 5 s, ses deux sessions reviennent à l'écran de connexion ; il quitte le groupe ; la reconnexion est refusée.
4. Un autre membre envoie un message, puis : `sh scripts/verifier.sh cles "Nom du groupe"`.

Résultat attendu : après la ligne « membre : leave », les messages utilisent une **nouvelle session Megolm** que
l'agent révoqué n'a jamais reçue. Test automatique : `test_revocation_depuis_la_console_coupe_toutes_les_sessions`
(deux sessions, ancien jeton refusé, plus de synchronisation, départ du groupe, reconnexion refusée).

## 3. Intrus

`docker compose run --rm tests test_securite.TestIntrus` : inscription refusée, connexion par mot de passe Matrix
impossible, API et consoles d'administration non exposées (403), faux jeton refusé, compte existant dans Keycloak mais
non enrôlé (sans rôle `agent`) refusé par la messagerie, mauvais code TOTP refusé. Avec le compte `visiteur.intrus`
dans le navigateur : « You are not allowed to log in here ».

## 4. Innovation : circuit administratif

1. `awa.ouedraogo` (responsable) crée un salon `[CONFIDENTIEL] Cellule RH` et invite deux agents, qui rejoignent le salon.
2. Le circuit apparaît en haut du salon : « Nouvelle communication administrative » → instruction de service, accusé demandé.
3. Chaque agent ouvre le circuit et clique « Pris connaissance » ; le responsable voit « 2/2 ont pris connaissance ».
4. `sh scripts/verifier.sh contenu "<mot du titre>"` : 0 occurrence ; même le type « bf.gouv.circuit » est invisible.

Les agents doivent être connectés au salon **avant** l'envoi de l'instruction (chiffrement de bout en bout).
Seuls les clics des destinataires comptent comme accusés, pas les confirmations de lecture automatiques d'Element.

## 5. Classification et rôles

`docker compose run --rm tests test_securite.TestAgents` : un agent simple ne peut pas classifier un salon (403),
un responsable le peut ; déclassement, ouverture au public et widget étranger refusés ; nom affiché imposé par l'annuaire.
Dans un salon `[CONFIDENTIEL]`, les messages disparaissent au bout de 5 minutes (durée de démonstration,
`config/synapse/homeserver.yaml`).
