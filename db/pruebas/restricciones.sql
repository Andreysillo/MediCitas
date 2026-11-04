-- Prueba de las restricciones del esquema contra un PostgreSQL real. No necesita datos previos: arma su
-- propia clínica y lo deshace todo al final (ROLLBACK).
--
--   psql -v ON_ERROR_STOP=1 -U medicitas -d medicitas -f db/pruebas/restricciones.sql
--
-- Cada intento ilegal debe ser rechazado por el MOTOR con un código SQLSTATE concreto; si el motor lo
-- deja pasar, la prueba falla. Es la base de las pruebas de invariantes I1 y I2 (T30, T31).

BEGIN;

-- Ejecuta una sentencia que debe fallar con el SQLSTATE esperado; si no falla o falla distinto, aborta.
CREATE FUNCTION pg_temp.debe_fallar(nombre text, esperado text, sentencia text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE sentencia;
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE = esperado THEN
            RAISE NOTICE 'OK    % -> %', nombre, SQLSTATE;
            RETURN;
        END IF;
        RAISE EXCEPTION 'FALLA % : esperaba % y llegó % (%)', nombre, esperado, SQLSTATE, SQLERRM;
    END;
    RAISE EXCEPTION 'FALLA % : el motor aceptó lo que debía rechazar', nombre;
END $$;

-- Ejecuta una sentencia que debe tener éxito.
CREATE FUNCTION pg_temp.debe_pasar(nombre text, sentencia text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE sentencia;
    RAISE NOTICE 'OK    % -> aceptado', nombre;
END $$;

-- ---------- Datos mínimos: dos clínicas ----------
INSERT INTO clinica (id, nombre, identificador, zona_horaria) VALUES
    ('00000000-0000-0000-0000-00000000000a', 'Clínica A', 'a', 'America/Costa_Rica'),
    ('00000000-0000-0000-0000-00000000000b', 'Clínica B', 'b', 'America/Costa_Rica');

INSERT INTO especialidad (id, clinica_id, nombre) VALUES
    ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-00000000000a', 'General'),
    ('00000000-0000-0000-0000-0000000000b1', '00000000-0000-0000-0000-00000000000b', 'General');

INSERT INTO usuario (id, clinica_id, rol_id, keycloak_sub, nombre) VALUES
    ('00000000-0000-0000-0000-000000000a01', '00000000-0000-0000-0000-00000000000a', 3, 'sub-a-rec',  'Recepción A'),
    ('00000000-0000-0000-0000-000000000a02', '00000000-0000-0000-0000-00000000000a', 4, 'sub-a-pro1', 'Profesional A1'),
    ('00000000-0000-0000-0000-000000000a03', '00000000-0000-0000-0000-00000000000a', 4, 'sub-a-pro2', 'Profesional A2'),
    ('00000000-0000-0000-0000-000000000b01', '00000000-0000-0000-0000-00000000000b', 4, 'sub-b-pro1', 'Profesional B1');

INSERT INTO profesional (id, clinica_id, usuario_id, especialidad_id, numero_colegiado) VALUES
    ('00000000-0000-0000-0000-00000000aa01', '00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-000000000a02', '00000000-0000-0000-0000-0000000000a1', 'COL-1'),
    ('00000000-0000-0000-0000-00000000aa02', '00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-000000000a03', '00000000-0000-0000-0000-0000000000a1', 'COL-2'),
    ('00000000-0000-0000-0000-00000000bb01', '00000000-0000-0000-0000-00000000000b', '00000000-0000-0000-0000-000000000b01', '00000000-0000-0000-0000-0000000000b1', 'COL-3');

INSERT INTO servicio (id, clinica_id, nombre, duracion_minutos, especialidad_id) VALUES
    ('00000000-0000-0000-0000-0000000005a1', '00000000-0000-0000-0000-00000000000a', 'Consulta', 30, '00000000-0000-0000-0000-0000000000a1'),
    ('00000000-0000-0000-0000-0000000005a2', '00000000-0000-0000-0000-00000000000a', 'Control',  20, '00000000-0000-0000-0000-0000000000a1'),
    ('00000000-0000-0000-0000-0000000005b1', '00000000-0000-0000-0000-00000000000b', 'Consulta', 30, '00000000-0000-0000-0000-0000000000b1');

-- El profesional A1 atiende Consulta; el A2, Consulta y Control; nadie de A atiende "Control" salvo A2.
INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id) VALUES
    ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000aa01', '00000000-0000-0000-0000-0000000005a1'),
    ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000aa02', '00000000-0000-0000-0000-0000000005a1'),
    ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000aa02', '00000000-0000-0000-0000-0000000005a2'),
    ('00000000-0000-0000-0000-00000000000b', '00000000-0000-0000-0000-00000000bb01', '00000000-0000-0000-0000-0000000005b1');

INSERT INTO paciente (id, clinica_id, identificacion, nombre, fecha_nacimiento) VALUES
    ('00000000-0000-0000-0000-0000000000f1', '00000000-0000-0000-0000-00000000000a', '1-1111-1111', 'Paciente 1 de A', '1990-01-01'),
    ('00000000-0000-0000-0000-0000000000f2', '00000000-0000-0000-0000-00000000000a', '2-2222-2222', 'Paciente 2 de A', '1991-02-02'),
    ('00000000-0000-0000-0000-0000000000f9', '00000000-0000-0000-0000-00000000000b', '9-9999-9999', 'Paciente de B',   '1992-03-03');

-- Atajo para insertar una cita de la clínica A. Las horas son del 2030-01-01, siempre en el futuro.
CREATE FUNCTION pg_temp.cita_a(id text, paciente text, profesional text, servicio text,
                               ini text, fin text, estado text DEFAULT 'RESERVADA') RETURNS text
LANGUAGE sql AS $$
    SELECT format($f$INSERT INTO cita (id, clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado, creada_por)
                     VALUES (%L, '00000000-0000-0000-0000-00000000000a', %L, %L, %L, %L, %L, %L,
                             '00000000-0000-0000-0000-000000000a01')$f$,
                  id, paciente, profesional, servicio, '2030-01-01 ' || ini || '-06', '2030-01-01 ' || fin || '-06', estado)
$$;

\set pa1 '''00000000-0000-0000-0000-00000000aa01'''
\set p1  '00000000-0000-0000-0000-0000000000f1'
\set p2  '00000000-0000-0000-0000-0000000000f2'
\set pr1 '00000000-0000-0000-0000-00000000aa01'
\set pr2 '00000000-0000-0000-0000-00000000aa02'
\set sv1 '00000000-0000-0000-0000-0000000005a1'
\set sv2 '00000000-0000-0000-0000-0000000005a2'
DO $$
DECLARE
    p1  text := '00000000-0000-0000-0000-0000000000f1';
    p2  text := '00000000-0000-0000-0000-0000000000f2';
    pr1 text := '00000000-0000-0000-0000-00000000aa01';
    pr2 text := '00000000-0000-0000-0000-00000000aa02';
    sv1 text := '00000000-0000-0000-0000-0000000005a1';
    sv2 text := '00000000-0000-0000-0000-0000000005a2';
BEGIN
    -- ===== I1: un profesional no tiene dos citas vigentes solapadas =====
    PERFORM pg_temp.debe_pasar('base: cita 09:00-09:30 del profesional 1',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000c1', p1, pr1, sv1, '09:00', '09:30'));
    PERFORM pg_temp.debe_fallar('I1 solape total con otro paciente', '23P01',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000c2', p2, pr1, sv1, '09:00', '09:30'));
    PERFORM pg_temp.debe_fallar('I1 solape parcial (09:15-09:45)', '23P01',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000c3', p2, pr1, sv1, '09:15', '09:45'));
    PERFORM pg_temp.debe_pasar('I1 cita contigua (09:30-10:00) sí se permite: intervalo [)',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000c4', p2, pr1, sv1, '09:30', '10:00'));
    PERFORM pg_temp.debe_pasar('I1 otro profesional a la misma hora, otro paciente',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000c5', p2, pr2, sv1, '09:00', '09:30'));

    -- ===== I2: un paciente no tiene dos citas vigentes solapadas =====
    PERFORM pg_temp.debe_fallar('I2 mismo paciente, otro profesional, mismo horario', '23P01',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000c6', p1, pr2, sv1, '09:10', '09:40'));

    -- ===== Estados: solo los vigentes ocupan agenda (I7) =====
    PERFORM pg_temp.debe_pasar('I7 cancelar libera: una CANCELADA no bloquea el espacio',
        format($f$INSERT INTO cita (id, clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado,
                                    creada_por, cancelada_por, cancelada_en, motivo_cancelacion)
                  VALUES ('00000000-0000-0000-0000-0000000000c7', '00000000-0000-0000-0000-00000000000a', %L, %L, %L,
                          '2030-01-01 09:00-06', '2030-01-01 09:30-06', 'CANCELADA',
                          '00000000-0000-0000-0000-000000000a01', '00000000-0000-0000-0000-000000000a01', now(), 'Prueba')$f$,
               p2, pr1, sv1));
    PERFORM pg_temp.debe_fallar('I1 una cita ATENDIDA también ocupa el espacio', '23P01',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000c8', p2, pr1, sv1, '09:00', '09:30', 'ATENDIDA'));
    PERFORM pg_temp.debe_fallar('I1 una AUSENTE también ocupa el espacio', '23P01',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000c9', p2, pr1, sv1, '09:00', '09:30', 'AUSENTE'));
    PERFORM pg_temp.debe_pasar('I7 reprogramar libera: una REPROGRAMADA no bloquea el espacio',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000ca', p2, pr1, sv1, '09:00', '09:30', 'REPROGRAMADA'));

    -- Liberar y volver a ocupar dentro de la misma transacción (lo que hace cancelar y reservar de nuevo).
    UPDATE cita SET estado = 'CANCELADA', cancelada_por = '00000000-0000-0000-0000-000000000a01',
                    cancelada_en = now(), motivo_cancelacion = 'Prueba'
     WHERE id = '00000000-0000-0000-0000-0000000000c1';
    PERFORM pg_temp.debe_pasar('I7 tras cancelar, el espacio queda libre de inmediato',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000cb', p1, pr1, sv1, '09:00', '09:30'));

    -- ===== CHECK de la cita =====
    PERFORM pg_temp.debe_fallar('fin debe ser posterior a inicio', '23514',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000cc', p1, pr1, sv1, '11:00', '11:00'));
    PERFORM pg_temp.debe_fallar('estado fuera de los cinco valores', '23514',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000cd', p1, pr1, sv1, '11:00', '11:30', 'PENDIENTE'));
    PERFORM pg_temp.debe_fallar('CANCELADA sin motivo ni responsable', '23514',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000ce', p1, pr1, sv1, '12:00', '12:30', 'CANCELADA'));
    PERFORM pg_temp.debe_fallar('datos de cancelación en una cita no cancelada', '23514',
        format($f$INSERT INTO cita (id, clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, creada_por, motivo_cancelacion)
                  VALUES ('00000000-0000-0000-0000-0000000000cf', '00000000-0000-0000-0000-00000000000a', %L, %L, %L,
                          '2030-01-01 13:00-06', '2030-01-01 13:30-06', '00000000-0000-0000-0000-000000000a01', 'sin estado')$f$,
               p1, pr1, sv1));

    -- ===== I5: el motor impide referencias entre clínicas =====
    PERFORM pg_temp.debe_fallar('I5 cita de la clínica A con un paciente de la clínica B', '23503',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000d1', '00000000-0000-0000-0000-0000000000f9', pr1, sv1, '14:00', '14:30'));
    PERFORM pg_temp.debe_fallar('I5 cita de la clínica A con un profesional de la clínica B', '23503',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000d2', p1, '00000000-0000-0000-0000-00000000bb01', sv1, '14:00', '14:30'));
    PERFORM pg_temp.debe_fallar('I5 profesional de A con una especialidad de B', '23503',
        $f$INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, numero_colegiado)
           VALUES ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-000000000a01',
                   '00000000-0000-0000-0000-0000000000b1', 'COL-X')$f$);

    -- ===== RF4: solo se agenda un servicio que el profesional tiene asociado =====
    PERFORM pg_temp.debe_fallar('el profesional 1 no atiende "Control"', '23503',
        pg_temp.cita_a('00000000-0000-0000-0000-0000000000d3', p1, pr1, sv2, '15:00', '15:20'));

    -- ===== Reprogramación =====
    PERFORM pg_temp.debe_fallar('una cita reprogramada tiene a lo sumo una sucesora', '23505',
        format($f$INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, creada_por, cita_origen_id)
                  SELECT clinica_id, paciente_id, profesional_id, servicio_id,
                         '2030-01-02 09:00-06'::timestamptz + (n || ' hours')::interval,
                         '2030-01-02 09:30-06'::timestamptz + (n || ' hours')::interval,
                         creada_por, '00000000-0000-0000-0000-0000000000ca'
                    FROM cita, generate_series(0, 1) n WHERE id = '00000000-0000-0000-0000-0000000000cb'$f$));

    -- ===== Identidad =====
    PERFORM pg_temp.debe_fallar('usuario de clínica sin clínica', '23514',
        $f$INSERT INTO usuario (rol_id, keycloak_sub, nombre) VALUES (3, 'sub-x', 'Sin clínica')$f$);
    PERFORM pg_temp.debe_fallar('administrador de plataforma con clínica', '23514',
        $f$INSERT INTO usuario (clinica_id, rol_id, keycloak_sub, nombre)
           VALUES ('00000000-0000-0000-0000-00000000000a', 1, 'sub-y', 'Plataforma con clínica')$f$);
    PERFORM pg_temp.debe_pasar('administrador de plataforma sin clínica',
        $f$INSERT INTO usuario (rol_id, keycloak_sub, nombre) VALUES (1, 'sub-z', 'Plataforma')$f$);
    PERFORM pg_temp.debe_fallar('keycloak_sub repetido', '23505',
        $f$INSERT INTO usuario (clinica_id, rol_id, keycloak_sub, nombre)
           VALUES ('00000000-0000-0000-0000-00000000000a', 3, 'sub-a-rec', 'Duplicado')$f$);

    -- ===== Horario semanal (RF5) =====
    PERFORM pg_temp.debe_pasar('horario: dos bloques el mismo día (jornada partida)',
        $f$INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin) VALUES
           ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000aa01', 1, '08:00', '12:00'),
           ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000aa01', 1, '13:00', '17:00')$f$);
    PERFORM pg_temp.debe_pasar('horario: bloque contiguo (12:00-13:00) sí se permite',
        $f$INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin)
           VALUES ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000aa01', 1, '12:00', '13:00')$f$);
    PERFORM pg_temp.debe_fallar('horario: bloque solapado (11:00-14:00)', '23P01',
        $f$INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin)
           VALUES ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000aa01', 1, '11:00', '14:00')$f$);
    PERFORM pg_temp.debe_pasar('horario: mismo bloque otro día',
        $f$INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin)
           VALUES ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000aa01', 2, '08:00', '12:00')$f$);
    PERFORM pg_temp.debe_fallar('horario: día 8', '23514',
        $f$INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin)
           VALUES ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000aa01', 8, '08:00', '12:00')$f$);
    PERFORM pg_temp.debe_fallar('horario: fin antes que inicio', '23514',
        $f$INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin)
           VALUES ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000aa01', 3, '12:00', '08:00')$f$);

    -- ===== Bloqueos y catálogo =====
    PERFORM pg_temp.debe_fallar('bloqueo: fin antes que inicio', '23514',
        $f$INSERT INTO bloqueo_agenda (clinica_id, profesional_id, inicio, fin, motivo)
           VALUES ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000aa01',
                   '2030-01-05 12:00-06', '2030-01-05 08:00-06', 'Error')$f$);
    PERFORM pg_temp.debe_fallar('servicio: duración cero', '23514',
        $f$INSERT INTO servicio (clinica_id, nombre, duracion_minutos, especialidad_id)
           VALUES ('00000000-0000-0000-0000-00000000000a', 'Instantáneo', 0, '00000000-0000-0000-0000-0000000000a1')$f$);
    PERFORM pg_temp.debe_fallar('servicio: nombre repetido en la misma clínica', '23505',
        $f$INSERT INTO servicio (clinica_id, nombre, duracion_minutos, especialidad_id)
           VALUES ('00000000-0000-0000-0000-00000000000a', 'Consulta', 15, '00000000-0000-0000-0000-0000000000a1')$f$);
    PERFORM pg_temp.debe_pasar('servicio: el mismo nombre en OTRA clínica sí se permite',
        $f$INSERT INTO servicio (clinica_id, nombre, duracion_minutos, especialidad_id)
           VALUES ('00000000-0000-0000-0000-00000000000b', 'Control', 15, '00000000-0000-0000-0000-0000000000b1')$f$);
    PERFORM pg_temp.debe_fallar('paciente: identificación repetida en la misma clínica', '23505',
        $f$INSERT INTO paciente (clinica_id, identificacion, nombre, fecha_nacimiento)
           VALUES ('00000000-0000-0000-0000-00000000000a', '1-1111-1111', 'Otro', '2000-01-01')$f$);
    PERFORM pg_temp.debe_fallar('clínica: identificador con mayúsculas', '23514',
        $f$INSERT INTO clinica (nombre, identificador, zona_horaria) VALUES ('X', 'Mala-Id', 'America/Costa_Rica')$f$);

    -- ===== Bitácora =====
    PERFORM pg_temp.debe_fallar('bitácora: acción inválida', '23514',
        $f$INSERT INTO registro_auditoria (clinica_id, usuario_id, paciente_id, accion, recurso)
           VALUES ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-000000000a01',
                   '00000000-0000-0000-0000-0000000000f1', 'BORRADO', 'NOTA_CLINICA')$f$);
    PERFORM pg_temp.debe_fallar('bitácora: paciente de otra clínica', '23503',
        $f$INSERT INTO registro_auditoria (clinica_id, usuario_id, paciente_id, accion, recurso)
           VALUES ('00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-000000000a01',
                   '00000000-0000-0000-0000-0000000000f9', 'LECTURA', 'NOTA_CLINICA')$f$);

    RAISE NOTICE '--- todas las restricciones respondieron como se esperaba ---';
END $$;

ROLLBACK;
