"""Cálculo de espacios disponibles (RF7, RF8). Es la consulta que más veces se ejecuta en el sistema.

Se resuelve entera en SQL, en una sola consulta, en tres pasos:
  1. bloques:    los bloques del horario semanal de cada profesional, convertidos a instantes reales de cada día.
  2. candidatos: dentro de cada bloque, un posible inicio cada PASO_MINUTOS, mientras la cita entera quepa en él (I3).
  3. filtro:     se descarta el candidato que se traslapa con una cita vigente (I1) o con un bloqueo (RF6), y el pasado.

Para saber qué hay ocupado se usa la misma expresión `tstzrange(inicio, fin, '[)')` que las restricciones de exclusión
de `cita` (db/migrations/004_citas.sql): así el motor puede resolver el traslape con ese índice GiST en vez de
recorrer todas las citas. El plan de ejecución se documenta en la tarea T15.
"""

from datetime import date, timedelta
from uuid import UUID

# Cada cuánto puede empezar una cita dentro de un bloque del horario. Lo comparte con la reserva (T12).
PASO_MINUTOS = 15

_SQL = """
WITH dias AS (
    SELECT %(desde)s::date + n AS fecha FROM generate_series(0, %(dias)s - 1) AS n
),
-- 1. Cada bloque del horario semanal en cada día del rango. El horario está en hora local de la clínica
--    ("08:00"): (fecha + hora) AT TIME ZONE zona lo convierte al instante absoluto que le corresponde.
bloques AS (
    SELECT p.id AS profesional_id, d.fecha,
           (d.fecha + h.hora_inicio) AT TIME ZONE %(zona)s AS desde,
           (d.fecha + h.hora_fin)    AT TIME ZONE %(zona)s AS hasta
      FROM profesional p
      JOIN profesional_servicio ps
        ON ps.clinica_id = p.clinica_id AND ps.profesional_id = p.id AND ps.servicio_id = %(servicio)s AND ps.activo
     CROSS JOIN dias d
      JOIN horario_atencion h
        ON h.profesional_id = p.id AND h.dia_semana = extract(isodow FROM d.fecha)
     WHERE p.clinica_id = %(clinica)s AND p.activo
       AND (%(profesional)s::uuid IS NULL OR p.id = %(profesional)s::uuid)
),
-- 2. Los inicios posibles. Si la duración no cabe en el bloque, generate_series no devuelve nada.
--    Cada bloque se calcula por separado: una cita no puede cruzar el almuerzo de una jornada partida.
candidatos AS (
    SELECT b.profesional_id, b.fecha, s.inicio, s.inicio + %(duracion)s::interval AS fin
      FROM bloques b
     CROSS JOIN LATERAL generate_series(b.desde, b.hasta - %(duracion)s::interval, %(paso)s::interval) AS s(inicio)
     WHERE s.inicio > now()
)
-- 3. Lo que queda libre. Dos intervalos semiabiertos [inicio, fin) se traslapan con `&&`; una cita que termina
--    justo cuando empieza el candidato no lo estorba.
SELECT c.profesional_id, c.fecha, c.inicio
  FROM candidatos c
 WHERE NOT EXISTS (
           SELECT 1 FROM cita ci
            WHERE ci.profesional_id = c.profesional_id
              AND ci.estado IN ('RESERVADA', 'ATENDIDA', 'AUSENTE')          -- las citas vigentes (I7)
              AND ci.id IS DISTINCT FROM %(ignorar)s::uuid                   -- la que se está reprogramando (RF10)
              AND tstzrange(ci.inicio, ci.fin, '[)') && tstzrange(c.inicio, c.fin, '[)'))
   AND NOT EXISTS (
           SELECT 1 FROM bloqueo_agenda bl
            WHERE bl.profesional_id = c.profesional_id
              AND tstzrange(bl.inicio, bl.fin, '[)') && tstzrange(c.inicio, c.fin, '[)'))
 ORDER BY c.profesional_id, c.inicio
"""


def espacios_libres(
    con,
    *,
    clinica_id: UUID,
    servicio_id: UUID,
    zona_horaria: str,
    duracion_minutos: int,
    desde: date,
    dias: int,
    profesional_id: UUID | None = None,
    ignorar_cita: UUID | None = None,
) -> list[dict]:
    """Filas {profesional_id, fecha, inicio} de los inicios libres, de los profesionales habilitados para el servicio.

    `profesional_id` limita a uno (RF7); sin él se consideran todos los de la clínica (RF8). `fecha` es el día
    local de la clínica; `inicio` es un instante absoluto. `ignorar_cita` libera el espacio de una cita que se
    está reprogramando, para que ella misma no estorbe a su nuevo horario.
    """
    return con.execute(
        _SQL,
        {
            "clinica": clinica_id,
            "servicio": servicio_id,
            "profesional": profesional_id,
            "ignorar": ignorar_cita,
            "zona": zona_horaria,
            "desde": desde,
            "dias": dias,
            "duracion": timedelta(minutes=duracion_minutos),
            "paso": timedelta(minutes=PASO_MINUTOS),
        },
    ).fetchall()
