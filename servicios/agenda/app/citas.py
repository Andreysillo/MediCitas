"""RF9: reservar una cita. La operación crítica del sistema."""

from fastapi import APIRouter, Depends, HTTPException
from medicitas_comun import CONEXION, Sesion, reintentar_si_deadlock, sesion_de_clinica

from .esquemas import Cita, SolicitudReserva
from .reserva import validar_y_calcular_fin

router = APIRouter(tags=["RF9 · Citas"])

# Matriz de permisos: reservar, reprogramar y cancelar son del administrador de clínica y de recepción.
ROLES_QUE_AGENDAN = ("ADM_CLINICA", "RECEPCION")


def puede_agendar(sesion: Sesion = Depends(sesion_de_clinica)) -> Sesion:
    if sesion.rol not in ROLES_QUE_AGENDAN:
        raise HTTPException(403, "Tu rol no puede reservar citas")
    return sesion


@router.post("/citas", response_model=Cita, status_code=201)
def reservar(solicitud: SolicitudReserva, sesion: Sesion = Depends(puede_agendar), con=CONEXION):
    """Reserva una cita. Desenlaces: concedida (201), espacio o paciente ya ocupados (409), solicitud inválida (422).

    Una sola transacción, en READ COMMITTED: validar (con el bloqueo de fila sobre el profesional) e insertar. Quien
    decide entre dos reservas simultáneas del último espacio NO es este código sino la restricción de exclusión: la
    segunda inserción espera a que la primera termine y, si ésta se confirma, el motor la rechaza con 23P01, que la
    API convierte en 409. El COMMIT ocurre antes de enviar la respuesta (ver CONEXION).
    """

    def reservar_una_vez():
        fin = validar_y_calcular_fin(
            con, sesion.clinica_id, solicitud.paciente_id, solicitud.profesional_id, solicitud.servicio_id, solicitud.inicio
        )
        return con.execute(
            # El INSERT lleva la clínica de la SESIÓN. Las claves foráneas compuestas garantizan que paciente,
            # profesional y servicio sean de esa misma clínica (I5).
            """WITH nueva AS (
                   INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, creada_por)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING id, paciente_id, profesional_id, servicio_id, inicio, fin, estado, creada_por, creada_en, clinica_id)
               SELECT n.id, n.paciente_id, n.profesional_id, n.servicio_id, n.inicio, n.fin, n.estado, n.creada_por, n.creada_en,
                      pa.nombre AS paciente, s.nombre AS servicio
                 FROM nueva n
                 JOIN paciente pa ON pa.clinica_id = n.clinica_id AND pa.id = n.paciente_id
                 JOIN servicio s  ON s.clinica_id  = n.clinica_id AND s.id  = n.servicio_id""",
            (sesion.clinica_id, solicitud.paciente_id, solicitud.profesional_id, solicitud.servicio_id,
             solicitud.inicio, fin, sesion.usuario_id),
        ).fetchone()

    # Si el motor aborta la transacción por deadlock, se repite entera (hasta 3 veces) antes de responder 503.
    return reintentar_si_deadlock(con, reservar_una_vez)
