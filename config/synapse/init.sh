#!/bin/sh
# Génère la clé de signature du serveur au premier démarrage, puis lance Synapse.
set -e
python -m synapse.app.homeserver -c /config/homeserver.yaml --generate-keys
mkdir -p /data/media_store
chown -R 991:991 /data
exec /start.py
