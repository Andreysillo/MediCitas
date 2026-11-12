"""Cálculo de espacios disponibles (RF7, RF8). Es la consulta que más veces se ejecuta en el sistema.

Se resuelve entera en SQL, en una sola consulta, en cuatro pasos:
  0. habilitados: los profesionales de la clínica que atienden el servicio.
  1. bloques:    los bloques del horario semanal de cada profesional, convertidos a instantes reales de cada día.
  2. candidatos: dentro de cada bloque, un posible inicio cada PASO_MINUTOS, mientras la cita entera quepa en él (I3).
  3. filtro:     se descarta el candidato que se traslapa con una cita vigente (I1) o con un bloqueo (RF6), y el pasado.

El traslape se escribe con la misma expresión `tstzrange(inicio, fin, '[)')` que las restricciones de exclusión de
`cita` (db/migrations/004_citas.sql). Así las citas se buscan con el índice GiST de la restricción de I1, y los bloqueos con
`bloqueo_por_profesional_y_rango` (008_indices.sql). Las mediciones están en db/README.md («Índices»).
"""

from datetime import date, timedelta
from uuid import UUID

# Cada cuánto puede empezar una cita dentro de un bloque del horario. Solo define lo que se OFRECE: la reserva acepta
# cualquier minuto exacto que cumpla las reglas.
PASO_MINUTOS = 15

_SQL = """
WITH dias AS (
    SELECT %(desde)s::date + n AS fecha FROM generate_series(0, %(dias)s - 1) AS n
),
-- 0. MATERIALIZED obliga a calcular esto primero: son pocas filas y descartan a quien no atiende el servicio antes de
--    generar candidatos. Sin él, con muchas clínicas en la base, el motor generaba los espacios de TODOS los profesionales
--    de la clínica y descartaba al final (medido en RF8: 1 120 búsquedas en `cita` en vez de 280).
habilitados AS MATERIALIZED (
    SELECT p.id
      FROM profesional p
      JOIN profesional_servicio ps
        ON ps.clinica_id = p.clinica_id AND ps.profesional_id = p.id AND ps.servicio_id = %(servicio)s AND ps.activo
     WHERE p.clinica_id = %(clinica)s AND p.activo
       AND (%(profesional)s::uuid IS NULL OR p.id = %(profesional)s::uuid)
),
-- 1. Cada bloque del horario semanal en cada día del rango. El horario está en hora local de la clínica
--    ("08:00"): (fecha + hora) AT TIME ZONE zona lo convierte al instante absoluto que le corresponde.
bloques AS (
    SELECT hb.id AS profesional_id, d.fecha,
           (d.fecha + h.hora_inicio) AT TIME ZONE %(zona)s AS desde,
           (d.fecha + h.hora_fin)    AT TIME ZONE %(zona)s AS hasta
      FROM habilitados hb
     CROSS JOIN dias d
      JOIN horario_atencion h
        ON h.profesional_id = hb.id AND h.dia_semana = extract(isodow FROM d.fecha)
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
              -- Redundante a propósito: en RF7 le dice al planificador qué profesional es, para que use el índice GiST
              -- de I1 con ese valor. En RF8 vale NULL y desaparece. Funciona porque la consulta no se prepara (ver abajo).
              AND (%(profesional)s::uuid IS NULL OR ci.profesional_id = %(profesional)s::uuid)
              AND ci.estado IN ('RESERVADA', 'ATENDIDA', 'AUSENTE')          -- las citas vigentes (I7)
              AND ci.id IS DISTINCT FROM %(ignorar)s::uuid                   -- la que se está reprogramando (RF10)
              AND tstzrange(ci.inicio, ci.fin, '[)') && tstzrange(c.inicio, c.fin, '[)'))
   AND NOT EXISTS (
           SELECT 1 FROM bloqueo_agenda bl
            WHERE bl.profesional_id = c.profesional_id
              AND (%(profesional)s::uuid IS NULL OR bl.profesional_id = %(profesional)s::uuid)   -- ídem
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
    # prepare=False: cada ejecución se planifica con sus valores. Preparada, psycopg la reutiliza desde la quinta vez y
    # Postgres puede pasarse a un plan genérico, que no sabe si `profesional` es NULL y recorre las tablas enteras
    # (medido con 83 mil citas: RF7 de 1,2 a 99 ms, RF8 de 24 a 1 384 ms). Planificar cuesta alrededor de 1 ms.
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
        prepare=False,
    ).fetchall()
