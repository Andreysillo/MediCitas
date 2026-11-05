"""Reglas que debe cumplir un espacio para recibir una cita. Las comparten reservar (RF9) y reprogramar (RF10), para
que las dos operaciones nunca discrepen.

NO comprueba los solapes con otras citas (I1, I2): esos los rechaza el motor al insertar, con las restricciones de
exclusión de `cita`. Revisarlos antes con un SELECT dejaría una ventana en la que dos solicitudes simultáneas pasan la
revisión y las dos insertan.
"""

from datetime import datetime, timedelta
from uuid import UUID

from fastapi import HTTPException

NO_EXISTEN = "El paciente, el profesional o el servicio no existen en esta clínica"


def validar_y_calcular_fin(con, clinica_id: UUID, paciente_id: UUID, profesional_id: UUID, servicio_id: UUID, inicio: datetime) -> datetime:
    """Valida la solicitud DENTRO de la transacción de la reserva y devuelve el `fin` de la cita (I4).

    Orden (importa):
      1. Bloqueo de fila FOR NO KEY UPDATE sobre el profesional y luego sobre el paciente, SIEMPRE en ese orden.
         a) Serializa las reservas del mismo profesional (o del mismo paciente). Sin esto, dos inserciones
            simultáneas que chocan en una restricción de exclusión se esperan una a la otra: Postgres inserta primero
            la entrada del índice y recién después revisa, así que cada una ve la entrada en curso de la otra y se
            produce un deadlock (medido: con 8 clientes disputando un espacio, varios abortaban con 40P01 y agotaban
            los reintentos). Con el bloqueo, la segunda espera ANTES de insertar, ve la cita ya confirmada y el motor
            la rechaza al instante con 23P01 (409). Reservas de profesionales y pacientes distintos siguen en paralelo.
         b) Quien cambia la agenda del profesional (un bloqueo nuevo, quitar un bloque de horario) toma el mismo
            bloqueo, así que o el cambio entra antes y esta reserva lo ve en el paso 4, o la reserva entra antes y el
            cambio la lista como conflicto. Nunca se cuela una cita en un bloqueo (I3).
         c) El orden fijo (profesional, luego paciente) evita que dos reservas se esperen en círculo.
         NO KEY UPDATE y no UPDATE: no estorba la verificación de claves foráneas de otras inserciones.
      2. Existencia, estado y habilitación (RF4), con la clínica de la sesión (I5): un id de otra clínica responde igual
         que uno inexistente.
      3. La duración sale del servicio, nunca del cliente (I4).
      4. Horario y bloqueos (I3), ya con el bloqueo tomado. Esto depende de READ COMMITTED: cada sentencia ve lo que otros
         confirmaron mientras esta esperaba el bloqueo (ver el pool en medicitas_comun/app.py).
    """
    profesional = con.execute(
        "SELECT activo FROM profesional WHERE id = %s AND clinica_id = %s FOR NO KEY UPDATE", (profesional_id, clinica_id)
    ).fetchone()
    paciente = con.execute(
        "SELECT 1 FROM paciente WHERE id = %s AND clinica_id = %s FOR NO KEY UPDATE", (paciente_id, clinica_id)
    ).fetchone()
    datos = con.execute(
        """SELECT s.duracion_minutos, s.activo AS servicio_activo, ps.activo AS habilitado
             FROM servicio s
             LEFT JOIN profesional_servicio ps
               ON ps.clinica_id = s.clinica_id AND ps.profesional_id = %(profesional)s AND ps.servicio_id = s.id
            WHERE s.id = %(servicio)s AND s.clinica_id = %(clinica)s""",
        {"clinica": clinica_id, "profesional": profesional_id, "servicio": servicio_id},
    ).fetchone()

    if profesional is None or paciente is None or datos is None:
        raise HTTPException(422, NO_EXISTEN)
    if not datos["servicio_activo"]:
        raise HTTPException(422, "El servicio está desactivado")
    if not profesional["activo"]:
        raise HTTPException(422, "El profesional no está activo")
    if not datos["habilitado"]:
        raise HTTPException(422, "El profesional no atiende ese servicio")

    fin = inicio + timedelta(minutes=datos["duracion_minutos"])

    # Una sola consulta con las tres comprobaciones; `now()` es la hora de la base, la misma que usa todo lo demás.
    espacio = con.execute(
        """SELECT %(inicio)s > now() AS futuro,
                  cabe_en_horario(%(profesional)s, %(inicio)s, %(fin)s) AS en_horario,
                  EXISTS (SELECT 1 FROM bloqueo_agenda b
                           WHERE b.profesional_id = %(profesional)s
                             AND tstzrange(b.inicio, b.fin, '[)') && tstzrange(%(inicio)s, %(fin)s, '[)')) AS bloqueado""",
        {"profesional": profesional_id, "inicio": inicio, "fin": fin},
    ).fetchone()
    if not espacio["futuro"]:
        raise HTTPException(422, "No se puede reservar en el pasado")
    if not espacio["en_horario"]:
        raise HTTPException(422, "Ese horario está fuera de la atención del profesional")
    if espacio["bloqueado"]:
        raise HTTPException(422, "El profesional tiene un bloqueo de agenda en ese horario")
    return fin
