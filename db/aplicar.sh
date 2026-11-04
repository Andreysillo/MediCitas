#!/bin/sh
# Aplica las migraciones y luego los datos semilla, en orden alfabético, cada archivo una sola vez.
#
# Lo corre el servicio `migraciones` del compose en cada `docker compose up`, antes de que arranquen las
# APIs: con la base vacía crea todo, y con una base existente solo aplica los archivos nuevos. Se conecta
# con las variables PG* de psql (PGHOST, PGPASSWORD), así que también sirve a mano contra cualquier base.
#
# Qué archivos ya se aplicaron lo recuerda la tabla schema_migrations. Cada archivo corre en UNA transacción
# junto con su anotación: si falla, no queda a medias ni anotado, y el script termina con error para que
# las APIs no arranquen sobre un esquema incompleto.
#
# CARGAR_SEMILLA=no omite db/seed/: en producción no se cargan datos de prueba.

set -eu

DB_DIR="${DB_DIR:-/db}"
PSQL="psql -v ON_ERROR_STOP=1 --username ${POSTGRES_USER:-postgres} --dbname ${POSTGRES_DB:-postgres}"

carpetas="$DB_DIR/migrations"
[ "${CARGAR_SEMILLA:-si}" = "no" ] || carpetas="$carpetas $DB_DIR/seed"

$PSQL -c "CREATE TABLE IF NOT EXISTS schema_migrations (
              archivo     text        PRIMARY KEY,
              aplicada_en timestamptz NOT NULL DEFAULT now())"

for carpeta in $carpetas; do
    for archivo in "$carpeta"/*.sql; do
        [ -e "$archivo" ] || continue
        # Se anota con la carpeta, para que una migración y una semilla con el mismo número no se confundan.
        nombre="$(basename "$carpeta")/$(basename "$archivo")"

        if [ "$($PSQL -tA -c "SELECT 1 FROM schema_migrations WHERE archivo = '$nombre'")" = "1" ]; then
            echo "ya aplicada: $nombre"
            continue
        fi

        echo "aplicando:   $nombre"
        $PSQL --single-transaction -f "$archivo" \
              -c "INSERT INTO schema_migrations (archivo) VALUES ('$nombre')"
    done
done
