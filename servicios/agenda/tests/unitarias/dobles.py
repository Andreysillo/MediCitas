"""Sustitutos para las pruebas unitarias: aíslan la lógica de la base de datos y de Redis.

Una prueba unitaria no necesita Postgres ni Redis: le entrega al código una conexión y un Redis falsos, que responden lo que la
prueba arma y recuerdan qué se les pidió. Así se comprueba una decisión del código (en qué orden bloquea, qué rechaza, qué
invalida) sin depender de que el motor la confirme, y la prueba falla en milisegundos señalando la línea.

Lo que el motor decide por su cuenta (los solapes I1 e I2, las claves foráneas, el trigger de estados) NO se puede probar aquí:
eso lo cubren las pruebas de integración, contra la base real.
"""

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from medicitas_comun import Sesion

# Un instante futuro y fijo, para que las pruebas no dependan del reloj.
INICIO = datetime(2030, 1, 7, 9, 0, tzinfo=timezone.utc)


class _Resultado:
    def __init__(self, filas):
        self.filas = filas

    def fetchone(self):
        return self.filas[0] if self.filas else None

    def fetchall(self):
        return list(self.filas)


class FalsaConexion:
    """Una conexión que no habla con ninguna base.

    Se arma con pares (fragmento de SQL, filas): la primera sentencia que contenga el fragmento recibe esas filas, o lanza la
    excepción si en lugar de filas se pasa una. Una sentencia que ninguna respuesta prevé hace fallar la prueba: el código
    pidió algo que la prueba no esperaba.
    """

    def __init__(self, *respuestas):
        self.respuestas = respuestas
        self.sentencias: list[tuple[str, object, dict]] = []     # (sql sin saltos de línea, parámetros, opciones)
        self.rollbacks = 0

    def execute(self, sql, params=None, **opciones):
        sql = " ".join(sql.split())
        self.sentencias.append((sql, params, opciones))
        for fragmento, filas in self.respuestas:
            if fragmento in sql:
                if isinstance(filas, Exception):
                    raise filas
                return _Resultado(filas)
        raise AssertionError(f"el código pidió una consulta que la prueba no previó: {sql[:140]}")

    def rollback(self):
        self.rollbacks += 1

    def posicion(self, *fragmentos) -> int:
        """Lugar (desde 0) de la primera sentencia que contiene TODOS los fragmentos. Falla si nunca se ejecutó."""
        for i, (sql, _, _) in enumerate(self.sentencias):
            if all(f in sql for f in fragmentos):
                return i
        raise AssertionError(f"nunca se ejecutó una sentencia con {fragmentos}")

    def ejecuto(self, *fragmentos) -> bool:
        return any(all(f in sql for f in fragmentos) for sql, _, _ in self.sentencias)

    def parametros(self, *fragmentos):
        return self.sentencias[self.posicion(*fragmentos)][1]


class FalsoRedis:
    """Un Redis en un diccionario. `eventos` es una lista compartida donde cada operación anota lo que hizo, para comprobar el
    orden. `fallos` y `demoras` hacen que una operación ("get", "set", "incr") lance una excepción o tarde."""

    def __init__(self, datos=None, eventos=None):
        self.datos = dict(datos or {})
        self.ttl: dict[str, int | None] = {}
        self.eventos = eventos if eventos is not None else []
        self.fallos: dict[str, Exception] = {}
        self.demoras: dict[str, float] = {}

    def _operar(self, nombre, clave):
        self.eventos.append((nombre, clave))
        if nombre in self.demoras:
            time.sleep(self.demoras[nombre])
        if nombre in self.fallos:
            raise self.fallos[nombre]

    def get(self, clave):
        self._operar("get", clave)
        return self.datos.get(clave)

    def set(self, clave, valor, ex=None):
        self._operar("set", clave)
        self.datos[clave] = valor
        self.ttl[clave] = ex
        return True

    def incr(self, clave):
        self._operar("incr", clave)
        self.datos[clave] = str(int(self.datos.get(clave) or 0) + 1)
        return int(self.datos[clave])


def pedido():
    """Lo único que el código toma de la solicitud HTTP: la lista de tareas que corren después del COMMIT."""
    return SimpleNamespace(state=SimpleNamespace(tras_commit=[]))


def confirmar(request) -> None:
    """Lo que hace `conexion` (medicitas_comun/app.py) cuando el COMMIT salió bien: correr las tareas pendientes."""
    for tarea in request.state.tras_commit:
        tarea()


def sesion_de(rol="RECEPCION") -> Sesion:
    return Sesion(usuario_id=uuid4(), clinica_id=uuid4(), rol=rol)


def fila_de_cita(estado="RESERVADA", futura=False, minutos=30, **extra) -> dict:
    """La fila que devuelve `buscar_cita`."""
    return {"id": uuid4(), "paciente_id": uuid4(), "profesional_id": uuid4(), "servicio_id": uuid4(),
            "inicio": INICIO, "fin": INICIO + timedelta(minutes=minutos), "estado": estado, "futura": futura, **extra}


OK_PROFESIONAL = [{"activo": True}]
OK_PACIENTE = [{"existe": 1}]
OK_SERVICIO = [{"duracion_minutos": 30, "servicio_activo": True, "habilitado": True}]
OK_ESPACIO = [{"futuro": True, "en_horario": True, "bloqueado": False}]


def conexion_de_reserva(*extra, profesional=OK_PROFESIONAL, paciente=OK_PACIENTE, servicio=OK_SERVICIO, espacio=OK_ESPACIO):
    """Una conexión que responde a las cuatro consultas de `validar_y_calcular_fin`, por defecto todas en regla. Cada
    argumento reemplaza la respuesta de una de ellas (una lista vacía es "no existe"); `extra` agrega las demás respuestas."""
    return FalsaConexion(
        ("FROM profesional WHERE id", profesional),
        ("FROM paciente WHERE id", paciente),
        ("FROM servicio s LEFT JOIN", servicio),
        ("AS futuro", espacio),
        *extra,
    )
