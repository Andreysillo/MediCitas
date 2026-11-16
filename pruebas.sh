#!/bin/sh
# Corre TODAS las pruebas del proyecto con un solo comando:   bash pruebas.sh
#
# Ejecuta, una tras otra, las unitarias y las de integración de los tres servicios contra la base real del compose
# (cada servicio tiene su servicio de pruebas en el perfil `pruebas`). Las pruebas arman sus propios datos: no hay que
# preparar nada, solo tener Docker encendido y el .env copiado de .env.example.
#
# Si un servicio falla, igual se corren los demás (así se ven todos los fallos de una vez) y el script termina con error.
# Termina con 0 solo si pasaron los tres.

set -u
cd "$(dirname "$0")"   # que funcione desde cualquier carpeta

fallidos=""
for servicio in agenda plataforma auditoria; do
  echo
  echo "=============== pruebas de $servicio ==============="
  # --build: que las pruebas usen el código actual. -T: sin terminal interactiva, para que corra también en un script o CI.
  if ! docker compose --profile pruebas run --rm --build -T "pruebas-$servicio"; then
    fallidos="$fallidos $servicio"
  fi
done

echo
echo "=============== resumen ==============="
if [ -n "$fallidos" ]; then
  echo "FALLARON las pruebas de:$fallidos"
  exit 1
fi
echo "Pasaron las pruebas de los tres servicios (agenda, plataforma y auditoria)."
