-- Semilla 001: clínicas, usuarios, catálogo, profesionales y horarios.
-- Los pacientes y las citas van en el siguiente archivo, porque dependen de estos horarios.
--
-- Los ids salen de md5('tipo:nombre')::uuid: son siempre los mismos en cualquier computadora y en cada
-- arranque. Importa para Keycloak: el realm versionado crea sus usuarios con estos mismos ids como `sub`
-- (usuario.keycloak_sub = usuario.id), así que el token de cada usuario de prueba ya apunta a su fila.

CREATE FUNCTION pg_temp.id(clave text) RETURNS uuid LANGUAGE sql IMMUTABLE AS $$ SELECT md5(clave)::uuid $$;

-- ---------- Clínicas ----------
INSERT INTO clinica (id, nombre, identificador, zona_horaria) VALUES
    (pg_temp.id('clinica:san-rafael'), 'Clínica San Rafael',      'san-rafael', 'America/Costa_Rica'),
    (pg_temp.id('clinica:del-valle'),  'Centro Médico del Valle', 'del-valle',  'America/Costa_Rica'),
    (pg_temp.id('clinica:los-robles'), 'Clínica Los Robles',      'los-robles', 'America/Costa_Rica');

-- ---------- Especialidades y servicios: catálogo propio de cada clínica ----------
CREATE TEMP TABLE def_servicio (clinica text, especialidad text, servicio text, minutos int) ON COMMIT DROP;
INSERT INTO def_servicio VALUES
    ('san-rafael', 'Medicina general', 'Consulta general',          20),
    ('san-rafael', 'Medicina general', 'Certificado médico',        15),
    ('san-rafael', 'Pediatría',        'Control de niño sano',      30),
    ('san-rafael', 'Pediatría',        'Consulta pediátrica',       20),
    ('san-rafael', 'Odontología',      'Limpieza dental',           45),
    ('san-rafael', 'Odontología',      'Valoración odontológica',   30),
    ('del-valle',  'Medicina general', 'Consulta general',          30),
    ('del-valle',  'Dermatología',     'Consulta dermatológica',    30),
    ('del-valle',  'Dermatología',     'Crioterapia',               15),
    ('del-valle',  'Ginecología',      'Control ginecológico',      30),
    ('del-valle',  'Ginecología',      'Ultrasonido',               45),
    ('los-robles', 'Fisioterapia',     'Sesión de fisioterapia',    60),
    ('los-robles', 'Fisioterapia',     'Evaluación inicial',        45),
    ('los-robles', 'Nutrición',        'Consulta nutricional',      45),
    ('los-robles', 'Nutrición',        'Control nutricional',       30),
    ('los-robles', 'Psicología',       'Sesión de psicoterapia',    60);

INSERT INTO especialidad (id, clinica_id, nombre)
SELECT DISTINCT pg_temp.id('especialidad:' || clinica || ':' || especialidad),
       pg_temp.id('clinica:' || clinica), especialidad
  FROM def_servicio;

INSERT INTO servicio (id, clinica_id, nombre, duracion_minutos, especialidad_id)
SELECT pg_temp.id('servicio:' || clinica || ':' || servicio),
       pg_temp.id('clinica:' || clinica), servicio, minutos,
       pg_temp.id('especialidad:' || clinica || ':' || especialidad)
  FROM def_servicio;

-- ---------- Usuarios ----------
-- Un administrador de plataforma (sin clínica), y por clínica: un administrador y una recepcionista.
INSERT INTO usuario (id, clinica_id, rol_id, keycloak_sub, nombre)
SELECT pg_temp.id(clave), clinica_id, rol_id, pg_temp.id(clave)::text, nombre
  FROM (VALUES
    ('usuario:plataforma',               NULL::uuid,                      1::smallint, 'Equipo MediCitas'),
    ('usuario:san-rafael:admin',         pg_temp.id('clinica:san-rafael'), 2::smallint, 'Marta Solís'),
    ('usuario:san-rafael:recepcion',     pg_temp.id('clinica:san-rafael'), 3::smallint, 'Daniela Chaves'),
    ('usuario:del-valle:admin',          pg_temp.id('clinica:del-valle'),  2::smallint, 'Jorge Herrera'),
    ('usuario:del-valle:recepcion',      pg_temp.id('clinica:del-valle'),  3::smallint, 'Karla Monge'),
    ('usuario:los-robles:admin',         pg_temp.id('clinica:los-robles'), 2::smallint, 'Silvia Alfaro'),
    ('usuario:los-robles:recepcion',     pg_temp.id('clinica:los-robles'), 3::smallint, 'Fernanda Ruiz')
  ) AS u (clave, clinica_id, rol_id, nombre);

-- ---------- Profesionales ----------
-- jornada: "completa" es una jornada partida (varios bloques por día, RF5); "manana" incluye el sábado.
CREATE TEMP TABLE def_profesional (clinica text, clave text, nombre text, especialidad text, jornada text) ON COMMIT DROP;
INSERT INTO def_profesional VALUES
    ('san-rafael', 'laura-mendez',    'Dra. Laura Méndez',   'Medicina general', 'completa'),
    ('san-rafael', 'carlos-jimenez',  'Dr. Carlos Jiménez',  'Medicina general', 'manana'),
    ('san-rafael', 'sofia-vargas',    'Dra. Sofía Vargas',   'Pediatría',        'tarde'),
    ('san-rafael', 'andres-rojas',    'Dr. Andrés Rojas',    'Odontología',      'completa'),
    ('del-valle',  'esteban-quesada', 'Dr. Esteban Quesada', 'Medicina general', 'completa'),
    ('del-valle',  'valeria-castro',  'Dra. Valeria Castro', 'Dermatología',     'manana'),
    ('del-valle',  'paula-arias',     'Dra. Paula Arias',    'Ginecología',      'completa'),
    ('los-robles', 'diego-navarro',   'Lic. Diego Navarro',  'Fisioterapia',     'completa'),
    ('los-robles', 'gabriela-soto',   'Lic. Gabriela Soto',  'Fisioterapia',     'tarde'),
    ('los-robles', 'natalia-perez',   'Lic. Natalia Pérez',  'Nutrición',        'manana'),
    ('los-robles', 'mauricio-leon',   'Dr. Mauricio León',   'Psicología',       'tarde');

INSERT INTO usuario (id, clinica_id, rol_id, keycloak_sub, nombre)
SELECT pg_temp.id('usuario:' || clinica || ':' || clave), pg_temp.id('clinica:' || clinica), 4,
       pg_temp.id('usuario:' || clinica || ':' || clave)::text, nombre
  FROM def_profesional;

INSERT INTO profesional (id, clinica_id, usuario_id, especialidad_id, numero_colegiado)
SELECT pg_temp.id('profesional:' || clinica || ':' || clave),
       pg_temp.id('clinica:' || clinica),
       pg_temp.id('usuario:' || clinica || ':' || clave),
       pg_temp.id('especialidad:' || clinica || ':' || especialidad),
       -- Número fijo derivado del nombre: estable entre arranques.
       'COL-' || (1000 + abs(hashtext(clinica || clave)) % 9000)
  FROM def_profesional;

-- Cada profesional atiende todos los servicios de SU especialidad (la regla de RF3 y RF4).
INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id)
SELECT pg_temp.id('clinica:' || p.clinica),
       pg_temp.id('profesional:' || p.clinica || ':' || p.clave),
       pg_temp.id('servicio:' || p.clinica || ':' || s.servicio)
  FROM def_profesional p
  JOIN def_servicio s ON s.clinica = p.clinica AND s.especialidad = p.especialidad;

-- ---------- Horario semanal (RF5) ----------
CREATE TEMP TABLE def_jornada (jornada text, dias int[], inicio time, fin time) ON COMMIT DROP;
INSERT INTO def_jornada VALUES
    ('completa', '{1,2,3,4,5}',   '08:00', '12:00'),
    ('completa', '{1,2,3,4,5}',   '13:00', '17:00'),   -- jornada partida: el almuerzo queda libre
    ('manana',   '{1,2,3,4,5,6}', '07:00', '12:00'),
    ('tarde',    '{1,2,3,4,5}',   '13:00', '19:00');

INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin)
SELECT pg_temp.id('clinica:' || p.clinica),
       pg_temp.id('profesional:' || p.clinica || ':' || p.clave),
       dia, j.inicio, j.fin
  FROM def_profesional p
  JOIN def_jornada j ON j.jornada = p.jornada
  CROSS JOIN LATERAL unnest(j.dias) AS dia;

-- ---------- Un bloqueo por vacaciones ----------
-- Dr. Carlos Jiménez no atiende de dentro de 8 días a dentro de 10. Existe ANTES de generar las citas,
-- así que la semilla no le asigna ninguna en esos días. (El bloqueo que cae sobre citas ya reservadas,
-- para ver los conflictos de RF6, se registra al final del siguiente archivo.)
INSERT INTO bloqueo_agenda (clinica_id, profesional_id, inicio, fin, motivo)
SELECT c.id,
       pg_temp.id('profesional:san-rafael:carlos-jimenez'),
       (((now() AT TIME ZONE c.zona_horaria)::date + 8)::timestamp) AT TIME ZONE c.zona_horaria,
       (((now() AT TIME ZONE c.zona_horaria)::date + 11)::timestamp) AT TIME ZONE c.zona_horaria,
       'Vacaciones'
  FROM clinica c WHERE c.identificador = 'san-rafael';
