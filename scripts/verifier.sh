#!/bin/sh
# Preuves pour le jury, à lancer sur le poste serveur depuis la racine du dépôt.
#
#   sh scripts/verifier.sh contenu "CHAINE-DE-CONTROLE"   le serveur ne lit rien
#       Cherche la chaîne (envoyée dans un message ou un fichier depuis Element) dans une copie
#       complète de la base, dans les fichiers stockés par Synapse et dans les journaux de tous les services.
#
#   sh scripts/verifier.sh cles "Nom du salon"            rotation des clés après une révocation
#       Liste, pour chaque message chiffré du salon, l'expéditeur et la session Megolm utilisée
#       (seule information de clé visible par le serveur), ainsi que les arrivées et départs.
set -eu
export MSYS_NO_PATHCONV=1   # Git Bash (Windows) : ne pas transformer /data en chemin Windows
cd "$(dirname "$0")/.."
sql() { docker compose exec -T postgres psql -U synapse -v ON_ERROR_STOP=1 "$@"; }

case "${1:-}" in
contenu)
	chaine="${2:?chaîne de contrôle manquante}"
	echo "Base de données (copie complète) : $(docker compose exec -T postgres pg_dump -U synapse synapse | grep -c -- "$chaine" || true) occurrence(s)"
	echo "Fichiers stockés par Synapse     : $(docker compose exec -T synapse sh -c 'test -d /data/media_store && { grep -rl -- "$1" /data || true; } | wc -l' _ "$chaine") fichier(s)"
	echo "Journaux de tous les services    : $(docker compose logs 2>&1 | grep -c -- "$chaine" || true) ligne(s)"
	echo "Derniers événements de message enregistrés (type, algorithme) :"
	sql -c "SELECT e.type, j.json::json->'content'->>'algorithm' AS algorithme, count(*)
	        FROM events e JOIN event_json j USING (event_id)
	        WHERE e.type IN ('m.room.message', 'm.room.encrypted') GROUP BY 1, 2;"
	;;
cles)
	nom="${2:?nom du salon manquant}"
	sql -v nom="$nom" <<'SQL'
SELECT to_char(to_timestamp(e.origin_server_ts / 1000), 'YYYY-MM-DD HH24:MI:SS') AS heure, e.sender AS qui,
       CASE WHEN e.type = 'm.room.member' THEN 'membre : ' || (j.json::json -> 'content' ->> 'membership') || ' ' || e.state_key
            ELSE 'message chiffré, session Megolm ' || left(j.json::json -> 'content' ->> 'session_id', 12) END AS evenement
FROM events e JOIN event_json j USING (event_id)
WHERE e.room_id IN (SELECT room_id FROM room_stats_state WHERE name = :'nom')
  AND e.type IN ('m.room.encrypted', 'm.room.member')
ORDER BY e.stream_ordering;
SQL
	;;
*)
	sed -n '2,12p' "$0"
	exit 1
	;;
esac
