"""Caché de la disponibilidad de RF7 en Redis (I8). La fuente de verdad sigue siendo PostgreSQL: todo lo que hay aquí se
puede perder sin consecuencias, y si Redis no responde, la consulta se calcula en la base.

Cada profesional tiene un número de versión, y la clave de cada copia lo incluye. Invalidar es subir ese número: las
copias anteriores quedan bajo claves que nadie vuelve a buscar y el TTL las borra. Así, un solo INCR invalida todas las
fechas y todos los servicios del profesional, incluso los de un bloqueo de varios días.

La versión también resuelve esta carrera: una consulta lee la base, otra solicitud reserva e invalida, y la consulta
guarda tarde su copia ya vieja. Como esa consulta anotó la versión ANTES de leer la base, su copia queda con el número
anterior y nadie la encuentra.

Lo que queda abierto: entre el COMMIT y el INCR hay unos milisegundos en que otro cliente aún lee la copia anterior. Si
además intenta reservar ese espacio, el motor responde 409 (I1). Y si el INCR falla, la copia dura como mucho TTL_SEGUNDOS.
"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from functools import lru_cache
from uuid import UUID

import redis
from fastapi import Request
from medicitas_comun import despues_del_commit

log = logging.getLogger("medicitas")

# Red de seguridad, no el mecanismo de I8: limita cuánto dura un error si falla un INCR, y limpia las versiones viejas.
TTL_SEGUNDOS = 300

# Lo máximo que Redis puede retrasar una solicitud. Los tiempos del socket no alcanzan: no cubren la resolución del nombre,
# y con el contenedor apagado cada solicitud tardaba unos 4 s (medido). Si se agotan los hilos, la tarea espera en la fila
# y el resultado es el mismo: se sigue sin Redis.
LIMITE_SEGUNDOS = 0.25
_hilos = ThreadPoolExecutor(max_workers=8, thread_name_prefix="redis")


@lru_cache
def _redis() -> redis.Redis | None:
    """Un cliente por proceso. Sin REDIS_URL no hay caché."""
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    return redis.Redis.from_url(url, socket_timeout=0.2, socket_connect_timeout=0.2, decode_responses=True)


def _con_limite(operacion):
    """Ejecuta `operacion()` en otro hilo y deja de esperarla al cumplirse el límite. Una operación que ya empezó sigue
    sola: un INCR que llega tarde todavía sirve."""
    futuro = _hilos.submit(operacion)
    try:
        return futuro.result(timeout=LIMITE_SEGUNDOS)
    except TimeoutError:
        futuro.cancel()   # si seguía en la fila, ya no ocupa un hilo
        raise


def _clave_version(profesional_id: UUID) -> str:
    return f"disp:version:{profesional_id}"


def espacios(clinica_id: UUID, profesional_id: UUID, servicio_id: UUID, duracion_minutos: int, fecha: date, calcular) -> list[datetime]:
    """Los inicios libres de esa consulta: de la caché si hay copia, y si no, de `calcular()`, que además se guarda."""
    r = _redis()
    if r is None:
        return calcular()

    def leer():
        version = r.get(_clave_version(profesional_id)) or "0"   # ANTES de calcular: de esto depende la carrera de arriba
        # La clave lleva todo lo que cambia la respuesta y nada más. La duración permite que `plataforma` edite un servicio
        # sin tocar Redis: con otra duración la clave es otra. Va sin usuario ni rol: todos ven la misma agenda.
        clave = f"disp:{clinica_id}:{profesional_id}:v{version}:{servicio_id}:{duracion_minutos}:{fecha}"
        return clave, r.get(clave)

    try:
        clave, guardado = _con_limite(leer)
    except (redis.RedisError, TimeoutError) as e:
        log.warning("caché no disponible, se calcula en la base", extra={"datos": {"error": type(e).__name__}})
        return calcular()

    if guardado is not None:
        # El paso del tiempo no dispara ninguna invalidación, pero solo puede quitar espacios: basta filtrar al leer.
        ahora = datetime.now(timezone.utc)
        return [i for i in map(datetime.fromisoformat, json.loads(guardado)) if i > ahora]

    inicios = calcular()
    try:
        copia = json.dumps([i.isoformat() for i in inicios])
        _con_limite(lambda: r.set(clave, copia, ex=TTL_SEGUNDOS))
    except (redis.RedisError, TimeoutError) as e:
        log.warning("no se pudo guardar en la caché", extra={"datos": {"error": type(e).__name__}})
    return inicios


def invalidar_tras_commit(request: Request, *profesionales: UUID) -> None:
    """Toda ruta que cambie citas vigentes, horarios o bloqueos debe llamar esto. Se ejecuta después del COMMIT: antes,
    una consulta podría volver a llenar la caché sin ver el cambio. Y antes de la respuesta: quien reservó ya no ve su
    espacio libre. Si falla, `conexion` lo registra y la solicitud sigue siendo un éxito, porque los datos ya se guardaron."""

    def subir_versiones():
        r = _redis()
        if r is not None:
            _con_limite(lambda: [r.incr(_clave_version(p)) for p in set(profesionales)])

    despues_del_commit(request, subir_versiones)
