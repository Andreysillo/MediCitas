"""Citas reservadas que un bloqueo (RF6) o un cambio de horario (I3) deja sin cubrir.

Nunca se cancelan solas: se listan para que recepción las reprograme. Solo cuentan las RESERVADAS que todavía
no terminaron; las atendidas, ausentes, canceladas y pasadas ya son historia.
"""

from datetime import datetime
from uuid import UUID

_CITAS_RESERVADAS_FUTURAS = """
    SELECT c.id, c.profesional_id, c.paciente_id, c.servicio_id, c.inicio, c.fin, c.estado,
           pa.nombre AS paciente, s.nombre AS servicio
      FROM cita c
      JOIN paciente pa ON pa.clinica_id = c.clinica_id AND pa.id = c.paciente_id
      JOIN servicio s  ON s.clinica_id  = c.clinica_id AND s.id  = c.servicio_id
     WHERE c.clinica_id = %(clinica)s AND c.profesional_id = %(profesional)s
       AND c.estado = 'RESERVADA' AND c.fin > now()
"""


def reservadas_futuras(con, clinica_id: UUID, profesional_id: UUID) -> list[dict]:
    return con.execute(
        _CITAS_RESERVADAS_FUTURAS + " ORDER BY c.inicio",
        {"clinica": clinica_id, "profesional": profesional_id},
    ).fetchall()


def en_bloqueo(citas: list[dict], inicio: datetime, fin: datetime) -> list[dict]:
    """Las citas que se traslapan con [inicio, fin). Dos rangos se traslapan si cada uno empieza antes de que termine el otro."""
    return [c for c in citas if c["inicio"] < fin and c["fin"] > inicio]


def fuera_de_horario(con, clinica_id: UUID, profesional_id: UUID) -> list[dict]:
    """I3: las reservas que ya no caben entera en ningún bloque del horario semanal.

    El horario está en hora local de la clínica y las citas son instantes absolutos, así que cada cita se
    convierte a la zona de su clínica para saber qué día de la semana y qué hora le corresponde.
    """
    return con.execute(
        _CITAS_RESERVADAS_FUTURAS
        + """
       AND NOT EXISTS (
           SELECT 1
             FROM horario_atencion h, clinica cl
            WHERE cl.id = c.clinica_id AND h.profesional_id = c.profesional_id
              AND h.dia_semana = extract(isodow FROM c.inicio AT TIME ZONE cl.zona_horaria)
              -- una cita que cruza la medianoche no cabe en ningún bloque
              AND (c.inicio AT TIME ZONE cl.zona_horaria)::date = (c.fin AT TIME ZONE cl.zona_horaria)::date
              AND (c.inicio AT TIME ZONE cl.zona_horaria)::time >= h.hora_inicio
              AND (c.fin    AT TIME ZONE cl.zona_horaria)::time <= h.hora_fin)
     ORDER BY c.inicio""",
        {"clinica": clinica_id, "profesional": profesional_id},
    ).fetchall()
