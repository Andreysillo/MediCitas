# Una sola receta para los tres servicios de Python: el compose elige cuál con el argumento SERVICIO.
FROM python:3.12-slim AS base

ARG SERVICIO
ENV SERVICIO=${SERVICIO} PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Primero las dependencias y después el código: si solo cambia el código, Docker reutiliza esta capa.
COPY comun /tmp/comun
COPY ${SERVICIO}/requirements.txt .
RUN pip install --no-cache-dir /tmp/comun -r requirements.txt && rm -rf /tmp/comun

COPY ${SERVICIO}/app ./app

# ---- Pruebas: `docker compose --profile pruebas run --rm pruebas-agenda`. Lleva pytest; la imagen de
# producción (la última etapa) no. ----
FROM base AS pruebas
ARG SERVICIO
COPY ${SERVICIO}/requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY ${SERVICIO}/tests ./tests
# Lo que se prueba igual en los tres servicios, una sola copia en pruebas_comunes/: el barrido de fugas entre clínicas
# (I5, T26) y la matriz de permisos con el token (RF17, T29).
COPY pruebas_comunes/ ./tests/
USER nobody
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider", "-q"]

# ---- Producción: es la última etapa, así que es la que construye `docker compose build` por defecto. ----
FROM base AS produccion

# Sin privilegios: si alguien compromete el proceso, no es root dentro del contenedor.
USER nobody
EXPOSE 8000

# /listo también comprueba la base, así `docker compose ps` muestra si el servicio puede atender de verdad.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/listo', timeout=2)"

# `exec`: uvicorn queda como el proceso principal y recibe el SIGTERM de `docker compose stop`, así termina
# las solicitudes en curso antes de salir. --root-path: el gateway publica el servicio bajo /api/<servicio>/.
# --no-access-log: cada solicitud ya queda en el log JSON del servicio.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --root-path /api/$SERVICIO --proxy-headers --forwarded-allow-ips '*' --no-access-log"]
