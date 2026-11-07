"""RF9 a RF13: el ciclo de vida de la cita. Reservar, reprogramar, cancelar y registrar el desenlace."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from medicitas_comun import CONEXION, Sesion, reintentar_si_deadlock, sesion_de_clinica

from . import cache
from .esquemas import Cancelacion, Cita, Desenlace, Error, Reprogramacion, SolicitudReserva
from .reserva import validar_y_calcular_fin

router = APIRouter(tags=["RF9 a RF13 · Citas"])

# RF13. Desde RESERVADA se puede pasar a los otros cuatro; los cuatro son finales. La migración 007 lo refuerza en el motor.
TRANSICIONES = {
    "RESERVADA": {"ATENDIDA", "AUSENTE", "CANCELADA", "REPROGRAMADA"},
    "ATENDIDA": set(),
    "AUSENTE": set(),
    "CANCELADA": set(),
    "REPROGRAMADA": set(),
}


def exigir_transicion(actual: str, nuevo: str) -> None:
    """Único punto donde se decide si una cita puede cambiar de estado."""
    if nuevo not in TRANSICIONES[actual]:
        raise HTTPException(409, f"Una cita {actual.lower()} no puede pasar a {nuevo.lower()}")


# Matriz de permisos: reservar, reprogramar y cancelar son del administrador de clínica y de recepción.
def puede_agendar(sesion: Sesion = Depends(sesion_de_clinica)) -> Sesion:
    if sesion.rol not in ("ADM_CLINICA", "RECEPCION"):
        raise HTTPException(403, "Tu rol no puede reservar, reprogramar ni cancelar citas")
    return sesion


def buscar_cita(con, sesion: Sesion, cita_id: UUID, *, bloquear: bool = False) -> dict:
    """La cita, si es de la clínica de la sesión; si no, 404, igual que una inexistente (I5).

    bloquear=True toma el bloqueo de fila: dos operaciones sobre la misma cita pasan de una en una, y la segunda lee el
    estado que dejó la primera (READ COMMITTED vuelve a leer la fila al obtener el bloqueo).
    """
    sql = """SELECT id, paciente_id, profesional_id, servicio_id, inicio, fin, estado, inicio > now() AS futura
               FROM cita WHERE id = %s AND clinica_id = %s"""
    fila = con.execute(sql + (" FOR NO KEY UPDATE" if bloquear else ""), (cita_id, sesion.clinica_id)).fetchone()
    if fila is None:
        raise HTTPException(404, "Cita no encontrada")
    return fila


def vista(con, cita_id: UUID) -> dict:
    """La cita completa, con los nombres de paciente y servicio. Solo se llama con ids ya validados contra la clínica."""
    return con.execute(
        """SELECT c.id, c.paciente_id, c.profesional_id, c.servicio_id, c.inicio, c.fin, c.estado, c.creada_por, c.creada_en,
                  c.cancelada_por, c.cancelada_en, c.motivo_cancelacion, c.cita_origen_id,
                  pa.nombre AS paciente, s.nombre AS servicio
             FROM cita c
             JOIN paciente pa ON pa.clinica_id = c.clinica_id AND pa.id = c.paciente_id
             JOIN servicio s  ON s.clinica_id  = c.clinica_id AND s.id  = c.servicio_id
            WHERE c.id = %s""",
        (cita_id,),
    ).fetchone()


def insertar(con, sesion: Sesion, paciente_id, profesional_id, servicio_id, inicio, fin, origen: UUID | None = None) -> UUID:
    """El INSERT lleva la clínica de la SESIÓN; las claves foráneas compuestas garantizan que paciente, profesional y
    servicio sean de esa misma clínica (I5). Aquí es donde el motor decide los solapes (I1, I2)."""
    return con.execute(
        """INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, creada_por, cita_origen_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (sesion.clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, sesion.usuario_id, origen),
    ).fetchone()["id"]


_ERRORES = {
    403: {"model": Error, "description": "Tu rol no puede hacer esto"},
    404: {"model": Error, "description": "La cita no existe en tu clínica"},
    409: {"model": Error, "description": "Transición no permitida, o espacio o paciente ya ocupados"},
    422: {"model": Error, "description": "Solicitud inválida"},
    503: {"model": Error, "description": "Conflicto transitorio: se puede repetir la solicitud"},
}


@router.post("/citas", response_model=Cita, status_code=201, responses={
    k: v for k, v in _ERRORES.items() if k != 404
} | {409: {"model": Error, "description": "Espacio ya tomado, o el paciente ya tiene otra cita a esa hora"}})
def reservar(solicitud: SolicitudReserva, request: Request, sesion: Sesion = Depends(puede_agendar), con=CONEXION):
    """RF9. Tres desenlaces: concedida (201), espacio ya tomado (409) y solicitud inválida (422).

    Una sola transacción, en READ COMMITTED: validar (con los bloqueos de fila) e insertar. Quien decide entre dos reservas
    del mismo espacio es la restricción de exclusión del motor, no este código. El COMMIT ocurre antes de enviar la
    respuesta (ver CONEXION).
    """

    def una_vez():
        fin = validar_y_calcular_fin(con, sesion.clinica_id, solicitud.paciente_id, solicitud.profesional_id,
                                     solicitud.servicio_id, solicitud.inicio)
        return vista(con, insertar(con, sesion, solicitud.paciente_id, solicitud.profesional_id, solicitud.servicio_id,
                                   solicitud.inicio, fin))

    cache.invalidar_tras_commit(request, solicitud.profesional_id)
    # Si el motor aborta la transacción por deadlock, se repite entera (hasta 3 veces) antes de responder 503.
    return reintentar_si_deadlock(con, una_vez)


@router.post("/citas/{cita_id}/reprogramar", response_model=Cita, status_code=201, responses=_ERRORES)
def reprogramar(cita_id: UUID, destino: Reprogramacion, request: Request, sesion: Sesion = Depends(puede_agendar), con=CONEXION):
    """RF10. Mueve la cita a otro espacio. No la edita: la antigua pasa a REPROGRAMADA y se crea otra que apunta a ella.

    Los dos cambios van en UNA transacción, así que nadie ve la cita duplicada ni los dos espacios ocupados, y si el nuevo
    espacio está tomado (409) la cita original queda intacta. Se conservan el paciente, el servicio y la duración (I4).
    """

    def una_vez():
        # Primera lectura, sin bloqueo: el paciente y la duración no cambian nunca (migración 007), y hacen falta para
        # tomar los bloqueos en el orden de siempre: profesional, paciente y, al final, la cita.
        cita = buscar_cita(con, sesion, cita_id)
        exigir_transicion(cita["estado"], "REPROGRAMADA")
        if destino.profesional_id == cita["profesional_id"] and destino.inicio == cita["inicio"]:
            raise HTTPException(422, "Elige un espacio distinto al actual")
        fin = validar_y_calcular_fin(con, sesion.clinica_id, cita["paciente_id"], destino.profesional_id, cita["servicio_id"],
                                     destino.inicio, duracion=cita["fin"] - cita["inicio"])

        # Ahora sí, con el bloqueo: otra operación pudo cambiarla mientras tanto.
        exigir_transicion(buscar_cita(con, sesion, cita_id, bloquear=True)["estado"], "REPROGRAMADA")

        # En este orden: la exclusión se revisa fila por fila, así que el espacio viejo debe liberarse ANTES de insertar.
        # Si no, moverla 15 minutos chocaría consigo misma.
        con.execute("UPDATE cita SET estado = 'REPROGRAMADA' WHERE id = %s", (cita_id,))
        cache.invalidar_tras_commit(request, cita["profesional_id"], destino.profesional_id)   # pueden ser dos agendas
        return vista(con, insertar(con, sesion, cita["paciente_id"], destino.profesional_id, cita["servicio_id"],
                                   destino.inicio, fin, origen=cita_id))

    return reintentar_si_deadlock(con, una_vez)


@router.post("/citas/{cita_id}/cancelar", response_model=Cita, responses=_ERRORES)
def cancelar(cita_id: UUID, datos: Cancelacion, request: Request, sesion: Sesion = Depends(puede_agendar), con=CONEXION):
    """RF11. Deja el motivo y quién canceló. El espacio se libera en este mismo COMMIT (I7)."""
    cita = buscar_cita(con, sesion, cita_id, bloquear=True)
    exigir_transicion(cita["estado"], "CANCELADA")
    con.execute(
        "UPDATE cita SET estado = 'CANCELADA', cancelada_por = %s, cancelada_en = now(), motivo_cancelacion = %s WHERE id = %s",
        (sesion.usuario_id, datos.motivo, cita_id),
    )
    cache.invalidar_tras_commit(request, cita["profesional_id"])
    return vista(con, cita_id)


@router.post("/citas/{cita_id}/desenlace", response_model=Cita, responses=_ERRORES)
def registrar_desenlace(cita_id: UUID, datos: Desenlace, sesion: Sesion = Depends(sesion_de_clinica), con=CONEXION):
    """RF12. Atendida o ausente, solo una vez pasada la hora de inicio. Según la matriz lo registran el administrador de
    clínica, recepción y el profesional: todos los roles con clínica, por eso basta `sesion_de_clinica`.

    No invalida la caché: ATENDIDA y AUSENTE siguen ocupando su espacio, así que la disponibilidad no cambia."""
    cita = buscar_cita(con, sesion, cita_id, bloquear=True)
    exigir_transicion(cita["estado"], datos.desenlace)
    if cita["futura"]:
        raise HTTPException(422, "El desenlace solo se registra una vez pasada la hora de inicio")
    con.execute("UPDATE cita SET estado = %s WHERE id = %s", (datos.desenlace, cita_id))
    return vista(con, cita_id)
