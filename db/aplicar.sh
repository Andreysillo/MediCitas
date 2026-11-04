#!/bin/sh
# Aplica las migraciones y luego los datos semilla, en orden alfabético, cada archivo una sola vez.
#
# Dos usos:
#   1. Automático: el compose lo monta en /docker-entrypoint-initdb.d/, así que la imagen de Postgres lo
#      ejecuta en el primer arranque, con la base vacía.
#   2. A mano, para agregar una migración nueva sin recrear la base (usa las variables PG* de psql).
#
# Qué archivos ya se aplicaron lo recuerda la tabla schema_migrations. Cada archivo corre en UNA transacción
# junto con su anotación: si falla, no queda a medias ni anotado.

DB_DIR="${DB_DIR:-/db}"
PSQL="psql -v ON_ERROR_STOP=1 --username ${POSTGRES_USER:-postgres} --dbname ${POSTGRES_DB:-postgres}"

$PSQL -c "CREATE TABLE IF NOT EXISTS schema_migrations (
              archivo     text        PRIMARY KEY,
              aplicada_en timestamptz NOT NULL DEFAULT now())"

for archivo in "$DB_DIR"/migrations/*.sql "$DB_DIR"/seed/*.sql; do
    [ -e "$archivo" ] || continue
    # Se anota con la carpeta, para que una migración y una semilla con el mismo número no se confundan.
    nombre="$(basename "$(dirname "$archivo")")/$(basename "$archivo")"

    if [ "$($PSQL -tA -c "SELECT 1 FROM schema_migrations WHERE archivo = '$nombre'")" = "1" ]; then
        echo "ya aplicada: $nombre"
        continue
    fi

    echo "aplicando:   $nombre"
    $PSQL --single-transaction -f "$archivo" \
          -c "INSERT INTO schema_migrations (archivo) VALUES ('$nombre')"
done
