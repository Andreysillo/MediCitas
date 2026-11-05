"""Arranque común de los servicios de MediCitas.

`crear_app(nombre)` devuelve una aplicación FastAPI que ya trae lo que todo servicio necesita en producción:
un pool de conexiones a PostgreSQL que se recupera solo si la base se reinicia, las rutas /salud y /listo
para los healthchecks, logs en JSON con el id de cada solicitud, y la traducción de los errores del motor
a códigos HTTP. Cada servicio solo agrega sus routers.
"""

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar

import psycopg
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg import errors
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout
from starlette.exceptions import HTTPException as StarletteHTTPException

from .restricciones import MENSAJES

log = logging.getLogger("medicitas")

# Id de la solicitud en curso: lo pone el middleware y lo lee el formato de los logs.
_solicitud: ContextVar[str] = ContextVar("solicitud", default="-")


class _FormatoJson(logging.Formatter):
    """Una línea JSON por evento, para que los logs de los tres servicios se puedan filtrar juntos."""

    def __init__(self, servicio: str):
        super().__init__()
        self.servicio = servicio

    def format(self, r: logging.LogRecord) -> str:
        datos = {
            "momento": self.formatTime(r, "%Y-%m-%dT%H:%M:%S%z"),
            "nivel": r.levelname,
            "servicio": self.servicio,
            "solicitud": _solicitud.get(),
            "mensaje": r.getMessage(),
            **getattr(r, "datos", {}),
        }
        if r.exc_info:
            datos["traza"] = self.formatException(r.exc_info)
        return json.dumps(datos, ensure_ascii=False)


# Errores del motor que son culpa de la solicitud, no del servidor. La restricción violada viaja en la
# respuesta para que el cliente distinga, por ejemplo, el solape del profesional (I1) del paciente (I2).
_ERRORES_BD = {
    errors.ExclusionViolation: (409, "El horario ya está ocupado"),
    errors.UniqueViolation: (409, "Ya existe un registro con esos datos"),
    errors.ForeignKeyViolation: (422, "Hace referencia a algo que no existe en esta clínica"),
    errors.CheckViolation: (422, "Los datos no cumplen las reglas del sistema"),
}


def conexion(request: Request):
    """Dependencia de FastAPI: una conexión por solicitud, dentro de UNA transacción.

    Al terminar la ruta sin error se hace COMMIT; si lanza una excepción, ROLLBACK. Así una reserva nunca
    queda a medias. Las rutas la piden con `CONEXION`, no con `Depends(conexion)`: ver abajo.
    """
    with request.app.state.pool.connection() as con:
        yield con


# scope="function": el COMMIT ocurre ANTES de enviar la respuesta. Con el valor por defecto ("request") FastAPI
# envía primero la respuesta y cierra la dependencia después: medido, el cliente recibía el 201 ~1 s antes de que
# se ejecutara el código posterior al `yield`. Una reserva "concedida" cuyo commit aún no ocurrió no sirve: quien
# consulta justo después (I7, I8) no la vería, y si el commit fallara el cliente ya habría recibido un éxito.
CONEXION = Depends(conexion, scope="function")


def crear_app(nombre: str) -> FastAPI:
    manejador = logging.StreamHandler()
    manejador.setFormatter(_FormatoJson(nombre))
    logging.basicConfig(level=os.getenv("NIVEL_LOG", "INFO"), handlers=[manejador], force=True)

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        # open=False + open(wait=False): el servicio arranca aunque la base todavía no responda, y /listo
        # lo reporta. check_connection descarta conexiones rotas (por ejemplo, tras reiniciar Postgres).
        app.state.pool = ConnectionPool(
            os.environ["DATABASE_URL"],
            min_size=1,
            max_size=int(os.getenv("BD_CONEXIONES", "10")),
            timeout=5,
            check=ConnectionPool.check_connection,
            kwargs={
                "row_factory": dict_row,  # las filas llegan como diccionarios: se devuelven tal cual como JSON
                # Opciones de CADA conexión del pool (un espacio dentro de un valor se escapa con barra invertida):
                #  - READ COMMITTED, explícito. Las reservas lo necesitan: toman un bloqueo de fila y después leen
                #    horarios y bloqueos; cada sentencia debe ver lo que otros confirmaron mientras esperaban el
                #    bloqueo. Con REPEATABLE READ la foto se toma antes de esperar y no vería un bloqueo de agenda
                #    confirmado en medio (I3). Las colisiones (I1, I2) las decide el motor con sus exclusiones.
                #  - lock_timeout: esperar un bloqueo más de 5 s es un problema; mejor un 503 que una solicitud colgada.
                #  - idle_in_transaction_session_timeout: una transacción abandonada no retiene bloqueos para siempre.
                "options": (
                    "-c default_transaction_isolation=read\\ committed"
                    f" -c lock_timeout={os.getenv('BD_LOCK_TIMEOUT_MS', '5000')}"
                    " -c idle_in_transaction_session_timeout=30000"
                ),
            },
            open=False,
        )
        app.state.pool.open(wait=False)
        log.info("servicio iniciado")
        yield
        app.state.pool.close()
        log.info("servicio detenido")

    # El prefijo /api/<nombre>/ con que el gateway publica el servicio se le pasa a uvicorn (--root-path).
    app = FastAPI(title=f"MediCitas · {nombre}", lifespan=ciclo_de_vida)

    @app.middleware("http")
    async def registrar_solicitud(request: Request, siguiente):
        # El gateway manda X-Request-ID; si no viene (llamada directa), se genera uno.
        _solicitud.set(request.headers.get("x-request-id") or uuid.uuid4().hex)
        inicio = time.perf_counter()
        respuesta = await siguiente(request)
        respuesta.headers["x-request-id"] = _solicitud.get()
        if request.url.path not in ("/salud", "/listo"):  # los healthchecks llenarían el log
            log.info(
                "solicitud",
                extra={"datos": {
                    "metodo": request.method,
                    "ruta": request.url.path,
                    "estado": respuesta.status_code,
                    "ms": round((time.perf_counter() - inicio) * 1000, 1),
                }},
            )
        return respuesta

    @app.get("/salud", include_in_schema=False)
    def salud():
        """Vivo: el proceso responde. No toca la base."""
        return {"estado": "ok"}

    @app.get("/listo", include_in_schema=False)
    def listo(request: Request):
        """Listo para atender: además alcanza la base."""
        try:
            with request.app.state.pool.connection(timeout=2) as con:
                con.execute("SELECT 1")
        except (PoolTimeout, psycopg.OperationalError):
            return JSONResponse({"estado": "sin base de datos"}, status_code=503)
        return {"estado": "ok"}

    for tipo, (estado, mensaje) in _ERRORES_BD.items():
        def traducir(request: Request, e: psycopg.Error, estado=estado, mensaje=mensaje):
            restriccion = e.diag.constraint_name
            log.info("rechazo del motor", extra={"datos": {"restriccion": restriccion}})
            return JSONResponse({"detalle": MENSAJES.get(restriccion, mensaje), "restriccion": restriccion}, status_code=estado)

        app.add_exception_handler(tipo, traducir)

    # Una sola forma para todo error de la API: {"detalle": "..."}. Así el frontend lee siempre el mismo campo.
    def error_http(request: Request, e: StarletteHTTPException):
        return JSONResponse({"detalle": e.detail}, status_code=e.status_code)

    def datos_invalidos(request: Request, e: RequestValidationError):
        campos = [{"campo": ".".join(str(x) for x in err["loc"][1:]), "problema": err["msg"]} for err in e.errors()]
        return JSONResponse({"detalle": "Los datos enviados no son válidos", "campos": campos}, status_code=422)

    app.add_exception_handler(StarletteHTTPException, error_http)
    app.add_exception_handler(RequestValidationError, datos_invalidos)

    # Fallos transitorios del motor (bloqueo esperado de más, deadlock que ya no se pudo reintentar): la solicitud
    # es válida y no se aplicó nada; el cliente puede repetirla.
    def reintentable(request: Request, e: psycopg.Error):
        log.warning("conflicto transitorio del motor", extra={"datos": {"error": type(e).__name__}})
        return JSONResponse({"detalle": "El sistema está ocupado, intenta de nuevo"}, status_code=503, headers={"Retry-After": "1"})

    for tipo in (errors.DeadlockDetected, errors.SerializationFailure, errors.LockNotAvailable):
        app.add_exception_handler(tipo, reintentable)

    # La base caída o el pool agotado: 503 para que el cliente reintente, en vez de un 500 genérico.
    def sin_base(request: Request, e: Exception):
        log.warning("base de datos no disponible", extra={"datos": {"error": type(e).__name__}})
        return JSONResponse({"detalle": "Servicio no disponible, intenta de nuevo"}, status_code=503)

    app.add_exception_handler(PoolTimeout, sin_base)
    app.add_exception_handler(psycopg.OperationalError, sin_base)

    # Cualquier otro error: se registra con su traza, pero al cliente solo le llega el id para rastrearlo.
    def error_interno(request: Request, e: Exception):
        log.error("error no controlado", exc_info=e)
        return JSONResponse({"detalle": "Error interno", "solicitud": _solicitud.get()}, status_code=500)

    app.add_exception_handler(Exception, error_interno)

    return app
