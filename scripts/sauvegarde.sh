#!/bin/sh
# Sauvegarde et restauration, à lancer sur le poste serveur depuis la racine du dépôt.
#
#   sh scripts/sauvegarde.sh                       -> crée sauvegardes/AAAAMMJJ-HHMMSS/
#   sh scripts/sauvegarde.sh restaurer <dossier>   -> remplace les données actuelles par la sauvegarde
#
# Contenu : base PostgreSQL (messages déjà chiffrés), fichiers Synapse (pièces jointes chiffrées, clé de
# signature du serveur), base Keycloak (agents, rôles, seconds facteurs), autorité de certification (Caddy).
# Une sauvegarde contient des clés privées du serveur : la garder sur un support chiffré, hors ligne.
# Aucune clé de déchiffrement des messages n'y figure : elles ne quittent jamais les appareils des agents.
set -eu
umask 077                   # sauvegardes lisibles par leur seul propriétaire (elles contiennent des clés privées)
export MSYS_NO_PATHCONV=1   # Git Bash (Windows) : ne pas transformer les chemins des conteneurs
cd "$(dirname "$0")/.."
projet=$(docker compose config --format json | sed -n 's/^ *"name": *"\([^"]*\)".*/\1/p' | head -1)
volume() { echo "${projet}_$1"; }
tar_volume() {   # tar_volume <volume> <c|x> <archive dans le dossier courant de sauvegarde>
	docker run --rm -v "$(volume "$1"):/v" -v "$PWD/$dossier:/sauvegarde" alpine:3.20 \
		sh -c "umask 077 && cd /v && tar $2zf /sauvegarde/$3 ."
}

if [ "${1:-}" = "restaurer" ]; then
	dossier="${2:?dossier de sauvegarde manquant}"
	printf 'Les données actuelles seront remplacées par %s. Tapez RESTAURER pour continuer : ' "$dossier"
	read -r reponse
	[ "$reponse" = "RESTAURER" ] || { echo "Abandon."; exit 1; }
	docker compose stop proxy synapse keycloak
	for v in synapse-data keycloak-data caddy-data; do
		docker run --rm -v "$(volume "$v"):/v" alpine:3.20 sh -c 'rm -rf /v/* /v/.[!.]* 2>/dev/null || true'
		tar_volume "$v" x "$v.tgz"
	done
	# Base recréée à l'identique (ce qui a été ajouté après la sauvegarde disparaît aussi).
	docker compose exec -T postgres sh -c 'dropdb -U synapse synapse && createdb -U synapse -E UTF8 --lc-collate=C --lc-ctype=C -T template0 synapse'
	docker compose exec -T postgres pg_restore -U synapse -d synapse --no-owner < "$dossier/base.dump"
	docker compose start keycloak synapse proxy
	echo "Restauration terminée depuis $dossier."
	exit 0
fi

dossier="sauvegardes/$(date +%Y%m%d-%H%M%S)"
mkdir -p -m 700 "$dossier"
docker compose exec -T postgres pg_dump -U synapse -Fc synapse > "$dossier/base.dump"
tar_volume synapse-data c synapse-data.tgz
tar_volume caddy-data c caddy-data.tgz
# Keycloak est arrêté quelques secondes pour copier sa base de façon cohérente ; la messagerie continue
# (le module annuaire ne modifie rien tant que Keycloak ne répond pas).
docker compose stop keycloak
tar_volume keycloak-data c keycloak-data.tgz
docker compose start keycloak
ls -l "$dossier"
echo "Sauvegarde terminée : $dossier"
