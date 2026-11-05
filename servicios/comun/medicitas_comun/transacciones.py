"""Ayudas para operaciones que deben poder repetirse cuando el motor las aborta por un conflicto transitorio."""

import logging
import random
import time

from psycopg import errors

log = logging.getLogger("medicitas")

# Un deadlock (40P01) significa que Postgres escogió esta transacción como víctima para que las demás avancen:
# no hay nada mal en la solicitud, solo se repite. 40001 es el equivalente de SERIALIZABLE; con READ COMMITTED
# no debería aparecer, pero repetirlo es igual de seguro.
_REINTENTABLES = (errors.DeadlockDetected, errors.SerializationFailure)


def reintentar_si_deadlock(con, operacion, *, intentos: int = 3):
    """Ejecuta `operacion()` (una transacción completa sobre `con`) y la repite si el motor la aborta por deadlock.

    Antes de repetir se hace ROLLBACK: el motor ya anuló la transacción y la conexión no admite más sentencias
    hasta entonces. Entre intentos espera un tiempo al azar, para que las dos transacciones que chocaron no
    vuelvan a pedir los bloqueos en el mismo orden y al mismo instante. Tras el último intento, el error sube y
    la API responde 503.

    `operacion` se vuelve a ejecutar entera, así que no debe tener efectos fuera de la base (enviar correos,
    escribir en Redis...) antes de que la transacción termine.
    """
    for intento in range(1, intentos + 1):
        try:
            return operacion()
        except _REINTENTABLES as e:
            con.rollback()
            log.warning("transacción abortada por el motor, se reintenta",
                        extra={"datos": {"error": type(e).__name__, "intento": intento, "de": intentos}})
            if intento == intentos:
                raise
            time.sleep(random.uniform(0.01, 0.05) * intento)
