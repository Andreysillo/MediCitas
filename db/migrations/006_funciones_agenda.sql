-- 006: funciones de la agenda que varios servicios y operaciones comparten.

-- ¿La cita [p_inicio, p_fin) cabe entera en algún bloque del horario semanal del profesional? (I3)
--
-- El horario está en hora LOCAL de la clínica ("08:00") y la cita es un instante absoluto, así que se convierte
-- el instante a la zona de la clínica para saber qué día de la semana y qué hora le corresponde.
-- Es la única definición de "cabe en el horario": la usan la reserva (RF9), la reprogramación (RF10) y la lista
-- de citas que quedan fuera al quitar un bloque del horario (RF5). Así las tres nunca discrepan.
--
-- Los parámetros llevan prefijo p_ porque un nombre como `inicio` se confundiría con la columna de cita.
CREATE FUNCTION cabe_en_horario(p_profesional uuid, p_inicio timestamptz, p_fin timestamptz)
RETURNS boolean
LANGUAGE sql STABLE
AS $$
    SELECT EXISTS (
        SELECT 1
          FROM profesional p
          JOIN clinica cl ON cl.id = p.clinica_id
          JOIN horario_atencion h ON h.profesional_id = p.id
         WHERE p.id = p_profesional
           AND h.dia_semana = extract(isodow FROM p_inicio AT TIME ZONE cl.zona_horaria)
           -- una cita que cruza la medianoche no cabe en ningún bloque
           AND (p_inicio AT TIME ZONE cl.zona_horaria)::date = (p_fin AT TIME ZONE cl.zona_horaria)::date
           AND (p_inicio AT TIME ZONE cl.zona_horaria)::time >= h.hora_inicio
           AND (p_fin    AT TIME ZONE cl.zona_horaria)::time <= h.hora_fin)
$$;
