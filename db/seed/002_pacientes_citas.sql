-- Semilla 002: pacientes, citas de -14 a +14 días respecto de hoy, notas clínicas y bitácora.
--
-- Las fechas son relativas al momento del primer arranque, así que siempre hay citas pasadas, de hoy y
-- futuras. Para refrescarlas: `docker compose down -v` y volver a levantar.
-- setseed fija el generador: dos arranques con las mismas fechas producen los mismos datos.

SELECT setseed(0.2026);

CREATE FUNCTION pg_temp.id(clave text) RETURNS uuid LANGUAGE sql IMMUTABLE AS $$ SELECT md5(clave)::uuid $$;

-- ---------- Pacientes: 80 por clínica ----------
-- Los números al azar se sortean en un CTE (una fila por paciente). Si se sortearan en un LATERAL que no
-- depende de la fila, PostgreSQL lo evaluaría una sola vez y todos los pacientes saldrían con el mismo nombre.
WITH sorteo AS (
    SELECT c.id AS clinica_id, c.identificador, i,
           1 + floor(random() * 20)::int AS n,  1 + floor(random() * 18)::int AS a1,  1 + floor(random() * 18)::int AS a2,
           floor(random() * 7)::int AS d1,      floor(random() * 900)::int AS d2,     floor(random() * 3)::int AS pref,
           floor(random() * 900)::int AS t1,    floor(random() * 9000)::int AS t2,    floor(random() * 99)::int AS cor,
           floor(random() * (date '2022-12-28' - date '1950-01-01'))::int AS dias
      FROM clinica c CROSS JOIN generate_series(0, 79) AS i
), nombre AS (
    SELECT s.*,
           (ARRAY['Ana','Luis','María','José','Lucía','Javier','Camila','Mateo','Isabel','Pablo','Elena','Tomás',
                  'Rebeca','Adrián','Valentina','Hugo','Mariana','Felipe','Carolina','Sebastián'])[s.n] AS nom,
           (ARRAY['Alvarado','Brenes','Calderón','Esquivel','Fallas','Granados','Hidalgo','Leiva','Madrigal','Mora',
                  'Murillo','Obando','Picado','Ramírez','Salazar','Ugalde','Villalobos','Zúñiga'])[s.a1] AS ap1,
           (ARRAY['Alvarado','Brenes','Calderón','Esquivel','Fallas','Granados','Hidalgo','Leiva','Madrigal','Mora',
                  'Murillo','Obando','Picado','Ramírez','Salazar','Ugalde','Villalobos','Zúñiga'])[s.a2] AS ap2
      FROM sorteo s
)
INSERT INTO paciente (id, clinica_id, identificacion, nombre, fecha_nacimiento, telefono, correo)
SELECT pg_temp.id('paciente:' || identificador || ':' || i),
       clinica_id,
       -- Formato de cédula costarricense. El bloque central sale del contador, así que nunca se repite.
       (1 + d1) || '-' || lpad((100 + i * 23)::text, 4, '0') || '-' || lpad((100 + d2)::text, 4, '0'),
       nom || ' ' || ap1 || ' ' || ap2,
       date '1950-01-01' + dias,
       (ARRAY['6', '7', '8'])[1 + pref] || (100 + t1) || '-' || (1000 + t2),
       translate(lower(nom || '.' || ap1), 'áéíóúñ', 'aeioun') || (1 + cor) || '@correo.cr'
  FROM nombre;

-- ---------- Comprobaciones de disponibilidad (las usa la generación de citas) ----------
-- Equivalen a lo que hará la reserva real (RF9): el espacio cae dentro de un bloque del horario y fuera de
-- los bloqueos (I3), y ni el profesional ni el paciente tienen otra cita vigente encima (I1 e I2).
-- La semilla las consulta para no generar datos que el motor rechazaría.
-- Los parámetros llevan prefijo p_: en una función SQL, un nombre sin prefijo que coincida con una columna
-- (como `fin`) se resuelve como la columna, no como el parámetro.
CREATE FUNCTION pg_temp.profesional_libre(p_prof uuid, p_ini timestamptz, p_fin timestamptz, p_zona text)
RETURNS boolean LANGUAGE sql AS $$
    SELECT EXISTS (
               SELECT 1 FROM horario_atencion h
                WHERE h.profesional_id = p_prof
                  AND h.dia_semana = extract(isodow FROM p_ini AT TIME ZONE p_zona)
                  AND (p_ini AT TIME ZONE p_zona)::date = (p_fin AT TIME ZONE p_zona)::date
                  AND (p_ini AT TIME ZONE p_zona)::time >= h.hora_inicio
                  AND (p_fin AT TIME ZONE p_zona)::time <= h.hora_fin)
       AND NOT EXISTS (
               SELECT 1 FROM bloqueo_agenda b
                WHERE b.profesional_id = p_prof AND tstzrange(b.inicio, b.fin) && tstzrange(p_ini, p_fin))
       AND NOT EXISTS (
               SELECT 1 FROM cita c
                WHERE c.profesional_id = p_prof AND c.estado IN ('RESERVADA', 'ATENDIDA', 'AUSENTE')
                  AND tstzrange(c.inicio, c.fin) && tstzrange(p_ini, p_fin))
$$;

CREATE FUNCTION pg_temp.paciente_libre(p_pac uuid, p_ini timestamptz, p_fin timestamptz)
RETURNS boolean LANGUAGE sql AS $$
    SELECT NOT EXISTS (
               SELECT 1 FROM cita c
                WHERE c.paciente_id = p_pac AND c.estado IN ('RESERVADA', 'ATENDIDA', 'AUSENTE')
                  AND tstzrange(c.inicio, c.fin) && tstzrange(p_ini, p_fin))
$$;

-- ---------- Citas ----------
-- Se recorre cada bloque del horario de cada profesional, día por día, y se van llenando espacios al azar.
-- La agenda se ve más llena cerca de hoy y más vacía hacia el futuro.
DO $$
DECLARE
    clin       record;
    prof       record;
    bloque     record;
    srv        record;
    hoy_local  date;
    dia        date;
    ini        timestamptz;
    fin        timestamptz;
    limite     timestamptz;
    ocupacion  numeric;
    pac        uuid;
    recepcion  uuid;
    estado     text;
    r          numeric;
    creada     timestamptz;
BEGIN
    FOR clin IN SELECT * FROM clinica ORDER BY identificador LOOP
        hoy_local := (now() AT TIME ZONE clin.zona_horaria)::date;
        SELECT id INTO recepcion FROM usuario WHERE clinica_id = clin.id AND rol_id = 3;

        FOR prof IN SELECT * FROM profesional WHERE clinica_id = clin.id ORDER BY id LOOP
            FOR desplazamiento IN -14..14 LOOP
                dia := hoy_local + desplazamiento;
                ocupacion := CASE WHEN desplazamiento <= 0 THEN 0.7 ELSE greatest(0.15, 0.7 - desplazamiento * 0.05) END;

                FOR bloque IN
                    SELECT hora_inicio, hora_fin FROM horario_atencion
                     WHERE profesional_id = prof.id AND dia_semana = extract(isodow FROM dia)
                     ORDER BY hora_inicio
                LOOP
                    ini    := (dia + bloque.hora_inicio) AT TIME ZONE clin.zona_horaria;
                    limite := (dia + bloque.hora_fin)    AT TIME ZONE clin.zona_horaria;

                    WHILE ini < limite LOOP
                        -- Un servicio al azar entre los que este profesional tiene habilitados.
                        SELECT s.id, s.duracion_minutos INTO srv
                          FROM profesional_servicio ps
                          JOIN servicio s ON s.clinica_id = ps.clinica_id AND s.id = ps.servicio_id
                         WHERE ps.profesional_id = prof.id AND ps.activo AND s.activo
                         ORDER BY random() LIMIT 1;
                        fin := ini + srv.duracion_minutos * interval '1 minute';
                        EXIT WHEN fin > limite;

                        -- Espacio que se deja vacío (o que cae en un bloqueo): se avanza 15 minutos.
                        IF random() > ocupacion OR NOT pg_temp.profesional_libre(prof.id, ini, fin, clin.zona_horaria) THEN
                            ini := ini + interval '15 minutes';
                            CONTINUE;
                        END IF;

                        -- Un paciente libre en ese intervalo (I2), al azar; si no hay, el espacio queda vacío.
                        SELECT p.id INTO pac FROM paciente p
                         WHERE p.clinica_id = clin.id AND pg_temp.paciente_libre(p.id, ini, fin)
                         ORDER BY random() LIMIT 1;
                        IF pac IS NULL THEN
                            ini := ini + interval '15 minutes';
                            CONTINUE;
                        END IF;

                        -- Estado según la fecha. Una cita solo puede estar atendida o ausente si ya pasó su
                        -- hora de inicio (RF12); las de hoy que ya pasaron aún pueden esperar su desenlace.
                        r := random();
                        IF ini < now() THEN
                            estado := CASE WHEN r < 0.75 THEN 'ATENDIDA' WHEN r < 0.87 THEN 'AUSENTE' ELSE 'CANCELADA' END;
                            IF estado = 'ATENDIDA' AND dia = hoy_local AND random() < 0.25 THEN estado := 'RESERVADA'; END IF;
                        ELSE
                            estado := CASE WHEN r < 0.88 THEN 'RESERVADA' ELSE 'CANCELADA' END;
                        END IF;

                        -- Se creó entre 1 y 10 días antes, pero nunca en el futuro.
                        creada := least(ini - (1 + floor(random() * 10)) * interval '1 day',
                                        now() - (1 + floor(random() * 48)) * interval '1 hour');

                        INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado,
                                          creada_por, creada_en, cancelada_por, cancelada_en, motivo_cancelacion)
                        VALUES (clin.id, pac, prof.id, srv.id, ini, fin, estado, recepcion, creada,
                                CASE WHEN estado = 'CANCELADA' THEN recepcion END,
                                CASE WHEN estado = 'CANCELADA' THEN least(creada + interval '6 hours', now()) END,
                                CASE WHEN estado = 'CANCELADA' THEN
                                    (ARRAY['El paciente avisó que no puede asistir', 'Cambio de planes del paciente',
                                           'Enfermedad del paciente', 'Solicitud por teléfono'])[1 + floor(random() * 4)::int]
                                END);
                        ini := fin;
                    END LOOP;
                END LOOP;
            END LOOP;
        END LOOP;
    END LOOP;
END $$;

-- ---------- Reprogramaciones ----------
-- Reprogramar no edita la cita (RF10): la antigua pasa a REPROGRAMADA y se crea otra que apunta a ella con
-- cita_origen_id. Se hace aquí, antes de las notas, porque una cita reprogramada deja de estar atendida.
-- Primero se libera la antigua y luego se inserta la nueva: la exclusión se revisa fila por fila y el nuevo
-- horario podría solaparse con el viejo.
--
-- La semilla inventa historia: toma citas que nacieron ATENDIDA y las vuelve REPROGRAMADA, una transición que el
-- trigger de la migración 007 prohíbe (y con razón). Por eso se apaga solo durante este bloque. Las migraciones
-- corren antes que la semilla, así que el trigger ya existe aquí.
ALTER TABLE cita DISABLE TRIGGER cita_protegida;

DO $$
DECLARE
    cand  record;
    nini  timestamptz;
    nfin  timestamptz;
BEGIN
    FOR cand IN
        SELECT t.* FROM (
            SELECT ci.*, cl.zona_horaria,
                   row_number() OVER (PARTITION BY ci.clinica_id, ci.inicio > now() ORDER BY random()) AS n
              FROM cita ci JOIN clinica cl ON cl.id = ci.clinica_id
             WHERE (ci.estado = 'RESERVADA' AND ci.inicio > now() + interval '1 day')   -- futuras
                OR (ci.estado = 'ATENDIDA'  AND ci.inicio < now() - interval '8 days')  -- pasadas, ya con nueva cita atendida
        ) t
        WHERE t.n <= CASE WHEN t.inicio > now() THEN 10 ELSE 5 END
    LOOP
        -- La nueva cita va al mismo servicio y a la misma hora de alguno de los 7 días siguientes.
        FOR k IN 1..7 LOOP
            nini := ((cand.inicio AT TIME ZONE cand.zona_horaria) + k * interval '1 day') AT TIME ZONE cand.zona_horaria;
            nfin := nini + (cand.fin - cand.inicio);
            IF pg_temp.profesional_libre(cand.profesional_id, nini, nfin, cand.zona_horaria)
               AND pg_temp.paciente_libre(cand.paciente_id, nini, nfin) THEN
                UPDATE cita SET estado = 'REPROGRAMADA' WHERE id = cand.id;
                INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado,
                                  creada_por, creada_en, cita_origen_id)
                VALUES (cand.clinica_id, cand.paciente_id, cand.profesional_id, cand.servicio_id, nini, nfin,
                        cand.estado, cand.creada_por,
                        cand.creada_en + (cand.inicio - cand.creada_en) / 2, cand.id);
                EXIT;
            END IF;
        END LOOP;
    END LOOP;
END $$;

ALTER TABLE cita ENABLE TRIGGER cita_protegida;

-- ---------- Notas clínicas ----------
-- Una de cada tres citas atendidas, escrita poco después de terminar. Texto ficticio y genérico.
INSERT INTO nota_clinica (clinica_id, cita_id, contenido, creada_en, actualizada_en)
SELECT c.clinica_id, c.id,
       (ARRAY[
           'Refiere cefalea de tres días sin fiebre. Examen físico sin hallazgos. Se indica reposo e hidratación; control si persiste.',
           'Control de rutina. Signos vitales dentro de parámetros normales. Se mantiene el plan actual.',
           'Dolor lumbar tras esfuerzo. Sin déficit neurológico. Se indica analgesia y ejercicios de movilidad.',
           'Evolución favorable respecto a la consulta anterior. Se programa nueva valoración en cuatro semanas.',
           'Tos seca de una semana. Auscultación limpia. Tratamiento sintomático y signos de alarma explicados.',
           'Se explica el plan de tratamiento y el paciente lo comprende. Se entregan indicaciones por escrito.'
       ])[1 + floor(random() * 6)::int],
       least(c.fin + interval '10 minutes', now()),
       least(c.fin + interval '10 minutes', now())
  FROM cita c
 WHERE c.estado = 'ATENDIDA' AND random() < 0.35;

-- ---------- Bitácora (RF18) ----------
-- Quién escribió y leyó notas y datos de contacto en las últimas semanas. Se inserta ordenada por fecha para
-- que el id, que es una identidad, también crezca con el tiempo.
INSERT INTO registro_auditoria (clinica_id, usuario_id, paciente_id, accion, recurso, ocurrido_en)
SELECT clinica_id, usuario_id, paciente_id, accion, recurso, ocurrido_en
  FROM (
        -- Cada nota: el profesional que atendió la escribió.
        SELECT n.clinica_id, p.usuario_id, c.paciente_id, 'ESCRITURA' AS accion, 'NOTA_CLINICA' AS recurso, n.creada_en AS ocurrido_en
          FROM nota_clinica n
          JOIN cita c        ON c.clinica_id = n.clinica_id AND c.id = n.cita_id
          JOIN profesional p ON p.clinica_id = c.clinica_id AND p.id = c.profesional_id
        UNION ALL
        -- Y en algunas, volvió a leerla en los tres días siguientes.
        SELECT n.clinica_id, p.usuario_id, c.paciente_id, 'LECTURA', 'NOTA_CLINICA',
               n.creada_en + random() * interval '3 days'
          FROM nota_clinica n
          JOIN cita c        ON c.clinica_id = n.clinica_id AND c.id = n.cita_id
          JOIN profesional p ON p.clinica_id = c.clinica_id AND p.id = c.profesional_id
         WHERE random() < 0.30
        UNION ALL
        -- Recepción consulta y actualiza datos de contacto: 40 accesos por clínica en las últimas 3 semanas.
        SELECT cl.id, rec.id, pa.id,
               CASE WHEN random() < 0.25 THEN 'ESCRITURA' ELSE 'LECTURA' END,
               'CONTACTO_PACIENTE',
               now() - random() * interval '20 days'
          FROM clinica cl
          JOIN usuario rec ON rec.clinica_id = cl.id AND rec.rol_id = 3
          CROSS JOIN generate_series(1, 40) AS acceso
          CROSS JOIN LATERAL (SELECT id FROM paciente WHERE clinica_id = cl.id AND acceso > 0
                               ORDER BY random() LIMIT 1) AS pa
       ) AS eventos
 WHERE ocurrido_en < now()
 ORDER BY ocurrido_en;

-- ---------- Bloqueo que cae sobre citas ya reservadas (RF6) ----------
-- En cada clínica, el profesional con más citas vigentes el próximo día hábil entre las 10:00 y las 12:00
-- queda bloqueado esa franja. El bloqueo NO cancela esas citas: quedan como conflicto para que recepción
-- las reprograme.
DO $$
DECLARE
    clin      record;
    dia       date;
    prof      uuid;
    b_ini     timestamptz;
    b_fin     timestamptz;
BEGIN
    FOR clin IN SELECT * FROM clinica ORDER BY identificador LOOP
        dia := (now() AT TIME ZONE clin.zona_horaria)::date + 1;
        WHILE extract(isodow FROM dia) > 5 LOOP dia := dia + 1; END LOOP;   -- salta sábado y domingo
        b_ini := (dia + time '10:00') AT TIME ZONE clin.zona_horaria;
        b_fin := (dia + time '12:00') AT TIME ZONE clin.zona_horaria;

        SELECT p.id INTO prof
          FROM profesional p
         WHERE p.clinica_id = clin.id
         ORDER BY (SELECT count(*) FROM cita c
                    WHERE c.profesional_id = p.id AND c.estado IN ('RESERVADA', 'ATENDIDA', 'AUSENTE')
                      AND tstzrange(c.inicio, c.fin) && tstzrange(b_ini, b_fin)) DESC, p.id
         LIMIT 1;

        INSERT INTO bloqueo_agenda (clinica_id, profesional_id, inicio, fin, motivo)
        VALUES (clin.id, prof, b_ini, b_fin, 'Permiso personal');
    END LOOP;
END $$;
