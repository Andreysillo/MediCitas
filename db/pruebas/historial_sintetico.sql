-- Volumen para medir los índices (T15). NUNCA contra una base real: db/aplicar.sh no lo aplica; se corre a mano.
--
--   docker compose exec -T db sh -c 'psql -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/pruebas/historial_sintetico.sql
--
-- Sobre la semilla agrega dos cosas, y todo pasa por las restricciones del motor:
--   1. Dos años de citas pasadas (de hace 730 a hace 90 días) para los profesionales de la semilla: unas 80 mil.
--      Cada profesional tiene a lo más una cita por franja de 30 min (I1), y en una franja los profesionales de una
--      clínica atienden a pacientes distintos (I2).
--   2. 2 000 clínicas más, con un profesional y 25 bloqueos cada una: 50 mil bloqueos. Así se ve lo que pasa en un
--      SaaS con muchos clientes, donde `bloqueo_agenda` guarda los bloqueos de todas las clínicas.
\set ON_ERROR_STOP 1

-- ---- 1. Historial de citas ----
INSERT INTO paciente (clinica_id, identificacion, nombre, fecha_nacimiento)
SELECT c.id, 'H-' || c.identificador || '-' || i, 'Paciente histórico ' || i, date '1970-01-01' + i * 7
  FROM clinica c CROSS JOIN generate_series(1, 300) AS i;

WITH profs AS (
    SELECT p.clinica_id, p.id AS profesional_id, cl.zona_horaria,
           (SELECT ps.servicio_id FROM profesional_servicio ps
             WHERE ps.clinica_id = p.clinica_id AND ps.profesional_id = p.id ORDER BY 1 LIMIT 1) AS servicio_id,
           row_number() OVER (PARTITION BY p.clinica_id ORDER BY p.id) - 1 AS k,
           (SELECT u.id FROM usuario u JOIN rol r ON r.id = u.rol_id
             WHERE u.clinica_id = p.clinica_id AND r.codigo = 'ADM_CLINICA' ORDER BY 1 LIMIT 1) AS admin
      FROM profesional p JOIN clinica cl ON cl.id = p.clinica_id
),
pacs AS (
    SELECT clinica_id, id, row_number() OVER (PARTITION BY clinica_id ORDER BY id) - 1 AS n,
           count(*) OVER (PARTITION BY clinica_id) AS total
      FROM paciente
),
franjas AS (
    SELECT d::date AS dia, s AS franja, row_number() OVER (ORDER BY d, s) AS g
      FROM generate_series(current_date - 730, current_date - 90, interval '1 day') AS d
     CROSS JOIN generate_series(0, 15) AS s
     WHERE extract(isodow FROM d) <= 5
),
filas AS (
    SELECT pr.*, f.g, (f.dia + time '08:00' + f.franja * interval '30 minutes') AT TIME ZONE pr.zona_horaria AS inicio,
           CASE (f.g + pr.k) % 10 WHEN 0 THEN 'CANCELADA' WHEN 1 THEN 'AUSENTE' ELSE 'ATENDIDA' END AS estado
      FROM profs pr CROSS JOIN franjas f
     WHERE pr.servicio_id IS NOT NULL
)
INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado, creada_por,
                  cancelada_por, cancelada_en, motivo_cancelacion)
SELECT fi.clinica_id, pa.id, fi.profesional_id, fi.servicio_id, fi.inicio, fi.inicio + interval '30 minutes', fi.estado,
       fi.admin,
       CASE WHEN fi.estado = 'CANCELADA' THEN fi.admin END,
       CASE WHEN fi.estado = 'CANCELADA' THEN fi.inicio - interval '1 day' END,
       CASE WHEN fi.estado = 'CANCELADA' THEN 'Historial sintético' END
  FROM filas fi
  JOIN pacs pa ON pa.clinica_id = fi.clinica_id AND pa.n = (fi.g * 7 + fi.k) % pa.total;

-- ---- 2. Muchas clínicas, cada una con sus bloqueos ----
INSERT INTO clinica (nombre, identificador, zona_horaria)
SELECT 'Clínica sintética ' || i, 'sintetica-' || i, 'America/Costa_Rica' FROM generate_series(1, 2000) AS i;

INSERT INTO especialidad (clinica_id, nombre)
SELECT id, 'General' FROM clinica WHERE identificador LIKE 'sintetica-%';

INSERT INTO usuario (clinica_id, rol_id, keycloak_sub, nombre)
SELECT c.id, r.id, 'sintetico-' || c.identificador, 'Profesional ' || c.nombre
  FROM clinica c CROSS JOIN rol r
 WHERE c.identificador LIKE 'sintetica-%' AND r.codigo = 'PROFESIONAL';

INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, numero_colegiado)
SELECT u.clinica_id, u.id, e.id, 'SIN-' || u.id
  FROM usuario u JOIN especialidad e ON e.clinica_id = u.clinica_id
 WHERE u.keycloak_sub LIKE 'sintetico-%';

-- 25 bloqueos de un día por profesional, repartidos entre hace un año y dentro de dos meses.
INSERT INTO bloqueo_agenda (clinica_id, profesional_id, inicio, fin, motivo)
SELECT p.clinica_id, p.id, d, d + interval '1 day', 'Bloqueo sintético'
  FROM profesional p JOIN clinica c ON c.id = p.clinica_id
 CROSS JOIN LATERAL (SELECT date_trunc('day', now()) - interval '365 days' + (j * 17) * interval '1 day' AS d
                       FROM generate_series(0, 24) AS j) AS dias
 WHERE c.identificador LIKE 'sintetica-%';

ANALYZE;

SELECT (SELECT count(*) FROM cita) AS citas, (SELECT count(*) FROM bloqueo_agenda) AS bloqueos,
       (SELECT count(*) FROM clinica) AS clinicas;
