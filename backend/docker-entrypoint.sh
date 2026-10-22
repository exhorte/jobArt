#!/bin/sh
# Applique les migrations Alembic avant de démarrer le processus demandé.
# RUN_MIGRATIONS=0 les saute (ex. worker de veille : seule l'API migre, le worker attend qu'elle soit saine).
set -eu

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    echo "[entrypoint] alembic upgrade head"
    alembic upgrade head
fi

exec "$@"
